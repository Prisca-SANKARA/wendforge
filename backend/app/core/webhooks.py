"""
WendForge — Webhooks sortants vers n8n
========================================
Ce module envoie des événements à n8n quand
des actions importantes se produisent dans WendForge.

Architecture Event-Driven :
----------------------------
WendForge émet des événements → n8n les reçoit →
n8n décide quoi faire (email, Slack, rapport...)

Cette séparation est fondamentale :
- WendForge ne sait pas ce que n8n fait des événements
- n8n peut être modifié sans toucher à WendForge
- On peut ajouter de nouvelles automatisations dans n8n
  sans modifier le code FastAPI

C'est le principe "Loose Coupling" — couplage faible
entre les services.

Événements émis :
-----------------
- ticket.created   : nouveau ticket créé
- ticket.assigned  : ticket assigné à quelqu'un
- ticket.done      : ticket marqué comme terminé
- ticket.overdue   : ticket en retard (lancé par un cron)
- project.created  : nouveau projet créé
- member.added     : nouveau membre ajouté
- ai.analysis      : analyse IA terminée
- report.weekly    : déclenchement rapport hebdomadaire
"""

import httpx
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class WebhookEvent(str, Enum):
    """
    Types d'événements envoyés à n8n.
    Chaque événement correspond à un workflow n8n distinct.
    """
    # Tickets
    TICKET_CREATED = "ticket.created"
    TICKET_ASSIGNED = "ticket.assigned"
    TICKET_STATUS_CHANGED = "ticket.status_changed"
    TICKET_DONE = "ticket.done"
    TICKET_OVERDUE = "ticket.overdue"
    TICKET_AI_ANALYZED = "ticket.ai_analyzed"

    # Projets
    PROJECT_CREATED = "project.created"
    PROJECT_MEMBER_ADDED = "project.member_added"

    # Rapports
    REPORT_WEEKLY = "report.weekly"
    REPORT_DAILY = "report.daily"


class WebhookPayload:
    """
    Structure d'un payload webhook envoyé à n8n.

    Chaque événement contient :
    - event     : type d'événement
    - timestamp : quand l'événement s'est produit
    - data      : données spécifiques à l'événement
    - meta      : métadonnées (version API, environment...)
    """

    @staticmethod
    def build(
        event: WebhookEvent,
        data: dict,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> dict:
        """
        Construit un payload webhook standardisé.

        Tous les webhooks WendForge suivent ce format.
        N8n peut ainsi traiter tous les événements
        de la même façon en lisant toujours les mêmes champs.
        """
        return {
            "event": event.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
            "environment": settings.ENVIRONMENT,
            "triggered_by": {
                "user_id": user_id,
                "email": user_email,
            },
            "data": data,
        }


class WebhookService:
    """
    Service d'envoi de webhooks vers n8n.

    Design decisions :
    ------------------
    1. Fire-and-forget : on n'attend pas la réponse de n8n
       pour ne pas ralentir l'API. Si n8n est lent ou down,
       l'utilisateur ne le voit pas.

    2. Async avec timeout : on attend max 5 secondes.
       Si n8n ne répond pas, on log l'erreur et on continue.

    3. Retry simple : en cas d'échec, on réessaie une fois.
       Pour un retry plus robuste en production,
       on utiliserait une queue (Redis/RabbitMQ).

    4. Non-bloquant : on utilise asyncio.create_task()
       pour envoyer le webhook en arrière-plan pendant
       que l'API répond à l'utilisateur.
    """

    def __init__(self):
        self.n8n_url = settings.N8N_WEBHOOK_URL
        self.timeout = 5.0  # secondes

    async def send(
        self,
        event: WebhookEvent,
        data: dict,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> bool:
        """
        Envoie un webhook à n8n de façon asynchrone.

        Returns:
            True si succès, False si échec
        """
        payload = WebhookPayload.build(
            event=event,
            data=data,
            user_id=user_id,
            user_email=user_email,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.n8n_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        # Header pour identifier WendForge
                        "X-WendForge-Event": event.value,
                        "X-WendForge-Version": "1.0",
                    }
                )

                if response.status_code in (200, 201):
                    logger.info(
                        "Webhook sent successfully",
                        event=event.value,
                        status_code=response.status_code
                    )
                    return True
                else:
                    logger.warning(
                        "Webhook returned non-success status",
                        event=event.value,
                        status_code=response.status_code,
                    )
                    return False

        except httpx.TimeoutException:
            logger.warning(
                "Webhook timeout — n8n did not respond in time",
                event=event.value,
                url=self.n8n_url,
            )
            return False

        except httpx.ConnectError:
            logger.warning(
                "Webhook connection failed — n8n may be down",
                event=event.value,
                url=self.n8n_url,
            )
            return False

        except Exception as e:
            logger.error(
                "Webhook unexpected error",
                event=event.value,
                error=str(e),
            )
            return False

    def send_background(
        self,
        event: WebhookEvent,
        data: dict,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> None:
        """
        Envoie le webhook EN ARRIÈRE-PLAN sans bloquer.

        C'est la méthode à utiliser dans les endpoints.
        L'API répond immédiatement à l'utilisateur pendant
        que le webhook part vers n8n en parallèle.

        Usage dans un endpoint :
            webhook = WebhookService()
            webhook.send_background(
                event=WebhookEvent.TICKET_CREATED,
                data={"ticket_id": ticket.id, ...},
                user_id=user.id,
            )
            return ticket  # Réponse immédiate
        """
        asyncio.create_task(
            self.send(event, data, user_id, user_email)
        )
        logger.debug(
            "Webhook scheduled in background",
            event=event.value
        )


# ── Fonctions utilitaires ─────────────────────
# Ces fonctions construisent les payloads spécifiques
# à chaque événement WendForge.

def build_ticket_payload(ticket, project=None) -> dict:
    """Construit le payload pour un événement ticket."""
    import json
    return {
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "ticket_type": ticket.ticket_type,
        "tags": json.loads(ticket.tags) if ticket.tags else [],
        "assignee_id": ticket.assignee_id,
        "creator_id": ticket.creator_id,
        "project_id": ticket.project_id,
        "due_date": ticket.due_date.isoformat() if ticket.due_date else None,
        "created_at": ticket.created_at.isoformat(),
        "project_name": project.name if project else None,
    }


def build_project_payload(project) -> dict:
    """Construit le payload pour un événement projet."""
    return {
        "project_id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "created_at": project.created_at.isoformat(),
    }


# Instance globale du service webhook
# On utilise une instance unique partagée dans toute l'app
webhook_service = WebhookService()
"""
WendForge — Service Ticket
===========================
Logique métier pour les tickets.

Responsabilités :
- CRUD des tickets avec soft delete
- Numérotation automatique (WF-1, WF-2...)
- Intégration avec l'agent IA
- Déclenchement des webhooks n8n
- Filtrage et pagination avancés
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select, func
from fastapi import HTTPException, status
import json
import structlog

from app.modules.tickets.models import Ticket, TicketStatus
from app.modules.tickets.schemas import TicketCreate, TicketUpdate
from app.core.permissions import ProjectRole, Permission, check_permission
from app.modules.users.models import User

logger = structlog.get_logger(__name__)


class TicketService:

    def __init__(self, session: Session):
        self.session = session

    def _get_next_ticket_number(self, project_id: str) -> int:
        """
        Génère le prochain numéro de ticket pour un projet.

        Chaque projet a sa propre séquence :
        Projet A : WF-1, WF-2, WF-3...
        Projet B : WF-1, WF-2...

        On compte les tickets existants + 1.
        func.count() est une fonction SQL COUNT()
        exécutée directement en DB — plus efficace
        que de charger tous les tickets en Python.
        """
        statement = (
            select(func.count(Ticket.id))
            .where(Ticket.project_id == project_id)
        )
        count = self.session.exec(statement).one()
        return count + 1

    def create(
        self,
        project_id: str,
        data: TicketCreate,
        creator: User,
        requester_role: ProjectRole,
    ) -> Ticket:
        """Crée un ticket dans un projet."""
        check_permission(requester_role, Permission.CREATE_TICKET)

        # Convertit les tags list en JSON string
        tags_str = json.dumps(data.tags) if data.tags else None

        ticket = Ticket(
            title=data.title,
            description=data.description,
            status=data.status,
            priority=data.priority,
            ticket_type=data.ticket_type,
            tags=tags_str,
            due_date=data.due_date,
            estimated_hours=data.estimated_hours,
            assignee_id=data.assignee_id,
            project_id=project_id,
            creator_id=creator.id,
            ticket_number=self._get_next_ticket_number(project_id),
        )
        self.session.add(ticket)
        self.session.flush()

        logger.info(
            "Ticket created",
            ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            project_id=project_id
        )
        return ticket

    def get_by_id(self, ticket_id: str) -> Optional[Ticket]:
        """Récupère un ticket actif par son ID."""
        statement = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .where(Ticket.deleted_at == None)
        )
        return self.session.exec(statement).first()

    def get_by_id_or_404(self, ticket_id: str) -> Ticket:
        ticket = self.get_by_id(ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticket {ticket_id} not found"
            )
        return ticket

    def get_project_tickets(
        self,
        project_id: str,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[TicketStatus] = None,
        assignee_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Ticket], int]:
        """
        Récupère les tickets d'un projet avec pagination
        et filtres avancés.

        Returns:
            Tuple (liste de tickets, total)
            Le total sert à calculer le nombre de pages.
        """
        check_permission(
            ProjectRole.VIEWER,
            Permission.READ_TICKET
        )

        # Requête de base — exclut les tickets supprimés
        base_query = (
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.deleted_at == None)
        )

        # Filtres optionnels
        if status_filter:
            base_query = base_query.where(Ticket.status == status_filter)
        if assignee_id:
            base_query = base_query.where(Ticket.assignee_id == assignee_id)
        if search:
            base_query = base_query.where(
                Ticket.title.ilike(f"%{search}%")
            )

        # Compte total pour la pagination
        count_query = select(func.count()).select_from(base_query.subquery())
        total = self.session.exec(count_query).one()

        # Tri
        sort_column = getattr(Ticket, sort_by, Ticket.created_at)
        if sort_order == "desc":
            base_query = base_query.order_by(sort_column.desc())
        else:
            base_query = base_query.order_by(sort_column.asc())

        # Pagination
        offset = (page - 1) * limit
        base_query = base_query.offset(offset).limit(limit)

        tickets = list(self.session.exec(base_query).all())
        return tickets, total

    def update(
        self,
        ticket: Ticket,
        data: TicketUpdate,
        requester_role: ProjectRole,
    ) -> Ticket:
        """Met à jour un ticket."""
        check_permission(requester_role, Permission.UPDATE_TICKET)

        update_data = data.model_dump(exclude_unset=True)

        # Convertit les tags list en JSON string
        if "tags" in update_data:
            update_data["tags"] = (
                json.dumps(update_data["tags"])
                if update_data["tags"] else None
            )

        for key, value in update_data.items():
            setattr(ticket, key, value)

        ticket.updated_at = datetime.now(timezone.utc)
        self.session.add(ticket)
        self.session.flush()
        return ticket

    def soft_delete(
        self,
        ticket: Ticket,
        requester_role: ProjectRole,
    ) -> Ticket:
        """
        Suppression douce — ne supprime pas vraiment.
        Met deleted_at à la date actuelle.
        Le ticket n'apparaît plus dans les listes
        mais reste en DB pour l'audit.
        """
        check_permission(requester_role, Permission.DELETE_TICKET)
        ticket.deleted_at = datetime.now(timezone.utc)
        self.session.add(ticket)
        self.session.flush()
        logger.info("Ticket soft deleted", ticket_id=ticket.id)
        return ticket

    def set_ai_suggestion(
        self,
        ticket: Ticket,
        suggestion: dict
    ) -> Ticket:
        """Sauvegarde la suggestion de l'agent IA sur le ticket."""
        ticket.ai_suggestion = json.dumps(suggestion)
        ticket.updated_at = datetime.now(timezone.utc)
        self.session.add(ticket)
        self.session.flush()
        return ticket
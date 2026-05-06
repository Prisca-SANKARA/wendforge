"""
WendForge — Router Tickets
===========================
Endpoints de l'API pour les tickets.

GET    /projects/{id}/tickets/         → liste paginée
POST   /projects/{id}/tickets/         → créer un ticket
GET    /projects/{id}/tickets/{tid}    → détail d'un ticket
PATCH  /projects/{id}/tickets/{tid}    → modifier un ticket
DELETE /projects/{id}/tickets/{tid}    → supprimer (soft)
POST   /projects/{id}/tickets/{tid}/analyze → analyse IA
"""

from fastapi import APIRouter, Depends, Request, Query, status
from sqlmodel import Session
from typing import Optional
import structlog

from app.core.webhooks import (
    webhook_service, WebhookEvent, build_ticket_payload
)
from app.database import get_session
from app.core.security import TokenData, get_current_user
from app.core.audit import AuditAction, get_audit_service
from app.core.rate_limit import rate_limit, RateLimitType
from app.modules.tickets.service import TicketService
from app.modules.tickets.models import TicketStatus
from app.modules.projects.service import ProjectService
from app.modules.users.service import UserService
from app.modules.tickets.schemas import (
    TicketCreate, TicketUpdate,
    TicketResponse, PaginatedTickets
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedTickets,
    summary="Liste des tickets",
)
async def get_tickets(
    project_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[TicketStatus] = Query(default=None),
    assignee_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """
    Récupère les tickets d'un projet avec pagination et filtres.

    Paramètres de query :
    - page          : numéro de page (défaut: 1)
    - limit         : tickets par page (défaut: 20, max: 100)
    - status_filter : filtrer par statut
    - assignee_id   : filtrer par assigné
    - search        : recherche dans le titre
    - sort_by       : champ de tri (created_at, updated_at, priority)
    - sort_order    : asc ou desc
    """
    import math

    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    tickets, total = ticket_service.get_project_tickets(
        project_id=project_id,
        page=page,
        limit=limit,
        status_filter=status_filter,
        assignee_id=assignee_id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return PaginatedTickets(
        data=tickets,
        total=total,
        page=page,
        limit=limit,
        pages=math.ceil(total / limit) if total > 0 else 0,
    )


@router.post(
    "/",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un ticket",
)
async def create_ticket(
    project_id: str,
    request: Request,
    data: TicketCreate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """
    Crée un ticket dans un projet.
    Si request_ai_analysis=True, l'agent IA analyse
    le ticket et suggère priorité et assigné.
    """
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    ticket = ticket_service.create(
        project_id=project_id,
        data=data,
        creator=user,
        requester_role=membership.role,
    )

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.TICKET_CREATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="ticket",
        resource_id=ticket.id,
        details={
            "title": ticket.title,
            "priority": ticket.priority,
            "ticket_number": ticket.ticket_number,
        },
    )

# Envoie le webhook à n8n en arrière-plan
    webhook_service.send_background(
    event=WebhookEvent.TICKET_CREATED,
    data=build_ticket_payload(ticket),
    user_id=user.id,
    user_email=user.email,
)

    return ticket


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Détail d'un ticket",
)
async def get_ticket(
    project_id: str,
    ticket_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """Récupère les détails complets d'un ticket."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    return ticket_service.get_by_id_or_404(ticket_id)


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Modifier un ticket",
)
async def update_ticket(
    project_id: str,
    ticket_id: str,
    request: Request,
    data: TicketUpdate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Modifie un ticket. Requiert le rôle MEMBER minimum."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    ticket = ticket_service.get_by_id_or_404(ticket_id)
    updated = ticket_service.update(ticket, data, membership.role)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.TICKET_UPDATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="ticket",
        resource_id=ticket_id,
    )

    # Webhook si le ticket est marqué comme terminé
    if data.status and data.status.value == "done":
     webhook_service.send_background(
        event=WebhookEvent.TICKET_DONE,
        data=build_ticket_payload(updated),
        user_id=user.id,
        user_email=user.email,
    )
    elif data.status:
     webhook_service.send_background(
        event=WebhookEvent.TICKET_STATUS_CHANGED,
        data={
            **build_ticket_payload(updated),
            "new_status": data.status.value,
        },
        user_id=user.id,
        user_email=user.email,
    )

    return updated


@router.delete(
    "/{ticket_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un ticket",
)
async def delete_ticket(
    project_id: str,
    ticket_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Suppression douce d'un ticket. Requiert PROJECT_MANAGER."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    ticket = ticket_service.get_by_id_or_404(ticket_id)
    ticket_service.soft_delete(ticket, membership.role)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.TICKET_DELETED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="ticket",
        resource_id=ticket_id,
    )

@router.post(
    "/{ticket_id}/analyze",
    response_model=dict,
    summary="Analyser un ticket avec l'IA",
    description="Utilise l'agent Claude pour analyser le ticket "
                "et suggérer priorité, assigné et détecter les doublons."
)
async def analyze_ticket_with_ai(
    project_id: str,
    ticket_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.AI)),
):
    """
    Lance l'analyse IA sur un ticket existant.
    Rate limit : 20 appels/heure/utilisateur.
    """
    from app.core.agent import WendForgeAgent

    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    ticket_service = TicketService(session)
    ticket = ticket_service.get_by_id_or_404(ticket_id)

    # Lance l'agent IA
    agent = WendForgeAgent(session)
    suggestion = await agent.analyze_ticket(
        title=ticket.title,
        description=ticket.description,
        project_id=project_id,
        ticket_type=ticket.ticket_type,
        requester_id=user.id,
    )

    # Sauvegarde la suggestion sur le ticket
    ticket_service.set_ai_suggestion(ticket, suggestion)

    # Audit
    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.AI_ANALYSIS_REQUESTED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="ticket",
        resource_id=ticket_id,
        details={"confidence": suggestion.get("confidence")},
    )

    return suggestion
    
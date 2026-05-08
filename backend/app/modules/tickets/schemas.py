"""
WendForge — Schemas Ticket
===========================
Contrats de l'API pour les tickets.

TicketCreate  : créer un ticket
TicketUpdate  : modifier un ticket (PATCH)
TicketResponse: ce que l'API retourne
TicketList    : version condensée pour les listes

L'agent IA enrichit le TicketResponse avec
des suggestions (priorité, assigné, doublons).
"""
from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.modules.tickets.models import TicketStatus, TicketPriority, TicketType
from app.modules.users.schemas import UserSummary


class TicketCreate(BaseModel):
    """Créer un ticket."""
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: TicketStatus = TicketStatus.TODO
    priority: TicketPriority = TicketPriority.MEDIUM
    ticket_type: TicketType = TicketType.TASK

    tags: Optional[List[str]] = None

    @validator('tags', pre=True)
    def parse_tags(cls, v):
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except:
                return []
        return v
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    assignee_id: Optional[str] = None
    # Si True, l'agent IA analyse et suggère priorité/assigné
    request_ai_analysis: bool = False


class TicketUpdate(BaseModel):
    """Modifier un ticket — tous les champs optionnels."""
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    ticket_type: Optional[TicketType] = None
    tags: Optional[List[str]] = None
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    actual_hours: Optional[float] = Field(default=None, ge=0)
    assignee_id: Optional[str] = None


class AISuggestion(BaseModel):
    """
    Suggestion de l'agent IA pour un ticket.
    Retournée dans TicketResponse quand une analyse
    a été demandée.
    """
    suggested_priority: Optional[TicketPriority] = None
    suggested_assignee_id: Optional[str] = None
    similar_tickets: Optional[List[str]] = None
    analysis: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class TicketResponse(BaseModel):
    """Ce que l'API retourne pour un ticket."""
    id: str
    ticket_number: int
    title: str
    description: Optional[str]
    status: TicketStatus
    priority: TicketPriority
    ticket_type: TicketType
    tags: Optional[List[str]] = None
    due_date: Optional[datetime]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    project_id: str
    creator: Optional[UserSummary]
    assignee: Optional[UserSummary]
    comment_count: Optional[int] = 0
    ai_suggestion: Optional[AISuggestion] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if hasattr(obj, 'tags') and isinstance(obj.tags, str):
            import json
            try:
                obj.tags = json.loads(obj.tags)
            except Exception:
                obj.tags = []
        return super().model_validate(obj, **kwargs)

    class Config:
        from_attributes = True


class TicketListResponse(BaseModel):
    """
    Version condensée pour les listes de tickets.
    On n'envoie pas toute la description dans une liste
    de 100 tickets — c'est trop lourd.
    """
    id: str
    ticket_number: int
    title: str
    status: TicketStatus
    priority: TicketPriority
    ticket_type: TicketType
    assignee: Optional[UserSummary]
    due_date: Optional[datetime]
    comment_count: Optional[int] = 0
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedTickets(BaseModel):
    """
    Réponse paginée pour les listes de tickets.
    Inclut les métadonnées de pagination que
    le frontend utilise pour afficher les pages.
    """
    data: List[TicketListResponse]
    total: int
    page: int
    limit: int
    pages: int
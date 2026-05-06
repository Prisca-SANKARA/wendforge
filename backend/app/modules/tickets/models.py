"""
WendForge — Modèle Ticket
==========================
Un ticket représente une tâche, un bug ou une feature
dans un projet. C'est l'entité centrale de WendForge.

Statuts du ticket (workflow) :
BACKLOG → TODO → IN_PROGRESS → IN_REVIEW → DONE
                                         → CANCELLED

Priorités :
CRITICAL > HIGH > MEDIUM > LOW

L'agent IA peut suggérer automatiquement la priorité
et le statut initial en analysant le titre et la description.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
import uuid

if TYPE_CHECKING:
    from app.modules.users.models import User
    from app.modules.projects.models import Project
    from app.modules.comments.models import Comment


class TicketStatus(str, Enum):
    """Statuts possibles d'un ticket."""
    BACKLOG = "backlog"           # Pas encore planifié
    TODO = "todo"                 # Planifié, pas commencé
    IN_PROGRESS = "in_progress"   # En cours
    IN_REVIEW = "in_review"       # En attente de review
    DONE = "done"                 # Terminé
    CANCELLED = "cancelled"       # Annulé


class TicketPriority(str, Enum):
    """Priorités d'un ticket."""
    CRITICAL = "critical"   # Bloquant, à traiter immédiatement
    HIGH = "high"           # Important, à traiter rapidement
    MEDIUM = "medium"       # Normal
    LOW = "low"             # Peut attendre


class TicketType(str, Enum):
    """Types de tickets."""
    FEATURE = "feature"   # Nouvelle fonctionnalité
    BUG = "bug"           # Correction de bug
    TASK = "task"         # Tâche générale
    IMPROVEMENT = "improvement"  # Amélioration existante
    QUESTION = "question" # Question / clarification


class TicketBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = Field(default=None)
    status: TicketStatus = Field(default=TicketStatus.TODO)
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM)
    ticket_type: TicketType = Field(default=TicketType.TASK)
    # Tags stockés en JSON string ["bug", "frontend", "urgent"]
    tags: Optional[str] = Field(default=None)
    # Date limite
    due_date: Optional[datetime] = Field(default=None)
    # Estimation en heures
    estimated_hours: Optional[float] = Field(default=None)
    # Heures réellement passées
    actual_hours: Optional[float] = Field(default=None)
    # Suggestion de l'agent IA stockée en JSON
    ai_suggestion: Optional[str] = Field(default=None)


class Ticket(TicketBase, table=True):
    """Table 'tickets' dans PostgreSQL."""
    __tablename__ = "tickets"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )
    # Numéro lisible du ticket dans le projet (ex: WF-42)
    ticket_number: int = Field(default=0)

    project_id: str = Field(
        foreign_key="projects.id",
        index=True
    )
    creator_id: str = Field(
        foreign_key="users.id",
        index=True
    )
    assignee_id: Optional[str] = Field(
        default=None,
        foreign_key="users.id",
        index=True
    )
    # Soft delete — on ne supprime jamais vraiment
    # deleted_at=None → ticket actif
    # deleted_at=<date> → ticket supprimé
    deleted_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Relations
    project: Optional["Project"] = Relationship(
        back_populates="tickets"
    )
    creator: Optional["User"] = Relationship(
        back_populates="created_tickets",
        sa_relationship_kwargs={"foreign_keys": "[Ticket.creator_id]"}
    )
    assignee: Optional["User"] = Relationship(
        back_populates="assigned_tickets",
        sa_relationship_kwargs={"foreign_keys": "[Ticket.assignee_id]"}
    )
    comments: List["Comment"] = Relationship(
        back_populates="ticket"
    )
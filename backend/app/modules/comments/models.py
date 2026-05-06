"""
WendForge — Modèle Comment
===========================
Les commentaires permettent aux membres d'une équipe
de discuter sur un ticket — poser des questions,
donner des mises à jour, partager des solutions.

Support du Markdown :
Le contenu des commentaires supporte le Markdown.
Le frontend affiche le rendu HTML, l'API stocke le
Markdown brut — plus sûr et plus flexible.

Mentions (@username) :
Les mentions sont stockées en JSON dans 'mentions'.
Le système de notifications (n8n) les lit pour alerter
les utilisateurs mentionnés.
"""

from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
import uuid

if TYPE_CHECKING:
    from app.modules.users.models import User
    from app.modules.tickets.models import Ticket


class CommentBase(SQLModel):
    # Contenu en Markdown
    content: str
    # Mentions @username stockées en JSON ["alice", "bob"]
    mentions: Optional[str] = Field(default=None)
    # Soft delete
    is_deleted: bool = Field(default=False)
    # Indique si le commentaire a été édité
    is_edited: bool = Field(default=False)


class Comment(CommentBase, table=True):
    """Table 'comments' dans PostgreSQL."""
    __tablename__ = "comments"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )
    ticket_id: str = Field(
        foreign_key="tickets.id",
        index=True
    )
    author_id: str = Field(
        foreign_key="users.id",
        index=True
    )
    # Permet les réponses à un commentaire (thread)
    parent_id: Optional[str] = Field(
        default=None,
        foreign_key="comments.id"
    )
    edited_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Relations
    ticket: Optional["Ticket"] = Relationship(
        back_populates="comments"
    )
    author: Optional["User"] = Relationship(
        back_populates="comments"
    )
    # Réponses à ce commentaire
    replies: List["Comment"] = Relationship(
    sa_relationship_kwargs={
        "primaryjoin": "Comment.parent_id == Comment.id",
        "foreign_keys": "[Comment.parent_id]",
        "remote_side": "[Comment.id]",
        "uselist": True,
        "overlaps": "parent"
    }
)
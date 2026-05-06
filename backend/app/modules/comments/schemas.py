"""
WendForge — Schemas Comment
============================
Contrats de l'API pour les commentaires.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.modules.users.schemas import UserSummary


class CommentCreate(BaseModel):
    """Créer un commentaire sur un ticket."""
    content: str = Field(min_length=1, max_length=5000)
    # Mentions extraites du contenu @username
    mentions: Optional[List[str]] = None
    # Répondre à un commentaire existant
    parent_id: Optional[str] = None


class CommentUpdate(BaseModel):
    """Modifier son commentaire."""
    content: str = Field(min_length=1, max_length=5000)
    mentions: Optional[List[str]] = None


class CommentResponse(BaseModel):
    """Ce que l'API retourne pour un commentaire."""
    id: str
    content: str
    mentions: Optional[List[str]]
    is_edited: bool
    is_deleted: bool
    parent_id: Optional[str]
    ticket_id: str
    author: Optional[UserSummary]
    replies: Optional[List["CommentResponse"]] = []
    edited_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# Nécessaire pour les modèles récursifs (replies)
CommentResponse.model_rebuild()
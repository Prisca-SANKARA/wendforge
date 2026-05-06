"""
WendForge — Schemas Project
============================
Contrats de l'API pour les projets et memberships.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.core.permissions import ProjectRole
from app.modules.users.schemas import UserSummary


class ProjectCreate(BaseModel):
    """Créer un nouveau projet."""
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    color: str = Field(default="#8b5cf6", pattern="^#[0-9a-fA-F]{6}$")
    emoji: Optional[str] = Field(default="📋")


class ProjectUpdate(BaseModel):
    """Modifier un projet — tous les champs optionnels."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    color: Optional[str] = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    emoji: Optional[str] = None
    is_archived: Optional[bool] = None


class ProjectResponse(BaseModel):
    """Ce que l'API retourne pour un projet."""
    id: str
    name: str
    description: Optional[str]
    color: str
    emoji: Optional[str]
    is_archived: bool
    owner_id: str
    created_at: datetime
    updated_at: datetime
    # Nombre de membres et tickets pour l'affichage
    member_count: Optional[int] = 0
    ticket_count: Optional[int] = 0

    class Config:
        from_attributes = True


class ProjectMemberAdd(BaseModel):
    """Ajouter un membre à un projet."""
    user_id: str
    role: ProjectRole = ProjectRole.MEMBER


class ProjectMemberUpdate(BaseModel):
    """Changer le rôle d'un membre."""
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    """Membre d'un projet avec ses infos."""
    id: str
    project_id: str
    user: UserSummary
    role: ProjectRole
    joined_at: datetime

    class Config:
        from_attributes = True
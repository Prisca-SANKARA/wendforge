"""
WendForge — Modèles Project et ProjectMember
=============================================
Project : un projet de travail avec des membres et tickets.

ProjectMember : table de jointure entre User et Project.
C'est une relation Many-to-Many (M2M) enrichie :
- Un user peut être membre de plusieurs projets
- Un projet peut avoir plusieurs membres
- Chaque membership a un rôle (ADMIN, MEMBER, VIEWER...)

Table de jointure enrichie vs simple :
Simple M2M : juste user_id + project_id
Enrichie   : user_id + project_id + role + joined_at + invited_by
On choisit enrichie car le rôle est crucial pour le RBAC.
"""

from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from app.core.permissions import ProjectRole
import uuid

if TYPE_CHECKING:
    from app.modules.users.models import User
    from app.modules.tickets.models import Ticket


class ProjectBase(SQLModel):
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None)
    # Couleur hexadécimale pour identifier visuellement le projet
    color: str = Field(default="#8b5cf6")
    emoji: Optional[str] = Field(default="📋")
    is_archived: bool = Field(default=False)


class Project(ProjectBase, table=True):
    """Table 'projects' dans PostgreSQL."""
    __tablename__ = "projects"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )
    # Qui a créé le projet
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Relations
    members: List["ProjectMember"] = Relationship(
        back_populates="project"
    )
    tickets: List["Ticket"] = Relationship(
        back_populates="project"
    )


class ProjectMember(SQLModel, table=True):
    """
    Table de jointure enrichie entre User et Project.
    Stocke le rôle de chaque membre dans chaque projet.
    """
    __tablename__ = "project_members"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )
    project_id: str = Field(
        foreign_key="projects.id",
        index=True
    )
    user_id: str = Field(
        foreign_key="users.id",
        index=True
    )
    # Rôle dans CE projet spécifiquement
    role: ProjectRole = Field(default=ProjectRole.MEMBER)
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Qui a invité ce membre
    invited_by: Optional[str] = Field(
        default=None,
        foreign_key="users.id"
    )

    # Relations
    project: Optional[Project] = Relationship(
        back_populates="members"
    )
    user: Optional["User"] = Relationship(
    back_populates="project_memberships",
    sa_relationship_kwargs={
        "primaryjoin": "ProjectMember.user_id == User.id",
        "foreign_keys": "[ProjectMember.user_id]"
    }
)
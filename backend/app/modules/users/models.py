"""
WendForge — Modèle User
========================
Représente un utilisateur dans WendForge.

Important : WendForge ne gère PAS les mots de passe.
C'est Keycloak qui s'en charge. Notre table users
ne stocke que les infos nécessaires à l'application
(préférences, rôles projet, etc.).

La colonne keycloak_id est l'identifiant Keycloak (sub du JWT).
C'est le lien entre notre DB et Keycloak.
"""

from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
import uuid

if TYPE_CHECKING:
    from app.modules.projects.models import ProjectMember
    from app.modules.tickets.models import Ticket
    from app.modules.comments.models import Comment


class UserBase(SQLModel):
    """
    Champs communs partagés entre les schémas User.
    UserBase n'est PAS une table — c'est juste une
    classe de base pour éviter la répétition.
    """
    keycloak_id: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)
    full_name: str
    avatar_url: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    # Préférences utilisateur stockées en JSON string
    preferences: Optional[str] = Field(default=None)


class User(UserBase, table=True):
    """
    Table 'users' dans PostgreSQL.
    table=True → SQLModel crée vraiment la table.
    """
    __tablename__ = "users"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_login: Optional[datetime] = Field(default=None)

    # Relations SQLModel
    # "back_populates" crée la relation bidirectionnelle :
    # user.project_memberships → liste des projets de l'user
    # project_member.user → l'user du membership
    project_memberships: List["ProjectMember"] = Relationship(
    back_populates="user",
    sa_relationship_kwargs={
        "primaryjoin": "User.id == ProjectMember.user_id",
        "foreign_keys": "[ProjectMember.user_id]"
    }
)
    assigned_tickets: List["Ticket"] = Relationship(
        back_populates="assignee",
        sa_relationship_kwargs={"foreign_keys": "[Ticket.assignee_id]"}
    )
    created_tickets: List["Ticket"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={"foreign_keys": "[Ticket.creator_id]"}
    )
    comments: List["Comment"] = Relationship(
        back_populates="author"
    )
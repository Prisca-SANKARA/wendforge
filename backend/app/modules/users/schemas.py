"""
WendForge — Schemas User
=========================
Contrats de l'API pour les utilisateurs.

UserCreate  : données pour créer un user (depuis Keycloak)
UserUpdate  : données pour modifier un user
UserResponse: ce que l'API retourne — jamais de données sensibles
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """
    Créer un utilisateur après sa première connexion Keycloak.
    Ces données viennent du token JWT Keycloak.
    """
    keycloak_id: str
    email: EmailStr
    username: str
    full_name: str
    avatar_url: Optional[str] = None


class UserUpdate(BaseModel):
    """
    Modifier son profil.
    Tous les champs sont Optional — on envoie
    uniquement ce qu'on veut modifier (PATCH).
    """
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: Optional[dict] = None


class UserResponse(BaseModel):
    """
    Ce que l'API retourne quand on parle d'un user.
    Jamais de keycloak_id ou données sensibles ici.
    """
    id: str
    email: str
    username: str
    full_name: str
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        # Permet de créer le schema depuis un objet SQLModel
        from_attributes = True


class UserSummary(BaseModel):
    """
    Version condensée d'un user pour les listes et relations.
    Ex: dans un ticket, on affiche juste le nom et l'avatar
    de l'assigné — pas toutes ses infos.
    """
    id: str
    username: str
    full_name: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True
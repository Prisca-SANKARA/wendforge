"""
WendForge — Système RBAC (Role-Based Access Control)
======================================================
Ce module gère les permissions granulaires de WendForge.

Concepts :
- Role : un rôle attribué à un utilisateur (ADMIN, MEMBER, VIEWER)
- Permission : une action spécifique (create_ticket, delete_project...)
- ProjectMember : l'association entre un User, un Project et un Role

Hiérarchie des rôles :
┌─────────────────────────────────────────┐
│  ADMIN                                  │
│  ├── Tout faire sur tous les projets    │
│  └── Gérer les utilisateurs             │
│                                         │
│  PROJECT_MANAGER                        │
│  ├── Créer/modifier/supprimer projets   │
│  └── Gérer les membres du projet        │
│                                         │
│  MEMBER                                 │
│  ├── Créer/modifier des tickets         │
│  └── Commenter                          │
│                                         │
│  VIEWER                                 │
│  └── Lire uniquement                    │
└─────────────────────────────────────────┘

Pourquoi ce système plutôt qu'un simple booléen is_admin ?
Un booléen is_admin ne permet que 2 états.
Le RBAC permet des permissions fines par projet :
- Alice est ADMIN sur le Projet A
- Alice est VIEWER sur le Projet B
- Bob est MEMBER sur les deux
"""

from enum import Enum
from typing import Optional
from fastapi import Depends, HTTPException, status
from sqlmodel import Session, select
import structlog

from app.core.security import TokenData, get_current_user
from app.database import get_session

logger = structlog.get_logger(__name__)


# ── Définition des rôles ──────────────────────
class ProjectRole(str, Enum):
    """
    Rôles possibles dans un projet WendForge.
    Hérite de str pour être sérialisable en JSON
    et stockable directement en base de données.
    """
    ADMIN = "admin"                     # Accès total
    PROJECT_MANAGER = "project_manager" # Gère le projet et les membres
    MEMBER = "member"                   # Contribue aux tickets
    VIEWER = "viewer"                   # Lecture seule


# ── Définition des permissions ────────────────
class Permission(str, Enum):
    """
    Permissions granulaires de WendForge.
    Chaque action dans l'API correspond à une permission.
    """
    # Projets
    CREATE_PROJECT = "create_project"
    READ_PROJECT = "read_project"
    UPDATE_PROJECT = "update_project"
    DELETE_PROJECT = "delete_project"
    MANAGE_MEMBERS = "manage_members"

    # Tickets
    CREATE_TICKET = "create_ticket"
    READ_TICKET = "read_ticket"
    UPDATE_TICKET = "update_ticket"
    DELETE_TICKET = "delete_ticket"
    ASSIGN_TICKET = "assign_ticket"
    CHANGE_TICKET_STATUS = "change_ticket_status"

    # Commentaires
    CREATE_COMMENT = "create_comment"
    READ_COMMENT = "read_comment"
    UPDATE_COMMENT = "update_comment"
    DELETE_COMMENT = "delete_comment"

    # Administration
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT_LOGS = "view_audit_logs"


# ── Matrice des permissions par rôle ─────────
# Définit exactement ce que chaque rôle peut faire.
# Pour modifier les droits d'un rôle, on ne change
# qu'ici — pas besoin de toucher aux endpoints.
ROLE_PERMISSIONS: dict[ProjectRole, set[Permission]] = {

    ProjectRole.ADMIN: {
        # L'admin peut tout faire
        Permission.CREATE_PROJECT,
        Permission.READ_PROJECT,
        Permission.UPDATE_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.MANAGE_MEMBERS,
        Permission.CREATE_TICKET,
        Permission.READ_TICKET,
        Permission.UPDATE_TICKET,
        Permission.DELETE_TICKET,
        Permission.ASSIGN_TICKET,
        Permission.CHANGE_TICKET_STATUS,
        Permission.CREATE_COMMENT,
        Permission.READ_COMMENT,
        Permission.UPDATE_COMMENT,
        Permission.DELETE_COMMENT,
        Permission.MANAGE_USERS,
        Permission.VIEW_AUDIT_LOGS,
    },

    ProjectRole.PROJECT_MANAGER: {
        # Gère le projet mais pas les utilisateurs globaux
        Permission.READ_PROJECT,
        Permission.UPDATE_PROJECT,
        Permission.MANAGE_MEMBERS,
        Permission.CREATE_TICKET,
        Permission.READ_TICKET,
        Permission.UPDATE_TICKET,
        Permission.DELETE_TICKET,
        Permission.ASSIGN_TICKET,
        Permission.CHANGE_TICKET_STATUS,
        Permission.CREATE_COMMENT,
        Permission.READ_COMMENT,
        Permission.UPDATE_COMMENT,
        Permission.DELETE_COMMENT,
        Permission.VIEW_AUDIT_LOGS,
    },

    ProjectRole.MEMBER: {
        # Contribue activement au projet
        Permission.READ_PROJECT,
        Permission.CREATE_TICKET,
        Permission.READ_TICKET,
        Permission.UPDATE_TICKET,
        Permission.CHANGE_TICKET_STATUS,
        Permission.CREATE_COMMENT,
        Permission.READ_COMMENT,
        Permission.UPDATE_COMMENT,
    },

    ProjectRole.VIEWER: {
        # Lecture seule — ne peut rien modifier
        Permission.READ_PROJECT,
        Permission.READ_TICKET,
        Permission.READ_COMMENT,
    },
}


def has_permission(role: ProjectRole, permission: Permission) -> bool:
    """
    Vérifie si un rôle a une permission spécifique.

    Args:
        role: Le rôle de l'utilisateur dans le projet
        permission: La permission à vérifier

    Returns:
        True si le rôle a la permission, False sinon

    Example:
        has_permission(ProjectRole.MEMBER, Permission.CREATE_TICKET)
        → True

        has_permission(ProjectRole.VIEWER, Permission.DELETE_PROJECT)
        → False
    """
    return permission in ROLE_PERMISSIONS.get(role, set())


def check_permission(role: ProjectRole, permission: Permission) -> None:
    """
    Vérifie une permission et lève une exception si refusée.
    Version "stricte" de has_permission pour les endpoints.

    Raises:
        HTTPException 403 : si la permission est refusée
    """
    if not has_permission(role, permission):
        logger.warning(
            "Permission denied",
            role=role,
            permission=permission
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {permission.value} requires at least {_minimum_role(permission)} role"
        )


def _minimum_role(permission: Permission) -> str:
    """
    Retourne le rôle minimum requis pour une permission.
    Utilisé pour les messages d'erreur clairs.
    """
    for role in [ProjectRole.VIEWER, ProjectRole.MEMBER,
                 ProjectRole.PROJECT_MANAGER, ProjectRole.ADMIN]:
        if has_permission(role, permission):
            return role.value
    return ProjectRole.ADMIN.value


def require_permission(permission: Permission):
    """
    Factory de dépendances FastAPI pour vérifier les permissions.

    Retourne une fonction de dépendance qui vérifie que
    l'utilisateur connecté a la permission requise.

    Comme les permissions sont liées à un projet spécifique,
    cette dépendance est utilisée avec le rôle récupéré
    depuis la base de données.

    Usage dans un endpoint :
        @router.post("/projects/{project_id}/tickets")
        async def create_ticket(
            project_id: str,
            user: TokenData = Depends(get_current_user),
            session: Session = Depends(get_session),
        ):
            # Récupérer le rôle de l'user dans ce projet
            member = get_project_member(session, project_id, user.user_id)
            check_permission(member.role, Permission.CREATE_TICKET)
            ...
    """
    def _check(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        # Les admins Keycloak ont toutes les permissions
        if current_user.is_admin():
            return current_user
        return current_user

    return _check


class PermissionChecker:
    """
    Classe utilitaire pour vérifier plusieurs permissions.

    Usage:
        checker = PermissionChecker(ProjectRole.MEMBER)
        checker.can(Permission.CREATE_TICKET)  # True
        checker.can(Permission.DELETE_PROJECT) # False
        checker.require(Permission.CREATE_TICKET) # OK
        checker.require(Permission.DELETE_PROJECT) # raise 403
    """

    def __init__(self, role: ProjectRole):
        self.role = role

    def can(self, permission: Permission) -> bool:
        """Vérifie si le rôle a une permission (sans exception)."""
        return has_permission(self.role, permission)

    def require(self, permission: Permission) -> None:
        """Vérifie et lève une exception si refusée."""
        check_permission(self.role, permission)

    def can_any(self, *permissions: Permission) -> bool:
        """Vérifie si le rôle a AU MOINS UNE des permissions."""
        return any(self.can(p) for p in permissions)

    def can_all(self, *permissions: Permission) -> bool:
        """Vérifie si le rôle a TOUTES les permissions."""
        return all(self.can(p) for p in permissions)
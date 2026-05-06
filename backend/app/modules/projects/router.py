"""
WendForge — Router Projects
============================
Endpoints de l'API pour les projets.

GET    /projects/           → mes projets
POST   /projects/           → créer un projet
GET    /projects/{id}       → détail d'un projet
PATCH  /projects/{id}       → modifier un projet
DELETE /projects/{id}       → supprimer un projet
GET    /projects/{id}/members         → membres du projet
POST   /projects/{id}/members         → ajouter un membre
PATCH  /projects/{id}/members/{uid}   → changer le rôle
DELETE /projects/{id}/members/{uid}   → retirer un membre
"""

from fastapi import APIRouter, Depends, Request, status
from sqlmodel import Session
from typing import List
import structlog

from app.database import get_session
from app.core.security import TokenData, get_current_user
from app.core.audit import AuditService, AuditAction, get_audit_service
from app.core.rate_limit import rate_limit, RateLimitType
from app.modules.projects.service import ProjectService
from app.modules.users.service import UserService
from app.modules.projects.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse,
    ProjectMemberAdd, ProjectMemberUpdate, ProjectMemberResponse
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProjectResponse],
    summary="Mes projets",
)
async def get_my_projects(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """Retourne tous les projets dont l'user est membre."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    projects = project_service.get_user_projects(user.id)
    return projects


@router.post(
    "/",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un projet",
)
async def create_project(
    request: Request,
    data: ProjectCreate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """
    Crée un nouveau projet.
    Le créateur est automatiquement ajouté comme ADMIN.
    """
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project = project_service.create(data, user)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_CREATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project",
        resource_id=project.id,
        details={"name": project.name},
    )

    return project


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Détail d'un projet",
)
async def get_project(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """
    Récupère les détails d'un projet.
    L'user doit être membre du projet pour y accéder.
    """
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project = project_service.get_by_id_or_404(project_id)

    # Vérifie que l'user est membre
    project_service.get_member_or_403(project_id, user.id)

    return project


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Modifier un projet",
)
async def update_project(
    request: Request,
    project_id: str,
    data: ProjectUpdate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Modifie un projet. Requiert le rôle PROJECT_MANAGER ou ADMIN."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project = project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    updated = project_service.update(project, data, membership.role)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_UPDATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project",
        resource_id=project_id,
    )

    return updated


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un projet",
)
async def delete_project(
    request: Request,
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Supprime un projet. Réservé aux ADMINS du projet."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project = project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    project_service.delete(project, membership.role)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_DELETED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project",
        resource_id=project_id,
    )


@router.get(
    "/{project_id}/members",
    response_model=List[ProjectMemberResponse],
    summary="Membres du projet",
)
async def get_project_members(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """Liste tous les membres d'un projet."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    from sqlmodel import select
    from app.modules.projects.models import ProjectMember
    statement = (
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
    )
    members = list(session.exec(statement).all())
    return members


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un membre",
)
async def add_project_member(
    request: Request,
    project_id: str,
    data: ProjectMemberAdd,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Ajoute un membre au projet. Requiert MANAGE_MEMBERS."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project = project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    new_member = project_service.add_member(
        project, data, membership.role, user.id
    )

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_MEMBER_ADDED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project",
        resource_id=project_id,
        details={"new_member_id": data.user_id, "role": data.role},
    )

    return new_member


@router.patch(
    "/{project_id}/members/{member_user_id}",
    response_model=ProjectMemberResponse,
    summary="Changer le rôle d'un membre",
)
async def update_member_role(
    request: Request,
    project_id: str,
    member_user_id: str,
    data: ProjectMemberUpdate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Change le rôle d'un membre dans le projet."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    requester_membership = project_service.get_member_or_403(
        project_id, user.id
    )
    target_membership = project_service.get_member_or_403(
        project_id, member_user_id
    )

    updated = project_service.update_member_role(
        target_membership, data, requester_membership.role
    )

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_MEMBER_ROLE_CHANGED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project_member",
        resource_id=target_membership.id,
        details={"new_role": data.role},
    )

    return updated


@router.delete(
    "/{project_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer un membre",
)
async def remove_project_member(
    request: Request,
    project_id: str,
    member_user_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Retire un membre du projet."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    requester_membership = project_service.get_member_or_403(
        project_id, user.id
    )
    target_membership = project_service.get_member_or_403(
        project_id, member_user_id
    )

    project_service.remove_member(
        target_membership, requester_membership.role
    )

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.PROJECT_MEMBER_REMOVED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="project",
        resource_id=project_id,
        details={"removed_user_id": member_user_id},
    )
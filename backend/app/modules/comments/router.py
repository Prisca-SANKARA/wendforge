"""
WendForge — Router Comments
============================
Endpoints de l'API pour les commentaires.

GET    /projects/{pid}/tickets/{tid}/comments/      → liste
POST   /projects/{pid}/tickets/{tid}/comments/      → créer
PATCH  /projects/{pid}/tickets/{tid}/comments/{cid} → modifier
DELETE /projects/{pid}/tickets/{tid}/comments/{cid} → supprimer
"""

from fastapi import APIRouter, Depends, Request, status
from sqlmodel import Session
from typing import List
import structlog

from app.modules.comments.models import Comment
from app.database import get_session
from app.core.security import TokenData, get_current_user
from app.core.audit import AuditAction, get_audit_service
from app.core.rate_limit import rate_limit, RateLimitType
from app.modules.comments.service import CommentService
from app.modules.projects.service import ProjectService
from app.modules.users.service import UserService
from app.modules.comments.schemas import (
    CommentCreate, CommentUpdate, CommentResponse
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[CommentResponse],
    summary="Commentaires d'un ticket",
)
async def get_comments(
    project_id: str,
    ticket_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """Récupère tous les commentaires d'un ticket."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    comment_service = CommentService(session)
    return comment_service.get_ticket_comments(ticket_id)


@router.post(
    "/",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un commentaire",
)
async def create_comment(
    project_id: str,
    ticket_id: str,
    request: Request,
    data: CommentCreate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Ajoute un commentaire sur un ticket."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    comment_service = CommentService(session)
    comment = comment_service.create(ticket_id, data, user)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.COMMENT_CREATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="comment",
        resource_id=comment.id,
        details={"ticket_id": ticket_id},
    )

    return comment


@router.patch(
    "/{comment_id}",
    response_model=CommentResponse,
    summary="Modifier un commentaire",
)
async def update_comment(
    project_id: str,
    ticket_id: str,
    comment_id: str,
    request: Request,
    data: CommentUpdate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Modifie un commentaire. Seul l'auteur peut modifier."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    project_service.get_member_or_403(project_id, user.id)

    comment_service = CommentService(session)
    comment = session.get(Comment, comment_id)
    if not comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Comment not found")

    updated = comment_service.update(comment, data, user.id)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.COMMENT_UPDATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="comment",
        resource_id=comment_id,
    )

    return updated


@router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un commentaire",
)
async def delete_comment(
    project_id: str,
    ticket_id: str,
    comment_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Supprime un commentaire. Auteur ou admin seulement."""
    user_service = UserService(session)
    user = user_service.get_or_create_from_token(current_user)

    project_service = ProjectService(session)
    project_service.get_by_id_or_404(project_id)
    membership = project_service.get_member_or_403(project_id, user.id)

    from app.modules.comments.models import Comment
    from app.core.permissions import ProjectRole
    comment = session.get(Comment, comment_id)
    if not comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Comment not found")

    comment_service = CommentService(session)
    comment_service.soft_delete(
        comment,
        user.id,
        is_admin=membership.role == ProjectRole.ADMIN
    )

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.COMMENT_DELETED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="comment",
        resource_id=comment_id,
    )
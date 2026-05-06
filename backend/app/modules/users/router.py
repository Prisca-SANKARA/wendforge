"""
WendForge — Router Users
=========================
Endpoints de l'API pour les utilisateurs.

GET  /users/me          → profil de l'user connecté
PUT  /users/me          → modifier son profil
GET  /users/{id}        → profil d'un autre user
GET  /users/            → liste des users (admin)
DELETE /users/{id}      → désactiver un user (admin)
"""

from fastapi import APIRouter, Depends, Request, status
from sqlmodel import Session
import structlog

from app.database import get_session
from app.core.security import TokenData, get_current_user, require_admin
from app.core.audit import AuditService, AuditAction, get_audit_service
from app.core.rate_limit import rate_limit, RateLimitType
from app.modules.users.service import UserService
from app.modules.users.schemas import UserResponse, UserUpdate, UserSummary

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Mon profil",
    description="Retourne le profil de l'utilisateur connecté. "
                "Crée le profil automatiquement si c'est la première connexion."
)
async def get_my_profile(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """
    Récupère ou crée le profil de l'utilisateur connecté.

    À chaque appel :
    1. Vérifie le token Keycloak
    2. Cherche l'user dans notre DB par keycloak_id
    3. Le crée si c'est la première connexion
    4. Met à jour last_login
    5. Retourne le profil
    """
    service = UserService(session)
    user = service.get_or_create_from_token(current_user)

    # Audit de connexion
    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.LOGIN_SUCCESS,
        request=request,
        user_id=user.id,
        user_email=user.email,
    )

    return user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Modifier mon profil",
)
async def update_my_profile(
    request: Request,
    data: UserUpdate,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.WRITE)),
):
    """Modifie le profil de l'utilisateur connecté."""
    service = UserService(session)
    user = service.get_or_create_from_token(current_user)
    updated_user = service.update(user, data)

    audit = get_audit_service(session)
    await audit.log_from_request(
        action=AuditAction.USER_UPDATED,
        request=request,
        user_id=user.id,
        user_email=user.email,
        resource_type="user",
        resource_id=user.id,
    )

    return updated_user


@router.get(
    "/{user_id}",
    response_model=UserSummary,
    summary="Profil d'un utilisateur",
)
async def get_user(
    user_id: str,
    current_user: TokenData = Depends(get_current_user),
    session: Session = Depends(get_session),
    _: None = Depends(rate_limit(RateLimitType.READ)),
):
    """
    Récupère le profil public d'un utilisateur.
    Retourne UserSummary — pas toutes les infos.
    """
    service = UserService(session)
    user = service.get_by_id(user_id)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    return user
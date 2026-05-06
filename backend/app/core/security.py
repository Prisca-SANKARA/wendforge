"""
WendForge — Sécurité & Vérification JWT Keycloak
==================================================
Ce module gère toute la vérification des tokens JWT
émis par Keycloak.

Flux d'authentification :
1. L'utilisateur se connecte sur Keycloak (avec MFA si activé)
2. Keycloak retourne un access_token JWT signé
3. Le client envoie ce token dans le header : Authorization: Bearer <token>
4. FastAPI appelle verify_token() qui :
   a. Récupère les clés publiques de Keycloak (JWKS)
   b. Vérifie la signature du token avec ces clés
   c. Vérifie que le token n'est pas expiré
   d. Retourne les données de l'utilisateur (claims)

Pourquoi JWKS ?
Keycloak signe les JWT avec sa clé privée.
Seule sa clé publique (disponible via JWKS) peut vérifier
cette signature. Ainsi on n'a jamais besoin de communiquer
le secret avec l'API.
"""
import jwt as pyjwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
import json
import base64
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from datetime import datetime
from typing import Optional
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# ── Schéma de sécurité HTTP Bearer ────────────
# HTTPBearer extrait automatiquement le token du header
# Authorization: Bearer <token>
# auto_error=False : on gère nous-mêmes l'erreur pour
# avoir un message plus précis
bearer_scheme = HTTPBearer(auto_error=False)

# ── Cache des clés JWKS ────────────────────────
# On ne veut pas appeler Keycloak à chaque requête.
# On met les clés en cache et on les rafraîchit
# seulement quand nécessaire.
_jwks_cache: Optional[dict] = None
_jwks_last_fetch: Optional[datetime] = None
JWKS_CACHE_TTL_SECONDS = 3600  # 1 heure


class TokenData:
    """
    Données extraites d'un token JWT Keycloak validé.

    Keycloak inclut ces informations dans le payload du JWT :
    - sub : identifiant unique de l'utilisateur (UUID Keycloak)
    - email : email de l'utilisateur
    - name : nom complet
    - preferred_username : nom d'utilisateur
    - realm_access.roles : rôles dans le realm Keycloak
    - resource_access : rôles spécifiques à notre client
    """

    def __init__(self, payload: dict):
        self.user_id: str = payload.get("sub", "")
        self.email: str = payload.get("email", "")
        self.username: str = payload.get("preferred_username", "")
        self.full_name: str = payload.get("name", "")
        self.email_verified: bool = payload.get("email_verified", False)

        # Récupère les rôles du realm
        realm_access = payload.get("realm_access", {})
        self.roles: list[str] = realm_access.get("roles", [])

        # Récupère les rôles spécifiques à notre client WendForge
        resource_access = payload.get("resource_access", {})
        client_access = resource_access.get(settings.KEYCLOAK_CLIENT_ID, {})
        self.client_roles: list[str] = client_access.get("roles", [])

    def has_role(self, role: str) -> bool:
        """Vérifie si l'utilisateur a un rôle spécifique."""
        return role in self.roles or role in self.client_roles

    def is_admin(self) -> bool:
        """Vérifie si l'utilisateur est admin WendForge."""
        return self.has_role("wendforge-admin")

    def __repr__(self) -> str:
        return f"TokenData(user_id={self.user_id}, email={self.email}, roles={self.roles})"


async def get_jwks() -> dict:
    """
    Récupère les clés publiques JWKS de Keycloak.

    JWKS = JSON Web Key Set
    C'est un endpoint Keycloak qui expose ses clés publiques.
    On les utilise pour vérifier la signature des JWT.

    On met en cache le résultat pendant 1 heure pour
    éviter d'appeler Keycloak à chaque requête.
    """
    global _jwks_cache, _jwks_last_fetch

    # Vérifie si le cache est valide
    now = datetime.utcnow()
    if _jwks_cache and _jwks_last_fetch:
        elapsed = (now - _jwks_last_fetch).seconds
        if elapsed < JWKS_CACHE_TTL_SECONDS:
            return _jwks_cache

    # Récupère les clés depuis Keycloak
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.KEYCLOAK_JWKS_URL,
                timeout=10.0  # Timeout de 10 secondes
            )
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_last_fetch = now
            logger.info("JWKS keys refreshed from Keycloak")
            return _jwks_cache

    except httpx.RequestError as e:
        logger.error("Failed to fetch JWKS from Keycloak", error=str(e))
        # Si le cache existe mais est expiré, on le retourne quand même
        # plutôt que de rejeter toutes les requêtes
        if _jwks_cache:
            logger.warning("Using stale JWKS cache")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable"
        )


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> TokenData:
    """
    Vérifie et décode un token JWT Keycloak.

    C'est la dépendance principale d'authentification.
    Elle est injectée dans chaque endpoint protégé :

        @router.get("/projects")
        async def get_projects(user: TokenData = Depends(verify_token)):
            ...

    Étapes de vérification :
    1. Vérifie que le token est présent
    2. Récupère les clés JWKS de Keycloak
    3. Décode et vérifie le token (signature + expiration)
    4. Retourne les données de l'utilisateur

    Raises:
        HTTPException 401 : token manquant, invalide ou expiré
        HTTPException 503 : Keycloak indisponible
    """

    # Vérifie que le token est présent
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Récupère les clés publiques de Keycloak
        jwks = await get_jwks()

        # Décode le token sans vérification d'abord
        # pour récupérer le kid (key ID) utilisé pour signer
        # Décode le header sans vérification
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Trouve la bonne clé dans le JWKS
        signing_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                signing_key = key
                break

        if not signing_key:
            logger.warning("No matching key found in JWKS", kid=kid)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no matching key"
            )

        # Décode et vérifie le token
        # jose vérifie automatiquement :
        # - La signature avec la clé publique
        # - La date d'expiration (exp)
        # - L'émetteur (iss)
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(json.dumps(signing_key))
        payload = pyjwt.decode(
    token,
    public_key,
    algorithms=["RS256"],
    options={
        "verify_exp": True,
        "verify_iss": False,
        "verify_aud": False,
    }
)

        logger.info(
            "Token verified successfully",
            user_id=payload.get("sub"),
            email=payload.get("email")
        )

        return TokenData(payload)

    except ExpiredSignatureError:
        logger.warning("Expired token received")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except InvalidTokenError as e:
        logger.warning("Invalid token", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    token_data: TokenData = Depends(verify_token)
) -> TokenData:
    """
    Alias de verify_token — plus lisible dans les endpoints.

    Usage:
        @router.get("/me")
        async def get_me(user: TokenData = Depends(get_current_user)):
            return {"email": user.email}
    """
    return token_data


async def require_admin(
    token_data: TokenData = Depends(verify_token)
) -> TokenData:
    """
    Vérifie que l'utilisateur est admin WendForge.
    À utiliser sur les endpoints réservés aux admins.

    Usage:
        @router.delete("/projects/{id}")
        async def delete_project(user: TokenData = Depends(require_admin)):
            ...
    """
    if not token_data.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return token_data
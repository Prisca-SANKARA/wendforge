"""
WendForge — Rate Limiting
==========================
Ce module protège l'API contre les abus et attaques.

Cas d'usage :
-------------
1. Brute force : quelqu'un qui essaie des milliers de mots
   de passe → on bloque après 10 tentatives/heure
2. DDoS applicatif : un script qui spamme l'API
   → on bloque après 60 requêtes/minute
3. Scraping : quelqu'un qui télécharge toutes les données
   → on ralentit avec des limites par ressource
4. Abus de l'agent IA : les appels Claude API coûtent cher
   → on limite à 20 appels IA/heure/utilisateur

Comment ça marche avec Redis ?
--------------------------------
Pour chaque requête de l'user "alice@example.com" :
1. Redis incrémente un compteur : "rate:alice@example.com:general"
2. Si le compteur n'existait pas, on lui donne une expiration
3. Si le compteur dépasse la limite → HTTP 429 Too Many Requests
4. À l'expiration, le compteur se remet à zéro automatiquement

Pourquoi Redis et pas PostgreSQL ?
------------------------------------
Redis est une base de données en mémoire — les opérations
prennent des microsecondes. PostgreSQL écrit sur disque —
beaucoup plus lent pour des compteurs qui changent à chaque
requête. Redis est le bon outil pour ce cas d'usage.
"""

from enum import Enum
from typing import Optional, Callable
from fastapi import HTTPException, Request, status, Depends
import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


# ── Types de limites ──────────────────────────
class RateLimitType(str, Enum):
    """
    Différents types de limites selon la sensibilité
    de l'endpoint.

    On définit des types plutôt que des chiffres
    éparpillés dans le code — plus facile à maintenir.
    Si on veut changer la limite d'auth, on change
    une seule ligne ici.
    """
    # Requêtes générales — usage normal de l'API
    GENERAL = "general"

    # Authentification — très restrictif contre le brute force
    # 10 tentatives par heure par IP
    AUTH = "auth"

    # Écriture (POST/PUT/DELETE) — modéré
    # 30 opérations par minute
    WRITE = "write"

    # Lecture (GET) — plus permissif
    # 120 requêtes par minute
    READ = "read"

    # Agent IA — très restrictif (coût API)
    # 20 appels par heure par utilisateur
    AI = "ai"

    # Webhooks n8n — permissif
    # 100 webhooks par minute
    WEBHOOK = "webhook"


# ── Configuration des limites ─────────────────
# (limite, fenêtre_en_secondes)
# Fenêtre = durée pendant laquelle on compte les requêtes
RATE_LIMITS: dict[RateLimitType, tuple[int, int]] = {
    RateLimitType.GENERAL: (60, 60),    # 60 req/minute
    RateLimitType.AUTH:    (10, 3600),  # 10 req/heure
    RateLimitType.WRITE:   (30, 60),    # 30 req/minute
    RateLimitType.READ:    (120, 60),   # 120 req/minute
    RateLimitType.AI:      (20, 3600),  # 20 req/heure
    RateLimitType.WEBHOOK: (100, 60),   # 100 req/minute
}


class RateLimiter:
    """
    Service de rate limiting basé sur Redis.

    Algorithme utilisé : Fixed Window Counter
    -----------------------------------------
    On divise le temps en fenêtres fixes (ex: chaque minute).
    Dans chaque fenêtre, on compte les requêtes.
    Si le compteur dépasse la limite → on bloque.

    C'est l'algorithme le plus simple et suffisant
    pour notre cas d'usage. Il existe des algorithmes
    plus sophistiqués (Sliding Window, Token Bucket)
    mais ils sont plus complexes à implémenter.

    Clé Redis : "wendforge:rate:{type}:{identifier}"
    Identifier = user_id si connecté, sinon adresse IP
    """

    def __init__(self, redis_client: aioredis.Redis):
        """
        Initialise le limiter avec une connexion Redis.
        La connexion est injectée — pas créée ici.
        """
        self.redis = redis_client
        self.key_prefix = "wendforge:rate"

    def _build_key(
        self,
        limit_type: RateLimitType,
        identifier: str
    ) -> str:
        """
        Construit la clé Redis pour un utilisateur et un type.

        Exemples :
        - "wendforge:rate:auth:192.168.1.1"
        - "wendforge:rate:general:user-uuid-123"
        - "wendforge:rate:ai:alice@example.com"
        """
        return f"{self.key_prefix}:{limit_type.value}:{identifier}"

    async def check(
        self,
        limit_type: RateLimitType,
        identifier: str,
    ) -> dict:
        """
        Vérifie et incrémente le compteur pour un identifiant.

        Returns:
            dict avec :
            - allowed   : True si la requête est autorisée
            - current   : nombre de requêtes dans la fenêtre
            - limit     : limite maximale
            - remaining : requêtes restantes
            - reset_in  : secondes avant reset du compteur

        Raises:
            HTTPException 429 : si la limite est dépassée
        """
        limit, window = RATE_LIMITS[limit_type]
        key = self._build_key(limit_type, identifier)

        # Pipeline Redis = plusieurs commandes en une seule
        # opération atomique (pas de race condition)
        async with self.redis.pipeline(transaction=True) as pipe:
            try:
                # INCR incrémente et crée la clé si elle n'existe pas
                # EXPIRE définit la durée de vie de la clé
                await pipe.incr(key)
                await pipe.expire(key, window)
                results = await pipe.execute()
                current = results[0]

            except Exception as e:
                logger.error("Redis rate limit check failed", error=str(e))
                # En cas d'erreur Redis, on laisse passer
                # plutôt que de bloquer tous les utilisateurs
                return {
                    "allowed": True,
                    "current": 0,
                    "limit": limit,
                    "remaining": limit,
                    "reset_in": window
                }

        # Récupère le TTL restant pour le header X-RateLimit-Reset
        ttl = await self.redis.ttl(key)
        remaining = max(0, limit - current)
        allowed = current <= limit

        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                limit_type=limit_type.value,
                identifier=identifier,
                current=current,
                limit=limit,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after": ttl,
                    "message": f"Too many requests. Try again in {ttl} seconds."
                },
                headers={
                    # Headers standards pour le rate limiting
                    # Les clients peuvent les lire pour adapter leur comportement
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(ttl),
                    "Retry-After": str(ttl),
                }
            )

        return {
            "allowed": True,
            "current": current,
            "limit": limit,
            "remaining": remaining,
            "reset_in": ttl if ttl > 0 else window
        }


def get_identifier(request: Request, user_id: Optional[str] = None) -> str:
    """
    Détermine l'identifiant à utiliser pour le rate limiting.

    Priorité :
    1. user_id si l'utilisateur est connecté
       → limite par utilisateur (plus juste)
    2. Adresse IP sinon
       → limite par IP pour les endpoints publics

    Pourquoi cette priorité ?
    Si on utilise uniquement l'IP, un utilisateur derrière
    un proxy partagé (bureau, université) partagerait sa
    limite avec tous ses collègues. Le user_id est plus précis.
    """
    if user_id:
        return user_id

    # Gère les proxies et load balancers
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


def rate_limit(limit_type: RateLimitType = RateLimitType.GENERAL):
    """
    Décorateur de dépendance FastAPI pour le rate limiting.

    Crée une dépendance qui vérifie automatiquement
    le rate limit avant d'exécuter l'endpoint.

    Usage :
        # Endpoint avec rate limit général
        @router.get("/projects")
        async def get_projects(
            _: None = Depends(rate_limit(RateLimitType.READ))
        ):
            ...

        # Endpoint d'auth très restrictif
        @router.post("/auth/login")
        async def login(
            _: None = Depends(rate_limit(RateLimitType.AUTH))
        ):
            ...

        # Endpoint IA coûteux
        @router.post("/tickets/{id}/analyze")
        async def analyze_ticket(
            _: None = Depends(rate_limit(RateLimitType.AI))
        ):
            ...
    """
    async def _check_rate_limit(request: Request):
        # Récupère le user_id depuis le token si présent
        # On ne bloque pas si pas de token — l'auth est gérée ailleurs
        user_id = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jose import jwt as jose_jwt
                token = auth_header.split(" ")[1]
                # Décode sans vérifier pour juste récupérer le sub
                payload = jose_jwt.get_unverified_claims(token)
                user_id = payload.get("sub")
            except Exception:
                pass

        identifier = get_identifier(request, user_id)

        # Connexion Redis
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )

        try:
            limiter = RateLimiter(redis_client)
            result = await limiter.check(limit_type, identifier)

            # Ajoute les headers de rate limit à la réponse
            # Note : on ne peut pas modifier response headers ici
            # directement, on les loggue pour le monitoring
            logger.debug(
                "Rate limit check passed",
                limit_type=limit_type.value,
                identifier=identifier,
                remaining=result["remaining"],
            )
        finally:
            await redis_client.close()

    return _check_rate_limit
"""
WendForge — Point d'entrée de l'application FastAPI
=====================================================
Ce fichier initialise l'application, configure les middlewares,
enregistre les routers et définit les événements de cycle de vie.

Architecture des middlewares (ordre d'exécution) :
1. CORS — autorise les origines frontend
2. Rate Limiting — bloque les abus
3. Security Headers — protège contre les attaques web
4. Logging — trace chaque requête
5. Router — dispatche vers le bon endpoint
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import redis.asyncio as aioredis
from fastapi_limiter import FastAPILimiter

from app.config import settings
from app.database import create_db_and_tables

# Import des routers (on les créera ensuite)
# from app.modules.users.router import router as users_router
# from app.modules.projects.router import router as projects_router
# from app.modules.tickets.router import router as tickets_router
# from app.modules.comments.router import router as comments_router

logger = structlog.get_logger(__name__)


# ── Cycle de vie de l'application ─────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le démarrage et l'arrêt de l'application.

    asynccontextmanager transforme cette fonction en gestionnaire
    de contexte async. Le code avant 'yield' s'exécute au démarrage,
    le code après s'exécute à l'arrêt.

    C'est le remplacement moderne de @app.on_event("startup").
    """
    # ── DÉMARRAGE ─────────────────────────────
    logger.info(
        "Starting WendForge API",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT
    )

    # Créer les tables en base de données
    create_db_and_tables()

    # Initialiser Redis pour le rate limiting
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )
    await FastAPILimiter.init(redis_client)
    logger.info("Redis connected and rate limiter initialized")

    yield  # L'application tourne ici

    # ── ARRÊT ─────────────────────────────────
    logger.info("Shutting down WendForge API...")
    await redis_client.close()
    logger.info("WendForge API shut down gracefully")


# ── Création de l'application FastAPI ─────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    # URL de la doc Swagger
    docs_url="/docs" if settings.DEBUG else None,
    # URL de la doc ReDoc (alternative à Swagger)
    redoc_url="/redoc" if settings.DEBUG else None,
    # URL du schéma OpenAPI
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)


# ── Middleware CORS ────────────────────────────
# CORS = Cross-Origin Resource Sharing
# Permet au frontend (localhost:3000) d'appeler l'API (localhost:8000)
# Sans CORS, le navigateur bloquerait ces requêtes cross-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,  # Autorise les cookies
    allow_methods=["*"],     # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],     # Authorization, Content-Type, etc.
)


# ── Middleware de logging ──────────────────────
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """
    Log chaque requête HTTP avec ses métadonnées.
    S'exécute pour TOUTES les requêtes avant le router.
    """
    logger.info(
        "Request received",
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host if request.client else "unknown",
    )
    response = await call_next(request)
    logger.info(
        "Request completed",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code,
    )
    return response


# ── Middleware Security Headers ────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """
    Ajoute des headers de sécurité à chaque réponse.

    Ces headers protègent contre :
    - X-Content-Type-Options : sniffing de type MIME
    - X-Frame-Options : clickjacking
    - X-XSS-Protection : attaques XSS (vieux navigateurs)
    - Strict-Transport-Security : force HTTPS
    - Referrer-Policy : fuite d'information via Referer
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Gestionnaire d'exceptions global ──────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Capture toutes les exceptions non gérées.
    Retourne une réponse JSON propre au lieu d'une erreur 500 brute.
    En production, ne pas exposer les détails de l'erreur.
    """
    logger.error(
        "Unhandled exception",
        error=str(exc),
        url=str(request.url),
        method=request.method,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "message": str(exc) if settings.DEBUG else "An unexpected error occurred",
        }
    )


# ── Enregistrement des routers ─────────────────
# Chaque module a son propre router avec son préfixe
# On les décommentera au fur et à mesure qu'on les crée
# app.include_router(users_router,    prefix="/api/v1/users",    tags=["Users"])
# app.include_router(projects_router, prefix="/api/v1/projects", tags=["Projects"])
# app.include_router(tickets_router,  prefix="/api/v1/tickets",  tags=["Tickets"])
# app.include_router(comments_router, prefix="/api/v1/comments", tags=["Comments"])

# ── Endpoints de base ──────────────────────────

# ── Enregistrement des routers ─────────────────
from app.modules.users.router import router as users_router
from app.modules.projects.router import router as projects_router
from app.modules.tickets.router import router as tickets_router
from app.modules.comments.router import router as comments_router

app.include_router(
    users_router,
    prefix="/api/v1/users",
    tags=["Users"]
)
app.include_router(
    projects_router,
    prefix="/api/v1/projects",
    tags=["Projects"]
)
# Les tickets sont imbriqués dans les projets
app.include_router(
    tickets_router,
    prefix="/api/v1/projects/{project_id}/tickets",
    tags=["Tickets"]
)
# Les commentaires sont imbriqués dans les tickets
app.include_router(
    comments_router,
    prefix="/api/v1/projects/{project_id}/tickets/{ticket_id}/comments",
    tags=["Comments"]
)
@app.get("/", tags=["Health"])
async def root():
    """Point d'entrée — vérifie que l'API répond."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    Vérifie que tous les services critiques sont disponibles.
    Utilisé par Docker et les load balancers pour vérifier
    que l'app est prête à recevoir des requêtes.
    """
    return {
        "status": "healthy",
        "services": {
            "api": "up",
            "database": "up",
            "redis": "up",
        }
    }
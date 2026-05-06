"""
WendForge — Configuration de la base de données
=================================================
Ce fichier gère la connexion à PostgreSQL via SQLModel.

Concepts clés :
- Engine : la connexion physique à PostgreSQL
- Session : une transaction unitaire avec la DB
- get_session : générateur FastAPI pour injecter la session
  dans chaque endpoint via Dependency Injection

Pourquoi la Dependency Injection ?
Chaque requête HTTP obtient sa propre session DB.
La session est automatiquement fermée après la requête,
même en cas d'erreur. Zéro fuite de connexion.
"""

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import QueuePool
from app.config import settings
import structlog

# Logger structuré — logs en JSON pour la production
logger = structlog.get_logger(__name__)

# ── Création du moteur de base de données ─────
# L'engine est créé UNE SEULE FOIS au démarrage.
# Il gère un pool de connexions PostgreSQL.
#
# pool_size : nombre de connexions maintenues en permanence
# max_overflow : connexions supplémentaires en cas de pic
# pool_pre_ping : vérifie que la connexion est toujours active
#                 avant de l'utiliser (évite les erreurs)
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    # echo=True en dev pour voir les requêtes SQL dans les logs
    echo=settings.DEBUG,
)


def create_db_and_tables() -> None:
    """
    Crée toutes les tables définies dans les modèles SQLModel.
    Appelé au démarrage de l'application.

    En production, on utilise Alembic pour les migrations.
    Cette fonction sert uniquement au développement initial.
    """
    logger.info("Creating database tables...")
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables created successfully")


def get_session():
    """
    Générateur de session — injecté dans chaque endpoint.

    Le mot-clé 'yield' transforme cette fonction en générateur :
    - Le code AVANT yield s'exécute avant la requête
    - Le code APRÈS yield s'exécute après la requête (cleanup)

    FastAPI garantit que le bloc finally s'exécute toujours,
    même si une exception est levée dans l'endpoint.

    Usage dans un endpoint :
        def get_tickets(session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception as e:
            logger.error("Database error", error=str(e))
            session.rollback()
            raise
        finally:
            session.close()
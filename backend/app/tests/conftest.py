"""
WendForge — Configuration des tests pytest
==========================================
conftest.py est le fichier de configuration global de pytest.
Les fixtures définies ici sont disponibles dans tous les tests.

Fixtures principales :
- engine     : moteur DB en mémoire SQLite pour les tests
- session    : session DB isolée par test
- client     : client HTTP FastAPI pour simuler des requêtes
- mock_user  : utilisateur de test avec token simulé
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool
from unittest.mock import patch, MagicMock

from app.main import app
from app.database import get_session
from app.core.security import get_current_user, TokenData


# ── Base de données de test ───────────────────
# On utilise SQLite en mémoire pour les tests.
# Pourquoi SQLite et pas PostgreSQL ?
# - Plus rapide — pas de connexion réseau
# - Isolé — chaque test repart de zéro
# - Pas besoin de Docker pour les tests unitaires
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(name="engine")
def engine_fixture():
    """
    Crée un moteur SQLite en mémoire pour les tests.
    
    StaticPool garantit que toutes les connexions
    utilisent la même instance en mémoire — essentiel
    pour SQLite qui ne supporte pas les connexions multiples.
    """
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    """
    Crée une session DB isolée pour chaque test.
    
    La session est rollback après chaque test —
    les données d'un test ne contaminent pas le suivant.
    """
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture(name="mock_token_data")
def mock_token_data_fixture():
    """
    Crée un TokenData simulé pour les tests.
    
    On ne veut pas appeler Keycloak dans les tests —
    on simule un utilisateur connecté directement.
    """
    token_data = MagicMock(spec=TokenData)
    token_data.user_id = "test-keycloak-uuid-123"
    token_data.email = "djamila.test@wendforge.com"
    token_data.username = "djamila_test"
    token_data.full_name = "Djamila Test"
    token_data.roles = []
    token_data.client_roles = []
    token_data.is_admin = MagicMock(return_value=False)
    token_data.has_role = MagicMock(return_value=False)
    return token_data


@pytest.fixture(name="client")
def client_fixture(session, mock_token_data):
    """
    Crée un client HTTP de test FastAPI.
    
    Override les dépendances FastAPI :
    - get_session → session de test SQLite
    - get_current_user → utilisateur simulé (pas Keycloak)
    - FastAPILimiter → désactivé en test
    
    Pourquoi override get_current_user ?
    Les tests ne doivent pas dépendre de Keycloak.
    On simule un utilisateur connecté directement.
    """
    def override_get_session():
        yield session

    def override_get_current_user():
        return mock_token_data

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    # Désactive le rate limiting en test
    with patch("app.core.rate_limit.RateLimiter.check") as mock_check:
        mock_check.return_value = {
            "allowed": True,
            "current": 1,
            "limit": 60,
            "remaining": 59,
            "reset_in": 60
        }

        with patch("fastapi_limiter.FastAPILimiter.init"):
            with TestClient(app) as client:
                yield client

    app.dependency_overrides.clear()
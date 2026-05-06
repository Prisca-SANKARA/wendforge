"""
WendForge — Configuration centralisée
======================================
Toutes les variables d'environnement sont lues ici.
Pydantic Settings valide automatiquement les types
et lève une erreur claire si une variable est manquante.

Pourquoi centraliser la config ?
- Un seul endroit pour chercher une variable
- Validation automatique au démarrage
- Tests plus faciles (on peut surcharger la config)
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """
    Configuration de l'application WendForge.
    Chaque attribut correspond à une variable d'environnement.
    Le nom de l'attribut est automatiquement mis en majuscules
    pour correspondre à la variable d'environnement.
    """

    # ── Application ───────────────────────────
    APP_NAME: str = "WendForge API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "Enterprise project management API with Keycloak SSO, MFA and AI agent"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # ── Base de données ───────────────────────
    DATABASE_URL: str
    # Pool de connexions — combien de connexions simultanées
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ── Redis ─────────────────────────────────
    REDIS_URL: str

    # ── Keycloak ──────────────────────────────
    KEYCLOAK_URL: str
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str

    # URL complète du endpoint JWKS de Keycloak
    # JWKS = JSON Web Key Set — les clés publiques pour vérifier les JWT
    @property
    def KEYCLOAK_JWKS_URL(self) -> str:
        return f"{self.KEYCLOAK_URL}/realms/{self.KEYCLOAK_REALM}/protocol/openid-connect/certs"

    # URL pour récupérer les infos d'un token
    @property
    def KEYCLOAK_USERINFO_URL(self) -> str:
        return f"{self.KEYCLOAK_URL}/realms/{self.KEYCLOAK_REALM}/protocol/openid-connect/userinfo"

    # ── Agent IA ──────────────────────────────
    CLAUDE_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    CLAUDE_MAX_TOKENS: int = 1000

    # ── n8n Webhooks ──────────────────────────
    N8N_WEBHOOK_URL: str = "http://n8n:5678/webhook/wendforge"

    # ── Rate Limiting ─────────────────────────
    # Nombre max de requêtes par minute par utilisateur
    RATE_LIMIT_PER_MINUTE: int = 60
    # Nombre max de tentatives de connexion par heure
    AUTH_RATE_LIMIT_PER_HOUR: int = 10

    # ── CORS ──────────────────────────────────
    # Origines autorisées à appeler l'API
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",  # Frontend React en dev
        "http://localhost:5173",  # Vite dev server
    ]

    class Config:
        # Lit les variables depuis le fichier .env
        env_file = ".env"
        # Respecte la casse des variables
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    Retourne l'instance de configuration.

    @lru_cache() signifie que la config est chargée UNE SEULE FOIS
    au démarrage et mise en cache. Les appels suivants retournent
    la même instance sans relire le fichier .env.

    Usage:
        from app.config import get_settings
        settings = get_settings()
        print(settings.APP_NAME)
    """
    return Settings()


# Instance globale pour les imports directs
settings = get_settings()
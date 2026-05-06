-- ─────────────────────────────────────────────
-- WendForge — Initialisation PostgreSQL
-- Crée les bases de données pour l'app et Keycloak
-- ─────────────────────────────────────────────

-- Base de données pour Keycloak
-- (Keycloak a besoin de sa propre DB séparée)
CREATE DATABASE keycloak;
GRANT ALL PRIVILEGES ON DATABASE keycloak TO wendforge_user;

-- Base de données pour n8n
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO wendforge_user;
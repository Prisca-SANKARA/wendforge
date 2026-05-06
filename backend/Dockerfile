# ─────────────────────────────────────────────
# WENDFORGE — Dockerfile Backend FastAPI
# Multi-stage build pour optimiser la taille de l'image
# ─────────────────────────────────────────────

# ── STAGE 1 : Builder ────────────────────────
# On utilise une image Python légère (alpine = minimal)
# Ce stage installe toutes les dépendances
FROM python:3.12-slim AS builder

# Définit le répertoire de travail dans le container
WORKDIR /app

# Copie uniquement le fichier des dépendances d'abord
# Pourquoi ? Docker cache chaque étape — si requirements.txt
# ne change pas, Docker réutilise le cache et ne réinstalle
# pas tout à chaque build. Gain de temps énorme.
COPY requirements.txt .

# Installe les dépendances dans un dossier séparé
# --no-cache-dir : n'enregistre pas le cache pip (image plus légère)
# --prefix=/install : installe dans /install au lieu de /usr
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── STAGE 2 : Production ─────────────────────
# Image finale — plus légère car elle ne contient pas
# les outils de build, seulement ce qui est nécessaire
FROM python:3.12-slim AS production

# Métadonnées de l'image
LABEL maintainer="SANKARA P. DJAMILATOU PRISCA"
LABEL project="WendForge"
LABEL version="1.0.0"

# Variables d'environnement Python
# PYTHONDONTWRITEBYTECODE : n'écrit pas les fichiers .pyc
# PYTHONUNBUFFERED : affiche les logs immédiatement (pas de buffer)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copie les dépendances installées depuis le stage builder
COPY --from=builder /install /usr/local

# Copie le code source de l'application
COPY . .

# Expose le port 8000 (documentation uniquement,
# le vrai mapping est dans docker-compose.yml)
EXPOSE 8000

# Commande de démarrage
# --host 0.0.0.0 : écoute sur toutes les interfaces réseau
# --port 8000 : port d'écoute
# --reload : redémarre automatiquement quand le code change
# --workers 1 : 1 worker en dev (plus en prod)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
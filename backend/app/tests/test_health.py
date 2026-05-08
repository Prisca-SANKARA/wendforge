"""
WendForge — Tests Health Check
================================
Tests simples pour vérifier que l'API répond correctement.
C'est le test le plus basique — si ça échoue, tout échoue.
"""

import pytest


def test_root_endpoint(client):
    """
    Vérifie que l'endpoint racine répond avec les bonnes infos.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "WendForge API"
    assert data["status"] == "running"


def test_health_endpoint(client):
    """
    Vérifie que le health check répond correctement.
    """
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
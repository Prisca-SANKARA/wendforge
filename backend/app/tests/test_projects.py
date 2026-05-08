"""
WendForge — Tests Projects
===========================
Tests pour les endpoints projets.

On teste :
- Création d'un projet
- Récupération de la liste
- Récupération d'un projet spécifique
- Modification d'un projet
- Suppression d'un projet
- Gestion des membres
"""

import pytest


@pytest.fixture
def created_project(client):
    """
    Fixture qui crée un projet de test.
    Réutilisée dans plusieurs tests.
    """
    # Crée d'abord le user
    client.get("/api/v1/users/me")

    response = client.post(
        "/api/v1/projects/",
        json={
            "name": "Projet Test WendForge",
            "description": "Un projet de test",
            "color": "#8b5cf6",
            "emoji": "🚀"
        }
    )
    assert response.status_code == 201
    return response.json()


def test_create_project(client):
    """
    Vérifie qu'on peut créer un projet.
    Le créateur doit être automatiquement ajouté comme ADMIN.
    """
    client.get("/api/v1/users/me")

    response = client.post(
        "/api/v1/projects/",
        json={
            "name": "Mon Projet Test",
            "description": "Description du projet",
            "color": "#667eea",
        }
    )
    assert response.status_code == 201
    data = response.json()

    assert "id" in data
    assert data["name"] == "Mon Projet Test"
    assert data["description"] == "Description du projet"
    assert data["color"] == "#667eea"
    assert data["is_archived"] is False
    assert "owner_id" in data


def test_get_my_projects(client, created_project):
    """
    Vérifie qu'on récupère bien ses projets.
    """
    response = client.get("/api/v1/projects/")
    assert response.status_code == 200

    projects = response.json()
    assert isinstance(projects, list)
    assert len(projects) >= 1

    # Vérifie que le projet créé est dans la liste
    project_ids = [p["id"] for p in projects]
    assert created_project["id"] in project_ids


def test_get_project_by_id(client, created_project):
    """
    Vérifie qu'on peut récupérer un projet par son ID.
    """
    project_id = created_project["id"]
    response = client.get(f"/api/v1/projects/{project_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["name"] == created_project["name"]


def test_get_project_not_found(client):
    """
    Vérifie qu'on obtient une 404 pour un projet inexistant.
    """
    client.get("/api/v1/users/me")
    response = client.get("/api/v1/projects/uuid-inexistant")
    assert response.status_code == 404


def test_update_project(client, created_project):
    """
    Vérifie qu'on peut modifier un projet dont on est ADMIN.
    """
    project_id = created_project["id"]
    response = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Projet Modifié", "description": "Nouvelle description"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Projet Modifié"
    assert data["description"] == "Nouvelle description"


def test_delete_project(client, created_project):
    """
    Vérifie qu'on peut supprimer un projet dont on est ADMIN.
    """
    project_id = created_project["id"]
    response = client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 204

    # Vérifie que le projet n'existe plus
    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 404
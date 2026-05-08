"""
WendForge — Tests Tickets
==========================
Tests pour les endpoints tickets.

On teste :
- Création d'un ticket
- Pagination et filtres
- Modification de statut
- Suppression douce
"""

import pytest


@pytest.fixture
def project_and_ticket(client):
    """
    Fixture qui crée un projet ET un ticket de test.
    """
    client.get("/api/v1/users/me")

    # Crée le projet
    proj_response = client.post(
        "/api/v1/projects/",
        json={"name": "Projet Tickets Test", "color": "#8b5cf6"}
    )
    assert proj_response.status_code == 201
    project = proj_response.json()

    # Crée le ticket
    ticket_response = client.post(
        f"/api/v1/projects/{project['id']}/tickets/",
        json={
            "title": "Bug critique sur la page login",
            "description": "La page login crash sur mobile",
            "priority": "high",
            "ticket_type": "bug",
        }
    )
    assert ticket_response.status_code == 201
    ticket = ticket_response.json()

    return {"project": project, "ticket": ticket}


def test_create_ticket(client):
    """
    Vérifie la création d'un ticket avec numérotation auto.
    """
    client.get("/api/v1/users/me")
    proj = client.post(
        "/api/v1/projects/",
        json={"name": "Test Create Ticket"}
    ).json()

    response = client.post(
        f"/api/v1/projects/{proj['id']}/tickets/",
        json={
            "title": "Premier ticket du projet",
            "priority": "medium",
            "ticket_type": "task",
        }
    )
    assert response.status_code == 201
    data = response.json()

    assert data["title"] == "Premier ticket du projet"
    assert data["ticket_number"] == 1
    assert data["status"] == "todo"
    assert data["priority"] == "medium"
    assert "creator" in data
    assert data["creator"]["username"] == "djamila_test"


def test_ticket_auto_numbering(client):
    """
    Vérifie que les tickets sont numérotés séquentiellement.
    """
    client.get("/api/v1/users/me")
    proj = client.post(
        "/api/v1/projects/",
        json={"name": "Test Numérotation"}
    ).json()

    ticket1 = client.post(
        f"/api/v1/projects/{proj['id']}/tickets/",
        json={"title": "Ticket 1", "ticket_type": "task"}
    ).json()

    ticket2 = client.post(
        f"/api/v1/projects/{proj['id']}/tickets/",
        json={"title": "Ticket 2", "ticket_type": "task"}
    ).json()

    ticket3 = client.post(
        f"/api/v1/projects/{proj['id']}/tickets/",
        json={"title": "Ticket 3", "ticket_type": "task"}
    ).json()

    assert ticket1["ticket_number"] == 1
    assert ticket2["ticket_number"] == 2
    assert ticket3["ticket_number"] == 3


def test_get_project_tickets(client, project_and_ticket):
    """
    Vérifie la récupération paginée des tickets.
    """
    project_id = project_and_ticket["project"]["id"]
    response = client.get(
        f"/api/v1/projects/{project_id}/tickets/",
        params={"page": 1, "limit": 10}
    )
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    assert "total" in data
    assert "pages" in data
    assert data["total"] >= 1
    assert isinstance(data["data"], list)


def test_update_ticket_status(client, project_and_ticket):
    """
    Vérifie qu'on peut changer le statut d'un ticket.
    """
    project_id = project_and_ticket["project"]["id"]
    ticket_id = project_and_ticket["ticket"]["id"]

    response = client.patch(
        f"/api/v1/projects/{project_id}/tickets/{ticket_id}",
        json={"status": "in_progress"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_soft_delete_ticket(client, project_and_ticket):
    """
    Vérifie la suppression douce — le ticket disparaît
    des listes mais n'est pas supprimé de la DB.
    """
    project_id = project_and_ticket["project"]["id"]
    ticket_id = project_and_ticket["ticket"]["id"]

    # Supprime le ticket
    response = client.delete(
        f"/api/v1/projects/{project_id}/tickets/{ticket_id}"
    )
    assert response.status_code == 204

    # Vérifie qu'il n'apparaît plus
    response = client.get(
        f"/api/v1/projects/{project_id}/tickets/{ticket_id}"
    )
    assert response.status_code == 404
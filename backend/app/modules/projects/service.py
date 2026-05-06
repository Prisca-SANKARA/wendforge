"""
WendForge — Service Project
============================
Logique métier pour les projets et memberships.

Responsabilités :
- CRUD des projets
- Gestion des membres (ajouter, retirer, changer rôle)
- Vérifier les droits avant chaque opération
- Déclencher les webhooks n8n sur les événements
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select
from fastapi import HTTPException, status
import structlog

from app.modules.projects.models import Project, ProjectMember
from app.modules.projects.schemas import (
    ProjectCreate, ProjectUpdate,
    ProjectMemberAdd, ProjectMemberUpdate
)
from app.core.permissions import ProjectRole, Permission, check_permission
from app.modules.users.models import User

logger = structlog.get_logger(__name__)


class ProjectService:

    def __init__(self, session: Session):
        self.session = session

    # ── CRUD Projets ──────────────────────────

    def create(self, data: ProjectCreate, owner: User) -> Project:
        """
        Crée un projet et ajoute automatiquement
        le créateur comme ADMIN du projet.

        Pourquoi ADMIN automatiquement ?
        Le créateur doit pouvoir gérer son projet
        sans qu'un autre admin lui donne les droits.
        """
        project = Project(
            **data.model_dump(),
            owner_id=owner.id
        )
        self.session.add(project)
        self.session.flush()

        # Ajoute le créateur comme ADMIN
        membership = ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role=ProjectRole.ADMIN
        )
        self.session.add(membership)
        self.session.flush()

        logger.info(
            "Project created",
            project_id=project.id,
            owner_id=owner.id
        )
        return project

    def get_by_id(self, project_id: str) -> Optional[Project]:
        """Récupère un projet par son ID."""
        return self.session.get(Project, project_id)

    def get_by_id_or_404(self, project_id: str) -> Project:
        """
        Récupère un projet ou lève une 404.
        Pattern courant en FastAPI — évite de vérifier
        None dans chaque endpoint.
        """
        project = self.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        return project

    def get_user_projects(self, user_id: str) -> List[Project]:
        """
        Récupère tous les projets dont l'user est membre.
        On joint ProjectMember et Project pour ne retourner
        que les projets accessibles à cet user.
        """
        statement = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .where(Project.is_archived == False)
            .order_by(Project.updated_at.desc())
        )
        return list(self.session.exec(statement).all())

    def update(
        self,
        project: Project,
        data: ProjectUpdate,
        requester_role: ProjectRole
    ) -> Project:
        """Met à jour un projet après vérification des droits."""
        check_permission(requester_role, Permission.UPDATE_PROJECT)

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(project, key, value)

        project.updated_at = datetime.now(timezone.utc)
        self.session.add(project)
        self.session.flush()
        logger.info("Project updated", project_id=project.id)
        return project

    def delete(
        self,
        project: Project,
        requester_role: ProjectRole
    ) -> None:
        """
        Supprime un projet et toutes ses données.
        Réservé aux admins uniquement.
        """
        check_permission(requester_role, Permission.DELETE_PROJECT)
        self.session.delete(project)
        self.session.flush()
        logger.info("Project deleted", project_id=project.id)

    # ── Gestion des membres ───────────────────

    def get_member(
        self,
        project_id: str,
        user_id: str
    ) -> Optional[ProjectMember]:
        """Récupère le membership d'un user dans un projet."""
        statement = (
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.user_id == user_id)
        )
        return self.session.exec(statement).first()

    def get_member_or_403(
        self,
        project_id: str,
        user_id: str
    ) -> ProjectMember:
        """
        Récupère le membership ou lève une 403.
        Si l'user n'est pas membre du projet,
        il n'a même pas le droit de savoir que le projet existe.
        """
        member = self.get_member(project_id, user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this project"
            )
        return member

    def add_member(
        self,
        project: Project,
        data: ProjectMemberAdd,
        requester_role: ProjectRole,
        invited_by: str
    ) -> ProjectMember:
        """Ajoute un membre au projet."""
        check_permission(requester_role, Permission.MANAGE_MEMBERS)

        # Vérifie que l'user n'est pas déjà membre
        existing = self.get_member(project.id, data.user_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this project"
            )

        membership = ProjectMember(
            project_id=project.id,
            user_id=data.user_id,
            role=data.role,
            invited_by=invited_by
        )
        self.session.add(membership)
        self.session.flush()
        logger.info(
            "Member added to project",
            project_id=project.id,
            user_id=data.user_id,
            role=data.role
        )
        return membership

    def update_member_role(
        self,
        membership: ProjectMember,
        data: ProjectMemberUpdate,
        requester_role: ProjectRole
    ) -> ProjectMember:
        """Change le rôle d'un membre."""
        check_permission(requester_role, Permission.MANAGE_MEMBERS)
        membership.role = data.role
        self.session.add(membership)
        self.session.flush()
        return membership

    def remove_member(
        self,
        membership: ProjectMember,
        requester_role: ProjectRole
    ) -> None:
        """Retire un membre du projet."""
        check_permission(requester_role, Permission.MANAGE_MEMBERS)
        self.session.delete(membership)
        self.session.flush()
"""
WendForge — Service Comment
============================
Logique métier pour les commentaires.

Fonctionnalités :
- Créer/modifier/supprimer des commentaires
- Répondre à un commentaire (threads)
- Détecter les mentions @username
- Déclencher les notifications n8n
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select
from fastapi import HTTPException, status
import json
import structlog

from app.modules.comments.models import Comment
from app.modules.comments.schemas import CommentCreate, CommentUpdate
from app.modules.users.models import User

logger = structlog.get_logger(__name__)


class CommentService:

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        ticket_id: str,
        data: CommentCreate,
        author: User,
    ) -> Comment:
        """Crée un commentaire sur un ticket."""

        # Si c'est une réponse, vérifie que le parent existe
        if data.parent_id:
            parent = self.session.get(Comment, data.parent_id)
            if not parent or parent.ticket_id != ticket_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent comment not found"
                )

        mentions_str = (
            json.dumps(data.mentions)
            if data.mentions else None
        )

        comment = Comment(
            content=data.content,
            mentions=mentions_str,
            parent_id=data.parent_id,
            ticket_id=ticket_id,
            author_id=author.id,
        )
        self.session.add(comment)
        self.session.flush()

        logger.info(
            "Comment created",
            comment_id=comment.id,
            ticket_id=ticket_id,
            author_id=author.id
        )
        return comment

    def get_ticket_comments(
        self,
        ticket_id: str
    ) -> List[Comment]:
        """
        Récupère les commentaires racines d'un ticket.
        On ne récupère que les commentaires sans parent
        (parent_id=None) — les replies sont chargées
        via la relation SQLModel.
        """
        statement = (
            select(Comment)
            .where(Comment.ticket_id == ticket_id)
            .where(Comment.parent_id == None)
            .where(Comment.is_deleted == False)
            .order_by(Comment.created_at.asc())
        )
        return list(self.session.exec(statement).all())

    def update(
        self,
        comment: Comment,
        data: CommentUpdate,
        requester_id: str,
    ) -> Comment:
        """
        Modifie un commentaire.
        Seul l'auteur peut modifier son commentaire.
        """
        if comment.author_id != requester_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own comments"
            )

        comment.content = data.content
        comment.mentions = (
            json.dumps(data.mentions)
            if data.mentions else None
        )
        comment.is_edited = True
        comment.edited_at = datetime.now(timezone.utc)
        comment.updated_at = datetime.now(timezone.utc)
        self.session.add(comment)
        self.session.flush()
        return comment

    def soft_delete(
        self,
        comment: Comment,
        requester_id: str,
        is_admin: bool = False,
    ) -> Comment:
        """
        Suppression douce d'un commentaire.
        L'auteur ou un admin peut supprimer.
        Le contenu est remplacé par un message générique
        pour ne pas casser les threads de réponses.
        """
        if comment.author_id != requester_id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own comments"
            )

        comment.is_deleted = True
        comment.content = "[Ce commentaire a été supprimé]"
        comment.updated_at = datetime.now(timezone.utc)
        self.session.add(comment)
        self.session.flush()
        return comment
"""
WendForge — Service User
=========================
Logique métier pour les utilisateurs.

Responsabilités :
- Créer/récupérer un user après connexion Keycloak
- Mettre à jour le profil
- Synchroniser avec les données Keycloak

Principe important :
--------------------
Un user est créé dans notre DB la PREMIÈRE FOIS
qu'il se connecte via Keycloak. Avant ça, il existe
dans Keycloak mais pas dans notre DB.
C'est le pattern "lazy user creation" — on ne crée
pas les users en avance, on les crée à la demande.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Session, select
import structlog

from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate
from app.core.security import TokenData

logger = structlog.get_logger(__name__)


class UserService:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Récupère un user par son ID WendForge."""
        return self.session.get(User, user_id)

    def get_by_keycloak_id(self, keycloak_id: str) -> Optional[User]:
        """
        Récupère un user par son ID Keycloak.
        Utilisé après vérification du JWT pour
        retrouver le user dans notre DB.
        """
        statement = select(User).where(User.keycloak_id == keycloak_id)
        return self.session.exec(statement).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """Récupère un user par email."""
        statement = select(User).where(User.email == email)
        return self.session.exec(statement).first()

    def get_or_create_from_token(self, token_data: TokenData) -> User:
        """
        Récupère le user depuis notre DB ou le crée
        s'il se connecte pour la première fois.

        C'est la fonction appelée à chaque requête
        authentifiée — elle synchronise notre DB
        avec les données Keycloak.

        Args:
            token_data : données extraites du JWT Keycloak

        Returns:
            L'objet User de notre DB
        """
        # Cherche le user par son ID Keycloak
        user = self.get_by_keycloak_id(token_data.user_id)

        if user:
            # Met à jour last_login à chaque connexion
            user.last_login = datetime.now(timezone.utc)
            # Synchronise email et nom si changés dans Keycloak
            if user.email != token_data.email:
                user.email = token_data.email
            if user.full_name != token_data.full_name:
                user.full_name = token_data.full_name
            self.session.add(user)
            logger.info("User logged in", user_id=user.id, email=user.email)
            return user

        # Première connexion — on crée le user
        user = User(
            keycloak_id=token_data.user_id,
            email=token_data.email,
            username=token_data.username or token_data.email.split("@")[0],
            full_name=token_data.full_name or token_data.username,
            last_login=datetime.now(timezone.utc),
        )
        self.session.add(user)
        self.session.flush()
        logger.info(
            "New user created",
            user_id=user.id,
            email=user.email
        )
        return user

    def update(self, user: User, data: UserUpdate) -> User:
        """
        Met à jour le profil d'un user.
        On utilise model_dump(exclude_unset=True) pour ne
        modifier que les champs envoyés — pas écraser
        avec None les champs non envoyés.
        """
        update_data = data.model_dump(exclude_unset=True)

        # Convertit preferences dict en JSON string
        if "preferences" in update_data and update_data["preferences"]:
            import json
            update_data["preferences"] = json.dumps(update_data["preferences"])

        for key, value in update_data.items():
            setattr(user, key, value)

        user.updated_at = datetime.now(timezone.utc)
        self.session.add(user)
        self.session.flush()
        logger.info("User updated", user_id=user.id)
        return user

    def deactivate(self, user: User) -> User:
        """Désactive un compte sans le supprimer."""
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        self.session.add(user)
        self.session.flush()
        return user
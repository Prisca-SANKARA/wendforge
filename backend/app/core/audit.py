"""
WendForge — Système d'Audit Log
=================================
Ce module trace toutes les actions importantes dans WendForge.

Pourquoi un audit log ?
------------------------
1. Sécurité : détecter les comportements suspects
   (ex: un user qui supprime 50 tickets en 1 minute)
2. Conformité : certaines normes (ISO 27001, RGPD) exigent
   de tracer qui accède à quelles données
3. Debug : comprendre ce qui s'est passé en cas de problème
4. Responsabilité : prouver qu'une action a été faite par tel user

Qu'est-ce qu'on trace ?
------------------------
- Qui    : user_id + email de l'utilisateur
- Quoi   : action effectuée (CREATE_TICKET, DELETE_PROJECT...)
- Sur quoi : resource_type + resource_id (quel ticket, quel projet)
- Quand  : timestamp précis
- Comment : adresse IP + user agent (navigateur)
- Résultat : succès ou échec + détails

Architecture :
--------------
On sépare le modèle SQLModel (table en DB) de la logique
d'enregistrement. Le service AuditService est le seul
endroit où on écrit des logs — pas de logs éparpillés
dans le code.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field, Session
import structlog
import uuid

logger = structlog.get_logger(__name__)


# ── Types d'actions auditées ──────────────────
class AuditAction(str, Enum):
    """
    Toutes les actions traçables dans WendForge.

    Nomenclature : VERBE_RESSOURCE
    - Verbe  : CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT...
    - Ressource : USER, PROJECT, TICKET, COMMENT...

    On utilise str comme base pour que les valeurs soient
    directement stockables en base de données sous forme
    de texte lisible (pas juste un entier mystérieux).
    """
    # Authentification
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"

    # Utilisateurs
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ROLE_CHANGED = "user_role_changed"

    # Projets
    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"
    PROJECT_MEMBER_ADDED = "project_member_added"
    PROJECT_MEMBER_REMOVED = "project_member_removed"
    PROJECT_MEMBER_ROLE_CHANGED = "project_member_role_changed"

    # Tickets
    TICKET_CREATED = "ticket_created"
    TICKET_UPDATED = "ticket_updated"
    TICKET_DELETED = "ticket_deleted"
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    TICKET_PRIORITY_CHANGED = "ticket_priority_changed"

    # Commentaires
    COMMENT_CREATED = "comment_created"
    COMMENT_UPDATED = "comment_updated"
    COMMENT_DELETED = "comment_deleted"

    # Sécurité
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

    # Agent IA
    AI_ANALYSIS_REQUESTED = "ai_analysis_requested"
    AI_SUGGESTION_APPLIED = "ai_suggestion_applied"


# ── Modèle de la table audit_logs ────────────
class AuditLog(SQLModel, table=True):
    """
    Table audit_logs dans PostgreSQL.

    SQLModel génère automatiquement la table avec tous ces champs.
    'table=True' indique que c'est une vraie table DB,
    pas juste un schéma de validation.

    Chaque ligne = une action tracée dans WendForge.
    """
    __tablename__ = "audit_logs"

    # Identifiant unique de chaque log
    # uuid4() génère un UUID aléatoire — plus sûr qu'un
    # auto-increment car il ne révèle pas le nombre total de logs
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True
    )

    # Qui a fait l'action ?
    # Nullable car certaines actions se font sans user connecté
    # (ex: tentative de connexion avec mauvais token)
    user_id: Optional[str] = Field(default=None, index=True)
    user_email: Optional[str] = Field(default=None)

    # Quelle action ?
    action: AuditAction = Field(index=True)

    # Sur quelle ressource ?
    # resource_type : "ticket", "project", "user"...
    # resource_id   : l'UUID de la ressource concernée
    resource_type: Optional[str] = Field(default=None)
    resource_id: Optional[str] = Field(default=None, index=True)

    # Détails supplémentaires en JSON
    # Ex: {"old_status": "todo", "new_status": "in_progress"}
    # On stocke comme str car SQLModel ne supporte pas JSON natif
    details: Optional[str] = Field(default=None)

    # Contexte réseau
    ip_address: Optional[str] = Field(default=None)
    user_agent: Optional[str] = Field(default=None)

    # L'action a-t-elle réussi ?
    success: bool = Field(default=True)

    # Message d'erreur si success=False
    error_message: Optional[str] = Field(default=None)

    # Quand ?
    # timezone.utc garantit que tous les timestamps sont en UTC
    # peu importe le fuseau horaire du serveur
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Service d'audit ───────────────────────────
class AuditService:
    """
    Service centralisé pour écrire les logs d'audit.

    Pourquoi une classe et pas des fonctions libres ?
    - Encapsulation : toute la logique d'audit est ici
    - Testabilité : on peut mocker AuditService dans les tests
    - Évolutivité : demain on peut ajouter un export vers
      un système SIEM (Security Information and Event Management)
      sans modifier tous les endroits qui appellent audit()

    Usage dans un endpoint :
        audit = AuditService(session)
        await audit.log(
            action=AuditAction.TICKET_CREATED,
            user_id=current_user.user_id,
            user_email=current_user.email,
            resource_type="ticket",
            resource_id=new_ticket.id,
            details={"title": new_ticket.title},
            request=request,
        )
    """

    def __init__(self, session: Session):
        """
        Initialise le service avec une session DB.
        La session est injectée — pas créée ici.
        Principe de l'Inversion de Dépendances (SOLID).
        """
        self.session = session

    async def log(
        self,
        action: AuditAction,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """
        Enregistre une action dans la table audit_logs.

        Args:
            action       : L'action effectuée (enum AuditAction)
            user_id      : ID Keycloak de l'utilisateur
            user_email   : Email de l'utilisateur
            resource_type: Type de ressource ("ticket", "project"...)
            resource_id  : ID de la ressource concernée
            details      : Données supplémentaires (dict → JSON string)
            ip_address   : Adresse IP du client
            user_agent   : Navigateur/client HTTP
            success      : True si l'action a réussi
            error_message: Message d'erreur si success=False

        Returns:
            L'objet AuditLog créé en base de données
        """
        import json

        # Convertit le dict details en JSON string pour le stockage
        details_str = json.dumps(details, ensure_ascii=False) if details else None

        audit_log = AuditLog(
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details_str,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )

        # Sauvegarde en base de données
        self.session.add(audit_log)
        self.session.flush()  # flush() envoie la requête SQL sans commit
                              # Le commit se fait dans get_session()
                              # après que tout l'endpoint est terminé

        # Log structuré pour la console/fichier
        log_method = logger.info if success else logger.warning
        log_method(
            "Audit log recorded",
            action=action.value,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            success=success,
        )

        return audit_log

    async def log_from_request(
        self,
        action: AuditAction,
        request,  # FastAPI Request object
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """
        Version de log() qui extrait automatiquement
        l'IP et le User-Agent depuis la requête FastAPI.

        C'est la méthode à utiliser dans les endpoints
        car elle capture le contexte réseau automatiquement.

        Usage:
            @router.post("/tickets")
            async def create_ticket(request: Request, ...):
                await audit.log_from_request(
                    action=AuditAction.TICKET_CREATED,
                    request=request,
                    user_id=current_user.user_id,
                    ...
                )
        """
        # Extrait l'adresse IP réelle
        # X-Forwarded-For est rempli par les proxies/load balancers
        # Si absent, on utilise l'IP directe du client
        ip_address = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )

        user_agent = request.headers.get("User-Agent", None)

        return await self.log(
            action=action,
            user_id=user_id,
            user_email=user_email,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )


# ── Fonction utilitaire ───────────────────────
def get_audit_service(
    session: Session,
) -> AuditService:
    """
    Crée et retourne une instance d'AuditService.

    Usage dans les endpoints FastAPI :
        @router.post("/tickets")
        async def create_ticket(
            session: Session = Depends(get_session),
        ):
            audit = get_audit_service(session)
            await audit.log(...)
    """
    return AuditService(session)
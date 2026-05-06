"""
WendForge — Agent IA (Claude API)
==================================
Ce module implémente l'agent IA de WendForge.

Architecture de l'agent :
--------------------------
L'agent suit le pattern "Tool Use" de Claude :
1. On envoie le contexte (ticket + projet + historique)
2. Claude analyse et peut appeler des "outils" (fonctions)
3. On exécute les outils demandés (chercher des tickets similaires...)
4. On renvoie les résultats à Claude
5. Claude retourne sa suggestion finale

Pourquoi ce pattern ?
Le simple "envoie du texte → reçois du texte" ne suffit pas
pour une analyse intelligente. Avec Tool Use, Claude peut
activement chercher des informations dans notre DB avant
de répondre — comme un vrai assistant qui fait ses recherches.

Outils disponibles pour l'agent :
- search_similar_tickets : cherche des tickets similaires
- get_project_members    : récupère les membres et leurs spécialités
- get_ticket_history     : historique des tickets d'un projet
"""

import json
from typing import Optional
from sqlmodel import Session, select
import anthropic
import structlog

from app.config import settings
from app.modules.tickets.models import Ticket, TicketPriority, TicketType
from app.modules.projects.models import ProjectMember
from app.modules.users.models import User
from app.core.audit import AuditService, AuditAction

logger = structlog.get_logger(__name__)


class WendForgeAgent:
    """
    Agent IA WendForge basé sur Claude API.

    Cet agent utilise le pattern Tool Use d'Anthropic :
    Claude peut appeler des fonctions définies ici pour
    récupérer des informations contextuelles avant de
    formuler sa suggestion.

    Usage :
        agent = WendForgeAgent(session)
        suggestion = await agent.analyze_ticket(
            title="Login page crashes on mobile",
            description="Users report the app crashes...",
            project_id="project-uuid",
            ticket_type="bug"
        )
    """

    def __init__(self, session: Session):
        self.session = session
        # Client Claude API officiel Anthropic
        self.client = anthropic.Anthropic(
            api_key=settings.CLAUDE_API_KEY
        )

    # ── Outils disponibles pour Claude ────────
    # Ces fonctions sont déclarées à Claude comme
    # des "outils" qu'il peut appeler.
    # Claude décide LUI-MÊME quand les appeler.

    def _search_similar_tickets(
        self,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> list[dict]:
        """
        Cherche des tickets similaires dans le projet.

        Outil que Claude peut appeler pour éviter
        de suggérer un doublon.

        Utilise une recherche case-insensitive sur le titre.
        En production on utiliserait un vrai système de
        recherche vectorielle (pgvector, Elasticsearch).
        """
        # Divise la query en mots-clés
        keywords = query.lower().split()[:5]

        statement = (
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.deleted_at == None)
            .limit(limit * 3)  # On prend plus et on filtre
        )
        all_tickets = self.session.exec(statement).all()

        # Score simple de similarité
        scored = []
        for ticket in all_tickets:
            title_lower = ticket.title.lower()
            score = sum(1 for kw in keywords if kw in title_lower)
            if score > 0:
                scored.append((score, ticket))

        # Trie par score décroissant
        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "ticket_number": t.ticket_number,
            }
            for _, t in scored[:limit]
        ]

    def _get_project_members(self, project_id: str) -> list[dict]:
        """
        Récupère les membres du projet avec leurs stats.

        Claude utilise cet outil pour suggérer
        l'assigné le plus approprié selon la charge
        de travail actuelle.
        """
        statement = (
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
        members_with_users = self.session.exec(statement).all()

        result = []
        for member, user in members_with_users:
            # Compte les tickets actifs assignés à ce membre
            active_tickets_count = self.session.exec(
                select(Ticket)
                .where(Ticket.assignee_id == user.id)
                .where(Ticket.project_id == project_id)
                .where(Ticket.deleted_at == None)
                .where(Ticket.status != "done")
            ).all()

            result.append({
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "role": member.role,
                "active_tickets": len(active_tickets_count),
            })

        return result

    def _get_ticket_type_stats(self, project_id: str) -> dict:
        """
        Statistiques sur les types de tickets du projet.
        Aide Claude à comprendre le contexte du projet.
        """
        tickets = self.session.exec(
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.deleted_at == None)
            .limit(50)
        ).all()

        stats = {
            "total": len(tickets),
            "by_priority": {},
            "by_type": {},
            "by_status": {},
        }

        for ticket in tickets:
            # Compte par priorité
            p = ticket.priority
            stats["by_priority"][p] = stats["by_priority"].get(p, 0) + 1
            # Compte par type
            t = ticket.ticket_type
            stats["by_type"][t] = stats["by_type"].get(t, 0) + 1
            # Compte par statut
            s = ticket.status
            stats["by_status"][s] = stats["by_status"].get(s, 0) + 1

        return stats

    # ── Définition des outils pour Claude ─────
    # Format requis par l'API Anthropic Tool Use

    def _get_tools_definition(self) -> list[dict]:
        """
        Définit les outils disponibles pour Claude.

        Claude lit ces descriptions pour décider
        QUAND et COMMENT appeler chaque outil.
        La qualité des descriptions est cruciale —
        une mauvaise description = mauvaise décision de Claude.
        """
        return [
            {
                "name": "search_similar_tickets",
                "description": (
                    "Search for similar tickets in the project to avoid duplicates "
                    "and understand the context. Use this when you need to check "
                    "if a similar issue already exists or to understand patterns."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query based on ticket title/description keywords"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max number of results (default 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_project_members",
                "description": (
                    "Get the list of project members with their current workload. "
                    "Use this to suggest the most appropriate assignee based on "
                    "availability and current ticket count."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_ticket_stats",
                "description": (
                    "Get statistics about tickets in this project — priority distribution, "
                    "types, and status breakdown. Use this to understand the project context "
                    "and make better priority suggestions."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        project_id: str
    ) -> str:
        """
        Exécute un outil appelé par Claude.

        Quand Claude décide d'appeler un outil,
        cette fonction l'exécute et retourne le résultat
        sous forme de JSON string.
        """
        logger.info(
            "Agent executing tool",
            tool=tool_name,
            input=tool_input
        )

        if tool_name == "search_similar_tickets":
            result = self._search_similar_tickets(
                project_id=project_id,
                query=tool_input.get("query", ""),
                limit=tool_input.get("limit", 5)
            )

        elif tool_name == "get_project_members":
            result = self._get_project_members(project_id)

        elif tool_name == "get_ticket_stats":
            result = self._get_ticket_type_stats(project_id)

        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, ensure_ascii=False, default=str)

    async def analyze_ticket(
        self,
        title: str,
        description: Optional[str],
        project_id: str,
        ticket_type: str,
        requester_id: Optional[str] = None,
    ) -> dict:
        """
        Analyse un ticket et retourne des suggestions.

        C'est la méthode principale de l'agent.
        Elle orchestre la conversation avec Claude
        en utilisant le pattern Tool Use.

        Args:
            title        : titre du ticket
            description  : description (peut être None)
            project_id   : ID du projet pour le contexte
            ticket_type  : type de ticket (bug, feature, task...)
            requester_id : ID de l'user qui demande l'analyse

        Returns:
            dict avec :
            - suggested_priority    : priorité suggérée
            - suggested_assignee_id : ID de l'assigné suggéré
            - similar_tickets       : IDs des tickets similaires
            - analysis              : explication de l'analyse
            - enhanced_description  : description enrichie
            - confidence            : niveau de confiance (0-1)
        """
        logger.info(
            "Agent analyzing ticket",
            title=title,
            project_id=project_id
        )

        # Prompt système — définit le comportement de l'agent
        system_prompt = """You are WendForge AI, an intelligent project management assistant.
Your role is to analyze tickets and provide actionable suggestions to help teams work more efficiently.

When analyzing a ticket, you MUST:
1. Use the available tools to gather context before making suggestions
2. Always check for similar tickets to avoid duplicates
3. Check team member workload before suggesting an assignee
4. Provide clear reasoning for your suggestions

Respond ONLY in valid JSON format with this exact structure:
{
    "suggested_priority": "critical|high|medium|low",
    "suggested_assignee_id": "user-id or null",
    "similar_tickets": ["ticket-id-1", "ticket-id-2"],
    "analysis": "Brief explanation of your analysis in French",
    "enhanced_description": "Improved description if the original was too short, null otherwise",
    "confidence": 0.0 to 1.0,
    "reasoning": {
        "priority_reason": "Why this priority",
        "assignee_reason": "Why this assignee or why null",
        "duplicate_risk": "low|medium|high"
    }
}"""

        # Message initial à Claude
        user_message = f"""Analyze this new ticket for project {project_id}:

**Title**: {title}
**Type**: {ticket_type}
**Description**: {description or "No description provided"}

Please use the available tools to gather context, then provide your analysis."""

        messages = [{"role": "user", "content": user_message}]
        tools = self._get_tools_definition()

        # Boucle Tool Use — Claude peut appeler plusieurs outils
        # avant de donner sa réponse finale
        max_iterations = 5  # Évite les boucles infinies
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Appel à Claude API
            response = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=settings.CLAUDE_MAX_TOKENS,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            logger.info(
                "Claude response received",
                stop_reason=response.stop_reason,
                iteration=iteration
            )

            # Si Claude a terminé son analyse
            if response.stop_reason == "end_turn":
                # Extrait le JSON de la réponse
                for block in response.content:
                    if block.type == "text":
                        try:
                            # Nettoie le JSON si entouré de backticks
                            text = block.text.strip()
                            if text.startswith("```"):
                                text = text.split("```")[1]
                                if text.startswith("json"):
                                    text = text[4:]
                            result = json.loads(text.strip())
                            logger.info(
                                "Agent analysis complete",
                                priority=result.get("suggested_priority"),
                                confidence=result.get("confidence")
                            )
                            return result
                        except json.JSONDecodeError as e:
                            logger.error(
                                "Failed to parse agent response",
                                error=str(e),
                                text=block.text
                            )
                            return self._fallback_suggestion()

            # Claude veut appeler des outils
            elif response.stop_reason == "tool_use":
                # Ajoute la réponse de Claude aux messages
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Exécute chaque outil demandé
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(
                            tool_name=block.name,
                            tool_input=block.input,
                            project_id=project_id
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })

                # Ajoute les résultats des outils aux messages
                messages.append({
                    "role": "user",
                    "content": tool_results
                })

            else:
                # Stop reason inattendu
                logger.warning(
                    "Unexpected stop reason",
                    stop_reason=response.stop_reason
                )
                break

        # Si on a dépassé le max d'itérations
        logger.warning("Agent reached max iterations")
        return self._fallback_suggestion()

    def _fallback_suggestion(self) -> dict:
        """
        Suggestion par défaut en cas d'erreur de l'agent.
        On ne veut jamais retourner une erreur à l'utilisateur
        quand l'IA échoue — on retourne une suggestion neutre.
        """
        return {
            "suggested_priority": TicketPriority.MEDIUM,
            "suggested_assignee_id": None,
            "similar_tickets": [],
            "analysis": "Analyse automatique non disponible. Priorité moyenne assignée par défaut.",
            "enhanced_description": None,
            "confidence": 0.0,
            "reasoning": {
                "priority_reason": "Default fallback",
                "assignee_reason": "AI analysis failed",
                "duplicate_risk": "unknown"
            }
        }

    async def generate_ticket_description(
        self,
        title: str,
        ticket_type: str,
        context: Optional[str] = None
    ) -> str:
        """
        Génère une description détaillée depuis un titre court.

        Utile quand un utilisateur crée un ticket rapide
        avec juste un titre — l'agent enrichit automatiquement.

        Args:
            title       : titre du ticket
            ticket_type : bug, feature, task...
            context     : contexte additionnel optionnel

        Returns:
            Description enrichie en Markdown
        """
        prompt = f"""Generate a detailed ticket description in French for:

Title: {title}
Type: {ticket_type}
{f'Context: {context}' if context else ''}

Write a clear, actionable description in Markdown with:
- Problem statement (for bugs) or Goal (for features)
- Acceptance criteria (bullet points)
- Technical notes if relevant

Keep it concise but complete. Maximum 300 words."""

        response = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text if response.content else ""

    async def summarize_project(
        self,
        project_id: str,
        project_name: str
    ) -> dict:
        """
        Génère un résumé intelligent du projet.

        Analyse tous les tickets et génère :
        - Résumé de l'état du projet
        - Points bloquants identifiés
        - Recommandations pour l'équipe
        - Tickets prioritaires à traiter

        Utilisé par n8n pour les rapports hebdomadaires.
        """
        # Récupère les données du projet
        tickets = self.session.exec(
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.deleted_at == None)
            .limit(100)
        ).all()

        stats = self._get_ticket_type_stats(project_id)
        members = self._get_project_members(project_id)

        # Construit le contexte pour Claude
        context = {
            "project_name": project_name,
            "total_tickets": len(tickets),
            "stats": stats,
            "team_size": len(members),
            "overloaded_members": [
                m for m in members if m["active_tickets"] > 5
            ],
            "critical_tickets": [
                {"title": t.title, "status": t.status}
                for t in tickets
                if t.priority == "critical" and t.status != "done"
            ][:10],
        }

        prompt = f"""Analyze this project status and generate a summary in French:

{json.dumps(context, ensure_ascii=False, indent=2)}

Respond in JSON:
{{
    "health_score": 0-100,
    "health_label": "excellent|good|attention|critical",
    "summary": "2-3 sentence project status summary",
    "blockers": ["list of identified blockers"],
    "recommendations": ["actionable recommendations"],
    "priority_actions": ["top 3 actions to take this week"]
}}"""

        response = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except Exception as e:
            logger.error("Failed to parse project summary", error=str(e))
            return {
                "health_score": 50,
                "health_label": "attention",
                "summary": "Résumé non disponible.",
                "blockers": [],
                "recommendations": [],
                "priority_actions": []
            }
from flask import Blueprint

from backend.routes.features.admin import register_admin_routes
from backend.routes.features.agent_plugins import register_agent_plugin_routes
from backend.routes.features.agent_providers import register_agent_provider_routes
from backend.routes.features.agent_skills import register_agent_skill_routes
from backend.routes.features.automations import register_automation_routes
from backend.routes.features.chat import register_chat_routes
from backend.routes.features.chatgpt import register_chatgpt_routes
from backend.routes.features.feedback import register_feedback_routes
from backend.routes.features.github import register_github_routes
from backend.routes.features.minds import register_mind_routes
from backend.routes.features.privacy import register_privacy_routes
from backend.routes.features.python import register_python_routes
from backend.routes.features.remind_workspaces import register_remind_workspace_routes
from backend.routes.features.sessions import register_session_routes
from backend.routes.features.share import register_share_routes
from backend.routes.features.system import register_system_routes
from backend.routes.features.user_state import register_user_state_routes
from backend.routes.features.workspaces import register_workspace_routes

api_bp = Blueprint("api", __name__)

register_admin_routes(api_bp)
register_agent_plugin_routes(api_bp)
register_agent_provider_routes(api_bp)
register_agent_skill_routes(api_bp)
register_automation_routes(api_bp)
register_chat_routes(api_bp)
register_chatgpt_routes(api_bp)
register_feedback_routes(api_bp)
register_github_routes(api_bp)
register_mind_routes(api_bp)
register_session_routes(api_bp)
register_share_routes(api_bp)
register_privacy_routes(api_bp)
register_python_routes(api_bp)
register_system_routes(api_bp)
register_user_state_routes(api_bp)

register_workspace_routes(api_bp)
register_remind_workspace_routes(api_bp)

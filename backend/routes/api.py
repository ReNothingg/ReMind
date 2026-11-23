from flask import Blueprint

from backend.routes.features.admin import register_admin_routes
from backend.routes.features.chat import register_chat_routes
from backend.routes.features.feedback import register_feedback_routes
from backend.routes.features.github import register_github_routes
from backend.routes.features.minds import register_mind_routes
from backend.routes.features.privacy import register_privacy_routes
from backend.routes.features.python import register_python_routes
from backend.routes.features.sessions import register_session_routes
from backend.routes.features.share import register_share_routes
from backend.routes.features.system import register_system_routes
from backend.routes.features.user_state import register_user_state_routes

api_bp = Blueprint("api", __name__)

register_admin_routes(api_bp)
register_chat_routes(api_bp)
register_feedback_routes(api_bp)
register_github_routes(api_bp)
register_mind_routes(api_bp)
register_session_routes(api_bp)
register_share_routes(api_bp)
register_privacy_routes(api_bp)
register_python_routes(api_bp)
register_system_routes(api_bp)
register_user_state_routes(api_bp)

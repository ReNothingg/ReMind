from flask import Blueprint

from routes.features.chat import register_chat_routes
from routes.features.privacy import register_privacy_routes
from routes.features.sessions import register_session_routes
from routes.features.share import register_share_routes
from routes.features.system import register_system_routes

api_bp = Blueprint("api", __name__)

register_chat_routes(api_bp)
register_session_routes(api_bp)
register_share_routes(api_bp)
register_privacy_routes(api_bp)
register_system_routes(api_bp)

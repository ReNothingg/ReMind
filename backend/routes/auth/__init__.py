from backend.routes.auth.browser import register_browser_routes
from backend.routes.auth.config import register_config_routes
from backend.routes.auth.credentials import register_credentials_routes
from backend.routes.auth.profile import register_profile_routes
from backend.routes.auth.providers import register_providers_routes


def register_auth_routes(app):
    register_browser_routes(app)
    register_config_routes(app)
    register_providers_routes(app)
    register_credentials_routes(app)
    register_profile_routes(app)

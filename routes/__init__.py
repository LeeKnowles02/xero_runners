"""Register all route groups on the Flask app."""
from .pages import register_pages
from .api import register_api
from .auth_routes import register_auth_routes


def register_routes(app, xero, state, token_store, client_id, client_secret, logger):
    register_pages(app)
    register_api(app, xero, state, logger)
    register_auth_routes(app, xero, token_store, client_id, client_secret, logger)

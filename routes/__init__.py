"""Register all route groups on the Flask app."""
from flask import g, request

from .pages import register_pages
from .api import register_api
from .auth_routes import register_auth_routes
from .exchange_rates_routes import register_exchange_rates_routes


def register_routes(app, xero, state, token_store, client_id, client_secret, logger):
    # Integration DB log: per-request correlation id for tracing API + OAuth callback with the UI.
    @app.before_request
    def _integration_log_correlation():
        if not (request.path.startswith("/api") or request.path == "/callback"):
            return
        try:
            import integration_db_log

            cid = request.headers.get("X-Correlation-ID") or integration_db_log.new_correlation_id()
            integration_db_log.set_log_context(correlation_id=cid)
            g._integration_correlation_id = cid
        except Exception:
            pass

    @app.after_request
    def _integration_log_correlation_header(response):
        cid = getattr(g, "_integration_correlation_id", None)
        if cid:
            response.headers["X-Correlation-ID"] = cid
        return response

    @app.teardown_request
    def _integration_log_teardown_request(_exc):
        if request.path.startswith("/api") or request.path == "/callback":
            try:
                import integration_db_log

                integration_db_log.set_log_context(clear=True)
            except Exception:
                pass

    register_pages(app)
    register_exchange_rates_routes(app)
    register_api(app, xero, state, logger)
    register_auth_routes(app, xero, token_store, client_id, client_secret, logger)

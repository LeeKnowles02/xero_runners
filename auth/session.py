"""In-memory auth session (single-user local app)."""
import time

auth_session = {
    "verifier": None,
    "state": None,
    "created_at": None,
    "scopes": None,
}

"""PKCE helpers for OAuth."""
import base64
import hashlib
import os


def b64url_nopad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def pkce_pair():
    verifier = b64url_nopad(os.urandom(48))
    challenge = b64url_nopad(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge

# server/server_auth.py
#
# Two authentication paths:
#   1. Web users (SPA) — Supabase-issued JWT in Authorization: Bearer header
#   2. Agent process  — long-lived agent token in X-Agent-Token header
#
# Neither path uses cookies, sessions, or CSRF tokens.
# The SPA manages its own Supabase session in the browser.

import hashlib
from typing import Optional

import jwt
from fastapi import HTTPException, Request

from .server_settings import SUPABASE_URL, SUPABASE_JWT_SECRET
from .server_supabase import get_supabase

# Cached JWKS client for RS256 verification (newer Supabase projects)
_jwks_client = None

def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwks_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hash_agent_token(raw: str) -> str:
    """One-way hash for an agent token. Stored in DB; raw token is never stored."""
    return "sha256:" + hashlib.sha256((raw or "").strip().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Web user auth (Supabase JWT)
# ---------------------------------------------------------------------------

def verify_supabase_jwt(token: str) -> dict:
    """Decode and verify a Supabase-issued access token. Returns the payload.

    Handles both HS256 (older projects, uses JWT secret) and RS256
    (newer projects, uses JWKS endpoint) automatically.
    """
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                raise RuntimeError("SUPABASE_JWT_SECRET env var must be set")
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            # RS256 or other asymmetric algorithm — verify via JWKS
            client = _get_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
            )

        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


def get_user_id_from_request(request: Request) -> str:
    """Extract user_id (UUID string) from a Bearer JWT in the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = auth[len("Bearer "):]
    payload = verify_supabase_jwt(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    return user_id


# ---------------------------------------------------------------------------
# Agent auth (X-Agent-Token header)
# ---------------------------------------------------------------------------

def require_user_from_agent_token(x_agent_token: Optional[str]) -> dict:
    """
    Look up an agent token by its hash and return {user_id, token_id}.
    Raises 401 if missing, unknown, or revoked.
    """
    if not x_agent_token:
        raise HTTPException(status_code=401, detail="Missing X-Agent-Token")

    token_hash = hash_agent_token(x_agent_token)
    sb = get_supabase()

    result = (
        sb.table("agent_tokens")
        .select("token_id, user_id, revoked")
        .eq("token_hash", token_hash)
        .maybe_single()
        .execute()
    )

    row = result.data
    if not row or row.get("revoked"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return {"user_id": row["user_id"], "token_id": row["token_id"]}


# ---------------------------------------------------------------------------
# Shared ownership checks (used by both auth paths)
# ---------------------------------------------------------------------------

def require_agent_belongs_to_user(agent_id: str, user_id: str) -> dict:
    """Verify the agent exists and belongs to this user. Returns the agent row."""
    sb = get_supabase()
    result = (
        sb.table("agents")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=403, detail="Forbidden or agent not found")
    return result.data


def require_job_in_progress(job_id: str, user_id: str) -> dict:
    """Return the job row if it is in_progress and belongs to this user."""
    sb = get_supabase()
    result = (
        sb.table("jobs")
        .select("*")
        .eq("job_id", job_id)
        .eq("user_id", user_id)
        .eq("status", "in_progress")
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found in progress")
    return result.data

# server/server_routes_auth.py
#
# PKCE-based agent token provisioning.
#
# Flow (see CLAUDE.md / plan for full description):
#   1. SPA calls POST /api/agent-tokens/provision  (JWT auth, user already logged in)
#      → server creates agent_token + auth_code, returns auth_code to SPA
#   2. SPA redirects browser to http://127.0.0.1:<port>/callback?code=<auth_code>
#   3. Wizard's local HTTP server catches the callback
#   4. Wizard calls POST /api/agent-tokens/exchange  (no auth, PKCE verifier required)
#      → server verifies PKCE, returns plaintext token, marks code used
#   5. Wizard saves token to config; browser can close

import hashlib
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .server_auth import get_user_id_from_request, require_user_from_agent_token
from .server_supabase import get_supabase
from .server_util import audit_log_event, utcnow_iso, enforce_rate_limit, get_client_ip, get_user_tier

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    agent_name: str
    code_challenge: str   # sha256(code_verifier), base64url-encoded, from wizard


class ExchangeRequest(BaseModel):
    code: str             # one-time auth code received from SPA via local redirect
    code_verifier: str    # original random secret; server verifies sha256(it)==challenge


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/agent-tokens/provision")
def provision_agent_token(request: Request, data: ProvisionRequest):
    """
    Called by the SPA after the user clicks "Authorize Agent" on /agent-setup.
    Creates a long-lived agent token and a short-lived PKCE auth code.
    The auth code is sent to the wizard's local HTTP listener via a browser redirect.
    """
    user_id = get_user_id_from_request(request)

    # Rate limit: 5 provisions per minute per IP
    ok, retry = enforce_rate_limit(request, "provision", limit=5, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})

    if not data.agent_name or not data.agent_name.strip():
        raise HTTPException(status_code=400, detail="agent_name is required")
    if not data.code_challenge or len(data.code_challenge) < 10:
        raise HTTPException(status_code=400, detail="code_challenge is required")

    sb = get_supabase()

    # Determine user tier and agent limits
    tier = get_user_tier(sb, user_id)
        
    max_agents = 3 if tier == "pro" else 1

    # Check how many actual agents this user currently has (not tokens,
    # since orphaned tokens from failed setups would incorrectly block).
    agents_res = (
        sb.table("agents")
        .select("agent_id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    current_agents = agents_res.count or 0

    if current_agents >= max_agents:
        raise HTTPException(
            status_code=403, 
            detail=f"You've reached your computer limit ({max_agents}). Remove one from Settings, or upgrade to Pro for up to 3."
        )

    # Generate one-time auth code for the PKCE exchange.
    # Token is NOT created here -- it is generated only after successful
    # PKCE verification in exchange_agent_token, so no plaintext secret
    # ever sits in the database.
    auth_code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(auth_code.encode()).hexdigest()
    # Double-hash the challenge: the client sends sha256(verifier) as base64url,
    # we hash that again so the DB never stores a value directly comparable to
    # what the client sends on the wire.
    challenge_hash = hashlib.sha256(data.code_challenge.encode()).hexdigest()

    sb.table("agent_auth_codes").insert({
        "code_hash": code_hash,
        "challenge_hash": challenge_hash,
        "user_id": user_id,
        "agent_name": data.agent_name.strip(),
    }).execute()

    audit_log_event("agent_token_provisioned", user_id=user_id, agent_name=data.agent_name.strip())

    # Return the auth_code to the SPA; SPA will redirect the browser to the wizard's
    # local listener at http://127.0.0.1:<port>/callback?code=<auth_code>
    return {"auth_code": auth_code}


@router.post("/agent-tokens/exchange")
def exchange_agent_token(request: Request, data: ExchangeRequest):
    """
    Called by the wizard's local HTTP server after receiving the browser callback.
    No user JWT required — security is provided by the PKCE code_verifier.

    Returns the plaintext agent token once, then marks the auth code as used.
    """
    if not data.code or not data.code_verifier:
        raise HTTPException(status_code=400, detail="code and code_verifier are required")

    # Rate limit: 10 exchange attempts per minute per IP
    ok, retry = enforce_rate_limit(request, "exchange", limit=10, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})

    sb = get_supabase()

    code_hash = hashlib.sha256(data.code.encode()).hexdigest()
    result = (
        sb.table("agent_auth_codes")
        .select("*")
        .eq("code_hash", code_hash)
        .eq("used", False)
        .maybe_single()
        .execute()
    )

    row = result.data
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

    # Check expiry (Postgres expires_at column compared in Python for simplicity)
    from datetime import datetime, timezone
    expires_at_str = row.get("expires_at", "")
    try:
        # Supabase returns ISO strings; strip trailing Z and parse
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=400, detail="Authorization code has expired")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expiry on authorization code")

    # PKCE verification: sha256(code_verifier) must match the stored challenge.
    # The stored challenge_hash is sha256(original_code_challenge), and the
    # original_code_challenge was base64url(sha256(code_verifier)).
    import base64
    verifier_digest = base64.urlsafe_b64encode(
        hashlib.sha256(data.code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    # Double-hash to match what we stored at provision time
    verifier_hash = hashlib.sha256(verifier_digest.encode()).hexdigest()

    if verifier_hash != row["challenge_hash"]:
        raise HTTPException(status_code=400, detail="PKCE verification failed")

    # Mark code as used (one-time)
    sb.table("agent_auth_codes").update({"used": True}).eq("code_hash", code_hash).execute()

    # NOW generate the agent token (only after successful PKCE verification,
    # so no plaintext token ever sits in the DB waiting to be exchanged)
    plaintext_token = secrets.token_urlsafe(32)
    token_hash = "sha256:" + hashlib.sha256(plaintext_token.encode()).hexdigest()
    agent_name = row.get("agent_name", "").strip()

    sb.table("agent_tokens").insert({
        "user_id": row["user_id"],
        "token_hash": token_hash,
        "agent_name": agent_name,
    }).execute()

    audit_log_event(
        "agent_token_exchanged",
        user_id=row["user_id"],
        agent_name=agent_name,
    )

    return {
        "agent_token": plaintext_token,
        "user_id": row["user_id"],
    }


@router.get("/agent-tokens")
def list_agent_tokens(request: Request):
    """Return all non-revoked agent tokens for the current user (no plaintext)."""
    user_id = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("agent_tokens")
        .select("token_id, agent_name, created_at, last_used_at, revoked")
        .eq("user_id", user_id)
        .eq("revoked", False)
        .order("created_at", desc=True)
        .execute()
    )
    return {"tokens": result.data or []}


@router.delete("/agent-tokens/{token_id}")
def revoke_agent_token(token_id: str, request: Request):
    """Revoke an agent token. The agent using this token will stop being authenticated."""
    user_id = get_user_id_from_request(request)
    sb = get_supabase()

    # Verify ownership before revoking
    existing = (
        sb.table("agent_tokens")
        .select("token_id, user_id")
        .eq("token_id", token_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Token not found")

    sb.table("agent_tokens").update({"revoked": True}).eq("token_id", token_id).execute()
    audit_log_event("agent_token_revoked", user_id=user_id, token_id=token_id)
    return {"status": "revoked"}


@router.get("/auth/agent-whoami")
def agent_whoami(request: Request):
    """Agent uses this to verify its token is still valid on startup."""
    x_agent_token = request.headers.get("X-Agent-Token")
    token_info = require_user_from_agent_token(x_agent_token)
    sb = get_supabase()
    profile = (
        sb.table("profiles")
        .select("name")
        .eq("user_id", token_info["user_id"])
        .maybe_single()
        .execute()
    )
    name = profile.data.get("name", "") if profile.data else ""
    return {"user_id": token_info["user_id"], "name": name}

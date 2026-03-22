# server/server_util.py
import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import Request
from fastapi.responses import HTMLResponse


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Audit log — writes to Supabase audit_log table
# ---------------------------------------------------------------------------

def _audit_sanitize(v, max_len: int = 500):
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v).replace("\r", "\\r").replace("\n", "\\n")
    return s[:max_len] + "..." if len(s) > max_len else s


def audit_log_event(event: str, **fields) -> None:
    """Write an audit log row to Supabase. Never raises — failures are printed only."""
    try:
        from .server_supabase import get_supabase
        details = {k: _audit_sanitize(v) for k, v in fields.items()
                   if k not in ("user_id", "agent_id", "job_id")}
        sb = get_supabase()
        sb.table("audit_log").insert({
            "event": event,
            "user_id": fields.get("user_id"),
            "agent_id": str(fields.get("agent_id")) if fields.get("agent_id") else None,
            "job_id": str(fields.get("job_id")) if fields.get("job_id") else None,
            "details": details,
        }).execute()
    except Exception as exc:
        print(f"[audit] failed to write event '{event}': {exc}")


# ---------------------------------------------------------------------------
# Security headers helper
# ---------------------------------------------------------------------------

def add_security_headers(resp: HTMLResponse) -> HTMLResponse:
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------
# Tier lookup with retry
# ---------------------------------------------------------------------------

def get_user_tier(sb, user_id: str) -> str:
    """Determine effective tier. Checks Stripe subscription first, then admin grants.
    Falls back to 'free' on any error."""
    for attempt in range(2):
        try:
            # 1. Check Stripe subscription
            sub = sb.table("subscriptions").select(
                "stripe_status, current_period_end, cancel_at_period_end"
            ).eq("user_id", user_id).maybe_single().execute()

            if sub and sub.data:
                status = sub.data.get("stripe_status")
                if status in ("active", "past_due", "trialing"):
                    return "pro"
                if status == "canceled" and sub.data.get("cancel_at_period_end"):
                    # User canceled gracefully — keep access until period ends
                    period_end = sub.data.get("current_period_end")
                    if period_end:
                        end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
                        if end_dt > datetime.now(timezone.utc):
                            return "pro"

            # 2. Check admin grants
            try:
                now_iso = utcnow_iso()
                grant = sb.table("admin_grants").select("id").eq(
                    "user_id", user_id
                ).eq("revoked", False).gt("granted_until", now_iso).limit(1).execute()

                if grant.data:
                    return "pro"
            except Exception as grant_exc:
                print(f"[tier] admin_grants query failed for {user_id}: {grant_exc}")
                # Don't let admin_grants failure block tier determination —
                # fall through to "free" but log so we can diagnose

            # 3. Default
            return "free"
        except Exception as exc:
            print(f"[tier] get_user_tier attempt {attempt+1} failed for {user_id}: {exc}")
            if attempt == 0:
                time.sleep(0.3)
    print(f"[tier] get_user_tier returning 'free' for {user_id} after all attempts failed")
    return "free"


def get_subscription_info(sb, user_id: str) -> dict:
    """Get full subscription + grant details for a user. Used by the profile endpoint."""
    info = {
        "tier_source": "none",
        "subscription_status": None,
        "current_period_end": None,
        "cancel_at_period_end": None,
        "has_active_grant": False,
        "grant_until": None,
    }
    try:
        # Stripe subscription
        sub = sb.table("subscriptions").select(
            "stripe_status, current_period_end, cancel_at_period_end"
        ).eq("user_id", user_id).maybe_single().execute()

        if sub and sub.data:
            info["subscription_status"] = sub.data.get("stripe_status")
            info["current_period_end"] = sub.data.get("current_period_end")
            info["cancel_at_period_end"] = sub.data.get("cancel_at_period_end")
            status = sub.data.get("stripe_status")
            if status in ("active", "past_due", "trialing"):
                info["tier_source"] = "stripe"
            elif status == "canceled" and sub.data.get("cancel_at_period_end"):
                period_end = sub.data.get("current_period_end")
                if period_end:
                    end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
                    if end_dt > datetime.now(timezone.utc):
                        info["tier_source"] = "stripe"

        # Admin grants
        try:
            now_iso = utcnow_iso()
            grant = sb.table("admin_grants").select(
                "granted_until"
            ).eq("user_id", user_id).eq("revoked", False).gt(
                "granted_until", now_iso
            ).order("granted_until", desc=True).limit(1).execute()

            if grant.data:
                info["has_active_grant"] = True
                info["grant_until"] = grant.data[0].get("granted_until")
                if info["tier_source"] == "none":
                    info["tier_source"] = "admin_grant"
        except Exception as grant_exc:
            print(f"[warn] admin_grants query failed in get_subscription_info for {user_id}: {grant_exc}")
    except Exception as exc:
        print(f"[warn] get_subscription_info failed for {user_id}: {exc}")

    return info


# ---------------------------------------------------------------------------
# Error classification (used for auto-retry decisions)
# ---------------------------------------------------------------------------

def is_permanent_error(reason: str) -> bool:
    r = (reason or "").lower()
    return any(s in r for s in [
        "no such file", "file not found", "cannot open", "can't open",
        "does not exist", "not found", "errno 2",
        "canceled by user", "cancelled by user", "canceled", "cancelled",
    ])


def is_retryable_error(reason: str) -> bool:
    r = (reason or "").lower()
    return any(m in r for m in [
        "blender exited with code", "exit code", "return code", "returncode",
        "segmentation fault", "segfault", "access violation",
        "crash", "crashed", "killed", "terminated",
    ])


# ---------------------------------------------------------------------------
# Minimal in-memory rate limiting
# ---------------------------------------------------------------------------

_RL_LOCK = threading.Lock()
_RL_BUCKETS: dict[str, Tuple[float, int]] = {}


def _anon_id(secret: str) -> str:
    return hashlib.sha256((secret or "").strip().encode()).hexdigest()[:16]


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


_RL_LAST_CLEANUP = 0.0
_RL_CLEANUP_INTERVAL = 300  # purge stale entries every 5 min


def rate_limit_allow(bucket_key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
    global _RL_LAST_CLEANUP
    now = time.time()
    with _RL_LOCK:
        # Periodically purge expired entries to prevent unbounded growth
        if now - _RL_LAST_CLEANUP > _RL_CLEANUP_INTERVAL:
            stale = [k for k, (ws, _) in _RL_BUCKETS.items() if now - ws > window_seconds * 2]
            for k in stale:
                del _RL_BUCKETS[k]
            _RL_LAST_CLEANUP = now

        win_start, count = _RL_BUCKETS.get(bucket_key, (now, 0))
        if now - win_start >= window_seconds:
            win_start, count = now, 0
        count += 1
        _RL_BUCKETS[bucket_key] = (win_start, count)
        if count <= limit:
            return True, 0
        return False, max(1, int(window_seconds - (now - win_start)))


# ---------------------------------------------------------------------------
# Short-lived stream tokens (HMAC-signed, no DB table required)
# ---------------------------------------------------------------------------

import hmac, json, base64

STREAM_TOKEN_TTL_SECONDS = 300  # 5 minutes


def _stream_token_secret() -> bytes:
    """Return a secret key for signing stream tokens.
    Uses SUPABASE_JWT_SECRET so we don't need another env var."""
    from .server_settings import SUPABASE_JWT_SECRET
    return ("stream:" + SUPABASE_JWT_SECRET).encode()


def create_stream_token(sb, user_id: str, job_id: str) -> str:
    """Generate a short-lived HMAC-signed token for video streaming.
    No database table needed — the token is self-contained."""
    expires_at = int((datetime.now(timezone.utc) + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)).timestamp())
    payload = json.dumps({"uid": user_id, "jid": job_id, "exp": expires_at}, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_stream_token_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_stream_token(sb, token: str, job_id: str) -> Optional[str]:
    """Verify an HMAC-signed stream token. Returns user_id if valid, else None."""
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None

    payload_b64, sig = parts
    expected_sig = hmac.new(_stream_token_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None

    if payload.get("jid") != job_id:
        return None

    if datetime.now(timezone.utc).timestamp() > payload.get("exp", 0):
        return None

    return payload.get("uid")


# ---------------------------------------------------------------------------
# Storage path sanitization
# ---------------------------------------------------------------------------

import re as _re

def sanitize_pass_name(pass_name: Optional[str]) -> str:
    """Sanitize a render pass name for use in Supabase storage paths.
    Only allows alphanumeric, underscore, space, hyphen. Max 64 chars."""
    if not pass_name:
        return "Combined"
    sanitized = _re.sub(r'[^a-zA-Z0-9_ -]', '', pass_name)[:64].strip()
    if not sanitized:
        return "Combined"
    return sanitized


def enforce_rate_limit(
        request: Request,
        endpoint: str,
        *,
        limit: int,
        window_seconds: int,
        token: Optional[str] = None,
) -> Tuple[bool, int]:
    """Apply per-IP rate limit; optionally also per-token."""
    ip = get_client_ip(request)
    ok, retry = rate_limit_allow(f"ip:{ip}|{endpoint}", limit, window_seconds)
    if not ok:
        return False, retry
    if token:
        kid = _anon_id(token)
        ok2, retry2 = rate_limit_allow(f"key:{kid}|{endpoint}", limit, window_seconds)
        if not ok2:
            return False, retry2
    return True, 0

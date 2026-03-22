# server/server_routes_admin.py
#
# Admin-only endpoints for managing users, tiers, announcements,
# emergency pause, audit log, and system stats.

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import time

from .server_auth import get_user_id_from_request
from .server_supabase import get_supabase
from .server_settings import ADMIN_EMAILS
from .server_util import audit_log_event, get_user_tier, get_subscription_info, utcnow_iso

router = APIRouter(prefix="/api/admin")

# ---------------------------------------------------------------------------
# Also mount a public endpoint for announcements (no admin auth needed)
# ---------------------------------------------------------------------------
public_router = APIRouter(prefix="/api/system")


def require_admin(request: Request):
    """Verify the caller is in the ADMIN_EMAILS list."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    try:
        user_res = sb.auth.admin.get_user_by_id(uid)
        email = user_res.user.email if user_res and user_res.user else None
        if not email or email not in ADMIN_EMAILS:
            raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
        return uid
    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin] Auth check failed: {e}")
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")


# ---------------------------------------------------------------------------
# Emergency Pause — in-memory cache
# ---------------------------------------------------------------------------

_emergency_pause_cache = {"value": None, "fetched_at": 0.0}
EMERGENCY_PAUSE_CACHE_TTL = 10  # seconds


def get_emergency_pause() -> dict:
    """Get the current emergency pause state, cached for 10s."""
    now = time.time()
    if (
        _emergency_pause_cache["value"] is not None
        and now - _emergency_pause_cache["fetched_at"] < EMERGENCY_PAUSE_CACHE_TTL
    ):
        return _emergency_pause_cache["value"]

    try:
        sb = get_supabase()
        res = sb.table("system_settings").select("value").eq("key", "emergency_pause").maybe_single().execute()
        val = res.data["value"] if res.data else {"enabled": False, "reason": None}
    except Exception as e:
        print(f"[admin] Failed to fetch emergency_pause: {e}")
        val = {"enabled": False, "reason": None}

    _emergency_pause_cache["value"] = val
    _emergency_pause_cache["fetched_at"] = now
    return val


def _invalidate_emergency_pause_cache():
    _emergency_pause_cache["value"] = None
    _emergency_pause_cache["fetched_at"] = 0.0


# ---------------------------------------------------------------------------
# Existing endpoints (unchanged)
# ---------------------------------------------------------------------------

class SetTierRequest(BaseModel):
    user_id: str
    tier: str


@router.get("/search-user")
def search_user(request: Request, email: str):
    """Search for a user by email across all users."""
    require_admin(request)
    sb = get_supabase()

    if not email or len(email) < 3:
        raise HTTPException(status_code=400, detail="Search query too short")

    try:
        res = sb.auth.admin.list_users()
        users = res if isinstance(res, list) else getattr(res, 'users', [])

        matches = []
        search_lower = email.lower()
        for u in users:
            u_email = getattr(u, 'email', '').lower()
            if search_lower in u_email:
                tier = get_user_tier(sb, u.id)
                sub_info = get_subscription_info(sb, u.id)

                matches.append({
                    "user_id": u.id,
                    "email": u.email,
                    "tier": tier,
                    "tier_source": sub_info["tier_source"],
                    "created_at": u.created_at,
                })

        return {"users": matches}
    except Exception as e:
        print(f"[admin] Search failed: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


@router.post("/set-tier")
def set_tier(request: Request, data: SetTierRequest):
    """Manually override a user's tier."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    if data.tier not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="Invalid tier")

    try:
        res = sb.table("profiles").update({"tier": data.tier}).eq("user_id", data.user_id).execute()
        if not res.data:
            sb.table("profiles").upsert({
                "user_id": data.user_id,
                "tier": data.tier
            }).execute()
    except Exception as e:
        print(f"[admin] Set tier failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to update tier")

    audit_log_event("admin_set_tier", user_id=admin_uid, target_user_id=data.user_id, tier=data.tier)
    return {"status": "success", "user_id": data.user_id, "tier": data.tier}


# ---------------------------------------------------------------------------
# Pro Grants
# ---------------------------------------------------------------------------

class GrantProRequest(BaseModel):
    user_id: str
    duration_days: Optional[int] = None
    duration_months: Optional[int] = None
    reason: Optional[str] = None


class RevokeGrantRequest(BaseModel):
    user_id: str
    force: bool = False


@router.post("/grant-pro")
def grant_pro(request: Request, data: GrantProRequest):
    """Grant a user Pro access for a specified duration."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    if not data.duration_days and not data.duration_months:
        raise HTTPException(status_code=400, detail="Specify duration_days or duration_months")
    if data.duration_days and data.duration_days < 1:
        raise HTTPException(status_code=400, detail="duration_days must be >= 1")
    if data.duration_months and data.duration_months < 1:
        raise HTTPException(status_code=400, detail="duration_months must be >= 1")

    now = datetime.now(timezone.utc)
    if data.duration_months:
        # Approximate months as 30 days each
        granted_until = now + timedelta(days=data.duration_months * 30)
    else:
        granted_until = now + timedelta(days=data.duration_days)

    try:
        insert_res = sb.table("admin_grants").insert({
            "user_id": data.user_id,
            "granted_by": admin_uid,
            "granted_until": granted_until.isoformat(),
            "reason": data.reason,
            "revoked": False,
        }).execute()

        if not insert_res.data:
            print(f"[admin] Grant insert returned no data for user {data.user_id}")
            raise HTTPException(status_code=500, detail="Grant insert failed - no row returned")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin] Grant pro insert failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to insert grant: {e}")

    # Update cached tier in profiles
    try:
        sb.table("profiles").update({"tier": "pro"}).eq("user_id", data.user_id).execute()
    except Exception as e:
        print(f"[admin] Profile tier cache update failed (grant still valid): {e}")

    # Verify the grant is visible to the tier system
    effective_tier = get_user_tier(sb, data.user_id)
    if effective_tier != "pro":
        print(f"[admin] WARNING: granted pro to {data.user_id} but get_user_tier returned '{effective_tier}'")

    audit_log_event(
        "admin_grant_pro", user_id=admin_uid,
        target_user_id=data.user_id,
        granted_until=granted_until.isoformat(),
        reason=data.reason or "",
    )

    return {
        "status": "success",
        "user_id": data.user_id,
        "granted_until": granted_until.isoformat(),
        "effective_tier": effective_tier,
    }


@router.post("/revoke-grant")
def revoke_grant(request: Request, data: RevokeGrantRequest):
    """Revoke all active admin grants for a user. Warns if user has Stripe subscription."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    # Check for active Stripe subscription
    sub = sb.table("subscriptions").select(
        "stripe_status, current_period_end"
    ).eq("user_id", data.user_id).maybe_single().execute()

    has_stripe = False
    if sub and sub.data:
        status = sub.data.get("stripe_status")
        if status in ("active", "past_due", "trialing"):
            has_stripe = True
        elif status == "canceled" and sub.data.get("current_period_end"):
            end_dt = datetime.fromisoformat(
                sub.data["current_period_end"].replace("Z", "+00:00")
            )
            if end_dt > datetime.now(timezone.utc):
                has_stripe = True

    if has_stripe and not data.force:
        return {
            "status": "warning",
            "message": "User has an active Stripe subscription. Revoking the admin grant won't affect their paid subscription. Set force=true to proceed.",
            "has_stripe_subscription": True,
        }

    # Revoke all active grants
    now_iso = utcnow_iso()
    try:
        sb.table("admin_grants").update({
            "revoked": True,
            "revoked_at": now_iso,
            "revoked_by": admin_uid,
        }).eq("user_id", data.user_id).eq("revoked", False).execute()

        # Update cached tier
        effective_tier = get_user_tier(sb, data.user_id)
        sb.table("profiles").update({"tier": effective_tier}).eq("user_id", data.user_id).execute()
    except Exception as e:
        print(f"[admin] Revoke grant failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to revoke grant")

    audit_log_event(
        "admin_revoke_grant", user_id=admin_uid,
        target_user_id=data.user_id,
        had_stripe=str(has_stripe),
    )

    return {
        "status": "success",
        "user_id": data.user_id,
        "effective_tier": effective_tier,
        "has_stripe_subscription": has_stripe,
    }


# ---------------------------------------------------------------------------
# Emergency Pause
# ---------------------------------------------------------------------------

class EmergencyPauseRequest(BaseModel):
    enabled: bool
    reason: Optional[str] = None
    cancel_active: bool = False


@router.post("/emergency-pause")
def set_emergency_pause(request: Request, data: EmergencyPauseRequest):
    """Toggle the global emergency pause. When enabled, agents receive no new jobs."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    value = {"enabled": data.enabled, "reason": data.reason}

    try:
        sb.table("system_settings").upsert({
            "key": "emergency_pause",
            "value": value,
            "updated_at": utcnow_iso(),
        }).execute()
    except Exception as e:
        print(f"[admin] Failed to set emergency_pause: {e}")
        raise HTTPException(status_code=500, detail="Failed to update emergency pause")

    _invalidate_emergency_pause_cache()

    # Optionally cancel all in-progress jobs
    canceled_count = 0
    if data.enabled and data.cancel_active:
        try:
            active_jobs = (
                sb.table("jobs")
                .select("job_id")
                .eq("status", "in_progress")
                .execute()
            )
            for job in (active_jobs.data or []):
                sb.table("jobs").update({
                    "cancel_requested": True,
                    "cancel_requested_at": utcnow_iso(),
                }).eq("job_id", job["job_id"]).execute()
                canceled_count += 1
        except Exception as e:
            print(f"[admin] Failed to cancel active jobs: {e}")

    audit_log_event(
        "admin_emergency_pause",
        user_id=admin_uid,
        enabled=str(data.enabled),
        reason=data.reason or "",
        canceled_active=str(canceled_count),
    )

    return {"status": "success", "enabled": data.enabled, "canceled_count": canceled_count}


@router.get("/system-status")
def get_system_status(request: Request):
    """Get emergency pause state + basic system counts."""
    require_admin(request)
    sb = get_supabase()

    pause = get_emergency_pause()

    try:
        users_count = sb.table("profiles").select("user_id", count="exact").execute().count or 0
        online_agents = sb.table("agents").select("agent_id", count="exact").neq("status", "offline").execute().count or 0
        offline_agents = sb.table("agents").select("agent_id", count="exact").eq("status", "offline").execute().count or 0
        active_jobs = sb.table("jobs").select("job_id", count="exact").eq("status", "in_progress").execute().count or 0
        queued_jobs = sb.table("jobs").select("job_id", count="exact").eq("status", "queued").execute().count or 0
    except Exception as e:
        print(f"[admin] Failed to fetch system status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch system status")

    return {
        "emergency_pause": pause,
        "total_users": users_count,
        "online_agents": online_agents,
        "offline_agents": offline_agents,
        "active_jobs": active_jobs,
        "queued_jobs": queued_jobs,
    }


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

class AnnouncementRequest(BaseModel):
    text: Optional[str] = None
    type: str = "info"  # info | warning | critical


@public_router.get("/announcement")
def get_announcement():
    """Public endpoint — returns the current system announcement or null."""
    try:
        sb = get_supabase()
        res = sb.table("system_settings").select("value").eq("key", "announcement").maybe_single().execute()
        if res.data:
            val = res.data["value"]
            if val.get("text"):
                return {"announcement": val}
        return {"announcement": None}
    except Exception as e:
        print(f"[admin] Failed to fetch announcement: {e}")
        return {"announcement": None}


@router.post("/announcement")
def set_announcement(request: Request, data: AnnouncementRequest):
    """Set or clear the system-wide announcement."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    if data.type not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="Invalid announcement type")

    value = {"text": data.text, "type": data.type}

    try:
        sb.table("system_settings").upsert({
            "key": "announcement",
            "value": value,
            "updated_at": utcnow_iso(),
        }).execute()
    except Exception as e:
        print(f"[admin] Failed to set announcement: {e}")
        raise HTTPException(status_code=500, detail="Failed to update announcement")

    audit_log_event(
        "admin_announcement",
        user_id=admin_uid,
        text=data.text or "(cleared)",
        type=data.type,
    )

    return {"status": "success", "announcement": value}


# ---------------------------------------------------------------------------
# Enhanced User Details
# ---------------------------------------------------------------------------

@router.get("/user/{user_id}/details")
def get_user_details(request: Request, user_id: str):
    """Get full details for a user: profile, subscription, grants, agents, recent jobs."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    # Audit: log that an admin viewed this user's details
    audit_log_event(sb, "admin_view_user", user_id=admin_uid, details=f"viewed user {user_id}")

    try:
        # Profile
        profile = sb.table("profiles").select("*").eq("user_id", user_id).maybe_single().execute()
        profile_data = profile.data if profile.data else None

        # Subscription info
        sub_info = get_subscription_info(sb, user_id)

        # Active admin grants
        now_iso = utcnow_iso()
        grants_res = sb.table("admin_grants").select(
            "id, granted_by, granted_until, reason, revoked, revoked_at, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()

        # Agents
        agents_res = sb.table("agents").select(
            "agent_id, name, status, last_seen, created_at"
        ).eq("user_id", user_id).order("created_at", desc=False).execute()

        # Recent jobs (last 20) — blend_relpath excluded for user privacy
        jobs_res = sb.table("jobs").select(
            "job_id, status, frame_start, frame_end, progress, "
            "fail_reason, created_at, completed_at, failed_at, agent_id"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()

    except Exception as e:
        print(f"[admin] Failed to fetch user details: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user details")

    return {
        "profile": profile_data,
        "subscription": sub_info,
        "grants": grants_res.data or [],
        "agents": agents_res.data or [],
        "jobs": jobs_res.data or [],
    }


# ---------------------------------------------------------------------------
# Admin Job Actions
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel")
def admin_cancel_job(request: Request, job_id: str):
    """Force-cancel any job regardless of owner."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    try:
        job = sb.table("jobs").select("job_id, status").eq("job_id", job_id).maybe_single().execute()
        if not job.data:
            raise HTTPException(status_code=404, detail="Job not found")

        status = job.data["status"]
        if status in ("completed", "canceled"):
            raise HTTPException(status_code=400, detail=f"Job already {status}")

        if status == "in_progress":
            # Signal the agent to stop
            sb.table("jobs").update({
                "cancel_requested": True,
                "cancel_requested_at": utcnow_iso(),
            }).eq("job_id", job_id).execute()
        else:
            # Queued or paused — cancel immediately
            sb.table("jobs").update({
                "status": "canceled",
                "failed_at": utcnow_iso(),
                "fail_reason": "Canceled by admin",
            }).eq("job_id", job_id).execute()

    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin] Failed to cancel job: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel job")

    audit_log_event("admin_cancel_job", user_id=admin_uid, job_id=job_id)
    return {"status": "success", "job_id": job_id}


@router.post("/jobs/{job_id}/requeue")
def admin_requeue_job(request: Request, job_id: str):
    """Requeue a failed or canceled job."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    try:
        job = sb.table("jobs").select("job_id, status").eq("job_id", job_id).maybe_single().execute()
        if not job.data:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.data["status"] not in ("failed", "canceled"):
            raise HTTPException(status_code=400, detail="Can only requeue failed or canceled jobs")

        sb.table("jobs").update({
            "status": "queued",
            "progress": 0,
            "progress_message": "",
            "current_frame": None,
            "agent_id": None,
            "fail_reason": None,
            "failed_at": None,
            "cancel_requested": False,
            "pause_requested": False,
            "paused": False,
            "available_at": utcnow_iso(),
            "requeue_reason": "Admin requeue",
        }).eq("job_id", job_id).execute()

    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin] Failed to requeue job: {e}")
        raise HTTPException(status_code=500, detail="Failed to requeue job")

    audit_log_event("admin_requeue_job", user_id=admin_uid, job_id=job_id)
    return {"status": "success", "job_id": job_id}


# ---------------------------------------------------------------------------
# Admin Agent Disconnect
# ---------------------------------------------------------------------------

@router.delete("/agents/{agent_id}")
def admin_delete_agent(request: Request, agent_id: str):
    """Admin: remove any agent and revoke its tokens, regardless of owner."""
    admin_uid = require_admin(request)
    sb = get_supabase()

    try:
        agent = sb.table("agents").select("agent_id, name, user_id").eq("agent_id", agent_id).maybe_single().execute()
        if not agent.data:
            raise HTTPException(status_code=404, detail="Agent not found")

        owner_uid = agent.data["user_id"]
        agent_name = agent.data.get("name", "")

        # Revoke tokens
        if agent_name:
            sb.table("agent_tokens").update({"revoked": True}).eq(
                "user_id", owner_uid
            ).eq("agent_name", agent_name).execute()

        # Delete agent record
        sb.table("agents").delete().eq("agent_id", agent_id).execute()
    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin] Failed to delete agent: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete agent")

    audit_log_event("admin_agent_deleted", user_id=admin_uid, agent_id=agent_id, target_user_id=owner_uid)
    return {"status": "deleted", "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Quick Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(request: Request):
    """At-a-glance service health stats."""
    require_admin(request)
    sb = get_supabase()

    from datetime import datetime, timezone, timedelta
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    try:
        total_users = sb.table("profiles").select("user_id", count="exact").execute().count or 0
        online_agents = sb.table("agents").select("agent_id", count="exact").neq("status", "offline").execute().count or 0
        offline_agents = sb.table("agents").select("agent_id", count="exact").eq("status", "offline").execute().count or 0
        active_jobs = sb.table("jobs").select("job_id", count="exact").eq("status", "in_progress").execute().count or 0
        queued_jobs = sb.table("jobs").select("job_id", count="exact").eq("status", "queued").execute().count or 0
        completed_24h = sb.table("jobs").select("job_id", count="exact").eq("status", "completed").gte("completed_at", cutoff_24h).execute().count or 0
        failed_24h = sb.table("jobs").select("job_id", count="exact").eq("status", "failed").gte("failed_at", cutoff_24h).execute().count or 0
    except Exception as e:
        print(f"[admin] Failed to fetch stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

    return {
        "total_users": total_users,
        "online_agents": online_agents,
        "offline_agents": offline_agents,
        "active_jobs": active_jobs,
        "queued_jobs": queued_jobs,
        "completed_24h": completed_24h,
        "failed_24h": failed_24h,
    }


# ---------------------------------------------------------------------------
# Audit Log Viewer
# ---------------------------------------------------------------------------

@router.get("/audit-log")
def get_audit_log(request: Request, limit: int = 50, event: Optional[str] = None):
    """View recent audit log entries."""
    require_admin(request)
    sb = get_supabase()

    if limit < 1 or limit > 200:
        limit = 50

    try:
        query = sb.table("audit_log").select("*").order("created_at", desc=True).limit(limit)
        if event:
            query = query.eq("event", event)
        res = query.execute()
    except Exception as e:
        print(f"[admin] Failed to fetch audit log: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch audit log")

    return {"entries": res.data or []}

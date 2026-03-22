# server/server_routes_agent.py
#
# Agent-facing API endpoints.
# All agent requests authenticate with X-Agent-Token header.
# URL paths and response shapes are unchanged from v1 so existing agents keep working.

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile, File, Form

from .server_auth import require_user_from_agent_token, require_agent_belongs_to_user
from .server_supabase import get_supabase
from .server_util import utcnow_iso, enforce_rate_limit, audit_log_event, get_user_tier
from .server_settings import (
    LATEST_AGENT_VERSION,
    MAX_AGENTS_FREE,
    MAX_AGENTS_PRO,
    MAX_BLEND_FILES,
    MAX_BLEND_INFO_BYTES,
)


def _version_tuple(v: str):
    """Parse '1.2.3' into (1, 2, 3) for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _requeue_jobs_for_agent(agent_id: str, reason: str) -> bool:
    """Move all in-progress jobs assigned to this agent back to queued status."""
    sb = get_supabase()
    result = (
        sb.table("jobs")
        .select("job_id")
        .eq("agent_id", agent_id)
        .eq("status", "in_progress")
        .execute()
    )
    if not result.data:
        return False

    now = utcnow_iso()
    for row in result.data:
        sb.table("jobs").update({
            "status": "queued",
            "agent_id": None,
            "assigned_at": None,
            "requeued_at": now,
            "requeued_reason": reason,
            "requeued_from_agent": agent_id,
        }).eq("job_id", row["job_id"]).execute()
        print(f"[recovery] Requeued job {row['job_id']} from agent {agent_id} ({reason})")

    return True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/agents/register")
def register_agent(data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    user_id = token_info["user_id"]

    import re as _re
    name = (data_in.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Agent name is required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Agent name too long (max 100 chars)")
    # Strip control characters to prevent XSS / stored injection
    name = _re.sub(r"[\x00-\x1f\x7f-\x9f]", "", name)

    sb = get_supabase()

    # Upsert: reuse existing agent with the same (user_id, name) instead of
    # creating a duplicate row on every restart.
    existing = (
        sb.table("agents")
        .select("agent_id")
        .eq("user_id", user_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    now = utcnow_iso()

    if existing.data and len(existing.data) > 0:
        agent_id = existing.data[0]["agent_id"]
        sb.table("agents").update({
            "status": "idle",
            "last_seen": now,
        }).eq("agent_id", agent_id).execute()
        audit_log_event("agent_reregistered", user_id=user_id, agent_id=agent_id, name=name)
        print(f"Re-registered existing agent '{name}' with id {agent_id}")
        return {"agent_id": agent_id}

    # Enforce tier-based agent limit before creating a new agent
    tier = get_user_tier(sb, user_id)
    max_agents = MAX_AGENTS_PRO if tier == "pro" else MAX_AGENTS_FREE
    agent_count = (
        sb.table("agents")
        .select("agent_id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    if (agent_count.count or 0) >= max_agents:
        raise HTTPException(
            status_code=403,
            detail=f"Agent limit reached ({max_agents} for {tier} tier). "
                   f"Remove an existing agent or upgrade your plan.",
        )

    result = sb.table("agents").insert({
        "user_id": user_id,
        "name": name,
        "status": "idle",
        "last_seen": now,
    }).execute()

    agent_id = result.data[0]["agent_id"]
    audit_log_event("agent_registered", user_id=user_id, agent_id=agent_id, name=name)
    print(f"Registered agent '{name}' with id {agent_id}")
    return {"agent_id": agent_id}


def _is_user_active(sb, user_id: str) -> tuple[bool, str]:
    """Check if the user has an active dashboard session.

    Returns (user_active, tier).  Piggybacks tier to avoid a second query.
    """
    from datetime import datetime, timezone, timedelta
    try:
        profile = (
            sb.table("profiles")
            .select("last_active_at, tier")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        data = profile.data or {}
        tier = data.get("tier", "free")
        last_active = data.get("last_active_at")
        if not last_active:
            return False, tier
        ts = datetime.fromisoformat(last_active.replace("Z", "+00:00"))
        active = (datetime.now(timezone.utc) - ts).total_seconds() < 90
        return active, tier
    except Exception:
        return False, "free"


@router.post("/agents/{agent_id}/heartbeat")
def agent_heartbeat(request: Request, agent_id: str, data_in: dict = None, x_agent_token: str = Header(None)):
    ok, retry_after = enforce_rate_limit(
        request, "agent_heartbeat", limit=12, window_seconds=60, token=x_agent_token
    )
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many heartbeats. Retry in {retry_after}s")

    token_info = require_user_from_agent_token(x_agent_token)
    agent = require_agent_belongs_to_user(agent_id, token_info["user_id"])

    if data_in is None:
        data_in = {}

    sb = get_supabase()
    new_boot_id = data_in.get("boot_id")
    old_boot_id = agent.get("boot_id")
    telemetry = data_in.get("telemetry")
    agent_version = data_in.get("agent_version")
    now = utcnow_iso()

    # Version check (safe for old agents that don't send agent_version)
    update_available = False
    if agent_version:
        update_available = _version_tuple(agent_version) < _version_tuple(LATEST_AGENT_VERSION)

    version_info = {
        "update_available": update_available,
        "latest_version": LATEST_AGENT_VERSION,
    }

    if new_boot_id and new_boot_id != old_boot_id:
        # Agent restarted — requeue its in-progress jobs
        recovered = _requeue_jobs_for_agent(agent_id, "agent restarted (boot_id changed)")
        update_data = {
            "boot_id": new_boot_id,
            "status": "idle",
            "last_seen": now,
        }
        if telemetry is not None:
             update_data["system_info"] = telemetry
        if agent_version:
            update_data["agent_version"] = agent_version

        if agent.get("rescan_requested"):
            update_data["rescan_requested"] = False
        sb.table("agents").update(update_data).eq("agent_id", agent_id).execute()

        user_active, tier = _is_user_active(sb, token_info["user_id"])
        return {
            "status": "alive",
            "agent_status": "idle",
            "recovered": bool(recovered),
            "last_seen": now,
            "has_queued_jobs": False,
            "has_paused_jobs": False,
            "has_preview_tasks": False,
            "rescan_requested": False,
            "user_active": user_active,
            "tier": tier,
            **version_info,
        }

    # Normal heartbeat — determine status
    user_id = token_info["user_id"]
    in_progress = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("agent_id", agent_id)
        .eq("status", "in_progress")
        .execute()
    )
    has_active = (in_progress.count or 0) > 0
    current_status = agent.get("status", "idle")

    if current_status == "offline":
        new_status = "idle"
    elif current_status == "busy" and not has_active:
        new_status = "idle"
    else:
        new_status = current_status

    # Piggyback polling signals so the agent can skip separate HTTP calls:
    # - has_queued_jobs: agent only polls next-job when True
    # - rescan_requested: agent only rescans blend files when True
    # - has_preview_tasks: agent only polls preview-tasks when True
    queued_jobs = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "queued")
        .execute()
    )
    has_queued = (queued_jobs.count or 0) > 0

    paused_jobs = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "paused")
        .execute()
    )
    has_paused = (paused_jobs.count or 0) > 0

    preview_tasks = (
        sb.table("preview_requests")
        .select("request_id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    has_previews = (preview_tasks.count or 0) > 0

    rescan = bool(agent.get("rescan_requested", False))

    update_data = {
        "last_seen": now,
        "status": new_status,
    }
    # Clear rescan flag atomically so the agent only processes it once
    if rescan:
        update_data["rescan_requested"] = False
    if telemetry is not None:
         update_data["system_info"] = telemetry
    if agent_version:
        update_data["agent_version"] = agent_version

    sb.table("agents").update(update_data).eq("agent_id", agent_id).execute()

    user_active, tier = _is_user_active(sb, user_id)
    return {
        "status": "alive", "last_seen": now, "agent_status": new_status,
        "has_queued_jobs": has_queued,
        "has_paused_jobs": has_paused,
        "has_preview_tasks": has_previews,
        "rescan_requested": rescan,
        "user_active": user_active,
        "tier": tier,
        **version_info,
    }


@router.post("/agents/{agent_id}/request-rescan")
def request_rescan(agent_id: str, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    require_agent_belongs_to_user(agent_id, token_info["user_id"])
    sb = get_supabase()
    sb.table("agents").update({
        "rescan_requested": True,
        "rescan_requested_at": utcnow_iso(),
    }).eq("agent_id", agent_id).execute()
    return {"status": "ok"}


@router.get("/agents/{agent_id}/rescan-status")
def rescan_status(agent_id: str, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    agent = require_agent_belongs_to_user(agent_id, token_info["user_id"])
    return {"rescan_requested": bool(agent.get("rescan_requested", False))}


@router.post("/agents/{agent_id}/blend-files")
def update_blend_files(agent_id: str, data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    require_agent_belongs_to_user(agent_id, token_info["user_id"])

    files = data_in.get("files", [])
    if not isinstance(files, list):
        raise HTTPException(status_code=400, detail="files must be a list")
    clean = [f.strip() for f in files if isinstance(f, str) and f.strip()]
    if len(clean) > MAX_BLEND_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BLEND_FILES} blend files allowed")

    # Blend file settings info (optional — sent when agent has blender_path)
    blend_info = data_in.get("blend_files_info", {})
    if not isinstance(blend_info, dict):
        blend_info = {}
    # Enforce size limit on blend_files_info to prevent oversized payloads
    import json as _json
    if blend_info and len(_json.dumps(blend_info)) > MAX_BLEND_INFO_BYTES:
        raise HTTPException(status_code=400, detail="blend_files_info too large (max 1MB)")

    update_data: dict = {
        "blend_files": clean,
        "blend_files_updated_at": utcnow_iso(),
        "last_seen": utcnow_iso(),
        "rescan_requested": False,
    }
    if blend_info:
        update_data["blend_files_info"] = blend_info

    sb = get_supabase()
    sb.table("agents").update(update_data).eq("agent_id", agent_id).execute()

    return {"status": "ok", "count": len(clean)}


@router.post("/agents/{agent_id}/next-job")
def next_job(request: Request, agent_id: str, x_agent_token: str = Header(None)):
    ok, retry_after = enforce_rate_limit(
        request, "agent_next_job", limit=30, window_seconds=60, token=x_agent_token
    )
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many polls. Retry in {retry_after}s")

    token_info = require_user_from_agent_token(x_agent_token)
    user_id = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, user_id)

    # Emergency pause — stop all job dispatch globally
    from .server_routes_admin import get_emergency_pause
    pause = get_emergency_pause()
    if pause.get("enabled"):
        return {"job": None}

    sb = get_supabase()
    now_iso = utcnow_iso()

    # Only one active job at a time per agent — block if this agent already
    # has an in-progress job.
    busy_check = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("agent_id", agent_id)
        .eq("status", "in_progress")
        .execute()
    )
    if (busy_check.count or 0) > 0:
        print(f"[next-job] Agent {agent_id} already has in-progress job, blocking")
        return {"job": None}

    # If the user has any paused jobs, don't start new work until they're
    # resumed or canceled — only one active job at a time.
    paused_check = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "paused")
        .eq("paused", True)
        .execute()
    )
    if (paused_check.count or 0) > 0:
        print(f"[next-job] User has paused jobs, blocking agent {agent_id}")
        return {"job": None}

    # Check for a resumed job targeted at this agent first — these always
    # take priority so the agent continues the same job it paused.
    # Order by available_at DESC so the most recently resumed job wins
    # (in case stale targets somehow survive).
    targeted = (
        sb.table("jobs")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "queued")
        .eq("paused", False)
        .neq("cancel_requested", True)
        .lte("available_at", now_iso)
        .eq("target_agent_id", agent_id)
        .order("available_at", desc=True)
        .limit(1)
        .execute()
    )

    if targeted.data:
        print(f"[next-job] Found targeted job {targeted.data[0]['job_id']} for agent {agent_id}")
        candidates = targeted.data
    else:
        # Before falling back to untargeted, check if there is ANY targeted job
        # for this user.  Targeted jobs are resumed jobs that must go to a
        # specific agent.  If one exists — whether for this agent or another —
        # don't hand out untargeted work.  (If it's for *this* agent but the
        # targeted query above missed it due to available_at timing, we still
        # block so we don't accidentally pick up a different queued job.)
        any_targeted = (
            sb.table("jobs")
            .select("job_id, target_agent_id")
            .eq("user_id", user_id)
            .eq("status", "queued")
            .eq("paused", False)
            .execute()
        )
        any_targeted_data = [j for j in (any_targeted.data or []) if j.get("target_agent_id")]
        if len(any_targeted_data) > 0:
            print(f"[next-job] Targeted job(s) exist for user, skipping untargeted for agent {agent_id}")
            return {"job": None}

        # No targeted job — find the oldest untargeted queued job.
        # NOTE: Separate query (not .or_()) to prevent filter injection
        # via crafted agent_id values.
        untargeted = (
            sb.table("jobs")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "queued")
            .eq("paused", False)
            .neq("cancel_requested", True)
            .lte("available_at", now_iso)
            .is_("target_agent_id", "null")
            .order("available_at", desc=False)
            .limit(1)
            .execute()
        )
        candidates = untargeted.data or []
        if candidates:
            print(f"[next-job] Found untargeted job {candidates[0]['job_id']} for agent {agent_id}")

    if not candidates:
        return {"job": None}

    job = candidates[0]
    job_id = job["job_id"]

    # Atomically claim the job (update status to in_progress)
    claimed = (
        sb.table("jobs")
        .update({
            "status": "in_progress",
            "agent_id": agent_id,
            "assigned_at": now_iso,
            "target_agent_id": None,
            "requeued_from_agent": None,
        })
        .eq("job_id", job_id)
        .eq("status", "queued")   # optimistic lock: only succeeds if still queued
        .execute()
    )

    if not claimed.data:
        # Another process claimed it first (unlikely, but safe to handle)
        return {"job": None, "message": "No jobs available yet"}

    # Mark agent busy
    sb.table("agents").update({
        "status": "busy",
        "last_seen": now_iso,
    }).eq("agent_id", agent_id).execute()

    # Fetch the updated job row to return
    updated = sb.table("jobs").select("*").eq("job_id", job_id).limit(1).execute()
    if not updated.data:
        return {"job": None, "message": "Job claimed but fetch failed"}
    job = updated.data[0]

    audit_log_event("job_assigned", user_id=user_id, job_id=job_id, agent_id=agent_id)
    print(f"Assigned job {job_id} to agent {agent_id}")

    # Include VRAM recovery preference (Pro-only feature)
    vram_recovery = False
    try:
        tier = get_user_tier(sb, user_id)
        if tier == "pro":
            prof = (
                sb.table("profiles")
                .select("vram_recovery_enabled")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            vram_recovery = bool((prof.data or {}).get("vram_recovery_enabled", False))
    except Exception:
        pass  # Default to disabled on any error

    return {"job": job, "vram_recovery_enabled": vram_recovery}


@router.post("/agents/{agent_id}/jobs/{job_id}/pause")
def agent_pause_job(agent_id: str, job_id: str, x_agent_token: str = Header(None)):
    """Agent requesting to pause its currently active job (initiated by local popup)."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, agent_id, status")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.data.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job not assigned to this agent")
    if job.data["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Job is not in progress")

    # Mirror the web API: mark pause_requested=True so the agent's render loop picks it up
    sb.table("jobs").update({"pause_requested": True}).eq("job_id", job_id).execute()
    return {"status": "pause_requested"}


@router.post("/agents/{agent_id}/jobs/{job_id}/resume")
def agent_resume_job(agent_id: str, job_id: str, x_agent_token: str = Header(None)):
    """Agent requesting to resume a paused job (initiated by local popup)."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, paused, status")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.data.get("paused"):
        raise HTTPException(status_code=400, detail="Job is not paused")

    # Clear stale target_agent_id from any OTHER queued jobs for this user.
    # Without this, a previously-resumed job that was never claimed keeps its
    # target_agent_id, and the next-job query picks it up instead of the one
    # the user actually just resumed.
    sb.table("jobs").update({"target_agent_id": None}).eq("user_id", uid).eq("status", "queued").neq("job_id", job_id).execute()

    # Mirror the web API: set status back to queued, unpause, and target
    # back to this agent so it doesn't get picked up by a different one.
    sb.table("jobs").update({
        "status": "queued",
        "paused": False,
        "available_at": utcnow_iso(),
        "target_agent_id": agent_id,
    }).eq("job_id", job_id).execute()
    return {"status": "resumed"}


@router.post("/agents/{agent_id}/jobs/{job_id}/cancel")
def agent_cancel_job(agent_id: str, job_id: str, x_agent_token: str = Header(None)):
    """Agent requesting to cancel its current or paused job (initiated by local popup).

    Mirrors the web API behaviour:
    - in_progress jobs → set cancel_requested=True; agent's render loop stops and
      calls /jobs/{id}/canceled when done.
    - queued+paused jobs → cancel immediately (no agent loop is running them).
    """
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, agent_id, status, paused")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job.data.get("status")
    if status == "in_progress":
        # Signal the render loop; it will call /jobs/{id}/canceled when it stops.
        sb.table("jobs").update({
            "cancel_requested": True,
            "cancel_requested_at": utcnow_iso(),
        }).eq("job_id", job_id).execute()
        return {"status": "cancel_requested"}
    elif status == "queued" and job.data.get("paused"):
        # Paused job has no running render — cancel immediately.
        now = utcnow_iso()
        sb.table("jobs").update({
            "status": "canceled",
            "fail_reason": "canceled by user",
            "failed_at": now,
        }).eq("job_id", job_id).execute()
        return {"status": "canceled"}
    else:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a job with status '{status}'")


# ---------------------------------------------------------------------------
# Blender addon: job submission + status polling
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/jobs/active-check")
def agent_check_active_jobs(agent_id: str, x_agent_token: str = Header(None)):
    """Check if the user has any queued or in-progress jobs (used by Blender addon)."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    result = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("user_id", uid)
        .in_("status", ["queued", "in_progress"])
        .execute()
    )
    count = result.count or 0
    return {"has_active": count > 0, "active_count": count}


@router.post("/agents/{agent_id}/submit-job")
def agent_submit_job(agent_id: str, data_in: dict, x_agent_token: str = Header(None)):
    """Create a render job authenticated via agent token (for the Blender addon)."""
    from .server_routes_api import CreateJobRequest, _create_job_for_user
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)
    # Parse the dict through the same Pydantic model used by the web API
    job_data = CreateJobRequest(**data_in)
    return _create_job_for_user(uid, job_data)


@router.get("/agents/{agent_id}/jobs/{job_id}/status")
def agent_job_status(agent_id: str, job_id: str, x_agent_token: str = Header(None)):
    """Poll job status for Blender addon progress display."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select(
            "job_id, status, progress, progress_message, current_frame, "
            "frame_start, frame_end, fail_reason, paused"
        )
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    if not job.data or len(job.data) == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.data[0]}


@router.get("/auth/whoami")
def whoami(x_agent_token: str = Header(None)):
    """Backward-compatible agent token verification endpoint."""
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


# ---------------------------------------------------------------------------
# Preview tasks for agent
# ---------------------------------------------------------------------------

import os
from pathlib import Path
from .server_settings import PREVIEW_TEMP_DIR


@router.get("/agents/{agent_id}/preview-tasks")
def get_preview_tasks(request: Request, agent_id: str, x_agent_token: str = Header(None)):
    """Return pending preview/compile requests for this agent's user."""
    ok, retry_after = enforce_rate_limit(
        request, "agent_preview_tasks", limit=20, window_seconds=60, token=x_agent_token
    )
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry in {retry_after}s")

    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()

    # Get the user's tier so the agent knows whether to extract extra passes
    tier = get_user_tier(sb, uid)

    # Auto-expire stale pending requests (older than 60s) to prevent pile-up.
    # Exclude compile requests — they are auto-queued on job completion and may
    # take longer to be picked up (give them 10 minutes).
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    frame_cutoff = (_dt.now(_tz.utc) - _td(seconds=60)).isoformat()
    compile_cutoff = (_dt.now(_tz.utc) - _td(minutes=10)).isoformat()
    try:
        sb.table("preview_requests") \
            .update({"status": "expired"}) \
            .eq("user_id", uid) \
            .eq("status", "pending") \
            .neq("type", "compile") \
            .lt("created_at", frame_cutoff) \
            .execute()
        sb.table("preview_requests") \
            .update({"status": "expired"}) \
            .eq("user_id", uid) \
            .eq("status", "pending") \
            .eq("type", "compile") \
            .lt("created_at", compile_cutoff) \
            .execute()
    except Exception:
        pass  # Non-critical — don't block task retrieval

    result = (
        sb.table("preview_requests")
        .select("request_id, job_id, type, frame, status, pass_name")
        .eq("user_id", uid)
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(5)
        .execute()
    )

    tasks = result.data or []

    # For each task, include the job's blend_relpath and frame range so the
    # agent knows where to find the rendered frames on disk.
    # Also filter to only jobs assigned to this agent.
    if tasks:
        job_ids = list({t["job_id"] for t in tasks})
        jobs_result = (
            sb.table("jobs")
            .select("job_id, blend_relpath, frame_start, frame_end, job_group_id, retry_of, agent_id")
            .in_("job_id", job_ids)
            .execute()
        )
        job_map = {j["job_id"]: j for j in (jobs_result.data or [])}

        # Only return tasks for jobs assigned to this agent
        filtered_tasks = []
        for t in tasks:
            j = job_map.get(t["job_id"], {})
            if j.get("agent_id") != agent_id:
                continue  # Skip tasks for jobs not assigned to this agent
            t["blend_relpath"] = j.get("blend_relpath")
            t["blend_file"] = j.get("blend_file")
            t["frame_start"] = j.get("frame_start")
            t["frame_end"] = j.get("frame_end")
            t["job_group_id"] = j.get("job_group_id") or j.get("retry_of") or t["job_id"]
            filtered_tasks.append(t)
        tasks = filtered_tasks

    # Mark them as processing so they aren't picked up again
    for t in tasks:
        sb.table("preview_requests").update({"status": "processing"}).eq("request_id", t["request_id"]).execute()

    return {"tasks": tasks, "tier": tier}


@router.post("/agents/{agent_id}/jobs/{job_id}/available-passes")
def update_available_passes(
    agent_id: str,
    job_id: str,
    data_in: dict,
    x_agent_token: str = Header(None),
):
    """Agent reports which render passes are available for a job (discovered during EXR extraction)."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    passes = data_in.get("passes", [])
    if not isinstance(passes, list) or not passes:
        raise HTTPException(status_code=400, detail="passes must be a non-empty list")

    # Sanitize pass names: allow only safe characters to prevent XSS
    import re as _re
    for p in passes:
        if not isinstance(p, str) or not _re.match(r'^[\w\s.()-]+$', p) or len(p) > 100:
            raise HTTPException(status_code=400, detail=f"Invalid pass name")

    sb = get_supabase()
    # Merge with existing passes (don't lose any already known)
    existing = sb.table("jobs").select("available_passes, agent_id").eq("job_id", job_id).eq("user_id", uid).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if existing.data[0].get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    current = existing.data[0].get("available_passes") or []
    merged = list(dict.fromkeys(current + passes))  # preserve order, deduplicate
    sb.table("jobs").update({"available_passes": merged}).eq("job_id", job_id).execute()

    return {"status": "ok", "passes": merged}


@router.post("/agents/{agent_id}/preview-fail")
def report_preview_failure(
    agent_id: str,
    data_in: dict,
    x_agent_token: str = Header(None),
):
    """Agent reports that a preview request could not be fulfilled (e.g. frame file missing)."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    request_id = data_in.get("request_id")
    reason = data_in.get("reason", "unknown")
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id is required")

    sb = get_supabase()
    row = (
        sb.table("preview_requests")
        .select("request_id, user_id")
        .eq("request_id", request_id)
        .limit(1)
        .execute()
    )
    if not row.data or len(row.data) == 0:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.data[0]["user_id"] != uid:
        raise HTTPException(status_code=403, detail="Forbidden")

    sb.table("preview_requests").update({
        "status": "failed",
        "completed_at": utcnow_iso(),
    }).eq("request_id", request_id).execute()

    return {"status": "failed", "reason": reason}


@router.post("/agents/{agent_id}/preview-preload")
def preload_preview(
    agent_id: str,
    job_id: str = Form(...),
    frame: int = Form(...),
    pass_name: str = Form(...),
    file: UploadFile = File(...),
    x_agent_token: str = Header(None),
):
    """Agent proactively uploads a preview pass to local disk on the VPS.

    Creates a ready preview_request row so future frontend requests find it
    instantly via the cache-hit path in create_preview_request().
    """
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()

    # Verify the job belongs to this user AND is assigned to this agent
    job_check = (
        sb.table("jobs")
        .select("job_id, agent_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    if not job_check.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if job_check.data[0].get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    # Don't duplicate — check if a ready result already exists for this job/frame/pass
    existing = (
        sb.table("preview_requests")
        .select("request_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .eq("type", "frame")
        .eq("frame", frame)
        .eq("pass_name", pass_name)
        .eq("status", "ready")
        .limit(1)
        .execute()
    )
    if existing.data and len(existing.data) > 0:
        return {"status": "already_ready"}

    # Read file bytes with size limit and save to local disk
    from .server_settings import MAX_PREVIEW_BYTES
    chunks = []
    total = 0
    while True:
        chunk = file.file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="Preview file too large")
        chunks.append(chunk)
    jpeg_bytes = b"".join(chunks)

    if not jpeg_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File is not a valid JPEG")

    from .server_routes_jobs import _upload_frame_preview
    _upload_frame_preview(uid, job_id, jpeg_bytes, frame, pass_name)

    request_id = str(uuid.uuid4())
    now = utcnow_iso()
    sb.table("preview_requests").insert({
        "request_id": request_id,
        "job_id": job_id,
        "user_id": uid,
        "type": "frame",
        "frame": frame,
        "pass_name": pass_name,
        "status": "ready",
        "created_at": now,
        "completed_at": now,
    }).execute()

    return {"status": "ready", "request_id": request_id}


@router.post("/agents/{agent_id}/preview-upload")
def upload_preview_result(
    agent_id: str,
    request_id: str = Form(...),
    file: UploadFile = File(...),
    x_agent_token: str = Header(None),
):
    """Agent uploads a completed preview file (JPEG or MP4) to local disk on the VPS."""
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    row = (
        sb.table("preview_requests")
        .select("request_id, job_id, type, user_id, status, frame, pass_name, created_at")
        .eq("request_id", request_id)
        .limit(1)
        .execute()
    )
    if not row.data or len(row.data) == 0:
        raise HTTPException(status_code=404, detail="Request not found")
    req = row.data[0]
    if req["user_id"] != uid:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Verify the underlying job is assigned to this agent
    job_check = (
        sb.table("jobs")
        .select("agent_id")
        .eq("job_id", req["job_id"])
        .limit(1)
        .execute()
    )
    if job_check.data and job_check.data[0].get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    # Read file bytes with size limit
    from .server_settings import MAX_PREVIEW_BYTES
    chunks = []
    total = 0
    while True:
        chunk = file.file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="Preview file too large")
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    # Validate file content: JPEG magic bytes for frame previews
    if req["type"] != "compile" and not file_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File is not a valid JPEG")

    # Save to local disk
    from .server_routes_jobs import _upload_frame_preview, _upload_compile_video
    if req["type"] == "compile":
        _upload_compile_video(uid, req["job_id"], file_bytes)
    else:
        frame = req.get("frame") or 0
        pass_name = req.get("pass_name") or "Combined"
        _upload_frame_preview(uid, req["job_id"], file_bytes, frame, pass_name)

    now = utcnow_iso()
    sb.table("preview_requests").update({
        "status": "ready",
        "completed_at": now,
    }).eq("request_id", request_id).execute()

    if req["type"] == "compile":
        job_res = sb.table("jobs").select("completed_at, job_id, blend_relpath, frame_start, frame_end, fail_reason, user_id, job_group_id").eq("job_id", req["job_id"]).execute()
        if job_res.data:
            job_data = job_res.data[0]
            completed_at = job_data.get("completed_at")
            req_created_at = req.get("created_at")
            if completed_at and req_created_at:
                from datetime import datetime
                c_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                r_time = datetime.fromisoformat(req_created_at.replace("Z", "+00:00"))
                if abs((c_time - r_time).total_seconds()) < 5:
                    from .server_notifications import send_notification
                    send_notification(uid, "completed", job_data)

    return {"status": "ready"}

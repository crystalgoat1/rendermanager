# server/server_routes_api.py
#
# REST API endpoints consumed by the Preact SPA.
# All endpoints require a valid Supabase JWT (Authorization: Bearer <token>).

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from .server_auth import get_user_id_from_request
from .server_settings import (
    MIN_FRAME_NUMBER,
    MAX_FRAME_NUMBER,
    MAX_FRAMES_PER_JOB,
    MAX_QUEUED_JOBS_PER_USER,
    FREE_HISTORY_LIMIT,
    ADMIN_EMAILS,
)
from .server_supabase import get_supabase
from .server_util import utcnow_iso, audit_log_event, get_user_tier, get_subscription_info, enforce_rate_limit

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# Allowed Blender CLI enum values (agent validates these too)
ALLOWED_ENGINES = {"CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"}
ALLOWED_FORMATS = {"PNG", "JPEG", "OPEN_EXR", "OPEN_EXR_MULTILAYER", "TIFF", "BMP", "HDR"}


class _JobRequestBase(BaseModel):
    blend_relpath: str
    frame_start: int
    frame_end: int
    render_engine: Optional[str] = None
    output_format: Optional[str] = None
    frame_step: Optional[int] = None
    threads: Optional[int] = None
    render_overrides: Optional[dict] = None

    @field_validator("render_engine")
    @classmethod
    def validate_engine(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if v not in ALLOWED_ENGINES:
            raise ValueError(f"render_engine must be one of {sorted(ALLOWED_ENGINES)}")
        return v

    @field_validator("output_format")
    @classmethod
    def validate_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if v not in ALLOWED_FORMATS:
            raise ValueError(f"output_format must be one of {sorted(ALLOWED_FORMATS)}")
        return v

    @field_validator("frame_step")
    @classmethod
    def validate_frame_step(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not (1 <= v <= 100):
            raise ValueError("frame_step must be between 1 and 100")
        return v

    @field_validator("threads")
    @classmethod
    def validate_threads(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not (0 <= v <= 64):
            raise ValueError("threads must be between 0 and 64")
        return v

    @field_validator("render_overrides")
    @classmethod
    def validate_render_overrides(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("render_overrides must be a dict")
        # Allowlist of valid override keys — mirrors agent_override.py ALLOWED_OVERRIDES.
        # Unknown keys are silently stripped as defense-in-depth (agent also validates).
        ALLOWED_KEYS = {
            "resolution_x", "resolution_y", "resolution_percentage", "film_transparent",
            "color_depth", "compression", "active_camera", "passes", "exr_codec",
            "pixel_filter_type", "pixel_filter_width", "use_motion_blur", "motion_blur_shutter",
            "use_compositing", "use_sequencer", "dither_intensity", "use_border",
            "use_crop_to_border", "use_lock_interface", "use_stamp", "use_overwrite",
            "use_placeholder", "view_transform", "look", "exposure", "gamma",
            "use_simplify", "simplify_subdivision_render", "simplify_child_particles_render",
            "simplify_volumes", "texture_limit_render", "use_camera_cull", "camera_cull_margin",
            "compositor_device",
            "cycles_samples", "cycles_use_denoising", "cycles_denoiser", "cycles_device",
            "cycles_use_adaptive_sampling", "cycles_adaptive_threshold", "cycles_adaptive_min_samples",
            "cycles_denoising_prefilter", "cycles_denoising_input_passes", "cycles_denoising_use_gpu",
            "cycles_max_bounces", "cycles_diffuse_bounces", "cycles_glossy_bounces",
            "cycles_transmission_bounces", "cycles_volume_bounces", "cycles_transparent_max_bounces",
            "cycles_sample_clamp_direct", "cycles_sample_clamp_indirect",
            "cycles_caustic_reflective", "cycles_caustic_refractive", "cycles_blur_glossy",
            "cycles_film_transparent_glass", "cycles_film_transparent_roughness",
            "cycles_motion_blur_position", "cycles_use_persistent_data",
            "cycles_use_auto_tile", "cycles_tile_size", "cycles_use_light_tree",
            "cycles_ao_bounces_render",
            "eevee_taa_render_samples", "eevee_use_bloom", "eevee_use_ssr", "eevee_use_gtao",
            "eevee_shadow_cube_size", "eevee_shadow_cascade_size",
            "eevee_volumetric_start", "eevee_volumetric_end",
            "eevee_volumetric_tile_size", "eevee_volumetric_samples",
        }
        from .server_validation import validate_override_value
        return {
            k: validated
            for k, val in v.items()
            if k in ALLOWED_KEYS and (validated := validate_override_value(k, val)) is not None
        }


class CreateJobRequest(_JobRequestBase):
    target_agent_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Blend file info
# ---------------------------------------------------------------------------

@router.get("/blend-info")
def get_blend_info(request: Request):
    """Get blend file settings from the user's agents.

    Pass ?agent_id=<id> to get files for a specific agent only.
    Without the param, merges all agents' files (legacy behaviour).
    """
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    agent_id = request.query_params.get("agent_id")

    query = sb.table("agents").select("agent_id, blend_files_info").eq("user_id", uid)
    if agent_id:
        query = query.eq("agent_id", agent_id)

    agents = query.execute()

    merged: dict = {}
    for agent in (agents.data or []):
        info = agent.get("blend_files_info")
        if isinstance(info, dict):
            merged.update(info)
    return {"blend_info": merged}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.get("/jobs")
def list_jobs(request: Request):
    """Return all jobs for the current user, newest first."""
    ok, retry = enforce_rate_limit(request, "list_jobs", limit=30, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("jobs")
        .select("*")
        .eq("user_id", uid)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"jobs": result.data or []}


class ReorderRequest(BaseModel):
    job_ids: list[str]


@router.post("/jobs/reorder")
def reorder_jobs(request: Request, data: ReorderRequest):
    """Re-order queued jobs by reassigning their available_at timestamps."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    if not data.job_ids:
        return {"ok": True}

    # Verify all job_ids belong to the user and are queued
    jobs = (
        sb.table("jobs")
        .select("job_id, status, available_at")
        .eq("user_id", uid)
        .eq("status", "queued")
        .in_("job_id", data.job_ids)
        .execute()
    )
    found_ids = {j["job_id"] for j in (jobs.data or [])}
    for jid in data.job_ids:
        if jid not in found_ids:
            raise HTTPException(status_code=400, detail=f"Job {jid} not found or not queued")

    # Assign ascending timestamps so ordering matches the provided list
    base = utcnow_iso()
    for i, jid in enumerate(data.job_ids):
        ts = (datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(seconds=i)).isoformat()
        sb.table("jobs").update({"available_at": ts}).eq("job_id", jid).execute()

    return {"ok": True}


def _create_job_for_user(uid: str, data: CreateJobRequest) -> dict:
    """Shared job creation logic used by both the web frontend and the Blender addon.

    Returns the full ``{"job": {...}}`` response dict.
    """
    # Validate frame range
    if data.frame_start < MIN_FRAME_NUMBER or data.frame_end > MAX_FRAME_NUMBER:
        raise HTTPException(
            status_code=400,
            detail=f"Frames must be between {MIN_FRAME_NUMBER} and {MAX_FRAME_NUMBER}",
        )
    if data.frame_end < data.frame_start:
        raise HTTPException(status_code=400, detail="frame_end must be >= frame_start")
    if data.frame_end - data.frame_start + 1 > MAX_FRAMES_PER_JOB:
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_FRAMES_PER_JOB} frames per job",
        )

    blend_relpath = (data.blend_relpath or "").strip()
    if not blend_relpath:
        raise HTTPException(status_code=400, detail="blend_relpath is required")

    sb = get_supabase()

    # Determine user tier
    tier = get_user_tier(sb, uid)

    if tier == "free":
        # Silently enforce file defaults for Free tier users (frontend may send default states)
        data.threads = None
        data.render_overrides = None
        max_queued_jobs = 1
    else:
        # For Pro, max jobs varies by agent count (8 per agent)
        agents_res = sb.table("agents").select("agent_id", count="exact").eq("user_id", uid).execute()
        agent_count = agents_res.count or 1
        max_queued_jobs = 8 * agent_count

    # Enforce per-user queued job limit
    active = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .eq("user_id", uid)
        .in_("status", ["queued", "in_progress"])
        .execute()
    )
    if (active.count or 0) >= max_queued_jobs:
        raise HTTPException(
            status_code=400,
            detail=f"You've reached the limit of {max_queued_jobs} active job(s) for your {tier} plan.",
        )

    job_id = str(uuid.uuid4())
    row: dict = {
        "job_id": job_id,
        "user_id": uid,
        "task": "render",
        "blend_relpath": blend_relpath,
        "frame_start": data.frame_start,
        "frame_end": data.frame_end,
        "status": "queued",
        "available_at": utcnow_iso(),
        "available_passes": ["Combined"],
    }
    if data.target_agent_id:
        row["target_agent_id"] = data.target_agent_id
    # Only store settings that were explicitly set; None = use .blend file default
    if data.render_engine is not None:
        row["render_engine"] = data.render_engine
    if data.output_format is not None:
        row["output_format"] = data.output_format
    if data.frame_step is not None:
        row["frame_step"] = data.frame_step
    if data.threads is not None:
        row["threads"] = data.threads
    if data.render_overrides:
        row["render_overrides"] = data.render_overrides

    result = sb.table("jobs").insert(row).execute()

    job = result.data[0]
    audit_log_event(
        "job_created",
        user_id=uid,
        job_id=job_id,
        blend_relpath=blend_relpath,
        frame_start=data.frame_start,
        frame_end=data.frame_end,
        render_engine=data.render_engine,
        output_format=data.output_format,
    )

    # Free-tier: auto-delete old history beyond FREE_HISTORY_LIMIT
    if tier == "free":
        try:
            old_jobs = (
                sb.table("jobs")
                .select("job_id")
                .eq("user_id", uid)
                .in_("status", ["completed", "failed", "canceled"])
                .order("created_at", desc=True)
                .range(FREE_HISTORY_LIMIT, FREE_HISTORY_LIMIT + 50)
                .execute()
            )
            for j in old_jobs.data or []:
                sb.table("jobs").delete().eq("job_id", j["job_id"]).execute()
        except Exception:
            pass  # Non-critical; don't fail job creation

    return {"job": job}


@router.post("/jobs")
def create_job(request: Request, data: CreateJobRequest):
    """Create a new render job and add it to the queue."""
    uid = get_user_id_from_request(request)
    return _create_job_for_user(uid, data)


class UpdateJobRequest(_JobRequestBase):
    pass


@router.patch("/jobs/{job_id}")
def update_job(job_id: str, data: UpdateJobRequest, request: Request):
    """Update settings for a queued (or paused) job before the agent picks it up."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    job = (
        sb.table("jobs")
        .select("job_id, user_id, status, paused")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.data["status"] != "queued":
        raise HTTPException(status_code=400, detail="Only queued jobs can be edited")

    blend_relpath = data.blend_relpath.strip().replace("\\", "/")
    if not blend_relpath:
        raise HTTPException(status_code=400, detail="blend_relpath is required")

    if data.frame_start < MIN_FRAME_NUMBER or data.frame_end > MAX_FRAME_NUMBER:
        raise HTTPException(status_code=400, detail="Frame number out of range")
    if data.frame_end < data.frame_start:
        raise HTTPException(status_code=400, detail="frame_end must be >= frame_start")
    if data.frame_end - data.frame_start + 1 > MAX_FRAMES_PER_JOB:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FRAMES_PER_JOB} frames per job")

    # Determine user tier
    tier = get_user_tier(sb, uid)

    if tier == "free":
        # Silently enforce file defaults for Free tier users
        data.threads = None
        data.render_overrides = None

    # None = clear to DB NULL, meaning Blender uses .blend file default
    updates = {
        "blend_relpath": blend_relpath,
        "frame_start": data.frame_start,
        "frame_end": data.frame_end,
        "render_engine": data.render_engine,
        "output_format": data.output_format,
        "frame_step": data.frame_step,
        "threads": data.threads,
        "render_overrides": data.render_overrides,
    }

    sb.table("jobs").update(updates).eq("job_id", job_id).execute()
    audit_log_event("job_updated", user_id=uid, job_id=job_id)
    return {"status": "updated"}


@router.post("/jobs/{job_id}/mark-viewed")
def mark_job_viewed(job_id: str, request: Request):
    """Mark a completed job as viewed (dismiss 'New' highlight)."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, user_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    from datetime import datetime, timezone
    sb.table("jobs").update({"viewed_at": datetime.now(timezone.utc).isoformat()}).eq("job_id", job_id).execute()
    return {"status": "viewed"}


@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: str, request: Request):
    """Request that an in-progress job be paused by the agent."""
    ok, retry = enforce_rate_limit(request, "job_control", limit=10, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, user_id, status")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.data["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Job is not in progress")
    sb.table("jobs").update({"pause_requested": True}).eq("job_id", job_id).execute()
    return {"status": "pause_requested"}


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, request: Request):
    """Resume a paused job."""
    ok, retry = enforce_rate_limit(request, "job_control", limit=10, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, user_id, status, paused, requeued_from_agent")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.data.get("status") != "paused":
        raise HTTPException(status_code=400, detail="Job is not paused")
    prev_agent = job.data.get("requeued_from_agent")
    update = {
        "status": "queued",
        "paused": False,
        "available_at": utcnow_iso(),
    }
    # Target the job back to the agent that was rendering it so it doesn't
    # get picked up by a different agent.
    if prev_agent:
        update["target_agent_id"] = prev_agent

    # Clear stale target_agent_id from any OTHER queued jobs for this user.
    # Without this, a previously-resumed job that was never claimed keeps its
    # target_agent_id, and the next-job query picks it up instead of the one
    # the user actually just resumed.
    sb.table("jobs").update({"target_agent_id": None}).eq("user_id", uid).eq("status", "queued").neq("job_id", job_id).execute()

    print(f"[resume] job={job_id} requeued_from_agent={prev_agent} target_agent_id={update.get('target_agent_id')}")
    sb.table("jobs").update(update).eq("job_id", job_id).execute()
    return {"status": "resumed", "target_agent_id": update.get("target_agent_id")}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    """Cancel a job. For in-progress jobs, signals the agent. For queued jobs, cancels immediately."""
    ok, retry = enforce_rate_limit(request, "job_control", limit=10, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, user_id, status, agent_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job.data["status"]
    if status == "in_progress":
        # Check if the assigned agent is already offline — cancel immediately if so
        agent_id = job.data.get("agent_id")
        agent_offline = False
        if agent_id:
            agent = sb.table("agents").select("status").eq("agent_id", agent_id).maybe_single().execute()
            agent_offline = agent.data and agent.data.get("status") == "offline"

        if agent_offline:
            sb.table("jobs").update({
                "status": "canceled",
                "cancel_requested": True,
                "agent_id": None,
                "failed_at": utcnow_iso(),
                "fail_reason": "canceled by user (agent offline)",
            }).eq("job_id", job_id).execute()
            return {"status": "canceled"}

        # Signal the agent to stop; it will call /jobs/{id}/canceled when done.
        # Record cancel_requested_at so the watchdog knows how long it's been
        # waiting (assigned_at is from job start, not cancel request time).
        sb.table("jobs").update({
            "cancel_requested": True,
            "cancel_requested_at": utcnow_iso(),
        }).eq("job_id", job_id).execute()
        return {"status": "cancel_requested"}
    elif status in ("queued", "paused"):
        # Immediately mark canceled — no agent is running it
        sb.table("jobs").update({
            "status": "canceled",
            "failed_at": utcnow_iso(),
            "fail_reason": "canceled by user",
        }).eq("job_id", job_id).execute()
        return {"status": "canceled"}
    else:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a job with status '{status}'")


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    """Permanently delete a job.  Force-cancels it first if still running."""
    ok, retry = enforce_rate_limit(request, "job_control", limit=10, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("job_id, user_id, status")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")

    # If the job is still active in any form, force-cancel it before deleting
    active_statuses = ("queued", "in_progress", "paused")
    if job.data["status"] in active_statuses:
        sb.table("jobs").update({
            "status": "canceled",
            "cancel_requested": True,
            "agent_id": None,
            "assigned_at": None,
            "failed_at": utcnow_iso(),
            "fail_reason": "removed by user",
        }).eq("job_id", job_id).execute()

    # Delete associated preview_requests first (foreign key constraint)
    sb.table("preview_requests").delete().eq("job_id", job_id).execute()

    sb.table("jobs").delete().eq("job_id", job_id).execute()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------

@router.delete("/account")
def delete_account(request: Request):
    """Permanently delete the user's account and all associated data."""
    ok, retry = enforce_rate_limit(request, "account_delete", limit=3, window_seconds=300)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    # Delete all user data in dependency order
    # 1. Preview requests (references jobs)
    sb.table("preview_requests").delete().eq("user_id", uid).execute()
    # 2. Jobs
    sb.table("jobs").delete().eq("user_id", uid).execute()
    # 3. Agent tokens (references agents)
    sb.table("agent_tokens").delete().eq("user_id", uid).execute()
    # 4. Agents
    sb.table("agents").delete().eq("user_id", uid).execute()
    # 5. Subscriptions
    sb.table("subscriptions").delete().eq("user_id", uid).execute()
    # 6. Admin grants
    sb.table("admin_grants").delete().eq("user_id", uid).execute()
    # 7. Audit log
    sb.table("audit_log").delete().eq("user_id", uid).execute()
    # 8. Profile
    sb.table("profiles").delete().eq("user_id", uid).execute()

    # 9. Delete the auth user
    try:
        sb.auth.admin.delete_user(uid)
    except Exception as e:
        print(f"[account] Failed to delete auth user {uid}: {e}")
        # Data is already gone — don't fail the request

    audit_log_event("account_deleted", user_id=uid)

    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@router.get("/agents")
def list_agents(request: Request):
    """Return all agents for the current user."""
    ok, retry = enforce_rate_limit(request, "list_agents", limit=30, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("agents")
        .select("agent_id, name, status, last_seen, blend_files, blend_files_updated_at, created_at")
        .eq("user_id", uid)
        .order("last_seen", desc=True)
        .execute()
    )
    return {"agents": result.data or []}


@router.post("/agents/{agent_id}/rescan")
def request_rescan(agent_id: str, request: Request):
    """Ask the agent to refresh its blend file list."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    agent = (
        sb.table("agents")
        .select("agent_id")
        .eq("agent_id", agent_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not agent.data:
        raise HTTPException(status_code=404, detail="Agent not found")
    sb.table("agents").update({
        "rescan_requested": True,
        "rescan_requested_at": utcnow_iso(),
    }).eq("agent_id", agent_id).execute()
    return {"status": "ok"}


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, request: Request):
    """Remove an agent record and revoke all its associated tokens.

    Security: the agent is pull-only, so it cannot be instructed to do anything
    by this endpoint. Revoking its token simply means future poll requests will
    fail authentication — the agent will stop polling automatically.
    """
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    # Verify ownership
    agent = (
        sb.table("agents")
        .select("agent_id, name")
        .eq("agent_id", agent_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not agent.data:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_name = agent.data.get("name", "")

    # Revoke tokens associated with this agent name for this user
    if agent_name:
        sb.table("agent_tokens").update({"revoked": True}).eq(
            "user_id", uid
        ).eq("agent_name", agent_name).execute()

    # Clean up any unused auth codes for this agent
    if agent_name:
        try:
            sb.table("agent_auth_codes").delete().eq(
                "user_id", uid
            ).eq("agent_name", agent_name).eq("used", False).execute()
        except Exception:
            pass  # non-critical cleanup

    # Delete the agent record
    sb.table("agents").delete().eq("agent_id", agent_id).eq("user_id", uid).execute()

    audit_log_event("agent_deleted", user_id=uid, agent_id=agent_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------

@router.post("/presence")
def update_presence(request: Request):
    """Lightweight ping — records that the user is actively on the dashboard."""
    ok, retry = enforce_rate_limit(request, "presence", limit=60, window_seconds=120)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    sb.table("profiles").update({"last_active_at": utcnow_iso()}).eq("user_id", uid).execute()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(request: Request):
    ok, retry = enforce_rate_limit(request, "get_profile", limit=30, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many requests. Retry after {retry}s.",
                            headers={"Retry-After": str(retry)})
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    
    # We try to fetch tier + active_agent_id. If columns are missing, fall back gracefully.
    try:
        result = (
            sb.table("profiles")
            .select("user_id, name, created_at, tier, active_agent_id, notification_preferences, vram_recovery_enabled")
            .eq("user_id", uid)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        err_str = str(e)
        if "Could not find" in err_str and ("tier" in err_str or "active_agent_id" in err_str or "notification" in err_str):
            # Fallback: try without the missing column(s)
            try:
                result = (
                    sb.table("profiles")
                    .select("user_id, name, created_at, tier, active_agent_id")
                    .eq("user_id", uid)
                    .maybe_single()
                    .execute()
                )
            except Exception:
                result = (
                    sb.table("profiles")
                    .select("user_id, name, created_at")
                    .eq("user_id", uid)
                    .maybe_single()
                    .execute()
                )
                if result.data:
                    result.data["tier"] = "free"
        else:
            print(f"[error] Profile fetch failed: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    # Ensure tier is populated even if column exists but is null
    if "tier" not in result.data or not result.data["tier"]:
        result.data["tier"] = "free"
    # Ensure active_agent_id has a fallback
    if "active_agent_id" not in result.data:
        result.data["active_agent_id"] = None

    # Ensure notification_preferences has a fallback
    if "notification_preferences" not in result.data or not result.data["notification_preferences"]:
        result.data["notification_preferences"] = {
            "email_enabled": True,
            "discord_enabled": False,
            "discord_webhook_url": None,
            "notify_on_complete": True,
            "notify_on_failure": True,
            "notify_on_agent_offline": False,
        }

    # Ensure vram_recovery_enabled has a fallback
    if "vram_recovery_enabled" not in result.data or result.data["vram_recovery_enabled"] is None:
        result.data["vram_recovery_enabled"] = False

    # Determine if user is an admin
    is_admin = False
    try:
        user_res = sb.auth.admin.get_user_by_id(uid)
        email = user_res.user.email if user_res and user_res.user else None
        if email and email in ADMIN_EMAILS:
            is_admin = True
    except Exception:
        # Fallback if auth.admin check fails (e.g. permission or service key issues)
        pass

    result.data["is_admin"] = is_admin

    # Add subscription/grant metadata
    sub_info = get_subscription_info(sb, uid)
    result.data.update(sub_info)

    cached_tier = result.data.get("tier")
    print(f"[profile] uid={uid} cached_tier={cached_tier} sub_info={sub_info}")

    # Safety net: if we have a Stripe customer but no active subscription in our DB,
    # check Stripe directly. This handles cases where the webhook was delayed or lost
    # (e.g. 100% off promo codes where invoice.paid may not fire).
    if sub_info.get("tier_source") == "none":
        try:
            sub_row = sb.table("subscriptions").select(
                "stripe_customer_id"
            ).eq("user_id", uid).maybe_single().execute()
            cust_id = sub_row.data.get("stripe_customer_id") if sub_row and sub_row.data else None
            if cust_id:
                import stripe as _stripe
                subs = _stripe.Subscription.list(customer=cust_id, status="active", limit=1)
                if subs.data:
                    from .server_routes_billing import _sync_subscription_to_db
                    _sync_subscription_to_db(sb, subs.data[0], user_id=uid)
                    # Re-fetch subscription info after sync
                    sub_info = get_subscription_info(sb, uid)
                    result.data.update(sub_info)
                    print(f"[profile] synced missed Stripe subscription for {uid}")
        except Exception as exc:
            print(f"[profile] Stripe fallback check failed: {exc}")

    # Always compute the real tier from the waterfall (Stripe → grant → free)
    # rather than relying solely on the denormalized cache in profiles.tier,
    # which may be stale if a webhook was delayed.
    effective_tier = get_user_tier(sb, uid)
    print(f"[profile] uid={uid} effective_tier={effective_tier}")
    if effective_tier != result.data.get("tier"):
        result.data["tier"] = effective_tier
        # Also update the cache so future reads are consistent
        try:
            sb.table("profiles").update({"tier": effective_tier}).eq("user_id", uid).execute()
        except Exception:
            pass

    return result.data


class SetActiveAgentRequest(BaseModel):
    agent_id: Optional[str] = None


@router.patch("/profile/active-agent")
def set_active_agent(request: Request, data: SetActiveAgentRequest):
    """Set the user's active agent (render node) for job submission."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    agent_id = data.agent_id

    # If agent_id is provided, verify it belongs to the user
    if agent_id:
        agent = (
            sb.table("agents")
            .select("agent_id")
            .eq("agent_id", agent_id)
            .eq("user_id", uid)
            .maybe_single()
            .execute()
        )
        if not agent.data:
            raise HTTPException(status_code=404, detail="Agent not found")

    sb.table("profiles").update({
        "active_agent_id": agent_id,
    }).eq("user_id", uid).execute()

    return {"status": "ok", "active_agent_id": agent_id}


# ---------------------------------------------------------------------------
# Notification preferences
# ---------------------------------------------------------------------------

_DEFAULT_NOTIFICATION_PREFS = {
    "email_enabled": True,
    "discord_enabled": False,
    "discord_webhook_url": None,
    "notify_on_complete": True,
    "notify_on_failure": True,
    "notify_on_agent_offline": False,
}


@router.get("/notification-preferences")
def get_notification_preferences(request: Request):
    """Return the user's notification preferences."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("profiles")
        .select("notification_preferences")
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    prefs = (result.data or {}).get("notification_preferences")
    if not prefs:
        prefs = dict(_DEFAULT_NOTIFICATION_PREFS)
    return {"preferences": prefs}


class UpdateNotificationPrefs(BaseModel):
    email_enabled: Optional[bool] = None
    discord_enabled: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    notify_on_complete: Optional[bool] = None
    notify_on_failure: Optional[bool] = None
    notify_on_agent_offline: Optional[bool] = None


@router.patch("/notification-preferences")
def update_notification_preferences(request: Request, data: UpdateNotificationPrefs):
    """Update the user's notification preferences (merge-patch)."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    # Validate Discord webhook URL if provided
    if data.discord_webhook_url is not None and data.discord_webhook_url != "":
        from urllib.parse import urlparse
        try:
            parsed = urlparse(data.discord_webhook_url)
            if not (
                parsed.scheme == "https"
                and (parsed.netloc == "discord.com" or parsed.netloc.endswith(".discord.com"))
                and "/api/webhooks/" in parsed.path
            ):
                raise ValueError()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid Discord webhook URL. It should look like: https://discord.com/api/webhooks/...",
            )

    # Fetch current prefs
    result = (
        sb.table("profiles")
        .select("notification_preferences")
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    current = (result.data or {}).get("notification_preferences") or dict(_DEFAULT_NOTIFICATION_PREFS)

    # Merge only provided fields
    updates = data.dict(exclude_unset=True)
    for key, val in updates.items():
        current[key] = val

    # If discord is being disabled, don't clear the URL (user might re-enable)
    # If discord_webhook_url is explicitly set to empty string, treat as clear
    if "discord_webhook_url" in updates and updates["discord_webhook_url"] == "":
        current["discord_webhook_url"] = None

    sb.table("profiles").update(
        {"notification_preferences": current}
    ).eq("user_id", uid).execute()

    return {"preferences": current}


# ---------------------------------------------------------------------------
# VRAM Recovery preference
# ---------------------------------------------------------------------------


@router.get("/vram-recovery")
def get_vram_recovery(request: Request):
    """Return the user's VRAM recovery preference."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("profiles")
        .select("vram_recovery_enabled")
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    enabled = bool((result.data or {}).get("vram_recovery_enabled", False))
    return {"enabled": enabled}


class UpdateVRAMRecovery(BaseModel):
    enabled: bool


@router.patch("/vram-recovery")
def update_vram_recovery(request: Request, data: UpdateVRAMRecovery):
    """Update the user's VRAM recovery preference. Requires Pro tier."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    # Only Pro users can enable VRAM recovery
    if data.enabled:
        tier = get_user_tier(sb, uid)
        if tier != "pro":
            raise HTTPException(status_code=403, detail="VRAM Recovery requires a Pro subscription")

    sb.table("profiles").update(
        {"vram_recovery_enabled": data.enabled}
    ).eq("user_id", uid).execute()

    return {"enabled": data.enabled}


# ---------------------------------------------------------------------------
# Preview requests  (frame browser & animation compile)
# ---------------------------------------------------------------------------

import os
from pathlib import Path
from fastapi.responses import FileResponse
from .server_settings import PREVIEW_TEMP_DIR


class PreviewRequest(BaseModel):
    type: str = "frame"      # "frame" or "compile"
    frame: Optional[int] = None
    pass_name: Optional[str] = None
    frame_start: Optional[int] = None   # for compile: requested start frame
    frame_end: Optional[int] = None     # for compile: requested end frame


@router.post("/jobs/{job_id}/preview-request")
def create_preview_request(job_id: str, data_in: PreviewRequest, request: Request):
    """Create a frame preview or compile request for the agent to fulfil."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()

    # Validate job belongs to user
    job = (
        sb.table("jobs")
        .select("job_id, user_id, frame_start, frame_end")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    if not job.data or len(job.data) == 0:
        raise HTTPException(status_code=404, detail="Job not found")

    req_type = data_in.type
    if req_type not in ("frame", "compile"):
        raise HTTPException(status_code=400, detail="type must be 'frame' or 'compile'")

    frame = data_in.frame
    job_data = job.data[0]
    if req_type == "frame":
        if frame is None:
            raise HTTPException(status_code=400, detail="frame is required for type=frame")
        frame = int(frame)
        fs = job_data.get("frame_start", 0)
        fe = job_data.get("frame_end", 0)
        if fs and fe and (frame < fs or frame > fe):
            raise HTTPException(status_code=400, detail=f"Frame {frame} is outside this job's range ({fs}-{fe})")

    # Determine user tier
    tier = get_user_tier(sb, uid)

    if tier == "free":
        if req_type == "compile":
            raise HTTPException(status_code=403, detail="Animation compilation requires the Pro tier.")
        if req_type == "frame" and data_in.pass_name and data_in.pass_name != "Combined":
            raise HTTPException(status_code=403, detail="Viewing passes other than Combined requires the Pro tier.")

    # For frame requests: reuse existing ready or pending result.
    # For compile requests: always create a new one (frame range may have grown).
    if req_type == "frame":
        pass_name = data_in.pass_name

        # Check for existing ready OR pending request (avoids duplicate work)
        existing = sb.table("preview_requests").select("request_id, status").eq("job_id", job_id).eq("user_id", uid).eq("type", "frame").eq("frame", frame).in_("status", ["ready", "pending", "processing"])

        if pass_name:
            existing = existing.eq("pass_name", pass_name)
        else:
            existing = existing.is_("pass_name", "null")

        existing = existing.order("created_at", desc=True).limit(1).execute()
        if existing.data and len(existing.data) > 0:
            return {
                "request_id": existing.data[0]["request_id"],
                "status": existing.data[0]["status"],
            }

    # Resolve the frame range for compile requests from the job data
    job_row = job.data[0]
    job_frame_start = job_row.get("frame_start", 1)
    job_frame_end = job_row.get("frame_end", 1)

    # Use frontend-provided range if present, otherwise fall back to job range
    compile_start = data_in.frame_start if data_in.frame_start is not None else job_frame_start
    compile_end = data_in.frame_end if data_in.frame_end is not None else job_frame_end

    if req_type == "compile":
        # Check if there's already a ready compile that covers the requested range
        existing_compile = (
            sb.table("preview_requests")
            .select("request_id, status, frame_start, frame_end")
            .eq("job_id", job_id)
            .eq("user_id", uid)
            .eq("type", "compile")
            .eq("status", "ready")
            .limit(1)
            .execute()
        )
        if existing_compile.data:
            row = existing_compile.data[0]
            old_start = row.get("frame_start")
            old_end = row.get("frame_end")
            # If the existing compile covers the same or wider range, reuse it
            if old_start is not None and old_end is not None:
                if old_start <= compile_start and old_end >= compile_end:
                    return {
                        "request_id": row["request_id"],
                        "status": "ready",
                    }

        # Different range or no existing compile — delete old records and recompile
        old = (
            sb.table("preview_requests")
            .select("request_id")
            .eq("job_id", job_id)
            .eq("user_id", uid)
            .eq("type", "compile")
            .execute()
        )
        for row in (old.data or []):
            sb.table("preview_requests").delete().eq("request_id", row["request_id"]).execute()

    request_id = str(uuid.uuid4())
    insert_data = {
        "request_id": request_id,
        "job_id": job_id,
        "user_id": uid,
        "type": req_type,
        "frame": frame,
        "status": "pending",
        "created_at": utcnow_iso(),
    }

    if data_in.pass_name:
        insert_data["pass_name"] = data_in.pass_name

    # Store frame range for compile requests so we can cache-check later
    if req_type == "compile":
        insert_data["frame_start"] = compile_start
        insert_data["frame_end"] = compile_end

    sb.table("preview_requests").insert(insert_data).execute()

    return {"request_id": request_id, "status": "pending"}


@router.get("/preview-requests/{request_id}")
def get_preview_request_status(request_id: str, request: Request):
    """Poll the status of a preview request."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("preview_requests")
        .select("request_id, status, type, frame")
        .eq("request_id", request_id)
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Request not found")
    return result.data[0]


@router.get("/preview-requests/{request_id}/file")
def get_preview_file(request_id: str, request: Request):
    """Return a signed URL for the preview file (JPEG or MP4) once it is ready."""
    uid = get_user_id_from_request(request)
    sb = get_supabase()
    result = (
        sb.table("preview_requests")
        .select("request_id, status, file_path, type, job_id, frame, pass_name")
        .eq("request_id", request_id)
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Request not found")

    row = result.data[0]
    if row["status"] != "ready":
        raise HTTPException(status_code=409, detail="Preview not ready yet")

    # Legacy records with file_path: serve temp file if it still exists
    fp = row.get("file_path")
    if fp:
        from pathlib import Path as _Path
        resolved = _Path(fp).resolve()
        allowed = _Path(PREVIEW_TEMP_DIR).resolve()
        if not str(resolved).startswith(str(allowed) + os.sep):
            raise HTTPException(status_code=403, detail="Access denied")
        if resolved.is_file():
            media_type = "video/mp4" if row["type"] == "compile" else "image/jpeg"
            return FileResponse(str(resolved), media_type=media_type)

    # Serve from local disk via token-authenticated URL
    from .server_util import create_stream_token
    job_id = row["job_id"]
    token = create_stream_token(sb, uid, job_id)

    if row["type"] == "compile":
        url = f"/jobs/{job_id}/compile-stream?token={token}"
    else:
        pass_name = row.get("pass_name") or "Combined"
        frame = row["frame"]
        url = f"/jobs/{job_id}/frame-preview-file?frame={frame}&pass_name={pass_name}&token={token}"

    return {"url": url}

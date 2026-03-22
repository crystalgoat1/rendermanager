# server/server_routes_jobs.py
#
# Job lifecycle endpoints — called by the agent during rendering.
# All requests authenticate with X-Agent-Token.

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, Request
from fastapi import Form

from .server_auth import (
    require_user_from_agent_token,
    require_agent_belongs_to_user,
    require_job_in_progress,
)
from .server_settings import (
    MAX_PREVIEW_BYTES,
    AUTO_RETRY_ENABLED,
    MAX_RETRIES,
    AUTO_RETRY_BACKOFF_SECONDS,
    PREVIEW_STORAGE_DIR,
)
from .server_supabase import get_supabase
from .server_util import utcnow_iso, is_permanent_error, is_retryable_error, enforce_rate_limit, audit_log_event, get_user_tier, create_stream_token, verify_stream_token, sanitize_pass_name
from .server_notifications import send_notification

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: save preview files to local disk (VPS)
# ---------------------------------------------------------------------------

import os as _os
from pathlib import Path as _Path


def _preview_path(relative: str) -> _Path:
    """Return absolute path inside PREVIEW_STORAGE_DIR for a relative path."""
    return _Path(PREVIEW_STORAGE_DIR) / relative


def _write_preview(relative_path: str, data: bytes) -> str:
    """Write preview bytes to local disk. Creates parent dirs as needed. Returns the relative path."""
    full = _preview_path(relative_path)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return relative_path


def _upload_preview(user_id: str, job_id: str, jpeg_bytes: bytes, pass_name: str = None) -> str:
    """Save latest preview JPEG to local disk. Returns the relative storage path."""
    safe_pass = sanitize_pass_name(pass_name)
    if safe_pass and safe_pass != "Combined":
        path = f"{user_id}/{job_id}/passes/{safe_pass}.jpg"
    else:
        path = f"{user_id}/{job_id}/latest.jpg"
    return _write_preview(path, jpeg_bytes)


def _upload_frame_preview(user_id: str, job_id: str, jpeg_bytes: bytes, frame: int, pass_name: str = "Combined") -> str:
    """Save a frame-specific preview JPEG to local disk. Returns the relative storage path."""
    safe_pass = sanitize_pass_name(pass_name)
    path = f"{user_id}/{job_id}/frames/{frame}/{safe_pass}.jpg"
    return _write_preview(path, jpeg_bytes)


def _upload_compile_video(user_id: str, job_id: str, mp4_bytes: bytes) -> str:
    """Save a compiled animation MP4 to local disk. Returns the relative storage path."""
    path = f"{user_id}/{job_id}/compile.mp4"
    return _write_preview(path, mp4_bytes)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/progress")
def job_progress(request: Request, job_id: str, data_in: dict, x_agent_token: str = Header(None)):
    ok, retry_after = enforce_rate_limit(
        request, "agent_progress", limit=60, window_seconds=60, token=x_agent_token
    )
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many progress updates. Retry in {retry_after}s")

    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    agent_id = data_in.get("agent_id")
    progress = data_in.get("progress")
    message = data_in.get("message", "")

    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    if not isinstance(progress, int) or not (0 <= progress <= 100):
        raise HTTPException(status_code=400, detail="progress must be an integer between 0 and 100")

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    sb = get_supabase()

    # Offset reported progress by any pause base so progress is continuous
    # across pauses. E.g. paused at 45%, agent reports 20% on resume →
    # stored as 45 + 20*(100-45)/100 = 56%.
    progress_base = int(job.get("progress_base", 0))
    actual_progress = min(100, int(progress_base + progress * (100 - progress_base) / 100))

    update_data = {
        "progress": actual_progress,
        "progress_message": message,
        "last_progress_at": utcnow_iso(),
    }
    current_frame = data_in.get("current_frame")
    if current_frame is not None and isinstance(current_frame, int):
        # Clamp to job's frame range to prevent out-of-range values
        frame_start = int(job.get("frame_start", 0))
        frame_end = int(job.get("frame_end", 1_000_000))
        current_frame = max(frame_start, min(current_frame, frame_end))
        update_data["current_frame"] = current_frame

    sb.table("jobs").update(update_data).eq("job_id", job_id).execute()

    return {"status": "ok"}


@router.post("/jobs/{job_id}/preview/latest")
def upload_latest_preview(
        request: Request,
        job_id: str,
        agent_id: str = Form(...),
        frame: Optional[int] = Form(None),
        pass_name: Optional[str] = Form(None),
        file: UploadFile = File(...),
        x_agent_token: str = Header(None),
):
    ok, retry_after = enforce_rate_limit(
        request, "agent_upload_preview", limit=30, window_seconds=60, token=x_agent_token
    )
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many previews. Retry in {retry_after}s")

    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    ct = (file.content_type or "").lower()
    if ct not in ("image/jpeg", "image/jpg"):
        raise HTTPException(status_code=400, detail="Preview must be JPEG")

    # Read body with size limit
    chunks = []
    total = 0
    while True:
        chunk = file.file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="Preview too large")
        chunks.append(chunk)
    jpeg_bytes = b"".join(chunks)

    if not jpeg_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File is not a valid JPEG")

    storage_path = _upload_preview(uid, job_id, jpeg_bytes, pass_name=pass_name)

    sb = get_supabase()
    
    # We only update the job's main latest_preview_path if it's the "Combined" pass
    # (or if no pass_name was provided, like regular PNG rendering)
    if not pass_name or pass_name == "Combined":
        update: dict = {
            "latest_preview_path": storage_path,
            "latest_preview_at": utcnow_iso(),
        }
        if frame is not None:
            update["latest_preview_frame"] = frame
        sb.table("jobs").update(update).eq("job_id", job_id).execute()
        
    # We also keep track of what passes have been uploaded 
    # we can append them to a JSON array `available_passes` on the job
    if pass_name:
        # We need to fetch current passes first, or we could handle this client-side 
        # by just checking if the path exists. 
        # A simpler approach is to append to `available_passes` using a SQL function,
        # but supabase python client doesn't make `array_append` easy without an RPC. 
        # We'll fetch and update for the MVP.
        try:
            res = sb.table("jobs").select("available_passes").eq("job_id", job_id).execute()
            if res.data:
                passes = res.data[0].get("available_passes") or []
                if pass_name not in passes:
                    passes.append(pass_name)
                    sb.table("jobs").update({"available_passes": passes}).eq("job_id", job_id).execute()
        except Exception:
            pass

    return {"status": "ok"}


@router.get("/jobs/{job_id}/preview-url")
def get_preview_url(job_id: str, request: Request, pass_name: Optional[str] = None):
    """
    Return a short-lived token URL for the latest preview image.
    Called by the SPA — requires user JWT.
    The returned URL can be used as an <img src> without auth headers.
    """
    from .server_auth import get_user_id_from_request
    uid = get_user_id_from_request(request)

    sb = get_supabase()
    job = (
        sb.table("jobs")
        .select("user_id, latest_preview_path")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=404, detail="Not found")

    storage_path = job.data.get("latest_preview_path")

    # For non-Combined passes: the agent only preloads Combined during live
    # render.  Don't speculatively construct a storage path — return 404 so
    # the frontend falls through to on-demand extraction via preview-request.
    if pass_name and pass_name != "Combined":
        raise HTTPException(status_code=404, detail="Use on-demand preview for non-Combined passes")

    if not storage_path:
        raise HTTPException(status_code=404, detail="No preview yet")

    file_path = _preview_path(storage_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Preview file not found on disk")

    token = create_stream_token(sb, uid, job_id)
    return {"url": f"/jobs/{job_id}/preview-file?token={token}"}


@router.get("/jobs/{job_id}/frame-preview-url")
def get_frame_preview_url(job_id: str, request: Request, frame: int, pass_name: Optional[str] = "Combined"):
    """
    Return a short-lived token URL for a specific frame's preview image.
    Checks that the frame was actually uploaded (preview_requests row exists with status=ready).
    """
    from .server_auth import get_user_id_from_request
    uid = get_user_id_from_request(request)

    sb = get_supabase()
    # Check that this frame/pass was actually uploaded
    q = (
        sb.table("preview_requests")
        .select("request_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .eq("type", "frame")
        .eq("frame", frame)
        .eq("status", "ready")
    )
    if pass_name and pass_name != "Combined":
        q = q.eq("pass_name", pass_name)
    else:
        q = q.or_("pass_name.is.null,pass_name.eq.Combined")
    result = q.limit(1).execute()
    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Frame preview not available yet")

    safe_pass = sanitize_pass_name(pass_name)
    token = create_stream_token(sb, uid, job_id)
    return {"url": f"/jobs/{job_id}/frame-preview-file?frame={frame}&pass_name={safe_pass}&token={token}"}


@router.get("/jobs/{job_id}/preview-file")
def serve_preview_file(job_id: str, token: str):
    """Serve the latest preview JPEG from local disk. Auth via stream token."""
    from fastapi.responses import Response

    sb = get_supabase()
    uid = verify_stream_token(sb, token, job_id)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired stream token")

    job = (
        sb.table("jobs")
        .select("latest_preview_path")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .maybe_single()
        .execute()
    )
    if not job.data or not job.data.get("latest_preview_path"):
        raise HTTPException(status_code=404, detail="No preview")

    file_path = _preview_path(job.data["latest_preview_path"])
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Preview file not found on disk")

    return Response(
        content=file_path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=10"},
    )


@router.get("/jobs/{job_id}/frame-preview-file")
def serve_frame_preview_file(job_id: str, frame: int, pass_name: str, token: str):
    """Serve a specific frame/pass preview JPEG from local disk. Auth via stream token."""
    from fastapi.responses import Response

    sb = get_supabase()
    uid = verify_stream_token(sb, token, job_id)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired stream token")

    safe_pass = sanitize_pass_name(pass_name)
    storage_path = f"{uid}/{job_id}/frames/{frame}/{safe_pass}.jpg"
    file_path = _preview_path(storage_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Frame preview not found on disk")

    return Response(
        content=file_path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=60, immutable"},
    )


@router.get("/jobs/{job_id}/compile-url")
def get_compile_url(job_id: str, request: Request):
    """Return a URL for the compiled animation video.

    Returns a proxy URL that streams the video through our server with proper
    Range-request support, guaranteeing mobile browser compatibility.
    """
    from .server_auth import get_user_id_from_request
    uid = get_user_id_from_request(request)

    sb = get_supabase()
    result = (
        sb.table("preview_requests")
        .select("request_id, frame_start, frame_end")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .eq("type", "compile")
        .eq("status", "ready")
        .limit(1)
        .execute()
    )
    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="No compiled video available")

    row = result.data[0]

    # Return a proxy URL instead of a Supabase signed URL.
    # The proxy endpoint handles Range requests and Content-Type properly,
    # which is required for mobile video playback (iOS Safari / Chrome).
    # Since <video> tags cannot send Authorization headers, we use a
    # short-lived single-use stream token instead of the full JWT.
    stream_token = create_stream_token(sb, uid, job_id)
    proxy_url = f"/jobs/{job_id}/compile-stream?token={stream_token}"
    return {
        "url": proxy_url,
        "frame_start": row.get("frame_start"),
        "frame_end": row.get("frame_end"),
    }


@router.get("/jobs/{job_id}/compile-stream")
def stream_compile_video(job_id: str, request: Request, token: Optional[str] = None):
    """Stream the compiled animation MP4 directly with proper Range support.

    Mobile browsers (especially iOS Safari) require:
    - Correct Content-Type: video/mp4
    - Content-Length header
    - HTTP 206 Partial Content for Range requests
    Supabase signed URLs don't always provide these reliably, so we proxy.
    Because <video> tags cannot send Authorization headers, we use a
    short-lived single-use stream token instead of the full JWT.
    """
    from fastapi.responses import Response, StreamingResponse
    from .server_auth import get_user_id_from_request

    if token:
        uid = verify_stream_token(get_supabase(), token, job_id)
        if not uid:
            raise HTTPException(status_code=401, detail="Invalid or expired stream token")
    else:
        uid = get_user_id_from_request(request)

    sb = get_supabase()

    # Verify the compile is ready and belongs to user
    compile_check = (
        sb.table("preview_requests")
        .select("request_id")
        .eq("job_id", job_id)
        .eq("user_id", uid)
        .eq("type", "compile")
        .eq("status", "ready")
        .limit(1)
        .execute()
    )
    if not compile_check.data or len(compile_check.data) == 0:
        raise HTTPException(status_code=404, detail="No compiled video available")

    storage_path = f"{uid}/{job_id}/compile.mp4"

    # Read MP4 from local disk
    file_path = _preview_path(storage_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    mp4_bytes = file_path.read_bytes()

    file_size = len(mp4_bytes)
    range_header = request.headers.get("range")

    if range_header:
        # Parse Range: bytes=START-END
        import re
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            content_length = end - start + 1
            return Response(
                content=mp4_bytes[start:end + 1],
                status_code=206,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(content_length),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=300",
                },
                media_type="video/mp4",
            )

    # No Range header — return the full file
    return Response(
        content=mp4_bytes,
        status_code=200,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=300",
        },
        media_type="video/mp4",
    )


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: str, data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    agent_id = data_in.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    now = utcnow_iso()
    sb = get_supabase()
    tier = get_user_tier(sb, uid)
    frame_start = int(job.get("frame_start", 1))
    frame_end = int(job.get("frame_end", 1))
    is_multi_frame = (frame_end > frame_start)
    auto_compile = (tier == "pro" and is_multi_frame)

    # Store VRAM recovery info if provided
    vram_recovery = data_in.get("vram_recovery")
    job_update = {
        "status": "completed",
        "progress": 100,
        "progress_base": 0,
        "completed_at": now,
        "agent_id": agent_id,
    }
    if vram_recovery and isinstance(vram_recovery, dict):
        job_update["vram_recovery"] = vram_recovery

    sb.table("jobs").update(job_update).eq("job_id", job_id).execute()

    sb.table("agents").update({
        "status": "idle",
        "last_seen": now,
    }).eq("agent_id", agent_id).execute()

    audit_log_event(
        "job_completed",
        user_id=uid,
        job_id=job_id,
        agent_id=agent_id,
        job_group_id=job.get("job_group_id"),
    )

    # Merge vram_recovery into the job dict for notification access
    if vram_recovery:
        job["vram_recovery"] = vram_recovery

    if auto_compile:
        import uuid
        request_id = str(uuid.uuid4())
        sb.table("preview_requests").insert({
            "request_id": request_id,
            "job_id": job_id,
            "user_id": uid,
            "type": "compile",
            "frame": None,
            "status": "pending",
            "created_at": now,
            "frame_start": frame_start,
            "frame_end": frame_end,
        }).execute()
        # Delay notification until compile completes
    else:
        # Fire notification (background thread)
        send_notification(uid, "completed", job)

    return {"status": "completed"}


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: str, data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    agent_id = data_in.get("agent_id")
    reason = data_in.get("reason", "unknown")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    attempt = int(job.get("attempt", 1))
    now = utcnow_iso()
    sb = get_supabase()

    # Mark current job as failed
    sb.table("jobs").update({
        "status": "failed",
        "failed_at": now,
        "fail_reason": reason,
    }).eq("job_id", job_id).execute()

    # Auto-retry if eligible
    if (
        AUTO_RETRY_ENABLED
        and attempt + 1 <= MAX_RETRIES
        and not is_permanent_error(reason)
        and is_retryable_error(reason)
    ):
        new_job_id = str(uuid.uuid4())
        available_at = (
            datetime.now(timezone.utc) + timedelta(seconds=AUTO_RETRY_BACKOFF_SECONDS)
        ).isoformat()
        retry_row = {
            "job_id": new_job_id,
            "job_group_id": job.get("job_group_id") or job_id,
            "user_id": uid,
            "task": job.get("task", "render"),
            "blend_relpath": job.get("blend_relpath"),
            "frame_start": job.get("frame_start"),
            "frame_end": job.get("frame_end"),
            "status": "queued",
            "retry_of": job_id,
            "attempt": attempt + 1,
            "available_at": available_at,
        }
        # Carry over render settings so retries use the same config
        for key in ("render_engine", "output_format", "frame_step", "threads", "render_overrides"):
            val = job.get(key)
            if val is not None:
                retry_row[key] = val
        sb.table("jobs").insert(retry_row).execute()

        audit_log_event(
            "job_retry_scheduled",
            user_id=uid,
            job_id=job_id,
            new_job_id=new_job_id,
            agent_id=agent_id,
            attempt=attempt + 1,
            backoff_seconds=AUTO_RETRY_BACKOFF_SECONDS,
            reason=reason,
        )
        print(f"Auto-retry scheduled: failed {job_id} -> new {new_job_id} (attempt {attempt + 1})")

    sb.table("agents").update({
        "status": "idle",
        "last_seen": now,
    }).eq("agent_id", agent_id).execute()

    # Only notify on final failure (no auto-retry scheduled)
    retried = (
        AUTO_RETRY_ENABLED
        and attempt + 1 <= MAX_RETRIES
        and not is_permanent_error(reason)
        and is_retryable_error(reason)
    )

    audit_log_event(
        "job_failed",
        user_id=uid,
        job_id=job_id,
        agent_id=agent_id,
        job_group_id=job.get("job_group_id"),
        reason=reason,
        attempt=attempt,
    )

    if not retried:
        send_notification(uid, "failed", job)

    return {"status": "failed"}


@router.get("/jobs/{job_id}/control")
def job_control(job_id: str, agent_id: str, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]
    require_agent_belongs_to_user(agent_id, uid)

    sb = get_supabase()
    result = (
        sb.table("jobs")
        .select("pause_requested, cancel_requested, agent_id, user_id")
        .eq("job_id", job_id)
        .eq("status", "in_progress")
        .maybe_single()
        .execute()
    )
    if not result.data:
        return {"pause": False, "cancel": False}

    job = result.data
    if job.get("user_id") != uid or job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "pause": bool(job.get("pause_requested", False)),
        "cancel": bool(job.get("cancel_requested", False)),
    }


@router.post("/jobs/{job_id}/paused")
def job_paused(job_id: str, data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    agent_id = data_in.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    now = utcnow_iso()
    sb = get_supabase()

    # If cancel was requested while the agent was pausing, cancel instead of
    # pausing — otherwise the cancel_requested flag gets cleared and the
    # cancel is silently lost.
    if job.get("cancel_requested"):
        sb.table("jobs").update({
            "status": "canceled",
            "failed_at": now,
            "fail_reason": "canceled by user",
            "pause_requested": False,
            "cancel_requested": False,
        }).eq("job_id", job_id).execute()

        sb.table("agents").update({
            "status": "idle",
            "last_seen": now,
        }).eq("agent_id", agent_id).execute()

        audit_log_event("job_canceled", user_id=uid, job_id=job_id, agent_id=agent_id)
        return {"status": "canceled"}

    sb.table("jobs").update({
        "status": "paused",
        "paused": True,
        "paused_at": now,
        "agent_id": None,
        "assigned_at": None,
        "pause_requested": False,
        "cancel_requested": False,
        "requeued_at": now,
        "requeued_reason": "paused by user",
        "requeued_from_agent": agent_id,
        # Snapshot current progress so resumed reporting starts from here
        "progress_base": int(job.get("progress", 0)),
    }).eq("job_id", job_id).execute()

    sb.table("agents").update({
        "status": "idle",
        "last_seen": now,
    }).eq("agent_id", agent_id).execute()

    audit_log_event("job_paused", user_id=uid, job_id=job_id, agent_id=agent_id)
    return {"status": "paused_and_requeued"}


@router.post("/jobs/{job_id}/canceled")
def job_canceled(job_id: str, data_in: dict, x_agent_token: str = Header(None)):
    token_info = require_user_from_agent_token(x_agent_token)
    uid = token_info["user_id"]

    agent_id = data_in.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    require_agent_belongs_to_user(agent_id, uid)

    job = require_job_in_progress(job_id, uid)
    if job.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Job is not assigned to this agent")

    now = utcnow_iso()
    sb = get_supabase()
    sb.table("jobs").update({
        "status": "canceled",
        "cancel_requested": False,
        "pause_requested": False,
        "failed_at": now,
        "fail_reason": "canceled by user",
    }).eq("job_id", job_id).execute()

    sb.table("agents").update({
        "status": "idle",
        "last_seen": now,
    }).eq("agent_id", agent_id).execute()

    audit_log_event("job_canceled", user_id=uid, job_id=job_id, agent_id=agent_id)
    return {"status": "canceled"}

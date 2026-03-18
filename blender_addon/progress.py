# blender_addon/progress.py
#
# Background job-status polling using bpy.app.timers + daemon threads.
# All HTTP work happens off the main thread; results are passed via a queue.

from __future__ import annotations

import queue
import threading
import time

import bpy

from . import api

_result_queue: queue.Queue = queue.Queue()
_active_job_id: str | None = None
_stop_flag = threading.Event()
_optimistic_until: float = 0.0  # time.monotonic() deadline; polling skips paused/status overwrite until then

POLL_INTERVAL = 3.0  # seconds
OPTIMISTIC_GUARD_SECONDS = 8.0  # how long to protect optimistic UI state


def set_optimistic_guard():
    """Call after an optimistic UI update so polling won't overwrite it."""
    global _optimistic_until
    _optimistic_until = time.monotonic() + OPTIMISTIC_GUARD_SECONDS


def _poll_once(backend_url: str, agent_id: str, token: str, job_id: str) -> None:
    """Fetch job status in a background thread and push the result to the queue."""
    try:
        data = api.get_job_status(backend_url, agent_id, token, job_id)
        _result_queue.put(("ok", data.get("job", {})))
    except Exception as e:
        _result_queue.put(("error", str(e)))


def _timer_callback() -> float | None:
    """Blender timer: drain the queue, update scene properties, schedule next poll."""
    global _active_job_id

    props = bpy.context.scene.remote_render

    # Drain all queued results (usually just one)
    latest = None
    while True:
        try:
            latest = _result_queue.get_nowait()
        except queue.Empty:
            break

    if latest is not None:
        kind, payload = latest
        guarded = time.monotonic() < _optimistic_until
        if kind == "ok" and isinstance(payload, dict):
            # Always update progress/frame info
            props.job_progress = int(payload.get("progress", 0))
            props.job_current_frame = int(payload.get("current_frame", 0) or 0)
            props.job_message = payload.get("progress_message", "") or ""
            props.job_total_frames = (
                int(payload.get("frame_end", 0)) - int(payload.get("frame_start", 0)) + 1
            )
            # Store the error message if the job failed server-side
            props.error_message = str(payload.get("error_message", ""))
            # Only overwrite status/paused if NOT in optimistic guard window
            if not guarded:
                props.job_status = payload.get("status", "")
                props.job_paused = bool(payload.get("paused", False))
        elif kind == "error":
            props.error_message = str(payload)

        # Force sidebar redraw
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()

    # Check if we should stop
    status = props.job_status
    if _stop_flag.is_set() or status in ("completed", "failed", "canceled"):
        _active_job_id = None
        return None  # unregister timer

    # Schedule next background poll
    if not _stop_flag.is_set() and _active_job_id:
        cfg = _get_config()
        if cfg:
            t = threading.Thread(
                target=_poll_once,
                args=(cfg["backend_url"], cfg["agent_id"], cfg["agent_token"], _active_job_id),
                daemon=True,
            )
            t.start()

    return POLL_INTERVAL


def _get_config() -> dict | None:
    """Read cached config from the addon's global state."""
    from . import _cached_config
    return _cached_config


def start_polling(job_id: str) -> None:
    """Begin polling a job. Only one job can be polled at a time."""
    global _active_job_id
    _stop_flag.clear()
    _active_job_id = job_id

    # Drain any stale results
    while not _result_queue.empty():
        try:
            _result_queue.get_nowait()
        except queue.Empty:
            break

    # Kick off the first poll immediately
    cfg = _get_config()
    if cfg:
        t = threading.Thread(
            target=_poll_once,
            args=(cfg["backend_url"], cfg["agent_id"], cfg["agent_token"], job_id),
            daemon=True,
        )
        t.start()

    # Register the timer
    if not bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.register(_timer_callback, first_interval=POLL_INTERVAL)


def stop_polling() -> None:
    """Stop polling the current job."""
    global _active_job_id
    _stop_flag.set()
    _active_job_id = None
    if bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.unregister(_timer_callback)


def is_polling() -> bool:
    return _active_job_id is not None

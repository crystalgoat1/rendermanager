import argparse
import atexit
import os
import threading
import time
import uuid
import msvcrt

from agent.agent_installer_gui import run_setup_wizard
from agent.brand import APP_DISPLAY_NAME
from agent.agent_config import (
    default_config_path,
    load_config_from_path,
    validate_config_for_mvp,
    ensure_agent_config,
    get_saved_agent_id,
    set_saved_agent_id,
    get_appdata_dir,
)
from agent.agent_backend import (
    BackendSession, AuthError, register_agent, send_heartbeat, get_next_job,
    complete_job, fail_job,
    get_preview_tasks, upload_preview_result, report_preview_failure,
    report_available_passes, preload_preview_pass,
)
from agent.agent_blend_scan import blend_publish_loop
from agent.agent_render import process_job, make_output_dir_for_job, find_frame_file
from agent.agent_local_cache import get_latest_cached, convert_frame_on_demand
from agent.agent_notify import notify_render_complete, notify_render_failed, notify_disconnected


HEARTBEAT_IDLE_SECONDS = 15
HEARTBEAT_ACTIVE_SECONDS = 10
HEARTBEAT_SLOW_SECONDS = 45    # user inactive, no render
JOB_POLL_SECONDS = 3
PREVIEW_POLL_SECONDS = 5
BOOT_ID = str(uuid.uuid4())

_lock_fp = None


def acquire_single_instance_lock() -> None:
    """
    Prevent running multiple agent instances globally by placing the lock in AppData.
    Windows-only lock using msvcrt. If lock cannot be acquired, raises RuntimeError.
    """
    global _lock_fp
    appdata_dir = get_appdata_dir()
    os.makedirs(appdata_dir, exist_ok=True)
    lock_path = os.path.join(appdata_dir, ".agent.lock")

    # Keep the file handle open for the lifetime of the process.
    _lock_fp = open(lock_path, "a+b")

    import time
    for _ in range(10):
        try:
            # Lock 1 byte of the file (non-blocking). If already locked, raises OSError.
            msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        try:
            _lock_fp.close()
        except Exception:
            pass
        _lock_fp = None
        raise RuntimeError(f"{APP_DISPLAY_NAME} is already running for this workspace.")

    atexit.register(release_single_instance_lock)


def release_single_instance_lock() -> None:
    """Explicitly release the single-instance lock. Safe to call multiple times."""
    global _lock_fp
    if _lock_fp is None:
        return
    try:
        msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        _lock_fp.close()
    except Exception:
        pass
    _lock_fp = None


def ensure_registered(session: BackendSession, cfg: dict) -> str:
    agent_id = get_saved_agent_id(cfg)
    if agent_id:
        try:
            send_heartbeat(session, agent_id, BOOT_ID)
            return agent_id
        except AuthError:
            raise  # Token revoked server-side — don't try to re-register
        except Exception as e:
            print("Saved agent_id failed heartbeat, will re-register:", e)

    print("No valid agent_id found. Registering...")
    agent_id = register_agent(session, cfg["name"])
    set_saved_agent_id(cfg, agent_id)
    print("Registered! agent_id =", agent_id)
    return agent_id


def heartbeat_loop(
    session: BackendSession,
    agent_id: str,
    stop_event: threading.Event,
    state: dict,
    cfg: dict,
):
    from agent.agent_telemetry import get_system_telemetry

    # Collect telemetry in a separate thread so it never blocks the heartbeat.
    _cached_telemetry = {}

    def _refresh_telemetry():
        nonlocal _cached_telemetry
        try:
            _cached_telemetry = get_system_telemetry(cfg.get("workspace_root", ""))
        except Exception:
            pass  # keep last cached value

    backoff = 1.0
    consecutive_403s = 0
    while not stop_event.is_set():
        # Only collect + send telemetry when someone might be looking at it
        # (rendering or user on dashboard).  Saves ~300 bytes per idle heartbeat.
        _should_telemetry = bool(state.get("active_job_id") or state.get("user_active"))
        if _should_telemetry:
            tele_thread = threading.Thread(target=_refresh_telemetry, daemon=True, name="telemetry")
            tele_thread.start()
            tele_thread.join(timeout=5.0)

        try:
            hb_start = time.time()
            _tele = _cached_telemetry if _should_telemetry else None
            resp = send_heartbeat(session, agent_id, BOOT_ID, telemetry=_tele)
            hb_elapsed = time.time() - hb_start
            if resp and resp.get("update_available"):
                state["update_available"] = True
                state["latest_version"] = resp.get("latest_version", "")
            # Propagate polling signals from server so other loops can skip HTTP calls
            state["has_queued_jobs"] = bool(resp.get("has_queued_jobs"))
            state["has_paused_jobs"] = bool(resp.get("has_paused_jobs"))
            state["has_preview_tasks"] = bool(resp.get("has_preview_tasks"))
            state["user_active"] = bool(resp.get("user_active"))
            if resp.get("tier"):
                state["tier"] = resp["tier"]
            if resp.get("rescan_requested"):
                state["rescan_requested"] = True
            was_disconnected = not state["connected"]
            state["connected"] = True
            backoff = 1.0
            consecutive_403s = 0
            if was_disconnected:
                print(f"[hb] Reconnected (heartbeat took {hb_elapsed:.1f}s)")
        except AuthError:
            # The server explicitly rejected our token (HTTP 401/403).
            # Only kill the agent if this happens repeatedly while idle.
            # During rendering, network congestion can cause spurious 403s
            # so we're much more lenient.
            consecutive_403s += 1
            is_rendering = bool(state.get("active_job_id"))
            threshold = 10 if is_rendering else 3

            if consecutive_403s >= threshold:
                print(f"\n[agent] Token unauthorized after {consecutive_403s} consecutive 401/403 responses — stopping agent\n")
                state["unauthorized"] = True
                state["connected"] = False
                stop_event.set()
                return

            print(f"[hb] Warning: Heartbeat auth rejected (attempt {consecutive_403s}/{threshold}). Retrying...")
            was_connected = state["connected"]
            state["connected"] = False
            backoff = min(backoff * 2.0, 30.0)
            if was_connected:
                notify_disconnected()

        except Exception as e:
            # Network errors, timeouts, etc. — never treat these as auth failures.
            consecutive_403s = 0
            was_connected = state["connected"]
            state["connected"] = False
            state["last_error"] = str(e)
            backoff = min(backoff * 2.0, 30.0)
            # Always log heartbeat failures so we can diagnose issues
            print(f"[hb] Heartbeat failed: {e}")
            if was_connected:
                notify_disconnected()

        is_rendering = bool(state.get("active_job_id"))
        has_queued = bool(state.get("has_queued_jobs"))
        user_active = bool(state.get("user_active"))

        if is_rendering or has_queued:
            interval = HEARTBEAT_ACTIVE_SECONDS     # 10s
        elif user_active:
            interval = HEARTBEAT_IDLE_SECONDS       # 15s
        else:
            interval = HEARTBEAT_SLOW_SECONDS       # 30s
        stop_event.wait(max(float(interval), backoff))


def job_loop(
        cfg: dict,
        session: BackendSession,
        agent_id: str,
        active_event: threading.Event,
        stop_event: threading.Event,
        state: dict,
):
    backoff = 1.0
    while not stop_event.is_set():
        if not active_event.is_set():
            state["status"] = "Paused (not polling)"
            stop_event.wait(0.5)
            continue

        # If we just paused a job, wait until the server signals that it's
        # been resumed (queued again).  The next-job endpoint will only hand
        # us the targeted/resumed job thanks to target_agent_id, so we won't
        # accidentally pick up a different one.
        if state.get("paused_job_id"):
            # Check if the user cancelled the paused job locally (popup button).
            if state.get("cancel_event") and state["cancel_event"].is_set():
                paused_jid = state["paused_job_id"]
                state["paused_job_id"] = None
                state["active_filename"] = None
                state["cancel_event"].clear()
                state["status"] = "Ready"
                print(f"[job_loop] Paused job {paused_jid} cancelled locally")
                continue
            # Check if the paused job was cancelled from the web dashboard.
            # The heartbeat tells us whether any paused jobs exist on the
            # server.  If not, our paused_job_id is stale (cancelled/deleted).
            if not state.get("has_paused_jobs"):
                paused_jid = state["paused_job_id"]
                state["paused_job_id"] = None
                state["active_filename"] = None
                state["status"] = "Ready"
                print(f"[job_loop] Paused job {paused_jid} no longer exists on server (cancelled from web?)")
                continue
            if not state.get("has_queued_jobs"):
                state["status"] = f"Paused: {state.get('active_filename', 'job')}"
                stop_event.wait(0.5)
                continue
            # has_queued_jobs is true — the paused job was likely resumed,
            # fall through to poll and the server will hand it back to us.

        # Skip the HTTP call when the heartbeat says no jobs are queued.
        # This is the single biggest egress saver for idle agents.
        # Exception: when user is active on the dashboard, poll every ~5 s
        # as a fallback so newly-created jobs are picked up quickly without
        # waiting for the next heartbeat cycle.
        if not state.get("has_queued_jobs"):
            user_active = state.get("user_active", False)
            if user_active:
                # User is on dashboard — poll at normal cadence so new
                # jobs start within a few seconds of creation.
                state["status"] = "Idle"
                stop_event.wait(JOB_POLL_SECONDS)
                # Fall through to the next-job HTTP call below
            else:
                state["status"] = "Idle"
                stop_event.wait(0.5)
                continue

        try:
            state["status"] = "Polling for jobs..."
            resp = get_next_job(session, agent_id)
            # Don't set state["connected"] here — only the heartbeat
            # thread should manage connection status.  The job loop
            # setting it caused a race where a job-loop timeout would
            # flicker the UI to "offline" even though heartbeats were fine.
            backoff = 1.0

            job = resp.get("job")
            if not job:
                stop_event.wait(JOB_POLL_SECONDS)
                continue

            vram_recovery = resp.get("vram_recovery_enabled", False)

            job_id = job.get("job_id")

            # If we still have a stale paused_job_id but the server gave us
            # a different job, the paused job was likely cancelled from the
            # dashboard.  Clear the stale state and accept the new job —
            # the server already claimed it (set to in_progress), so
            # rejecting it would leave it stuck forever.
            paused_id = state.get("paused_job_id")
            if paused_id and job_id != paused_id:
                print(f"[job_loop] Clearing stale paused_job_id {paused_id}, accepting new job {job_id}")
                state["paused_job_id"] = None
                state["has_paused_jobs"] = False

            blend_relpath = job.get("blend_relpath", "")
            filename = os.path.basename(blend_relpath) if blend_relpath else f"job {job_id[:8]}"
            state["active_job_id"] = job_id
            state["active_filename"] = filename
            state["paused_job_id"] = None
            state["status"] = f"Rendering {filename}"

            try:
                # Clear any stale local control signals from a previous job
                state["pause_event"].clear()
                state["cancel_event"].clear()

                def _on_prog(pct, msg, cur_frame):
                    state["status"] = msg
                result = process_job(
                    cfg, session, agent_id, job,
                    stop_event=stop_event,
                    progress_cb=_on_prog,
                    vram_recovery_enabled=vram_recovery,
                    pause_event=state["pause_event"],
                    cancel_event=state["cancel_event"],
                    state=state,
                )
                state["active_job_id"] = None

                # process_job returns a dict: {"status": "completed", "vram_recovery": {...}}
                result_status = result.get("status") if isinstance(result, dict) else result
                vram_recovery_info = result.get("vram_recovery") if isinstance(result, dict) else None

                if result_status == "completed":
                    complete_job(session, job_id, agent_id, vram_recovery=vram_recovery_info)
                    state["status"] = f"Completed {filename}"
                    state["last_completed_job"] = job_id
                    state["active_filename"] = None
                    notify_render_complete(filename)
                elif result_status == "paused":
                    state["status"] = f"Paused: {filename}"
                    state["paused_job_id"] = job_id
                    state["has_paused_jobs"] = True  # prevent race with heartbeat
                elif result_status == "canceled":
                    state["status"] = f"Canceled: {filename}"
                    state["active_filename"] = None
                else:
                    state["status"] = f"{filename}: {result_status}"
                    state["active_filename"] = None
            except Exception as e:
                state["active_job_id"] = None
                state["last_error"] = str(e)
                state["status"] = f"{filename} failed"
                state["last_failed_job"] = job_id
                state["active_filename"] = None
                notify_render_failed(filename, str(e))
                try:
                    fail_job(session, job_id, agent_id, str(e))
                except Exception:
                    pass

            # Always pause before polling again, even if we just finished a job
            stop_event.wait(JOB_POLL_SECONDS)

        except Exception as e:
            state["active_job_id"] = None
            # Don't set state["connected"] = False here — let the
            # heartbeat thread be the single source of truth for
            # connection status.
            state["last_error"] = str(e)
            state["status"] = "Server unreachable (retrying)"
            backoff = min(backoff * 2.0, 30.0)
            stop_event.wait(backoff)


def preview_task_loop(
    cfg: dict,
    session: BackendSession,
    agent_id: str,
    stop_event: threading.Event,
    state: dict,
):
    """Background loop: polls for and processes frame preview / compile requests."""
    output_root = cfg["output_root"]
    blend_root = cfg["blend_root"]
    workspace_root = cfg["workspace_root"]

    # Poll faster during active render (user may be switching passes) and
    # when the heartbeat says tasks exist.  Idle = very slow background check.
    PREVIEW_RENDER_SECONDS = 5   # during active render
    PREVIEW_IDLE_SECONDS = 30    # no render, no tasks flagged

    while not stop_event.is_set():
        has_tasks = state.get("has_preview_tasks")
        is_rendering = bool(state.get("active_job_id"))
        user_active = bool(state.get("user_active"))

        # Skip polling entirely when nobody is watching and nothing to do
        if not user_active and not is_rendering and not has_tasks:
            stop_event.wait(PREVIEW_IDLE_SECONDS)
            continue

        if has_tasks:
            interval = PREVIEW_POLL_SECONDS  # 5s — fast, tasks waiting
        elif is_rendering:
            interval = PREVIEW_RENDER_SECONDS  # 5s — user might request passes
        else:
            interval = PREVIEW_IDLE_SECONDS  # 30s — nothing happening

        try:
            data = get_preview_tasks(session, agent_id)
            tasks = data.get("tasks", [])
            tier = data.get("tier", "free")
        except Exception as e:
            print(f"[preview] Error getting tasks: {e}")
            stop_event.wait(PREVIEW_POLL_SECONDS)
            continue

        for task in tasks:
            if stop_event.is_set():
                break
            try:
                _process_preview_task(task, tier, cfg, session, agent_id,
                                      output_root, blend_root, workspace_root, state)
            except Exception as e:
                print(f"[preview] Error processing task {task.get('request_id')}: {e}")

        # If we just processed tasks, check again quickly in case more are queued
        if tasks:
            stop_event.wait(1)
        else:
            stop_event.wait(interval)


# Track which (job, frame) combos have already been preloaded so we don't re-upload
_preloaded_frames: dict[str, int] = {}  # job_id → last preloaded frame


def _background_preload_passes(
    render_path: str | None,
    cache_dir: str | None,
    all_passes: list[str],
    already_uploaded_pass: str,
    frame: int,
    session: BackendSession,
    agent_id: str,
    job_id: str,
    files_map: dict[str, str] | None = None,
    temp_dir_to_cleanup: str | None = None,
):
    """Spawn a daemon thread to preload sibling passes without blocking the preview loop.

    Two modes:
    - files_map or cache_dir provided: upload directly from existing files.
    - render_path provided (EXR): extract each pass individually and upload one at a time.
    """
    def _do_preload():
        import tempfile
        import shutil as _shutil

        try:
            if files_map or cache_dir:
                # Files already extracted — just upload them
                _preload_sibling_passes(
                    cache_dir, all_passes, already_uploaded_pass, frame,
                    session, agent_id, job_id,
                    files_map=files_map,
                )
            elif render_path and render_path.lower().endswith(".exr"):
                # Extract each pass individually and upload immediately (streaming)
                from .agent_exr_preview import extract_single_exr_pass

                if _preloaded_frames.get(job_id) == frame:
                    return
                _preloaded_frames[job_id] = frame

                for pname in all_passes:
                    if pname == already_uploaded_pass:
                        continue
                    tmp = tempfile.mkdtemp(prefix="agent_preload_")
                    dst = os.path.join(tmp, f"{pname}.jpg")
                    try:
                        if extract_single_exr_pass(render_path, pname, dst):
                            ok = preload_preview_pass(
                                session, agent_id,
                                job_id, frame, pname, dst,
                            )
                            if ok:
                                print(f"[preview] Preloaded pass '{pname}' for frame {frame}")
                    finally:
                        _shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            print(f"[preview] Background preload error: {e}")
        finally:
            if temp_dir_to_cleanup:
                import shutil as _shutil2
                _shutil2.rmtree(temp_dir_to_cleanup, ignore_errors=True)

    t = threading.Thread(target=_do_preload, daemon=True, name="preload-passes")
    t.start()


def _preload_sibling_passes(
    cache_dir: str | None,
    all_passes: list[str],
    already_uploaded_pass: str,
    frame: int,
    session: BackendSession,
    agent_id: str,
    job_id: str,
    files_map: dict[str, str] | None = None,
):
    """Upload sibling EXR passes so pass-switching is instant on the frontend.

    Runs AFTER the main requested pass is already uploaded and marked ready,
    so it doesn't block the user's current request.
    Skips if this (job, frame) was already preloaded.
    """
    # Skip if we already preloaded this exact frame for this job
    if _preloaded_frames.get(job_id) == frame:
        return
    _preloaded_frames[job_id] = frame

    for pname in all_passes:
        if pname == already_uploaded_pass:
            continue

        # Find the JPEG file path
        jpg_path = None
        if files_map and pname in files_map:
            jpg_path = files_map[pname]
        elif cache_dir:
            import os
            candidate = os.path.join(cache_dir, f"{pname}.jpg")
            if os.path.isfile(candidate):
                jpg_path = candidate

        if not jpg_path:
            continue

        ok = preload_preview_pass(
            session, agent_id,
            job_id, frame, pname, jpg_path,
        )
        if ok:
            print(f"[preview] Preloaded pass '{pname}' for frame {frame}")


def _process_preview_task(
    task: dict, tier: str, cfg: dict, session: BackendSession, agent_id: str,
    output_root: str, blend_root: str, workspace_root: str, state: dict,
):
    """Handle a single preview/compile task.

    For frame requests:
      1. Check latest-frame local cache (fast path ~1-2s)
      2. Fall back to on-demand conversion from source file (~1-4s)

    For compile requests:
      - Blocked during active render (resource contention)
      - Supports pass_name for EXR pass selection
    """
    import shutil

    request_id = task["request_id"]
    job_id = task["job_id"]
    req_type = task["type"]
    blend_relpath = task.get("blend_relpath") or ""
    job_group_id = task.get("job_group_id") or job_id

    # Reconstruct the output directory path (same logic as agent_render.py)
    blend_file = os.path.join(blend_root, blend_relpath) if blend_relpath else ""
    job_out_dir = make_output_dir_for_job(output_root, blend_file, job_group_id)
    output_pattern = os.path.join(job_out_dir, "render_####")

    if req_type == "frame":
        frame = task.get("frame")
        if frame is None:
            report_preview_failure(session, agent_id, request_id, "no frame number")
            return

        pass_name = task.get("pass_name") or "Combined"
        blender_path = cfg.get("blender_path", "blender")

        # ── Fast path: latest-frame local cache ──
        cached = get_latest_cached(workspace_root, job_id)
        if cached and cached["frame"] == frame:
            cache_dir = cached["dir"]
            # Look strictly for the requested pass
            jpg_path = os.path.join(cache_dir, f"{pass_name}.jpg")

            if os.path.isfile(jpg_path):
                upload_preview_result(session, agent_id, request_id, jpg_path)
                # Report available passes for EXR (so frontend knows the pass names)
                all_passes = cached.get("passes", [])
                if len(all_passes) > 1:
                    report_available_passes(session, agent_id, job_id, all_passes)
                print(f"[preview] Served frame {frame} pass '{pass_name}' from latest cache")
                return

        # ── Slow path: on-demand conversion from source file ──
        render_path = find_frame_file(output_pattern, frame)
        if not render_path:
            report_preview_failure(session, agent_id, request_id,
                                   f"Frame {frame} not found on disk")
            return

        ext = os.path.splitext(render_path)[1].lower()

        # ── EXR fast path: extract only the requested pass first ──
        if ext == ".exr":
            import tempfile
            from .agent_exr_preview import extract_single_exr_pass, get_exr_pass_names

            # 1) Read pass list from header (no pixel data, very fast)
            all_passes = get_exr_pass_names(render_path)
            if all_passes and len(all_passes) > 1:
                report_available_passes(session, agent_id, job_id, all_passes)

            # 2) Extract only the requested pass → upload → user sees result fast
            tmp = tempfile.mkdtemp(prefix="agent_preview_single_")
            dst = os.path.join(tmp, f"{pass_name}.jpg")
            try:
                if extract_single_exr_pass(render_path, pass_name, dst):
                    upload_preview_result(session, agent_id, request_id, dst)
                    print(f"[preview] Served frame {frame} pass '{pass_name}' (single-pass fast) for job {job_id}")
                    return
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            # Single extraction failed — fall through to full extraction below

        # ── Fallback: full extraction (PNG/JPG or EXR single-pass failure) ──
        result = convert_frame_on_demand(render_path, blender_path)
        if not result:
            report_preview_failure(session, agent_id, request_id,
                                   "Failed to convert frame to preview")
            return

        # Find the requested pass
        files = result["files"]
        jpg_path = files.get(pass_name) or files.get("Combined")
        if not jpg_path:
            jpg_path = next(iter(files.values()))

        upload_preview_result(session, agent_id, request_id, jpg_path)

        # Report available passes for EXR
        all_passes = result["passes"]
        if len(all_passes) > 1:
            report_available_passes(session, agent_id, job_id, all_passes)

        # Clean up temp dir
        shutil.rmtree(result.get("temp_dir", ""), ignore_errors=True)

        print(f"[preview] Served frame {frame} pass '{pass_name}' on-demand for job {job_id}")

    elif req_type == "compile":
        # Log a warning if compiling during active render but don't block it —
        # compilation uses ffmpeg/OpenEXR (not Blender) so no resource conflict
        if state.get("active_job_id"):
            print(f"[preview] Compiling while render is active (job {state['active_job_id']})")

        frame_start = task.get("frame_start", 1)
        frame_end = task.get("frame_end", 1)
        pass_name = task.get("pass_name")
        try:
            from .agent_compile import compile_animation
            blender_path = cfg.get("blender_path", "blender")
            mp4_path = compile_animation(
                job_out_dir, output_pattern, frame_start, frame_end,
                blender_path=blender_path,
                pass_name=pass_name,
                blend_file=blend_file,
            )
            upload_preview_result(session, agent_id, request_id, mp4_path)
            try:
                os.remove(mp4_path)
            except Exception:
                pass
            print(f"[preview] Compiled and uploaded animation for job {job_id}")
        except Exception as e:
            print(f"[preview] Compile failed for {job_id}: {e}")
            report_preview_failure(session, agent_id, request_id, str(e)[:200])


def _show_msg(title: str, msg: str, *, auto_close_seconds: int = 5):
    """Show a branded startup notification that auto-closes after a few seconds."""
    try:
        import customtkinter as ctk

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        BG = "#0B0B14"
        SURFACE = "#131321"
        TEXT = "#e2e8f0"
        MUTED = "#94a3b8"
        SUCCESS = "#10b981"

        win = ctk.CTk()
        win.title(title)
        win.configure(fg_color=BG)
        try:
            win.wm_attributes("-transparentcolor", BG)
        except Exception:
            pass
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.overrideredirect(True)  # borderless

        # Size and center on screen
        w, h = 340, 180
        sx = win.winfo_screenwidth()
        sy = win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sx - w) // 2}+{(sy - h) // 2}")

        # Main frame with rounded look
        frame = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Checkmark
        check_label = ctk.CTkLabel(
            frame, text="\u2713", font=("Segoe UI", 36, "bold"),
            text_color=SUCCESS,
        )
        check_label.pack(pady=(20, 4))

        # Title
        title_label = ctk.CTkLabel(
            frame, text=title, font=("Segoe UI", 16, "bold"),
            text_color=TEXT,
        )
        title_label.pack(pady=(0, 2))

        # Message
        msg_label = ctk.CTkLabel(
            frame, text=msg, font=("Segoe UI", 12),
            text_color=MUTED,
        )
        msg_label.pack(pady=(0, 4))

        # Countdown text
        countdown_var = ctk.StringVar(value=f"Closing in {auto_close_seconds}s")
        countdown_label = ctk.CTkLabel(
            frame, textvariable=countdown_var, font=("Segoe UI", 10),
            text_color=MUTED,
        )
        countdown_label.pack(pady=(4, 12))

        remaining = [auto_close_seconds]

        def _tick():
            remaining[0] -= 1
            if remaining[0] <= 0:
                win.destroy()
                return
            countdown_var.set(f"Closing in {remaining[0]}s")
            win.after(1000, _tick)

        win.after(1000, _tick)

        # Click anywhere to close immediately
        win.bind("<Button-1>", lambda e: win.destroy())

        win.mainloop()
    except Exception:
        # Fallback to basic messagebox if customtkinter unavailable
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            messagebox.showinfo(title, msg, parent=r)
            r.destroy()
        except Exception:
            pass


def run_agent_loop(cfg: dict, prompt_success: bool = False):
    """Main agent lifecycle: register, spawn threads, run system tray."""
    # Acquire lock BEFORE touching server, so duplicates never start polling.
    try:
        acquire_single_instance_lock()
    except RuntimeError as e:
        print("[agent] Already running — only one instance allowed at a time.")
        if prompt_success:
            _show_msg(APP_DISPLAY_NAME, "Already running in the background.")
        return

    if prompt_success:
        _show_msg(APP_DISPLAY_NAME, "Running in the background.")

    try:
        _run_agent_loop_inner(cfg)
    finally:
        release_single_instance_lock()


def _run_agent_loop_inner(cfg: dict):
    backend_url = cfg["backend_url"]
    agent_token = cfg["agent_token"]
    session = BackendSession(backend_url, agent_token)

    stop_event = threading.Event()
    active_event = threading.Event()
    active_event.set()

    # Migration: ignore legacy "enabled" config field
    if "enabled" in cfg and not cfg["enabled"]:
        print("[agent] Ignoring legacy 'enabled: false' config field. Agent now always runs when started.")

    # Local control events — set by the popup directly so pause/cancel is
    # instant without waiting for an HTTP server round-trip.
    pause_event  = threading.Event()
    cancel_event = threading.Event()

    state = {
        "status": "Starting...",
        "connected": False,
        "agent_id": None,
        "last_error": "",
        "last_completed_job": None,
        "last_failed_job": None,
        "active_job_id": None,
        "active_filename": None,
        "paused_job_id": None,
        "session": session,
        "has_queued_jobs": False,
        "has_paused_jobs": False,
        "has_preview_tasks": False,
        # Local control signals (same-process, zero-latency)
        "pause_event":  pause_event,
        "cancel_event": cancel_event,
        # User presence — set by heartbeat, controls polling frequency
        "user_active": False,
        "tier": "free",
    }

    # Register agent (may fail if server is down; caller decides what to do)
    state["status"] = "Registering..."
    try:
        agent_id = ensure_registered(session, cfg)
    except RuntimeError as e:
        err_str = str(e).lower()
        if "unauthorized" in err_str or "401" in err_str or "403" in err_str or "registration failed" in err_str:
            print("\n[agent] Authorization failed. Launching setup wizard...\n")
            from .agent_installer_gui import run_setup_wizard
            cfg_path = cfg.get("config_path") or default_config_path()
            run_setup_wizard(existing_config_path=cfg_path)
            return
        raise
    state["agent_id"] = agent_id
    state["status"] = "Running"
    print("Agent running. agent_id:", agent_id)

    # Worker threads
    t_hb = threading.Thread(
        target=heartbeat_loop,
        args=(session, agent_id, stop_event, state, cfg),
        daemon=False,
        name="heartbeat",
    )
    t_scan = threading.Thread(
        target=blend_publish_loop,
        args=(session, agent_id, cfg["blend_root"], stop_event),
        kwargs={"blender_path": cfg.get("blender_path", ""), "agent_state": state},
        daemon=False,
        name="blend-scan",
    )
    t_job = threading.Thread(
        target=job_loop,
        args=(cfg, session, agent_id, active_event, stop_event, state),
        daemon=False,
        name="job-loop",
    )
    t_preview = threading.Thread(
        target=preview_task_loop,
        args=(cfg, session, agent_id, stop_event, state),
        daemon=True,
        name="preview-tasks",
    )

    t_hb.start()
    t_scan.start()
    t_job.start()
    t_preview.start()

    # System tray (lifecycle owner)
    try:
        from .agent_tray import TrayApp
        tray = TrayApp(cfg, state, active_event, stop_event)
        tray.start()

        # Main thread waits for shutdown signal.
        while not stop_event.is_set():
            stop_event.wait(1.0)

        tray.stop()

    except Exception as e:
        # If the tray fails to start (missing pystray, etc.), fall back
        # to the old Tkinter UI so the agent still works.
        print(f"[warn] System tray failed ({e}), falling back to Tkinter UI.")
        try:
            from .agent_ui import start_agent_ui
            start_agent_ui(cfg, state, active_event, stop_event)
        except Exception as e2:
            _handle_ui_failure(cfg, e2, stop_event)

    stop_event.set()
    t_job.join(timeout=5)
    t_scan.join(timeout=5)
    t_hb.join(timeout=5)
    print("Agent stopped.")

    # If the agent was stopped because the token was revoked, launch setup wizard
    if state.get("unauthorized"):
        print("[agent] Launching setup wizard for re-authorization...")
        from agent.agent_installer_gui import run_setup_wizard
        from agent.agent_config import default_config_path, load_config_from_path, save_config_to_path
        cfg_path = cfg.get("config_path") or default_config_path()
        # Clear the stale token from disk so the wizard shows "Not Authorized"
        try:
            saved = load_config_from_path(cfg_path)
            saved["agent_token"] = ""
            save_config_to_path(cfg_path, saved)
        except Exception:
            pass
        run_setup_wizard(existing_config_path=cfg_path)


def _handle_ui_failure(cfg: dict, error: Exception, stop_event: threading.Event):
    """Show error popup and write a log file when UI cannot start."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_DISPLAY_NAME, f"UI failed to start:\n\n{error}")
        r.destroy()
    except Exception:
        pass

    try:
        logs_dir = os.path.join(cfg.get("workspace_root", os.path.expanduser("~")), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        with open(os.path.join(logs_dir, "agent_startup_error.txt"), "w", encoding="utf-8") as f:
            f.write(repr(error))
    except Exception:
        pass

    stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true", help="Run setup wizard")
    parser.add_argument("--run", action="store_true", help="Run agent")
    parser.add_argument("--autostart", action="store_true", help="Started by Windows Task Scheduler")
    parser.add_argument("--uninstall-addon", action="store_true", help="Uninstall the Blender addon from all discovered Blender versions in AppData")
    parser.add_argument("--config", type=str, default="", help="Path to agent_config.json")
    parser.add_argument("--silent", action="store_true", help="Suppress startup toast (used when launched from setup wizard)")
    args = parser.parse_args()

    if args.uninstall_addon:
        import re, shutil
        print("[uninstall] Sweeping Blender AppData and ProgramData for addon cleanup...")
        
        # 1. Search in User AppData (most common)
        appdata = os.environ.get("APPDATA", "")
        # 2. Search in System ProgramData (common for "Global/Shared" extensions - two people icon)
        programdata = os.environ.get("PROGRAMDATA", "")
        
        search_roots = []
        if appdata:
            search_roots.append(os.path.join(appdata, "Blender Foundation", "Blender"))
        if programdata:
            search_roots.append(os.path.join(programdata, "Blender Foundation", "Blender"))

        addon_folder_names = ["render_manager", "remote_renderer"]

        for blender_base in search_roots:
            if not os.path.isdir(blender_base):
                continue
            
            # Look inside versioned subfolders (e.g., "4.2", "4.3")
            for name in os.listdir(blender_base):
                m = re.match(r"^(\d+)\.(\d+)$", name)
                if m:
                    # Possible locations for addons/extensions
                    paths_to_check = [
                        os.path.join(blender_base, name, "extensions", "user_default"),
                        os.path.join(blender_base, name, "scripts", "addons"),
                        # Also check system-level extensions if they exist in this structure
                        os.path.join(blender_base, name, "extensions", "blender_org"),
                    ]
                    
                    for base_path in paths_to_check:
                        if not os.path.isdir(base_path):
                            continue
                            
                        # Check for both possible folder names
                        for addon_name in addon_folder_names:
                            p = os.path.join(base_path, addon_name)
                            if os.path.isdir(p):
                                print(f"[uninstall] Deleting {p}")
                                try:
                                    shutil.rmtree(p)
                                except Exception as exc:
                                    print(f"  -> Failed: {exc}")
        
        print("[uninstall] Addon sweep complete.")

        # Also remove the agent's own AppData folder (%APPDATA%\RenderManager)
        for folder_name in ("RenderManager", "RenderRemote", "RemoteRenderer"):
            agent_appdata = os.path.join(appdata, folder_name)
            if os.path.isdir(agent_appdata):
                print(f"[uninstall] Deleting agent data: {agent_appdata}")
                try:
                    shutil.rmtree(agent_appdata)
                except Exception as exc:
                    print(f"  -> Failed: {exc}")

        print("[uninstall] Full cleanup complete.")
        return

    if not args.setup and not args.run:
        cfg_path = default_config_path()
        cfg_dir = os.path.dirname(cfg_path)

        if os.path.exists(cfg_path):
            cfg = load_config_from_path(cfg_path)
            ok, reason = validate_config_for_mvp(cfg)
            if ok:
                print(f"[agent] Config loaded from {cfg_path}")
                run_agent_loop(cfg, prompt_success=not args.autostart)
                return
            print(f"[agent] Config invalid: {reason}")
            print("[agent] Launching setup wizard...")
            run_setup_wizard(default_config_dir=cfg_dir, existing_config_path=cfg_path)
            return

        print(f"[agent] No config found at {cfg_path}")
        print("[agent] Launching setup wizard...")
        run_setup_wizard(default_config_dir=cfg_dir, existing_config_path=None)
        return

    if args.setup:
        cfg_path = default_config_path()
        cfg_dir = os.path.dirname(cfg_path)
        existing = cfg_path if os.path.exists(cfg_path) else None
        run_setup_wizard(default_config_dir=cfg_dir, existing_config_path=existing)
        return

    if args.run:
        if args.config:
            cfg = load_config_from_path(args.config)
            ok, reason = validate_config_for_mvp(cfg)
            if not ok:
                raise SystemExit(f"Invalid config: {reason}")
            run_agent_loop(cfg, prompt_success=not args.silent)
            return

        # No explicit config path — load or create default config.
        # If the token is missing/invalid, open the setup wizard instead of crashing.
        try:
            cfg = ensure_agent_config()
        except RuntimeError:
            print("[agent] No valid agent token - launching setup wizard...")
            cfg_path = default_config_path()
            run_setup_wizard(existing_config_path=cfg_path if os.path.exists(cfg_path) else None)
            return

        run_agent_loop(cfg)
        return


if __name__ == "__main__":
    main()

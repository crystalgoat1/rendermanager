import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import sys
from pathlib import Path
from typing import Optional

from .agent_backend import (
    BackendSession, get_job_control, send_progress, notify_paused, notify_canceled,
    preload_preview_pass, upload_latest_preview, report_available_passes
)
from .agent_notify import notify_render_complete, notify_render_failed, notify_disconnected
from .agent_override import validate_overrides, generate_override_script
from .agent_local_cache import LatestFrameUpdater, get_latest_cached, cleanup_latest


# ---------------------------------------------------------------------------
# VRAM Recovery — auto-recover from GPU out-of-memory errors
# ---------------------------------------------------------------------------
# Each tier applies progressively more memory-saving overrides.
# All tiers produce pixel-identical output (zero quality loss).
VRAM_RECOVERY_TIERS = [
    {},  # Tier 0: original settings
    {"cycles_use_persistent_data": False},
    {"cycles_use_persistent_data": False, "cycles_tile_size": 1024},
    {"cycles_use_persistent_data": False, "cycles_tile_size": 512},
    {"cycles_use_persistent_data": False, "cycles_tile_size": 256},
    {"cycles_use_persistent_data": False, "cycles_device": "CPU"},
]

_OOM_PATTERNS = [
    "cuda out of memory",
    "out of memory",
    "failed to allocate",
    "ran out of memory",
    "memory allocation failed",
    "optix out of memory",
    "hip out of memory",
    "oneapi out of memory",
    "system is out of gpu memory",
]


def _is_oom_output(output_lines: list) -> bool:
    """Check if collected Blender output contains OOM error patterns."""
    joined = "\n".join(output_lines).lower()
    return any(p in joined for p in _OOM_PATTERNS)


def _tier_description(tier: int) -> str:
    """Human-readable description of a VRAM recovery tier."""
    descriptions = [
        "original settings",
        "disabling persistent data",
        "reducing tile size (1024)",
        "reducing tile size (512)",
        "reducing tile size (256)",
        "CPU fallback",
    ]
    return descriptions[min(tier, len(descriptions) - 1)]


# Security: only these fields are used from server job payloads.
# The agent extracts ONLY these fields and ignores everything else,
# preventing the server from injecting unexpected data.
USED_JOB_FIELDS = {
    "job_id",
    "blend_relpath",
    "blend_file",
    "frame",
    "frame_start",
    "frame_end",
    "job_group_id",
    "retry_of",
    # Blender CLI settings — strict enum/range-validated below
    "render_engine",
    "output_format",
    "frame_step",
    "threads",
    "render_overrides",
}

# Strict allowlists — only these literal strings are ever passed to Blender.
# Any value not in these sets is silently ignored (Blender uses its scene default).
_ALLOWED_ENGINES = frozenset({"CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"})
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "OPEN_EXR", "OPEN_EXR_MULTILAYER", "TIFF", "BMP", "HDR"})

# ---------------------------------------------------------------------------
# Blender version detection (cached per executable path)
# ---------------------------------------------------------------------------
_blender_version_cache: dict[str, tuple[int, ...]] = {}


def _get_blender_version(blender_path: str) -> tuple[int, ...]:
    """Return the major Blender version tuple, e.g. (4, 2, 0). Cached per path."""
    if blender_path in _blender_version_cache:
        return _blender_version_cache[blender_path]
    version = ()
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        result = subprocess.run(
            [blender_path, "--version"],
            capture_output=True, text=True, timeout=15,
            creationflags=creationflags,
        )
        m = re.search(r"Blender\s+(\d[\d.]+)", result.stdout)
        if m:
            version = tuple(int(n) for n in m.group(1).split("."))
    except Exception:
        pass
    _blender_version_cache[blender_path] = version
    return version


def _fix_engine_for_blender_version(engine: Optional[str], blender_path: str) -> Optional[str]:
    """Remap EEVEE engine enum for the installed Blender version.

    Blender 4.0+ renamed BLENDER_EEVEE → BLENDER_EEVEE_NEXT.
    Passing the old enum to 4.0+ causes an access-violation crash.
    Passing the new enum to 3.x would similarly fail.
    """
    if engine is None:
        return None
    ver = _get_blender_version(blender_path)
    if not ver:
        return engine  # unknown version, pass through unchanged
    if ver >= (4, 0) and engine == "BLENDER_EEVEE":
        return "BLENDER_EEVEE_NEXT"
    if ver < (4, 0) and engine == "BLENDER_EEVEE_NEXT":
        return "BLENDER_EEVEE"
    return engine


def validate_and_sanitize_job(job: dict) -> dict:
    """Extract only known fields from a server job payload.

    The agent never trusts arbitrary server data. Only whitelisted
    fields are extracted; everything else is silently dropped.
    New render-settings fields use strict enum/range checks so that
    no arbitrary string can ever be injected into the Blender command.
    """
    if not isinstance(job, dict):
        raise RuntimeError("Job payload is not a dict")

    sanitized = {k: job[k] for k in USED_JOB_FIELDS if k in job}

    if "job_id" not in sanitized:
        raise RuntimeError("Job missing required field: job_id")

    # Type-check critical frame fields
    if "frame_start" in sanitized and not isinstance(sanitized["frame_start"], int):
        raise RuntimeError("frame_start must be an integer")
    if "frame_end" in sanitized and not isinstance(sanitized["frame_end"], int):
        raise RuntimeError("frame_end must be an integer")

    # Validate render_engine — drop if unknown (Blender uses scene default)
    if "render_engine" in sanitized:
        if sanitized["render_engine"] not in _ALLOWED_ENGINES:
            sanitized.pop("render_engine", None)

    # Validate output_format — drop if unknown
    if "output_format" in sanitized:
        if sanitized["output_format"] not in _ALLOWED_FORMATS:
            sanitized.pop("output_format", None)

    # Validate frame_step — must be int 1–100
    if "frame_step" in sanitized:
        fs = sanitized["frame_step"]
        if not isinstance(fs, int) or not (1 <= fs <= 100):
            sanitized.pop("frame_step", None)

    # Validate threads — must be int 0–64
    if "threads" in sanitized:
        t = sanitized["threads"]
        if not isinstance(t, int) or not (0 <= t <= 64):
            sanitized.pop("threads", None)

    # Validate render_overrides — only accept whitelisted keys/values
    if "render_overrides" in sanitized:
        ro = sanitized["render_overrides"]
        if isinstance(ro, dict) and ro:
            sanitized["render_overrides"] = validate_overrides(ro)
        else:
            sanitized.pop("render_overrides", None)

    return sanitized

# Parses lines like: "Saved: 'C:\\...\\render_0001.png'"
SAVED_RE = re.compile(r"Saved:\s*'(.+?)'", re.IGNORECASE)


class PauseRequested(Exception):
    pass


class CancelRequested(Exception):
    pass


def strip_wrapping_quotes(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    if len(s) >= 2 and ((s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'"))):
        return s[1:-1].strip()
    return s


def sanitize_folder_name(name: str) -> str:
    name = (name or "").strip()
    for ch in r'\\/:*?"<>|':
        name = name.replace(ch, "_")
    if name:
        name = name[:50].rstrip(" .")
    return name or "render"


def get_frame_png_path(output_pattern: str, frame: int) -> str:
    """Legacy helper — returns the .png path for a frame. Use find_frame_file() for format-agnostic lookups."""
    frame_str = str(frame).zfill(4)
    return output_pattern.replace("####", frame_str) + ".png"


def find_frame_file(output_pattern: str, frame: int) -> Optional[str]:
    """Find the actual rendered frame file regardless of extension (png, exr, jpg, etc.).

    Returns the file path if found, or None.
    """
    import glob
    frame_str = str(frame).zfill(4)
    base = output_pattern.replace("####", frame_str)
    matches = glob.glob(base + ".*")
    if matches:
        return matches[0]
    return None


def is_frame_done(png_path: str) -> bool:
    try:
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False


def find_first_missing_frame(output_pattern: str, frame_start: int, frame_end: int) -> int:
    for f in range(frame_start, frame_end + 1):
        found = find_frame_file(output_pattern, f)
        if not found or not is_frame_done(found):
            return f
    return frame_end + 1


def make_output_dir_for_job(output_root: str, blend_file_path: str, job_group_id: str) -> str:
    base = sanitize_folder_name(os.path.splitext(os.path.basename(blend_file_path))[0])
    short = (job_group_id or "group")[:8]
    out_dir = os.path.join(output_root, f"{base}__{short}")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _stop_proc(proc: subprocess.Popen):
    """Forcefully kill the Blender process tree.

    On Windows, ``proc.terminate()`` only sends CTRL_BREAK to the direct
    child.  Blender spawns sub-processes (e.g. OptiX denoiser, USD
    hydra) that survive the parent termination, leaving orphan GPU
    processes.  ``taskkill /F /T`` kills the entire tree instantly.
    """
    pid = proc.pid
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass
    else:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _render_range_single_process(
        blender_path: str,
        blend_file: str,
        output_pattern: str,
        frame_start: int,
        frame_end: int,
        session: BackendSession,
        job_id: str,
        agent_id: str,
        on_frame_saved=None,
        render_engine: Optional[str] = None,
        output_format: Optional[str] = None,
        frame_step: Optional[int] = None,
        threads: Optional[int] = None,
        override_script_path: Optional[str] = None,
        progress_cb=None,
        already_rendered: int = 0,
        original_total: Optional[int] = None,
        stop_event=None,
        output_collector: Optional[list] = None,
        pause_event=None,
        cancel_event=None,
):
    command = [
        blender_path,
        "-b",
        blend_file,
        "-o",
        output_pattern,
        "-s",
        str(frame_start),
        "-e",
        str(frame_end),
    ]
    if output_format:
        command.extend(["-F", output_format])
    if render_engine:
        command.extend(["-E", render_engine])
    if threads is not None:
        command.extend(["-t", str(threads)])
    if frame_step is not None and frame_step > 1:
        command.extend(["-j", str(frame_step)])
    if override_script_path and os.path.isfile(override_script_path):
        command.extend(["--python", override_script_path])
    command.append("-a")

    creationflags = 0
    if sys.platform == "win32":
        # Check if CREATE_NO_WINDOW exists in subprocess, otherwise use 0x08000000
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags
    )

    remaining_frames = (frame_end - frame_start) + 1
    total_frames = original_total if original_total is not None else remaining_frames
    rendered_frames = already_rendered
    last_counted_frame = None

    _last_server_progress = [0.0]  # mutable container for closure

    def push_progress(message: str, cur_frame: Optional[int] = None):
        # Report progress relative to THIS session's work (0-100% of the
        # frames being rendered now).  The server applies progress_base to
        # map this back to absolute job progress, so we must NOT include
        # already_rendered here — that would double-count the paused offset.
        session_done = rendered_frames - already_rendered
        pct = int(min(99.0, (float(session_done) / float(max(1, remaining_frames))) * 100.0))
        if progress_cb:
            progress_cb(pct, message, cur_frame)
        # Throttle server progress updates to every 3s — the dashboard uses
        # Supabase realtime so sub-second updates are wasted egress.
        # Always send the first update (pct==0) and completion (pct>=99).
        now = time.time()
        if pct >= 99 or pct == 0 or (now - _last_server_progress[0]) >= 3.0:
            _last_server_progress[0] = now
            try:
                send_progress(session, job_id, agent_id, pct, message, current_frame=cur_frame)
            except Exception:
                pass

    if original_total and original_total > remaining_frames:
        push_progress(f"Rendering frame {frame_start} ({rendered_frames + 1}/{total_frames})")
    else:
        push_progress(f"Blender started (frames {frame_start}-{frame_end})")

    # ------------------------------------------------------------------
    # Read stdout in a background thread so that control-signal checks
    # are never blocked waiting for Blender to produce output.
    # ------------------------------------------------------------------
    line_queue: queue.Queue[Optional[str]] = queue.Queue()

    def _reader():
        try:
            if proc.stdout:
                for raw_line in proc.stdout:
                    line_queue.put(raw_line)
        except Exception:
            pass
        finally:
            line_queue.put(None)  # sentinel: stream ended

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        last_control_check = 0.0
        stream_ended = False

        while not stream_ended:
            # Drain all available lines (non-blocking after the first
            # blocking wait of up to 0.25 s).  Short timeout so local
            # pause/cancel events are detected within a quarter-second.
            lines_batch: list[str] = []
            try:
                item = line_queue.get(timeout=0.25)
                if item is None:
                    stream_ended = True
                else:
                    lines_batch.append(item)
            except queue.Empty:
                pass

            # Grab any extra lines that are already queued
            while True:
                try:
                    item = line_queue.get_nowait()
                    if item is None:
                        stream_ended = True
                        break
                    lines_batch.append(item)
                except queue.Empty:
                    break

            # --- Process collected lines ---------------------------------
            for raw_line in lines_batch:
                line = (raw_line or "").strip()
                if not line:
                    continue
                try:
                    print("[blender]", line)
                except UnicodeEncodeError:
                    print("[blender]", line.encode("ascii", errors="replace").decode())
                if output_collector is not None:
                    output_collector.append(line)
                    if len(output_collector) > 200:
                        output_collector.pop(0)

                m = SAVED_RE.search(line)
                if m:
                    saved_path = m.group(1)
                    saved_lower = (saved_path or "").lower()
                    if not (saved_lower.endswith(".png") or
                            saved_lower.endswith(".jpg") or
                            saved_lower.endswith(".jpeg") or
                            saved_lower.endswith(".exr")):
                        continue

                    if os.path.exists(saved_path):
                        basename = os.path.basename(saved_path)
                        if not basename.startswith("render_"):
                            continue

                        basename_noext = os.path.splitext(basename)[0]
                        m_frame = re.search(r"(\d+)$", basename_noext)
                        frame_num = int(m_frame.group(1)) if m_frame else None

                        if frame_num is not None:
                            if frame_num != last_counted_frame:
                                last_counted_frame = frame_num
                                rendered_frames = min(total_frames, rendered_frames + 1)
                                push_progress(f"Saved frame ({rendered_frames}/{total_frames})", cur_frame=frame_num)

                        if on_frame_saved and frame_num is not None:
                            on_frame_saved(frame_num, saved_path)

            # --- Check control signals -----------------------------------
            # Local events (set by popup in same process) are checked every
            # loop iteration — zero latency.  The server poll is a fallback
            # for signals that arrive from the web dashboard.
            if cancel_event and cancel_event.is_set():
                _stop_proc(proc)
                raise CancelRequested("cancel requested (local)")
            if pause_event and pause_event.is_set():
                _stop_proc(proc)
                raise PauseRequested("pause requested (local)")

            now = time.time()
            if now - last_control_check >= 3.0:
                last_control_check = now
                try:
                    ctrl = get_job_control(session, job_id, agent_id)
                except Exception as e:
                    print(f"[render] Control check failed: {e}")
                    ctrl = {"pause": False, "cancel": False}

                if ctrl.get("cancel"):
                    _stop_proc(proc)
                    raise CancelRequested("cancel requested")
                if ctrl.get("pause"):
                    _stop_proc(proc)
                    raise PauseRequested("pause requested")

            if stop_event and stop_event.is_set():
                _stop_proc(proc)
                raise RuntimeError("Agent shutdown requested")

        rc = proc.wait()
        last_expected = find_frame_file(output_pattern, frame_end)
        if rc != 0 and (not last_expected or not is_frame_done(last_expected)):
            raise RuntimeError(f"Blender exited with code {rc} (and last frame missing)")

    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        reader_thread.join(timeout=3)


def process_job(cfg: dict, session: BackendSession, agent_id: str, job: dict,
                stop_event=None, progress_cb=None, vram_recovery_enabled: bool = False,
                pause_event=None, cancel_event=None, state=None) -> dict:
    job = validate_and_sanitize_job(job)

    job_id = job.get("job_id", "")
    blend_root = cfg["blend_root"]
    output_root = cfg["output_root"]
    blender_path = cfg["blender_path"]
    workspace_root = cfg["workspace_root"]

    blend_relpath = strip_wrapping_quotes(job.get("blend_relpath"))
    blend_file_raw = strip_wrapping_quotes(job.get("blend_file"))

    root = Path(blend_root).resolve()
    blend_file = ""
    if blend_relpath:
        full = Path(os.path.join(str(root), blend_relpath)).resolve()
        if not full.is_relative_to(root):
            raise RuntimeError(f"Invalid blend_relpath (escapes BlendFiles folder): {blend_relpath}")
        blend_file = str(full)
    elif blend_file_raw:
        full = Path(blend_file_raw).resolve()
        if not full.is_relative_to(root):
            raise RuntimeError(f"Invalid blend_file (outside BlendFiles folder): {blend_file_raw}")
        blend_file = str(full)

    if not blend_file:
        raise RuntimeError("Missing blend_relpath/blend_file")
    if not os.path.isfile(blend_file):
        raise RuntimeError(f"Blend file not found: {blend_file}")

    frame = job.get("frame")
    frame_start = job.get("frame_start")
    frame_end = job.get("frame_end")
    if frame is not None and (frame_start is None and frame_end is None):
        frame_start = frame
        frame_end = frame

    if frame_start is None or frame_end is None:
        raise RuntimeError("Missing frame_start/frame_end")
    
    # These must be ints because of validate_and_sanitize_job
    fs_val: int = frame_start
    fe_val: int = frame_end

    if fe_val < fs_val:
        raise RuntimeError("frame_end must be >= frame_start")

    job_group_id = job.get("job_group_id") or job.get("retry_of") or job_id
    job_out_dir = make_output_dir_for_job(output_root, blend_file, job_group_id)
    output_pattern = os.path.join(job_out_dir, "render_####")

    # -- Preview upload buffering ------------------------------------------
    # When the user is not on the dashboard, we buffer preview uploads
    # and flush them in batches to reduce egress.
    _preview_buffer: list[dict] = []
    _buffer_lock = threading.Lock()
    _batch_stop = threading.Event()

    def _flush_preview_buffer():
        """Upload all buffered previews."""
        with _buffer_lock:
            batch = list(_preview_buffer)
            _preview_buffer.clear()
        for item in batch:
            path = item.get("path")
            if path and os.path.isfile(path):
                try:
                    preload_preview_pass(session, agent_id, job_id, item["frame"], "Combined", path)
                except Exception:
                    pass
            if len(item.get("passes", [])) > 1:
                try:
                    report_available_passes(session, agent_id, job_id, item["passes"])
                except Exception:
                    pass

    def _batch_upload_loop():
        """Runs in background — flushes buffered previews every 30 s or
        immediately when the user becomes active."""
        last_flush = time.time()
        while not _batch_stop.is_set():
            _batch_stop.wait(5)
            if _batch_stop.is_set():
                break
            user_active = (state or {}).get("user_active", False)
            elapsed = time.time() - last_flush
            if (user_active or elapsed >= 30) and _preview_buffer:
                _flush_preview_buffer()
                last_flush = time.time()

    def _on_cached_callback(res_dict: dict):
        frame_num = res_dict["frame"]
        passes = res_dict["passes"]
        files = res_dict.get("files", {})
        combined_path = files.get("Combined")

        user_active = (state or {}).get("user_active", True)
        tier = (state or {}).get("tier", "free")

        # Always update the job's latest preview so the dashboard card
        # shows a thumbnail immediately (instead of 404 → on-demand fallback).
        if combined_path:
            upload_latest_preview(session, job_id, agent_id, combined_path, frame_num)

        if user_active:
            # Immediate upload — user is watching
            if combined_path:
                preload_preview_pass(session, agent_id, job_id, frame_num, "Combined", combined_path)
            if len(passes) > 1:
                try:
                    report_available_passes(session, agent_id, job_id, passes)
                except Exception:
                    pass
        elif tier == "pro":
            # Pro: buffer for batch upload every ~30 s
            with _buffer_lock:
                _preview_buffer.append({"frame": frame_num, "path": combined_path, "passes": passes})
        # Free + inactive → skip (next frame when user opens dashboard will upload)

    batch_thread = threading.Thread(target=_batch_upload_loop, daemon=True, name="preview-batch")
    batch_thread.start()

    updater = LatestFrameUpdater(workspace_root, job_id, blender_path, on_cached_callback=_on_cached_callback)
    updater.start()

    def _on_frame_saved(frame_num: int, saved_path: str):
        updater.push(frame_num, saved_path)

    resume_start = find_first_missing_frame(output_pattern, fs_val, fe_val)
    if resume_start > fe_val:
        _batch_stop.set()
        updater.stop()
        cleanup_latest(workspace_root, job_id)
        send_progress(session, job_id, agent_id, 100, "All frames already rendered", current_frame=fe_val)
        return {"status": "completed"}
    
    if resume_start != fs_val:
        current_fs = resume_start
        send_progress(session, job_id, agent_id, 0, f"Resuming from frame {current_fs}", current_frame=current_fs - 1)
    else:
        current_fs = fs_val

    try:
        # Only send the folder name, not the full absolute path (privacy)
        send_progress(session, job_id, agent_id, 0, f"Output folder: {os.path.basename(job_out_dir)}")
    except Exception:
        pass

    render_engine = _fix_engine_for_blender_version(job.get("render_engine"), blender_path)
    output_format = job.get("output_format")
    frame_step = int(job["frame_step"]) if job.get("frame_step") is not None else None
    threads = int(job["threads"]) if job.get("threads") is not None else None

    override_script = None
    overrides = job.get("render_overrides")
    if overrides and isinstance(overrides, dict):
        override_script = generate_override_script(overrides, job_id, tempfile.gettempdir())

    user_device = (overrides or {}).get("cycles_device") if overrides else None
    use_vram_recovery = (
        vram_recovery_enabled
        and render_engine in ("CYCLES", None)
        and user_device != "CPU"
    )

    vram_recovery_stats = None

    try:
        if use_vram_recovery:
            vram_recovery_stats = _render_with_vram_recovery(
                blender_path=blender_path,
                blend_file=blend_file,
                output_pattern=output_pattern,
                frame_start=current_fs,
                frame_end=fe_val,
                session=session,
                job_id=job_id,
                agent_id=agent_id,
                on_frame_saved=_on_frame_saved,
                render_engine=render_engine,
                output_format=output_format,
                frame_step=frame_step,
                threads=threads,
                base_overrides=overrides,
                progress_cb=progress_cb,
                already_rendered=current_fs - fs_val,
                original_total=(fe_val - fs_val) + 1,
                stop_event=stop_event,
                pause_event=pause_event,
                cancel_event=cancel_event,
            )
        else:
            _render_range_single_process(
                blender_path=blender_path,
                blend_file=blend_file,
                output_pattern=output_pattern,
                frame_start=current_fs,
                frame_end=fe_val,
                session=session,
                job_id=job_id,
                agent_id=agent_id,
                on_frame_saved=_on_frame_saved,
                render_engine=render_engine,
                output_format=output_format,
                frame_step=frame_step,
                threads=threads,
                override_script_path=override_script,
                progress_cb=progress_cb,
                already_rendered=current_fs - fs_val,
                original_total=(fe_val - fs_val) + 1,
                stop_event=stop_event,
                pause_event=pause_event,
                cancel_event=cancel_event,
            )

        cached = get_latest_cached(workspace_root, job_id)
        if cached and len(cached.get("passes", [])) > 1:
            try:
                report_available_passes(session, agent_id, job_id, cached["passes"])
            except Exception as e:
                print(f"[warn] Failed to report available passes: {e}")

        send_progress(session, job_id, agent_id, 100, "All frames rendered")

        result = {"status": "completed"}
        if vram_recovery_stats and vram_recovery_stats.get("recovered_frames", 0) > 0:
            result["vram_recovery"] = vram_recovery_stats
        return result

    except PauseRequested:
        resp = notify_paused(session, job_id, agent_id)
        # If cancel was requested while we were pausing, the server
        # cancels instead of pausing and tells us.  Honour that so the
        # job_loop doesn't enter the stale paused-job wait loop.
        if isinstance(resp, dict) and resp.get("status") == "canceled":
            return {"status": "canceled"}
        return {"status": "paused"}

    except CancelRequested:
        notify_canceled(session, job_id, agent_id)
        return {"status": "canceled"}

    finally:
        # Stop the batch upload loop and flush any remaining buffered previews
        _batch_stop.set()
        _flush_preview_buffer()
        updater.stop()
        cleanup_latest(workspace_root, job_id)
        if override_script:
            try:
                os.remove(override_script)
            except OSError:
                pass


def _render_with_vram_recovery(
        blender_path: str,
        blend_file: str,
        output_pattern: str,
        frame_start: int,
        frame_end: int,
        session: BackendSession,
        job_id: str,
        agent_id: str,
        on_frame_saved=None,
        render_engine: Optional[str] = None,
        output_format: Optional[str] = None,
        frame_step: Optional[int] = None,
        threads: Optional[int] = None,
        base_overrides: Optional[dict] = None,
        progress_cb=None,
        already_rendered: int = 0,
        original_total: Optional[int] = None,
        stop_event=None,
        pause_event=None,
        cancel_event=None,
) -> dict:
    total_frames = original_total or (frame_end - frame_start + 1)
    remaining_frames = (frame_end - frame_start) + 1
    rendered_count = already_rendered
    current_tier = 0
    step = frame_step if frame_step and frame_step > 1 else 1
    recovered_frames = 0
    max_tier_used = 0

    def push_progress(message: str, cur_frame: Optional[int] = None):
        # Report progress relative to THIS session's work (0-100% of the
        # frames being rendered now).  The server applies progress_base to
        # map this back to absolute job progress.
        session_done = rendered_count - already_rendered
        pct = int(min(99.0, (float(session_done) / float(max(1, remaining_frames))) * 100.0))
        if progress_cb:
            progress_cb(pct, message, cur_frame)
        try:
            send_progress(session, job_id, agent_id, pct, message, current_frame=cur_frame)
        except Exception:
            pass

    push_progress(f"VRAM Recovery enabled - rendering frames {frame_start}-{frame_end}")

    for frame in range(frame_start, frame_end + 1, step):
        if find_frame_file(output_pattern, frame):
            rendered_count += 1
            continue

        tier = current_tier
        frame_succeeded = False

        while tier < len(VRAM_RECOVERY_TIERS):
            effective_overrides = dict(base_overrides or {})
            effective_overrides.update(VRAM_RECOVERY_TIERS[tier])

            recovery_script = None
            if effective_overrides:
                recovery_script = generate_override_script(
                    effective_overrides, f"{job_id}_vram_t{tier}", tempfile.gettempdir()
                )

            output_collector: list[str] = []
            try:
                if tier > 0:
                    push_progress(
                        f"Frame {frame}: VRAM recovery - {_tier_description(tier)}",
                        cur_frame=frame,
                    )

                _render_range_single_process(
                    blender_path=blender_path,
                    blend_file=blend_file,
                    output_pattern=output_pattern,
                    frame_start=frame,
                    frame_end=frame,
                    session=session,
                    job_id=job_id,
                    agent_id=agent_id,
                    on_frame_saved=on_frame_saved,
                    render_engine=render_engine,
                    output_format=output_format,
                    threads=threads,
                    override_script_path=recovery_script,
                    progress_cb=progress_cb,
                    already_rendered=rendered_count,
                    original_total=total_frames,
                    stop_event=stop_event,
                    output_collector=output_collector,
                    pause_event=pause_event,
                    cancel_event=cancel_event,
                )

                frame_succeeded = True
                rendered_count += 1

                if tier > 0:
                    recovered_frames += 1
                    max_tier_used = max(max_tier_used, tier)

                if tier > 0:
                    current_tier = max(0, tier - 1)
                    print(f"[vram-recovery] Frame {frame} succeeded at tier {tier} ({_tier_description(tier)}), "
                          f"next frame will start at tier {current_tier}")
                else:
                    current_tier = 0

                break

            except (PauseRequested, CancelRequested):
                raise

            except RuntimeError:
                if _is_oom_output(output_collector) and tier + 1 < len(VRAM_RECOVERY_TIERS):
                    print(f"[vram-recovery] Frame {frame}: OOM at tier {tier} ({_tier_description(tier)}), "
                          f"escalating to tier {tier + 1} ({_tier_description(tier + 1)})")
                    tier += 1
                    current_tier = tier
                    continue
                else:
                    if _is_oom_output(output_collector):
                        raise RuntimeError(
                            f"Frame {frame}: GPU out of memory - all VRAM recovery tiers exhausted "
                            f"(tried up to {_tier_description(tier)})"
                        )
                    raise

            finally:
                if recovery_script:
                    try:
                        os.remove(recovery_script)
                    except OSError:
                        pass

        if not frame_succeeded:
            raise RuntimeError(f"Frame {frame}: all VRAM recovery tiers exhausted")

    return {
        "recovered_frames": recovered_frames,
        "max_tier": max_tier_used,
        "max_tier_name": _tier_description(max_tier_used) if max_tier_used > 0 else None,
    }

"""Local JPEG preview cache for rendered frames.

Keeps only the latest rendered frame's JPEG(s) in a well-known location.
For frame browser requests, converts from source render files on-demand.
"""

import json
import os
import queue
import shutil
import threading
from typing import Optional

from PIL import Image


from agent.agent_config import get_appdata_dir


def get_latest_cache_dir(workspace: str, job_id: str) -> str:
    appdata_dir = get_appdata_dir()
    return os.path.join(appdata_dir, "Previews", "latest", job_id)


def _convert_image_to_jpeg(src_path: str, dst_path: str, quality: int = 85):
    """Convert a PNG/JPEG/TIFF/BMP image to JPEG using Pillow."""
    img = Image.open(src_path)
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.save(dst_path, "JPEG", quality=quality, optimize=True)


def _convert_source_file(src_path: str, output_dir: str, blender_path: str = "") -> Optional[dict]:
    """Convert a single render file (PNG/JPEG/EXR) to JPEG(s).

    Returns {"passes": [...], "files": {"Combined": "/path/Combined.jpg", ...}}
    or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    ext = os.path.splitext(src_path)[1].lower()

    if ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"):
        out_path = os.path.join(output_dir, "Combined.jpg")
        try:
            _convert_image_to_jpeg(src_path, out_path)
            return {"passes": ["Combined"], "files": {"Combined": out_path}}
        except Exception as e:
            print(f"[cache] Failed to convert {src_path}: {e}")
            return None

    if ext == ".exr":
        # Try fast OpenEXR extraction first
        from .agent_exr_preview import extract_exr_passes_openexr
        res = extract_exr_passes_openexr(src_path, output_dir)
        if res and res.get("extracted_files"):
            return {"passes": res["passes"], "files": res["extracted_files"]}

        # Fall back to Blender
        if blender_path:
            from .agent_exr_preview import extract_exr_passes_with_blender
            res = extract_exr_passes_with_blender(blender_path, src_path)
            if res and res.get("extracted_files"):
                files = {}
                for pname, pjpg in res["extracted_files"].items():
                    dst = os.path.join(output_dir, f"{pname}.jpg")
                    shutil.copy2(pjpg, dst)
                    files[pname] = dst
                try:
                    shutil.rmtree(res["temp_dir"], ignore_errors=True)
                except Exception:
                    pass
                return {"passes": list(files.keys()), "files": files}

        print(f"[cache] EXR extraction failed for {src_path}")
        return None

    print(f"[cache] Unsupported format: {ext}")
    return None


# ── Thread-safe latest-frame cache ──────────────────────────────────────

_cache_lock = threading.Lock()


def cache_latest_frame(
    src_path: str, workspace: str, job_id: str,
    frame_num: int, blender_path: str = "",
    on_cached_callback=None
) -> Optional[dict]:
    """Convert a render file and store as the latest cached frame.

    For EXR files, only extracts the Combined pass (fast, ~1-3s) instead of
    all passes (~15-30s) to avoid heavy CPU usage that blocks the GUI.
    Pass names are still read from the header so the frontend knows what's
    available; other passes are loaded on-demand when the user requests them.

    Overwrites any previous latest cache for this job.  Thread-safe.
    """
    cache_dir = get_latest_cache_dir(workspace, job_id)
    ext = os.path.splitext(src_path)[1].lower()

    with _cache_lock:
        # Clear previous cache contents (keep directory)
        if os.path.isdir(cache_dir):
            for f in os.listdir(cache_dir):
                try:
                    os.remove(os.path.join(cache_dir, f))
                except Exception:
                    pass

        # For EXR: extract only Combined pass (fast) + read pass list from header
        if ext == ".exr":
            from .agent_exr_preview import extract_single_exr_pass, get_exr_pass_names
            os.makedirs(cache_dir, exist_ok=True)

            all_passes = get_exr_pass_names(src_path) or ["Combined"]
            dst = os.path.join(cache_dir, "Combined.jpg")
            if not extract_single_exr_pass(src_path, "Combined", dst):
                return None

            files = {"Combined": dst}
            meta = {"frame": frame_num, "passes": all_passes}
            with open(os.path.join(cache_dir, "_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f)
            
            res_dict = {"frame": frame_num, "passes": all_passes, "files": files}
            if on_cached_callback:
                on_cached_callback(res_dict)
            return res_dict

        # Non-EXR: full conversion (fast for single-layer images)
        result = _convert_source_file(src_path, cache_dir, blender_path)
        if not result:
            return None

        # Write metadata last (acts as commit marker)
        meta = {"frame": frame_num, "passes": result["passes"]}
        with open(os.path.join(cache_dir, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)

        res_dict = {"frame": frame_num, "passes": result["passes"], "files": result["files"]}
        if on_cached_callback:
            on_cached_callback(res_dict)
        return res_dict


def get_latest_cached(workspace: str, job_id: str) -> Optional[dict]:
    """Read the latest cached frame info.

    Returns {"frame": N, "passes": [...], "dir": "/path/"} or None.  Thread-safe.
    Uses a timed lock acquire so the preview thread isn't blocked for 15-30s
    while LatestFrameUpdater is converting a multi-pass EXR frame.
    """
    cache_dir = get_latest_cache_dir(workspace, job_id)
    meta_path = os.path.join(cache_dir, "_meta.json")

    if not _cache_lock.acquire(timeout=0.5):
        return None  # Cache busy — caller falls through to on-demand path

    try:
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return {"frame": meta["frame"], "passes": meta["passes"], "dir": cache_dir}
        except Exception:
            return None
    finally:
        _cache_lock.release()


def get_cached_pass_file(workspace: str, job_id: str, pass_name: str = "Combined") -> Optional[str]:
    """Get the path to a specific pass JPEG in the latest cache."""
    cache_dir = get_latest_cache_dir(workspace, job_id)
    path = os.path.join(cache_dir, f"{pass_name}.jpg")
    return path if os.path.isfile(path) else None


def convert_frame_on_demand(src_path: str, blender_path: str = "") -> Optional[dict]:
    """Convert a render file to JPEG(s) in a temp directory.

    Caller must clean up the returned temp_dir after use.
    Returns {"passes": [...], "files": {...}, "temp_dir": "/path/"} or None.
    """
    import tempfile
    tmp = tempfile.mkdtemp(prefix="agent_preview_ondemand_")
    result = _convert_source_file(src_path, tmp, blender_path)
    if not result:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    result["temp_dir"] = tmp
    return result


def cleanup_latest(workspace: str, job_id: str):
    """Delete the latest cache directory for a job."""
    cache_dir = get_latest_cache_dir(workspace, job_id)
    with _cache_lock:
        shutil.rmtree(cache_dir, ignore_errors=True)


# ── Background updater (runs during render) ─────────────────────────────

class LatestFrameUpdater:
    """Background thread that keeps the latest-frame cache current during render."""

    def __init__(self, workspace: str, job_id: str, blender_path: str = "", on_cached_callback=None):
        self._workspace = workspace
        self._job_id = job_id
        self._blender_path = blender_path
        self._on_cached_callback = on_cached_callback
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="latest-cache")
        self._thread.start()

    def push(self, frame_num: int, src_path: str):
        """Queue a frame for caching.  Only the newest queued entry is processed."""
        self._queue.put((frame_num, src_path))

    def stop(self):
        self._stop.set()
        self._queue.put(None)  # unblock the thread
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                break

            # Drain queue — only process the newest entry
            newest = item
            while not self._queue.empty():
                try:
                    nxt = self._queue.get_nowait()
                    if nxt is None:
                        return
                    newest = nxt
                except queue.Empty:
                    break

            frame_num, src_path = newest
            try:
                cache_latest_frame(
                    src_path, self._workspace, self._job_id,
                    frame_num, self._blender_path,
                    on_cached_callback=self._on_cached_callback
                )
                print(f"[cache] Cached latest frame {frame_num}")
            except Exception as e:
                print(f"[cache] Failed to cache frame {frame_num}: {e}")

import os
import time
import threading

from .agent_backend import BackendSession, publish_blend_files
from .agent_blend_info import read_blend_info

SCAN_RECURSIVE = True
MAX_BLEND_FILES = 500
BLEND_SCAN_INTERVAL = 10  # seconds between local filesystem checks

# Cache: {relpath: {"mtime": float, "info": dict}}
_info_cache: dict[str, dict] = {}


def list_blend_files(blend_root: str):
    results = []
    root = os.path.abspath(blend_root)
    if not os.path.isdir(root):
        return results

    if SCAN_RECURSIVE:
        walker = os.walk(root, followlinks=False)
    else:
        walker = [(root, [], os.listdir(root))]

    for dirpath, _, filenames in walker:
        for name in filenames:
            if name.lower().endswith(".blend"):
                full_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(full_path, root).replace("\\", "/")
                results.append(rel_path)
                if len(results) >= MAX_BLEND_FILES:
                    return sorted(results)
    return sorted(results)


def read_blend_files_info(
    blend_root: str, files: list[str], blender_path: str
) -> dict[str, dict]:
    """Read settings from each blend file, using mtime-based caching."""
    root = os.path.abspath(blend_root)
    result: dict[str, dict] = {}

    for relpath in files:
        full_path = os.path.join(root, relpath.replace("/", os.sep))
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            continue

        # Check cache
        cached = _info_cache.get(relpath)
        if cached and cached["mtime"] == mtime:
            result[relpath] = cached["info"]
            continue

        # Read fresh
        info = read_blend_info(blender_path, full_path)
        if info:
            _info_cache[relpath] = {"mtime": mtime, "info": info}
            result[relpath] = info
        else:
            # Remove stale cache entry
            _info_cache.pop(relpath, None)

    return result


def blend_publish_loop(
    session: BackendSession, agent_id: str,
    blend_root: str, stop_event: threading.Event,
    blender_path: str = "",
    agent_state: dict | None = None,
):
    """Event-driven blend file publisher.

    Only publishes to the server when:
    1. Local files actually changed (mtime-based detection)
    2. The server requested a rescan (piggybacked on heartbeat response)
    3. First run (initial publish)

    No periodic "safety" publishes — the heartbeat already proves liveness.
    No separate HTTP call to /rescan-status — the heartbeat carries that flag.
    """
    last_state_hash = None

    def get_workspace_state(root: str):
        """Returns a list of (relpath, mtime) for all blend files."""
        files = list_blend_files(root)
        state = []
        for f in files:
            full_path = os.path.join(root, f.replace("/", os.sep))
            try:
                state.append((f, os.path.getmtime(full_path)))
            except OSError:
                continue
        return files, state

    while not stop_event.is_set():
        try:
            files, current_state = get_workspace_state(blend_root)

            # Check if the heartbeat flagged a rescan request
            rescan_requested = agent_state and agent_state.pop("rescan_requested", False)
            state_changed = (current_state != last_state_hash)

            if rescan_requested or state_changed:
                # Skip headless Blender (read_blend_files_info) while a render
                # is active — it spawns blender -b processes that compete for
                # VRAM and can exhaust the GPU.
                rendering = agent_state and agent_state.get("active_job_id")
                blend_info: dict[str, dict] = {}
                if blender_path and not rendering:
                    blend_info = read_blend_files_info(blend_root, files, blender_path)

                payload = {
                    "files": files,
                    "blend_files_info": blend_info,
                }
                publish_blend_files(session, agent_id, payload)

                if rescan_requested or (state_changed and last_state_hash is not None):
                    print(f"[agent] Published {len(files)} blend files"
                          f"{' (rescan requested)' if rescan_requested else ' (files changed)'}.")

                last_state_hash = current_state

        except Exception as e:
            print("Blend publish loop error:", e)

        stop_event.wait(BLEND_SCAN_INTERVAL)

# blender_addon/config.py
#
# Reads the agent's config from disk (same PC) and checks if the agent is running.

from __future__ import annotations

import json
import os

DEFAULT_CONFIG_FILENAME = "agent_config.json"


def _default_config_path() -> str:
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    # Check new folder first, fall back to legacy folder
    new_path = os.path.join(appdata, "RenderManager", DEFAULT_CONFIG_FILENAME)
    if os.path.exists(new_path):
        return new_path
    # Legacy folder names
    for legacy_name in ("RenderRemote", "RemoteRenderer"):
        legacy_path = os.path.join(appdata, legacy_name, DEFAULT_CONFIG_FILENAME)
        if os.path.exists(legacy_path):
            return legacy_path
    return new_path  # default to new location


def find_config_path() -> str | None:
    """Search for agent_config.json using the same resolution order as the agent.

    Returns the path if found, None otherwise.
    """
    # 1. Env var
    envp = os.environ.get("AGENT_CONFIG_PATH")
    if envp and os.path.isfile(envp):
        return os.path.abspath(envp)

    # 2. Local directory
    local = os.path.abspath(DEFAULT_CONFIG_FILENAME)
    if os.path.isfile(local):
        return local

    # 3. AppData default
    default = _default_config_path()
    if os.path.isfile(default):
        return os.path.abspath(default)

    return None


def load_config(path: str) -> dict | None:
    """Load and parse agent_config.json. Returns None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None

    # Resolve workspace paths (same defaults as the agent)
    default_workspace = r"C:\RenderManagerWorkspace"
    workspace = os.path.abspath(cfg.get("workspace_root") or default_workspace)
    cfg["workspace_root"] = workspace
    cfg["blend_root"] = os.path.abspath(
        cfg.get("blend_root") or os.path.join(workspace, "BlendFiles")
    )

    return cfg


def is_agent_running(workspace_root: str) -> bool:
    """Check if the agent process is running by trying to lock the lock file.

    The agent holds an exclusive msvcrt lock on ``.agent.lock`` in AppData for
    its lifetime.  If we can lock it, the agent is NOT running.  If we can't,
    it IS running.
    """
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    # Check new folder first, fall back to legacy names
    for folder in ("RenderManager", "RenderRemote", "RemoteRenderer"):
        candidate = os.path.join(appdata, folder, ".agent.lock")
        if os.path.exists(candidate):
            lock_path = candidate
            break
    else:
        # Default to new location even if it doesn't exist yet
        lock_path = os.path.join(appdata, "RenderManager", ".agent.lock")
    if not os.path.exists(lock_path):
        return False

    try:
        import msvcrt

        fp = open(lock_path, "a+b")
        try:
            msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            # Lock succeeded -> agent is NOT running. Unlock and close.
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            fp.close()
            return False
        except OSError:
            # Lock failed -> agent IS running
            fp.close()
            return True
    except Exception:
        return False

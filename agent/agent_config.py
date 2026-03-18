import base64
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple

from agent.brand import APP_APPDATA_FOLDER, APP_DEFAULT_WORKSPACE


# ---------------------------------------------------------------------------
# Windows DPAPI helpers (encrypts data so only the same Windows user can decrypt)
# ---------------------------------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt a string using Windows DPAPI. Returns base64-encoded ciphertext."""
    data = plaintext.encode("utf-8")
    blob_in = _DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("DPAPI CryptProtectData failed")
    encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _dpapi_decrypt(ciphertext_b64: str) -> str:
    """Decrypt a base64-encoded DPAPI ciphertext. Returns the original string."""
    data = base64.b64decode(ciphertext_b64)
    blob_in = _DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("DPAPI CryptUnprotectData failed")
    decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return decrypted.decode("utf-8")


def _is_windows() -> bool:
    return sys.platform == "win32"

DEFAULT_CONFIG_FILENAME = "agent_config.json"

DEFAULT_BACKEND_URL = "https://rendermanager.com"
DEFAULT_AGENT_NAME = "my_pc"
DEFAULT_WORKSPACE = os.path.join(os.path.expanduser("~"), APP_DEFAULT_WORKSPACE)
DEFAULT_BLENDER_PATH = r"C:\Program Files\Blender Foundation\Blender\blender.exe"

_OLD_APPDATA_FOLDERS = ["RemoteRenderer", "RenderRemote"]  # legacy folder names for migration


def _migrate_appdata_if_needed(new_base: str) -> None:
    """If an old appdata folder exists but the new one doesn't, copy it."""
    if os.path.isdir(new_base):
        return
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    for old_name in _OLD_APPDATA_FOLDERS:
        old_base = os.path.join(appdata, old_name)
        if os.path.isdir(old_base):
            try:
                shutil.copytree(old_base, new_base)
                return
            except Exception:
                pass  # best-effort migration


def get_appdata_dir() -> str:
    """Get the standard configuration directory (Windows AppData)."""
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    base = os.path.join(appdata, APP_APPDATA_FOLDER)
    _migrate_appdata_if_needed(base)
    return base


def default_config_path() -> str:
    """Store config in a standard per-user location (Windows AppData)."""
    return os.path.join(get_appdata_dir(), DEFAULT_CONFIG_FILENAME)


def resolve_config_path(explicit_path: Optional[str] = None) -> str:
    """
    Search order:
    1) explicit_path (CLI / caller)
    2) env AGENT_CONFIG_PATH
    3) local ./agent_config.json
    4) %APPDATA%\\{APP_APPDATA_FOLDER}\\agent_config.json
    """
    if explicit_path:
        return os.path.abspath(explicit_path)

    envp = os.environ.get("AGENT_CONFIG_PATH")
    if envp:
        return os.path.abspath(envp)

    local = os.path.abspath(DEFAULT_CONFIG_FILENAME)
    if os.path.exists(local):
        return local

    return os.path.abspath(default_config_path())


def load_config_from_path(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            cfg.setdefault("config_path", os.path.abspath(path))

            # Decrypt DPAPI-encrypted token if present
            if "agent_token_encrypted" in cfg and "agent_token" not in cfg:
                if _is_windows():
                    try:
                        cfg["agent_token"] = _dpapi_decrypt(cfg["agent_token_encrypted"])
                    except Exception as e:
                        print(f"[config] Failed to decrypt agent token: {e}")
                else:
                    print("[config] Warning: encrypted token found but not on Windows, cannot decrypt")

            # Migration: if plaintext token exists, encrypt it and re-save
            if "agent_token" in cfg and "agent_token_encrypted" not in cfg and _is_windows():
                try:
                    cfg["agent_token_encrypted"] = _dpapi_encrypt(cfg["agent_token"])
                    save_cfg = dict(cfg)
                    save_cfg.pop("agent_token", None)  # remove plaintext from disk
                    save_cfg["config_path"] = os.path.abspath(path)
                    tmp = os.path.abspath(path) + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fw:
                        json.dump(save_cfg, fw, indent=2)
                    os.replace(tmp, os.path.abspath(path))
                    print("[config] Migrated agent token to encrypted storage")
                except Exception as e:
                    print(f"[config] Token encryption migration failed (token still works): {e}")

            return cfg
    except Exception:
        return {}


def save_config_to_path(path: str, cfg: dict) -> None:
    if not path:
        raise ValueError("Config path is required")
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    cfg = dict(cfg)
    cfg["config_path"] = path

    # Encrypt the agent token before writing to disk (Windows only)
    if "agent_token" in cfg and _is_windows():
        try:
            cfg["agent_token_encrypted"] = _dpapi_encrypt(cfg["agent_token"])
            del cfg["agent_token"]  # never write plaintext to disk
        except Exception as e:
            print(f"[config] Warning: DPAPI encryption failed, saving token in plaintext: {e}")

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def validate_config_for_mvp(cfg: dict) -> Tuple[bool, str]:
    backend_url = (cfg.get("backend_url") or "").strip()
    agent_token = (cfg.get("agent_token") or "").strip()
    blender_path = (cfg.get("blender_path") or "").strip()
    name = (cfg.get("name") or "").strip()
    workspace_root = (cfg.get("workspace_root") or "").strip()
    blend_root = (cfg.get("blend_root") or "").strip()
    output_root = (cfg.get("output_root") or "").strip()

    if not backend_url:
        return False, "Server URL is required."
    if not (backend_url.startswith("http://") or backend_url.startswith("https://")):
        return False, "Server URL must start with http:// or https://"
    if backend_url.startswith("http://"):
        from urllib.parse import urlparse as _urlparse
        _host = _urlparse(backend_url).hostname or ""
        if _host not in ("localhost", "127.0.0.1") and not _host.startswith("192.168."):
            return False, "Non-local server URLs must use HTTPS."

    if not agent_token or len(agent_token) < 10:
        return False, "Agent not authorized. Please run setup and log in."

    if not name:
        return False, "Agent name is required."

    if not workspace_root:
        return False, "Workspace folder is required."
    if not blend_root:
        return False, "blend_root is missing (should be inside workspace)."
    if not output_root:
        return False, "output_root is missing (should be inside workspace)."

    if not blender_path:
        return False, "Blender path is required."
    if not os.path.exists(blender_path):
        return False, "Blender path does not exist."
    if not blender_path.lower().endswith("blender.exe"):
        return False, "Please select blender.exe."

    return True, "OK"


def ensure_agent_config(config_path: Optional[str] = None, *, interactive: bool = True) -> dict:
    """
    Load config. Agent tokens are issued only through the GUI wizard.
    If the token is missing, raises RuntimeError so the caller opens setup.
    """
    cfg_path = resolve_config_path(config_path)
    try:
        cfg = load_config_from_path(cfg_path) or {}
    except Exception:
        cfg = {}

    cfg["backend_url"] = cfg.get("backend_url") or DEFAULT_BACKEND_URL
    cfg["name"] = cfg.get("name") or DEFAULT_AGENT_NAME

    workspace = os.path.abspath(cfg.get("workspace_root") or DEFAULT_WORKSPACE)
    cfg["workspace_root"] = workspace
    cfg["blend_root"] = os.path.abspath(cfg.get("blend_root") or os.path.join(workspace, "BlendFiles"))
    cfg["output_root"] = os.path.abspath(cfg.get("output_root") or os.path.join(workspace, "Renders"))

    os.makedirs(cfg["blend_root"], exist_ok=True)
    os.makedirs(cfg["output_root"], exist_ok=True)

    # Optional: copy example blend file if it exists and workspace is fresh
    _copy_example_blend(cfg["blend_root"])

    if not cfg.get("agent_token"):
        raise RuntimeError("Config missing agent_token. Please run setup to log in.")

    save_config_to_path(cfg_path, cfg)
    return cfg


def get_bundle_dir() -> str:
    """Get the root directory of the application bundle or source code.
    Correctly handles PyInstaller OneFile/OneDir modes and dev mode.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller base path
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        # In OneDir mode, data files are often moved into an _internal folder
        internal = os.path.join(base, "_internal")
        return internal if os.path.isdir(internal) else base
    
    # Dev mode: assumes this file is in agent/ and we want the repo root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _copy_example_blend(blend_root: str) -> None:
    """Check if we have any .blend files bundled and copy them if the user doesn't have them."""
    app_base = get_bundle_dir()
    example_src_dir = os.path.join(app_base, "example_blend")
    
    if not os.path.isdir(example_src_dir):
        return
        
    try:
        source_files = os.listdir(example_src_dir)
        blend_files = [f for f in source_files if f.lower().endswith(".blend")]
        
        for blend_file in blend_files:
            src_path = os.path.join(example_src_dir, blend_file)
            dst_path = os.path.join(blend_root, blend_file)
            
            if not os.path.exists(dst_path):
                shutil.copy2(src_path, dst_path)
                print(f"[agent] Copied {blend_file} to workspace.")
    except Exception as e:
        print(f"[agent] Failed to copy example blend files: {e}")


def get_saved_agent_id(cfg: dict) -> Optional[str]:
    return cfg.get("agent_id")


def set_saved_agent_id(cfg: dict, agent_id: str):
    cfg["agent_id"] = agent_id
    cfg_path = cfg.get("config_path") or resolve_config_path(None)
    save_config_to_path(cfg_path, cfg)

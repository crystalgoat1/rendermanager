# agent/agent_installer_gui.py
#
# Setup wizard for the Render Manager agent.
#
# Authentication flow (PKCE + local HTTP redirect, RFC 8252):
#   1. User clicks "Log in with Browser"
#   2. Wizard generates PKCE code_verifier + code_challenge
#   3. Wizard starts a one-shot local HTTP server on 127.0.0.1:<random_port>
#   4. Wizard opens the user's browser to {server_url}/agent-setup?port=...&challenge=...
#   5. User logs in (if not already) and clicks "Authorize Agent"
#   6. Server SPA calls POST /api/agent-tokens/provision, then redirects browser to
#      http://127.0.0.1:<port>/callback?code=<auth_code>
#   7. Wizard's local server catches the callback
#   8. Wizard calls POST /api/agent-tokens/exchange to get the plaintext token
#   9. Wizard shows "Logged in as <name>", enables Save/Run

import base64
import hashlib
import http.server
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import requests

from .agent_config import (
    DEFAULT_BACKEND_URL,
    resolve_config_path,
    load_config_from_path,
    save_config_to_path,
    validate_config_for_mvp,
    get_bundle_dir,
    _copy_example_blend,
)
from .agent_backend import verify_agent_token
from .brand import APP_DISPLAY_NAME, APP_MODEL_ID, APP_DEFAULT_WORKSPACE, AGENT_VERSION

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

WINDOW_TITLE = f"{APP_DISPLAY_NAME} Setup v{AGENT_VERSION}"
HARDCODED_BACKEND_URL = DEFAULT_BACKEND_URL
# Brand-aligned palette — see frontend/BRAND.md
ACCENT       = "#6366f1"   # primary
ACCENT_HOVER = "#4f46e5"
BG           = "#0B0B14"   # bg-base
CARD_BG      = "#131321"   # bg-surface
BORDER       = "#1e1e2e"   # ≈ white/10 on bg-base
TEXT         = "#e2e8f0"   # slate-200
MUTED        = "#94a3b8"   # slate-400
SUCCESS      = "#10b981"   # emerald-500
ERROR        = "#ef4444"   # red-500
WARNING      = "#f59e0b"   # amber-500


# ---------------------------------------------------------------------------
# URL safety helper
# ---------------------------------------------------------------------------

def _is_probably_https(url: str) -> bool:
    url = (url or "").strip().lower()
    if url.startswith("http://127.") or url.startswith("http://localhost"):
        return True
    if url.startswith("http://192.168.") or url.startswith("http://10.") or url.startswith("http://172."):
        return True
    return url.startswith("https://")


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Challenge = base64url(sha256(verifier))."""
    verifier = secrets.token_urlsafe(32)
    digest   = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# One-shot local HTTP listener
# ---------------------------------------------------------------------------

def _start_local_listener(port: int, result: dict) -> None:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                params = urllib.parse.parse_qs(parsed.query)
                code = params.get("code", [""])[0]
                if code:
                    result["code"] = code
                    body = (
                        b"<html><body style='font-family:sans-serif;text-align:center;"
                        b"padding:60px;background:#0f0f1a;color:#e8e8f0'>"
                        b"<h2 style='color:#4caf50'>Agent authorized!</h2>"
                        b"<p>You can close this tab and return to the setup wizard.</p>"
                        b"</body></html>"
                    )
                else:
                    result["error"] = "No code in callback"
                    body = b"<html><body>Authorization failed. You can close this tab.</body></html>"
            else:
                body = b"<html><body>Unexpected request.</body></html>"

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 120
    server.handle_request()
    server.server_close()


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

def _exchange_token(backend_url: str, auth_code: str, code_verifier: str) -> dict:
    res = requests.post(
        f"{backend_url}/api/agent-tokens/exchange",
        json={"code": auth_code, "code_verifier": code_verifier},
        timeout=15,
    )
    if res.status_code != 200:
        try:
            detail = res.json().get("detail", res.text)
        except Exception:
            detail = res.text
        raise RuntimeError(f"Token exchange failed: {detail}")
    return res.json()


# ---------------------------------------------------------------------------
# Post-setup onboarding screen
# ---------------------------------------------------------------------------

def _show_success_screen(root, dashboard_url: str = "", blend_root: str = ""):
    """Replace the wizard content with a success/next-steps screen."""
    # Clear all existing widgets
    for widget in root.winfo_children():
        widget.destroy()

    root.configure(fg_color=BG)

    frame = ctk.CTkFrame(root, fg_color=BG)
    frame.pack(fill="both", expand=True, padx=24, pady=24)

    # Green checkmark
    ctk.CTkLabel(
        frame, text="\u2714",
        font=ctk.CTkFont(size=48), text_color=SUCCESS,
    ).pack(pady=(20, 8))

    ctk.CTkLabel(
        frame, text="You're all set!",
        font=ctk.CTkFont(family="Inter", size=22, weight="bold"), text_color=TEXT,
    ).pack(pady=(0, 20))

    tips_frame = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=10)
    tips_frame.pack(fill="x", pady=(0, 20))

    blend_path_short = blend_root.replace(os.path.expanduser("~"), "~") if blend_root else "your workspace"
    tips = [
        ("Agent is running in the background", "Look for the Render Manager icon in your system tray (near the clock)."),
        (f"Your Workspace Folder", f"{blend_root}\nSave or drop your .blend files here so the agent can access them."),
        ("Submit your first render", "Use the web dashboard, or in Blender: open the side panel (N) > Render Manager tab, or use the top menu Render > Render Manager: Background Render."),
    ]
    for title, desc in tips:
        tip_row = ctk.CTkFrame(tips_frame, fg_color="transparent")
        tip_row.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(
            tip_row, text=title, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        ).pack(fill="x")
        ctk.CTkLabel(
            tip_row, text=desc, anchor="w", wraplength=440, justify="left",
            font=ctk.CTkFont(size=11), text_color=MUTED,
        ).pack(fill="x", pady=(0, 6))

    # Close / Open Dashboard button (no auto-close timer)
    btn_label = "Open Dashboard" if dashboard_url else "Close"

    def _close():
        if dashboard_url:
            try:
                webbrowser.open(dashboard_url)
            except Exception:
                pass
        root.destroy()
        sys.exit(0)

    close_btn = ctk.CTkButton(
        frame, text=btn_label, command=_close,
        height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        font=ctk.CTkFont(family="Inter", size=13, weight="bold"), corner_radius=8,
    )
    close_btn.pack(fill="x")


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

def run_setup_wizard(
    existing_config_path: str | None = None,
    default_config_dir: str | None = None,
) -> int:
    # Tell Windows this is its own app, not "python.exe" — fixes taskbar icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)
    except Exception:
        pass

    root = ctk.CTk()
    root.title(WINDOW_TITLE)
    w, h = 560, 460
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.resizable(False, False)
    root.configure(fg_color=BG)

    # Window + taskbar icon
    _ico_path = os.path.join(get_bundle_dir(), "agent", "assets", "gradient_icon_256_transparent.ico")
    try:
        root.iconbitmap(_ico_path)
        root.after(50, lambda: root.iconbitmap(_ico_path))  # re-apply after window maps
    except Exception:
        pass

    # Apply Windows 11 native rounded corners if possible
    try:
        import ctypes
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(2)), 4)
    except Exception:
        pass

    # ---- State ----
    workspace_var  = tk.StringVar(value=os.path.expanduser(f"~\\{APP_DEFAULT_WORKSPACE}"))
    
    def _find_default_blender_exe() -> tuple[str, bool, bool]:
        """Find the best Blender executable.

        Returns (path, was_auto_detected, is_ms_store).
        Priority:
          1. Standard install dirs + Steam — pick the highest version across all.
          2. Any extra per-user Steam library dirs found in libraryfolders.vdf.
          3. MS Store stub — only used as a last resort (marked with is_ms_store=True).
        """
        import re as _re

        # --- 1. Collect all candidate base directories to search ---
        candidate_bases = [
            r"C:\Program Files\Blender Foundation",
            r"C:\Program Files (x86)\Blender Foundation",
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender",
            r"C:\Program Files\Steam\steamapps\common\Blender",
            r"C:\Blender",
        ]

        # Also scan additional Steam library folders from libraryfolders.vdf
        _steam_roots = [
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Steam"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Steam"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Steam"),
        ]
        for _sr in _steam_roots:
            _vdf = os.path.join(_sr, "steamapps", "libraryfolders.vdf")
            if os.path.isfile(_vdf):
                try:
                    with open(_vdf, "r", encoding="utf-8", errors="ignore") as _fh:
                        for _line in _fh:
                            _m = _re.search(r'"path"\s+"([^"]+)"', _line)
                            if _m:
                                _lib = os.path.join(_m.group(1), "steamapps", "common", "Blender")
                                if _lib not in candidate_bases:
                                    candidate_bases.append(_lib)
                except Exception:
                    pass

        # --- 2. Search all base dirs, track best (newest) version ---
        best_path = ""
        best_ver_tuple = ()

        def _version_tuple(folder_name: str):
            """Convert 'Blender 4.3.0' or '4.3' style names to a sortable tuple."""
            nums = _re.findall(r"\d+", folder_name)
            return tuple(int(n) for n in nums) if nums else ()

        def _version_from_exe(exe_path: str):
            """Run blender --version to get version tuple when folder name lacks it."""
            try:
                import subprocess
                result = subprocess.run(
                    [exe_path, "--version"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                m = _re.search(r"Blender\s+(\d[\d.]+)", result.stdout)
                if m:
                    return tuple(int(n) for n in m.group(1).split("."))
            except Exception:
                pass
            return ()

        for base in candidate_bases:
            if not os.path.isdir(base):
                continue
            # The base itself might BE the Blender dir (e.g. Steam path)
            if os.path.isfile(os.path.join(base, "blender.exe")):
                exe = os.path.join(base, "blender.exe")
                ver_t = _version_tuple(os.path.basename(base))
                if not ver_t:
                    ver_t = _version_from_exe(exe)
                if ver_t > best_ver_tuple or (not best_ver_tuple and not best_path):
                    best_ver_tuple = ver_t
                    best_path = exe
                continue
            # Or it's a parent dir containing "Blender X.Y" subdirs
            try:
                entries = os.listdir(base)
            except PermissionError:
                continue
            for item in entries:
                if not item.lower().startswith("blender"):
                    continue
                exe = os.path.join(base, item, "blender.exe")
                if os.path.isfile(exe):
                    ver_t = _version_tuple(item)
                    if not ver_t:
                        ver_t = _version_from_exe(exe)
                    if ver_t > best_ver_tuple or (not best_ver_tuple and not best_path):
                        best_ver_tuple = ver_t
                        best_path = exe

        if best_path:
            return (best_path, True, False)

        # --- 3. Last resort: MS Store stub ---
        winapps = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "blender.exe"
        )
        if os.path.isfile(winapps):
            return (winapps, True, True)

        return ("", False, False)

    _discovered_exe, _was_auto, _is_ms_store = _find_default_blender_exe()
    blender_var    = tk.StringVar(value=_discovered_exe)
    status_var     = tk.StringVar(value="")
    _auth          = {"token": None, "user_name": None}
    agent_name     = os.environ.get("COMPUTERNAME", "RenderNode")

    # ---- Prefill from existing config ----
    if existing_config_path and os.path.exists(existing_config_path):
        try:
            existing = load_config_from_path(existing_config_path)
            workspace_var.set(existing.get("workspace_root", workspace_var.get()))
            blender_var.set(existing.get("blender_path", ""))
            if existing.get("agent_token"):
                _auth["token"] = existing["agent_token"]
                agent_name = existing.get("name", agent_name)
        except Exception as exc:
            pass

    # ---- Header ----
    header = ctk.CTkFrame(root, fg_color=BG, corner_radius=0, height=70)
    header.pack(fill="x")
    header.pack_propagate(False)

    ctk.CTkLabel(
        header,
        text="Set Up Render Manager",
        font=ctk.CTkFont(family="Inter", size=24, weight="bold"),
        text_color=TEXT,
    ).pack(pady=(20, 0))

    # ---- Form card ----
    card = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
    card.pack(fill="both", expand=True, padx=24, pady=(16, 24))

    # ---- Account Row (Inline Auth) ----
    account_row = ctk.CTkFrame(card, fg_color="transparent")
    account_row.pack(fill="x", padx=20, pady=(20, 10))
    
    ctk.CTkLabel(account_row, text="Account", width=110, anchor="w",
                 font=ctk.CTkFont(family="Inter", size=13, weight="bold"), text_color=TEXT).pack(side="left")

    auth_label_var = tk.StringVar(value="Not Authorized")
    auth_label = ctk.CTkLabel(account_row, textvariable=auth_label_var, font=ctk.CTkFont(family="Inter", size=13),
                              text_color=MUTED, anchor="w", width=220)
    auth_label.pack(side="left", padx=(8, 0))

    btn_auth = ctk.CTkButton(account_row, text="Log In", width=80, height=32,
                             fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                             corner_radius=8, font=ctk.CTkFont(family="Inter", size=12, weight="bold"))
    btn_auth.pack(side="right")

    def _update_auth_ui(is_loading=False):
        if is_loading:
            auth_label_var.set("Waiting for browser...")
            auth_label.configure(text_color=MUTED)
            btn_auth.configure(state="normal", text="Cancel", fg_color=BORDER, hover_color="#3a3a5a", command=do_cancel_login)
        elif _auth.get("token"):
            name = _auth.get("user_name") or "Authorized"
            auth_label_var.set(name)
            auth_label.configure(text_color=SUCCESS)
            btn_auth.configure(state="normal", text="Sign Out", fg_color=BORDER, hover_color="#3a3a5a", command=do_sign_out)
            status_var.set("")
        else:
            auth_label_var.set("Not Authorized")
            auth_label.configure(text_color=ERROR)
            btn_auth.configure(state="normal", text="Log In", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=do_browser_login)

    # To allow cancelling the login wait
    _cancel_auth_event = threading.Event()

    def do_sign_out():
        _auth["token"] = None
        _auth["user_name"] = None
        _update_auth_ui()

    def do_cancel_login():
        _cancel_auth_event.set()
        _auth["token"] = None
        _update_auth_ui()
        # Fire a dummy request to unblock the local HTTPServer immediately
        try:
            requests.get("http://127.0.0.1:" + str(getattr(do_cancel_login, "current_port", 0)) + "/callback?error=cancelled", timeout=1)
        except Exception:
            pass

    def do_browser_login():
        _cancel_auth_event.clear()
        port = _find_free_port()
        do_cancel_login.current_port = port
        code_verifier, code_challenge = _generate_pkce()
        result = {}

        listener_thread = threading.Thread(
            target=_start_local_listener, args=(port, result), daemon=True
        )
        listener_thread.start()

        auth_url = (
            f"{HARDCODED_BACKEND_URL}/agent-setup"
            f"?port={port}"
            f"&challenge={urllib.parse.quote(code_challenge)}"
            f"&name={urllib.parse.quote(agent_name)}"
        )
        webbrowser.open(auth_url)
        _update_auth_ui(is_loading=True)

        def poll():
            listener_thread.join(timeout=900)  # 15 minutes to allow plenty of time
            if _cancel_auth_event.is_set():
                return
                
            if result.get("code"):
                try:
                    data = _exchange_token(HARDCODED_BACKEND_URL, result["code"], code_verifier)
                    if _cancel_auth_event.is_set(): return
                    _auth["token"] = data["agent_token"]
                    _auth["user_name"] = data.get("user_name") or "Authorized Account"
                    root.after(0, _update_auth_ui)
                except Exception as exc:
                    if _cancel_auth_event.is_set(): return
                    root.after(0, lambda: _on_login_failure(str(exc)))
            elif result.get("error"):
                if result.get("error") == "cancelled": return
                root.after(0, lambda: _on_login_failure(result["error"]))
            else:
                root.after(0, lambda: _on_login_failure("Timed out waiting for browser authorization."))

        threading.Thread(target=poll, daemon=True).start()

    def _on_login_failure(reason: str):
        _auth["token"] = None
        _update_auth_ui()
        messagebox.showerror("Authorization failed", reason)


    # ---- Form Fields ----
    def _field(parent, label: str, var: tk.StringVar, btn_text=None, btn_cmd=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(10, 0))
        
        lbl = ctk.CTkLabel(row, text=label, width=110, anchor="w",
                           font=ctk.CTkFont(family="Inter", size=13, weight="bold"), text_color=TEXT)
        lbl.pack(side="left")
        
        entry = ctk.CTkEntry(row, textvariable=var, font=ctk.CTkFont(family="Consolas", size=12),
                             fg_color=BG, border_color=BORDER, text_color=TEXT,
                             corner_radius=8, height=36)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        
        cmd = btn_cmd or (lambda: _browse(var, label))
        btn = ctk.CTkButton(row, text=btn_text or "Browse" + ("..." if not btn_text else ""), width=70, height=36,
                            fg_color=BORDER, hover_color="#3a3a5a", text_color=TEXT,
                            corner_radius=8, font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
                            command=cmd)
        btn.pack(side="right", padx=(8, 0))
        return lbl, row

    def _browse(var: tk.StringVar, label: str):
        if "workspace" in label.lower():
            path = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser("~"))
        elif "blender" in label.lower():
            path = filedialog.askopenfilename(
                title="Select blender.exe",
                filetypes=[("Blender Executable", "blender.exe"), ("Executable", "*.exe"), ("All files", "*.*")],
            )
        else:
            path = None # Should not happen
        if path:
            var.set(path)

    _field(card, "Workspace",    workspace_var,  "Browse...")
    _, blender_row = _field(card, "Blender .exe", blender_var,    "Find...")

    # Show auto-detect indicator if Blender was found automatically
    detect_label = None
    if _was_auto and _discovered_exe:
        if _is_ms_store:
            detect_label = ctk.CTkLabel(
                card,
                text="⚠ Microsoft Store version detected - may not work correctly. Browse for your preferred install.",
                font=ctk.CTkFont(family="Inter", size=11),
                text_color=WARNING, anchor="w", wraplength=400, justify="left",
            )
        else:
            detect_label = ctk.CTkLabel(
                card, text="Detected automatically",
                font=ctk.CTkFont(family="Inter", size=11),
                text_color=MUTED, anchor="w",
            )
        detect_label.pack(fill="x", padx=(140, 20), pady=(2, 0))

    # Hide the auto-detect label when the user manually changes the path
    def _on_blender_path_changed(*_args):
        if detect_label and blender_var.get() != _discovered_exe:
            detect_label.pack_forget()
        elif detect_label and blender_var.get() == _discovered_exe:
            detect_label.pack(fill="x", padx=(140, 20), pady=(2, 0))
    blender_var.trace_add("write", _on_blender_path_changed)

    # ---- Blender Addon Row ----
    addon_row = ctk.CTkFrame(card, fg_color="transparent")
    addon_row.pack(fill="x", padx=20, pady=(10, 0))

    ctk.CTkLabel(addon_row, text="Blender Addon", width=110, anchor="w",
                 font=ctk.CTkFont(family="Inter", size=13, weight="bold"), text_color=TEXT).pack(side="left")

    addon_status_var = tk.StringVar(value="Not installed")
    addon_status_label = ctk.CTkLabel(addon_row, textvariable=addon_status_var,
                                      font=ctk.CTkFont(family="Inter", size=13),
                                      text_color=MUTED, anchor="w", width=220)
    addon_status_label.pack(side="left", padx=(8, 0))

    btn_addon = ctk.CTkButton(addon_row, text="Install", width=80, height=32,
                              fg_color=BORDER, hover_color="#3a3a5a", text_color=TEXT,
                              corner_radius=8, font=ctk.CTkFont(family="Inter", size=12, weight="bold"))
    btn_addon.pack(side="right")

    # Addon description
    ctk.CTkLabel(card, text="Optional. Lets you submit renders directly from Blender's Render menu.",
                 font=ctk.CTkFont(family="Inter", size=11), text_color=MUTED,
                 anchor="w", wraplength=350, justify="left").pack(fill="x", padx=(140, 20), pady=(2, 0))

    def _find_blender_addon_versions() -> list[str]:
        """Find Blender version dirs under %APPDATA%/Blender Foundation/Blender/.

        Returns (version_str, addons_dir, is_extension) tuples.
        Blender 4.2+ uses extensions/user_default/, older uses scripts/addons/.
        """
        appdata = os.environ.get("APPDATA", "")
        blender_base = os.path.join(appdata, "Blender Foundation", "Blender")
        if not os.path.isdir(blender_base):
            return []
        versions = []
        for name in os.listdir(blender_base):
            m = re.match(r"^(\d+)\.(\d+)$", name)
            if m:
                major, minor = int(m.group(1)), int(m.group(2))
                # Skip Blender versions below 4.0 (addon requires 4.0+)
                if major < 4:
                    continue
                if major > 4 or (major == 4 and minor >= 2):
                    # Blender 4.2+: new extensions system
                    addons_dir = os.path.join(blender_base, name, "extensions", "user_default")
                    versions.append((name, addons_dir, True))
                else:
                    # Blender 4.0–4.1: legacy addons path
                    addons_dir = os.path.join(blender_base, name, "scripts", "addons")
                    versions.append((name, addons_dir, False))
        return sorted(versions, key=lambda x: x[0], reverse=True)

    def _get_addon_source_dir() -> str | None:
        """Locate the bundled blender_addon/ folder."""
        addon_src = os.path.join(get_bundle_dir(), "blender_addon")
        if os.path.isdir(addon_src) and os.path.isfile(os.path.join(addon_src, "__init__.py")):
            return addon_src
        return None

    def _read_addon_version(init_path: str):
        """Extract bl_info version tuple from an addon __init__.py."""
        try:
            with open(init_path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r'"version"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)', content)
            if m:
                return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
        return None

    def _get_installed_addon_version():
        """Return (is_installed, version_tuple) for the first found installation."""
        for _ver, addons_dir, _is_ext in _find_blender_addon_versions():
            for folder_name in ["remote_renderer", "render_manager"]:
                init_path = os.path.join(addons_dir, folder_name, "__init__.py")
                if os.path.isfile(init_path):
                    return True, _read_addon_version(init_path)
        return False, None

    def _get_bundled_addon_version():
        """Return version tuple of the bundled addon."""
        addon_src = _get_addon_source_dir()
        if addon_src:
            return _read_addon_version(os.path.join(addon_src, "__init__.py"))
        return None

    def _update_addon_ui():
        installed, installed_ver = _get_installed_addon_version()
        bundled_ver = _get_bundled_addon_version()

        if not installed:
            addon_status_var.set("Not installed")
            addon_status_label.configure(text_color=ERROR)
            btn_addon.configure(text="Install", state="normal")
        elif bundled_ver and installed_ver and bundled_ver > installed_ver:
            ver_str = ".".join(str(x) for x in bundled_ver)
            addon_status_var.set(f"Update available (v{ver_str})")
            addon_status_label.configure(text_color=WARNING)
            btn_addon.configure(text="Update", state="normal")
        else:
            ver_str = ".".join(str(x) for x in installed_ver) if installed_ver else ""
            status = f"Installed v{ver_str}" if ver_str else "Installed"
            addon_status_var.set(status)
            addon_status_label.configure(text_color=SUCCESS)
            btn_addon.configure(text="Reinstall", state="normal")

    def do_install_addon():
        addon_src = _get_addon_source_dir()
        if not addon_src:
            messagebox.showerror("Addon Not Found",
                                 "Could not find the blender_addon folder next to the agent package.")
            return

        versions = _find_blender_addon_versions()
        if not versions:
            messagebox.showerror("Blender Not Found",
                                 "No Blender user data found.\n\n"
                                 "Open Blender at least once first so it creates\n"
                                 "its config folder, then try again.")
            return

        def _install_task():
            installed_to = []
            errors = []
            for ver, addons_dir, is_extension in versions:
                dest = os.path.join(addons_dir, "remote_renderer")
                try:
                    os.makedirs(addons_dir, exist_ok=True)
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.copytree(addon_src, dest)
                    # Blender 4.2+ requires blender_manifest.toml in the addon root
                    manifest_src = os.path.join(addon_src, "blender_manifest.toml")
                    if is_extension and os.path.isfile(manifest_src):
                        shutil.copy2(manifest_src, os.path.join(dest, "blender_manifest.toml"))
                    installed_to.append(ver)
                except Exception as exc:
                    errors.append(f"Blender {ver}: {exc}")

            if installed_to:
                # Try to auto-enable the addon in Blender
                blender_exe = blender_var.get().strip()
                addon_enabled = False
                if blender_exe and os.path.isfile(blender_exe):
                    # Try multiple enable approaches for different Blender versions
                    enable_script = (
                        "import bpy, sys\n"
                        "enabled = False\n"
                        "for mod in ['bl_ext.user_default.remote_renderer', 'remote_renderer', 'bl_ext.user_default.render_manager', 'render_manager']:\n"
                        "    try:\n"
                        "        bpy.ops.preferences.addon_enable(module=mod)\n"
                        "        enabled = True\n"
                        "        break\n"
                        "    except Exception:\n"
                        "        pass\n"
                        "if not enabled:\n"
                        "    try:\n"
                        "        bpy.ops.extensions.package_enable(module='remote_renderer')\n"
                        "        enabled = True\n"
                        "    except Exception:\n"
                        "        pass\n"
                        "if enabled:\n"
                        "    bpy.ops.wm.save_userpref()\n"
                        "    print('ADDON_ENABLED_OK')\n"
                        "else:\n"
                        "    print('ADDON_ENABLE_FAILED')\n"
                    )
                    try:
                        result = subprocess.run(
                            [blender_exe, "--background", "--python-expr", enable_script],
                            timeout=45, capture_output=True, text=True,
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {})
                        )
                        addon_enabled = "ADDON_ENABLED_OK" in (result.stdout or "")
                    except Exception:
                        pass

                def _on_success():
                    _update_addon_ui()
                    ver_list = ", ".join(installed_to)
                    if addon_enabled:
                        msg = f"Addon installed and enabled for Blender {ver_list}.\n\nIt will appear in Blender's Render menu.\nRestart Blender if it's currently open."
                    else:
                        msg = f"Addon installed for Blender {ver_list}.\n\nIt could not be auto-enabled. Please open Blender and enable it manually:\nEdit > Preferences > Add-ons > search \"{APP_DISPLAY_NAME}\"\n\nRestart Blender if it's currently open."
                    if errors:
                        msg += f"\n\nSome versions failed:\n" + "\n".join(errors)
                    messagebox.showinfo("Addon Installed", msg)
                root.after(0, _on_success)
            else:
                def _on_fail():
                    _update_addon_ui()
                    messagebox.showerror("Install Failed", "\n".join(errors))
                root.after(0, _on_fail)

        addon_status_var.set("Installing... (may take a moment)")
        addon_status_label.configure(text_color=WARNING)
        btn_addon.configure(text="...", state="disabled")
        threading.Thread(target=_install_task, daemon=True).start()

    btn_addon.configure(command=do_install_addon)
    _update_addon_ui()

    # ---- Start with Windows Row ----
    from .agent_service import is_autostart_enabled
    autostart_row = ctk.CTkFrame(card, fg_color="transparent")
    autostart_row.pack(fill="x", padx=20, pady=(10, 0))

    ctk.CTkLabel(autostart_row, text="Start with Windows", width=110, anchor="w",
                 font=ctk.CTkFont(family="Inter", size=13, weight="bold"), text_color=TEXT).pack(side="left")

    autostart_var = tk.BooleanVar(value=is_autostart_enabled() if existing_config_path else True)
    autostart_switch = ctk.CTkSwitch(
        autostart_row, text="", variable=autostart_var,
        onvalue=True, offvalue=False, width=46,
        progress_color=ACCENT, button_color=TEXT, button_hover_color="#d1d5db",
        fg_color=BORDER,
    )
    autostart_switch.pack(side="left", padx=(8, 0))

    # Init auth UI state
    _update_auth_ui()

    # Validate saved token against the server in the background
    if _auth.get("token"):
        def _verify_saved_token():
            try:
                verify_agent_token(HARDCODED_BACKEND_URL, _auth["token"])
            except Exception:
                _auth["token"] = None
                _auth["user_name"] = None
                root.after(0, _update_auth_ui)
        threading.Thread(target=_verify_saved_token, daemon=True).start()

    # ---- Finish Flow ----
    def build_config() -> dict:
        workspace = workspace_var.get().strip()
        cfg_path  = resolve_config_path(existing_config_path)
        return {
            "backend_url":    HARDCODED_BACKEND_URL,
            "agent_token":    _auth.get("token") or "",
            "name":           agent_name,
            "blender_path":   blender_var.get().strip(),
            "workspace_root": workspace,
            "blend_root":     os.path.join(workspace, "BlendFiles"),
            "output_root":    os.path.join(workspace, "Renders"),
            "config_path":    cfg_path,
            "autostart":      autostart_var.get(),
        }

    def validate_local() -> tuple[bool, str]:
        cfg = build_config()
        ok, reason = validate_config_for_mvp(cfg)
        return ok, reason

    def save_and_run():
        ok, reason = validate_local()
        if not ok:
            messagebox.showerror("Validation Failed", reason)
            return

        cfg = build_config()
        cfg_path = cfg["config_path"]
        try:
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            os.makedirs(cfg["blend_root"],  exist_ok=True)
            os.makedirs(cfg["output_root"], exist_ok=True)
            save_config_to_path(cfg_path, cfg)

            # Deploy example blend files immediately
            _copy_example_blend(cfg["blend_root"])

            try:
                from .agent_service import enable_autostart, disable_autostart
                if cfg["autostart"]:
                    enable_autostart()
                else:
                    disable_autostart()
            except Exception as exc:
                print(f"[setup] Autostart registration failed: {exc}")

            # Launch the agent as a separate process, then exit cleanly.
            try:
                if getattr(sys, 'frozen', False):
                    # PyInstaller exe: just pass --run directly
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32":
                        flags |= subprocess.CREATE_NO_WINDOW
                    subprocess.Popen(
                        [sys.executable, "--run", "--config", cfg_path],
                        creationflags=flags
                    )
                else:
                    # Dev mode: invoke via Python module
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32":
                        flags |= subprocess.CREATE_NO_WINDOW
                    subprocess.Popen(
                        [sys.executable, "agent_entry.py", "--run", "--config", cfg_path],
                        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        creationflags=flags
                    )
            except Exception as launch_exc:
                messagebox.showwarning(
                    APP_DISPLAY_NAME,
                    f"Settings saved, but the agent could not be started:\n{launch_exc}\n\n"
                    "Try launching the app again manually.",
                )

            if existing_config_path is None:
                # First-time setup: show onboarding tips
                _show_success_screen(root, dashboard_url=cfg["backend_url"] + "/dashboard", blend_root=cfg.get("blend_root", ""))
            else:
                # Re-opening wizard: just close, agent is already restarting
                root.destroy()
                sys.exit(0)
        except SystemExit:
            raise
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    # ---- Big Finish Button ----
    btn_row = ctk.CTkFrame(root, fg_color="transparent")
    btn_row.pack(fill="x", padx=24, pady=(0, 24))

    btn_finish = ctk.CTkButton(
        btn_row, text="Save & Start App", command=save_and_run,
        height=48, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        font=ctk.CTkFont(family="Inter", size=14, weight="bold"), corner_radius=10,
    )
    btn_finish.pack(fill="x")

    def _on_escape(e):
        root.destroy()
    root.bind("<Escape>", _on_escape)

    root.mainloop()
    return 0

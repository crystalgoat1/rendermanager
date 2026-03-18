import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from agent.brand import APP_DISPLAY_NAME, APP_MODEL_ID, AGENT_VERSION

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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


def _open_folder(path: str):
    if not path:
        messagebox.showerror("Open folder", "Folder path is missing.")
        return
    path = os.path.abspath(path)
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
    except Exception as e:
        messagebox.showerror("Open folder failed", f"Could not open:\n{path}\n\n{e}")


def _copy_blend_files(src_paths: list[str], dst_folder: str) -> tuple[int, list[str]]:
    os.makedirs(dst_folder, exist_ok=True)
    copied = 0
    errors: list[str] = []
    for src in src_paths:
        try:
            if not src.lower().endswith(".blend"):
                errors.append(f"Not a .blend file: {src}")
                continue
            if not os.path.exists(src):
                errors.append(f"Missing: {src}")
                continue
            dst = os.path.join(dst_folder, os.path.basename(src))
            shutil.copy2(src, dst)
            copied += 1
        except Exception as e:
            errors.append(f"{src}: {e}")
    return copied, errors


def _build_dashboard(
    root: ctk.CTk,
    cfg: dict,
    state: dict,
    active_event: threading.Event,
    stop_event: threading.Event,
    *,
    is_lifecycle_owner: bool,
):
    root.title(f"{APP_DISPLAY_NAME} v{AGENT_VERSION} - Dashboard")
    root.geometry("680x460")
    root.resizable(False, False)
    root.configure(fg_color=BG)

    # Window + taskbar icon
    _ico_path = os.path.join(os.path.dirname(__file__), "assets", "gradient_icon_256_transparent.ico")
    try:
        root.iconbitmap(_ico_path)
        root.after(50, lambda: root.iconbitmap(_ico_path))
    except Exception:
        pass

    workspace_root = cfg.get("workspace_root", "")
    blend_root     = cfg.get("blend_root", "")
    output_root    = cfg.get("output_root", "")

    # ---- Header ----
    header = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=0, height=64)
    header.pack(fill="x")
    header.pack_propagate(False)

    ctk.CTkLabel(
        header, text=APP_DISPLAY_NAME,
        font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT,
    ).pack(side="left", padx=20, pady=16)

    # Connection dot (top right of header)
    conn_dot = ctk.CTkLabel(
        header, text="●  Connected",
        font=ctk.CTkFont(size=12), text_color=SUCCESS,
    )
    conn_dot.pack(side="right", padx=20)

    # ---- Update banner (hidden by default) ----
    import webbrowser
    update_banner = ctk.CTkButton(
        root, text="",
        height=30, corner_radius=6,
        fg_color="#2a1f00", hover_color="#3a2a00",
        text_color=WARNING, font=ctk.CTkFont(size=12, weight="bold"),
        anchor="w",
        command=lambda: webbrowser.open("https://rendermanager.com/download"),
    )

    # ---- Status card ----
    status_card = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=10)
    status_card.pack(fill="x", padx=16, pady=(14, 0))

    status_var    = tk.StringVar(value="Starting...")
    active_var    = tk.StringVar(value="Unknown")
    agent_id_var  = tk.StringVar(value="(not registered yet)")
    last_error_var = tk.StringVar(value="None")

    def _stat_row(parent, label: str, var: tk.StringVar, color=TEXT):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(row, text=label, width=100, anchor="w",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(side="left")
        lbl = ctk.CTkLabel(row, textvariable=var, anchor="w",
                           font=ctk.CTkFont(family="Consolas", size=12), text_color=color)
        lbl.pack(side="left", fill="x", expand=True)
        return lbl

    status_lbl    = _stat_row(status_card, "Status",    status_var)
    _              = _stat_row(status_card, "Mode",      active_var)
    _              = _stat_row(status_card, "Agent ID",  agent_id_var,  MUTED)
    error_lbl      = _stat_row(status_card, "Last error", last_error_var, MUTED)

    # spacer at bottom of card
    ctk.CTkFrame(status_card, fg_color="transparent", height=12).pack()

    # ---- Paths card ----
    paths_card = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=10)
    paths_card.pack(fill="x", padx=16, pady=(10, 0))

    def _path_row(parent, label: str, path: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(row, text=label, width=100, anchor="w",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(side="left")
        ctk.CTkLabel(row, text=path or "(missing)", anchor="w",
                     font=ctk.CTkFont(family="Consolas", size=11), text_color=MUTED).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="Open", width=70, height=26,
            fg_color=BORDER, hover_color="#3a3a5a", text_color=TEXT,
            font=ctk.CTkFont(size=11), corner_radius=6,
            command=lambda p=path: _open_folder(p),
        ).pack(side="right")

    _path_row(paths_card, "Workspace", workspace_root)
    _path_row(paths_card, "BlendFiles", blend_root)
    _path_row(paths_card, "Renders",    output_root)
    ctk.CTkFrame(paths_card, fg_color="transparent", height=12).pack()

    # ---- Action buttons ----
    btn_row = ctk.CTkFrame(root, fg_color="transparent")
    btn_row.pack(fill="x", padx=16, pady=(14, 0))

    def set_paused():
        active_event.clear()

    def set_active():
        active_event.set()

    def stop_agent():
        if messagebox.askyesno("Stop agent", "Stop the agent now?"):
            stop_event.set()
            try:
                root.destroy()
            except Exception:
                pass

    def add_blend_files():
        if not blend_root:
            messagebox.showerror("Missing config", "blend_root is missing in config.")
            return
        paths = filedialog.askopenfilenames(
            title="Select .blend files to add",
            filetypes=[("Blender Files", "*.blend")],
        )
        if not paths:
            return
        copied, errors = _copy_blend_files(list(paths), blend_root)
        msg = f"Copied {copied} file(s) into:\n{blend_root}"
        if errors:
            msg += "\n\nSome files failed:\n" + "\n".join(errors[:8])
        messagebox.showinfo("Add .blend files", msg)

    ctk.CTkButton(
        btn_row, text="Pause", command=set_paused,
        width=90, height=34, fg_color=BORDER, hover_color="#3a3a5a",
        text_color=TEXT, font=ctk.CTkFont(size=12), corner_radius=7,
    ).pack(side="left")

    ctk.CTkButton(
        btn_row, text="Resume", command=set_active,
        width=90, height=34, fg_color=BORDER, hover_color="#3a3a5a",
        text_color=TEXT, font=ctk.CTkFont(size=12), corner_radius=7,
    ).pack(side="left", padx=(8, 0))

    ctk.CTkButton(
        btn_row, text="Add .blend...", command=add_blend_files,
        width=110, height=34, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        text_color="#fff", font=ctk.CTkFont(size=12, weight="bold"), corner_radius=7,
    ).pack(side="left", padx=(18, 0))

    if is_lifecycle_owner:
        ctk.CTkButton(
            btn_row, text="Stop Agent", command=stop_agent,
            width=100, height=34, fg_color="transparent", hover_color="#2a0f0f",
            text_color=ERROR, border_width=1, border_color="#5a2020",
            font=ctk.CTkFont(size=12), corner_radius=7,
        ).pack(side="right")
    else:
        def on_close_btn():
            try:
                root.destroy()
            except Exception:
                pass

        ctk.CTkButton(
            btn_row, text="Close", command=on_close_btn,
            width=90, height=34, fg_color=BORDER, hover_color="#3a3a5a",
            text_color=TEXT, font=ctk.CTkFont(size=12), corner_radius=7,
        ).pack(side="right")

    # ---- Footer ----
    footer_text = (
        "Pause stops job polling. Heartbeat continues so the server still shows you online."
        if is_lifecycle_owner
        else "The agent keeps running in the system tray when this window is closed."
    )
    ctk.CTkLabel(
        root, text=footer_text,
        font=ctk.CTkFont(size=11), text_color=MUTED,
        anchor="w", justify="left",
    ).pack(fill="x", padx=20, pady=(12, 0))

    # ---- Refresh loop ----
    def refresh():
        if stop_event.is_set():
            try:
                root.destroy()
            except Exception:
                pass
            return

        connected = state.get("connected", False)
        conn_dot.configure(
            text="●  Connected" if connected else "●  Disconnected",
            text_color=SUCCESS if connected else ERROR,
        )

        status = state.get("status", "-")
        status_var.set(status)
        if "Working" in status or "Saved frame" in status:
            status_lbl.configure(text_color=WARNING)
        elif connected:
            status_lbl.configure(text_color=SUCCESS)
        else:
            status_lbl.configure(text_color=ERROR)

        if state.get("update_available") and not update_banner.winfo_ismapped():
            ver = state.get("latest_version", "")
            update_banner.configure(text=f"  \u2b06 Update available (v{ver}) - Click to download")
            update_banner.pack(fill="x", padx=20, pady=(10, 0), before=status_card)

        active_var.set("Active (polling)" if active_event.is_set() else "Paused")
        agent_id_var.set(state.get("agent_id") or "(not registered yet)")
        err = state.get("last_error") or "None"
        last_error_var.set(err)
        error_lbl.configure(text_color=ERROR if err != "None" else MUTED)

        root.after(400, refresh)

    def on_close():
        if is_lifecycle_owner:
            stop_event.set()
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(200, refresh)


def _set_app_id():
    """Tell Windows this is its own app, not python.exe — fixes taskbar icon."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)
    except Exception:
        pass


def open_dashboard_window(
    cfg: dict,
    state: dict,
    active_event: threading.Event,
    stop_event: threading.Event,
):
    """Open the dashboard as a standalone window (tray mode)."""
    _set_app_id()
    root = ctk.CTk()
    _build_dashboard(root, cfg, state, active_event, stop_event, is_lifecycle_owner=False)
    root.mainloop()


def start_agent_ui(
    cfg: dict,
    state: dict,
    active_event: threading.Event,
    stop_event: threading.Event,
):
    """Fallback: dashboard owns the agent lifecycle (no system tray)."""
    _set_app_id()
    root = ctk.CTk()
    _build_dashboard(root, cfg, state, active_event, stop_event, is_lifecycle_owner=True)
    root.mainloop()

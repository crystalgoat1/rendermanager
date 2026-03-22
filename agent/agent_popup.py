"""Floating tray popup for the Render Manager Agent.

Left-click on the tray icon opens this popup above the taskbar.
Layout (top -> bottom):
  Header (dot + title + settings + close)
  ─────────────────────────────────────────
  Status   (single human-readable line + progress bar when rendering)
    └─ Pause / Cancel row  (only when rendering or paused)
  ─────────────────────────────────────────
  Actions  (Dashboard · Renders · + Add)
  ─────────────────────────────────────────
  Footer   (Quit)
"""

import os
import shutil
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk
from agent.brand import APP_DISPLAY_NAME

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Brand-aligned palette — see frontend/BRAND.md
ACCENT       = "#6366f1"   # primary
ACCENT_HOVER = "#4f46e5"
BG           = "#0B0B14"   # bg-base
SURFACE      = "#131321"   # bg-surface (cards, panels)
ELEVATED     = "#1A1A2E"   # bg-elevated (modals, dropdowns)
BORDER       = "#1e1e2e"   # ≈ white/10 on bg-base (Tkinter can't do opacity)
TEXT         = "#e2e8f0"   # slate-200
MUTED        = "#94a3b8"   # slate-400
SUCCESS      = "#10b981"   # emerald-500
ERROR        = "#ef4444"   # red-500
WARNING      = "#f59e0b"   # amber-500

# Height changes dynamically: IDLE when no job, ACTIVE when rendering/paused.
POPUP_W        = 320
POPUP_H_IDLE   = 200
POPUP_H_ACTIVE = 285
POPUP_H_UPDATE = 36    # extra height when update banner is visible


# ── Positioning ──────────────────────────────────────────────────────────────

def _popup_position(root, target_h: int) -> tuple[int, int]:
    """Return (x, y) for bottom-right corner above the taskbar.

    Problem: CTk sets the process as Per-Monitor DPI aware, so ctypes APIs
    return PHYSICAL pixels, but Tkinter's geometry() still uses LOGICAL pixels.
    Fix: compute scale = winfo_screenwidth / GetSystemMetrics(SM_CXSCREEN).
    """
    sw_tk = root.winfo_screenwidth()
    sh_tk = root.winfo_screenheight()

    scale = 1.0
    if hasattr(root, "_get_window_scaling"):
        scale = root._get_window_scaling()

    scaled_w = int(POPUP_W * scale)
    scaled_h = int(target_h * scale)

    # Safe default: bottom-right, assume ~48 px taskbar
    x = sw_tk - scaled_w - 12
    y = sh_tk - scaled_h - 48

    try:
        import ctypes
        from ctypes import wintypes

        sw_phys = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN
        sh_phys = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN

        if sw_phys > 0 and sh_phys > 0:
            sx = sw_tk / sw_phys
            sy = sh_tk / sh_phys

            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0   # SPI_GETWORKAREA
            )
            if rect.right > 0 and rect.bottom > 0:
                wa_right  = int(rect.right  * sx)
                wa_bottom = int(rect.bottom * sy)
                if 0 < wa_right <= sw_tk and 0 < wa_bottom <= sh_tk:
                    x = wa_right  - scaled_w - 12
                    y = wa_bottom - scaled_h - 12
    except Exception:
        pass

    return max(0, x), max(0, y)


# ── State helpers ─────────────────────────────────────────────────────────────

def _status_color(state: dict) -> str:
    if not state.get("connected", False):
        return ERROR
    if state.get("active_job_id") or state.get("paused_job_id"):
        return WARNING
    return SUCCESS


# ── Blend-file helpers ────────────────────────────────────────────────────────

def _copy_blend_files(src_paths: list[str], dst: str) -> tuple[int, list[str]]:
    os.makedirs(dst, exist_ok=True)
    copied, errors = 0, []
    for src in src_paths:
        try:
            if not src.lower().endswith(".blend"):
                errors.append(f"Not a .blend file: {os.path.basename(src)}")
                continue
            if not os.path.exists(src):
                errors.append(f"Not found: {os.path.basename(src)}")
                continue
            shutil.copy2(src, os.path.join(dst, os.path.basename(src)))
            copied += 1
        except Exception as e:
            errors.append(f"{os.path.basename(src)}: {e}")
    return copied, errors

# ── Rounded window corners ────────────────────────────────────────────────────

def _apply_rounded_corners(root) -> None:
    """Apply native rounded corners to a borderless window.

    Win11: Uses DwmSetWindowAttribute (smooth, anti-aliased OS-level corners).
    Win10 fallback: Uses SetWindowRgn (aliased but functional).
    """
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

        # Try Windows 11 native rounded corners first
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWM_CORNER_ROUND = 2
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWM_CORNER_ROUND)), 4,
        )
        if result == 0:
            return  # success — native corners applied
    except Exception:
        pass

    # Fallback: SetWindowRgn for Win10
    try:
        import ctypes, ctypes.wintypes
        hwnd = root.winfo_id()
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 0 and h > 0:
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 16, 16)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:
        pass


# ── Persistent popup state ────────────────────────────────────────────────────
# The Tk root + mainloop are kept alive across open/close cycles so that
# re-opening the popup is instant (no interpreter re-init).

_popup_root = None  # type: ctk.CTk | None
_popup_visible = threading.Event()   # set = window is on screen


def show_existing_popup() -> bool:
    """If the popup thread is alive, bring the window back.  Returns True if successful."""
    root = _popup_root
    if root is None:
        return False
    try:
        root.after(0, root._show_popup)   # post to the Tk mainloop thread
        return True
    except Exception:
        return False


def is_popup_alive() -> bool:
    """True when the popup mainloop is running (even if the window is hidden)."""
    return _popup_root is not None


# ── Main popup ───────────────────────────────────────────────────────────────

def open_tray_popup(
    cfg: dict,
    state: dict,
    active_event: threading.Event,
    stop_event: threading.Event,
    on_quit,
    on_closed=None,
):
    """Create and show the floating dashboard popup. Blocks until closed/quit."""
    global _popup_root

    blend_root  = cfg.get("blend_root",  "")
    output_root = cfg.get("output_root", "")

    root = ctk.CTk()
    _popup_root = root
    root.withdraw()                 # hide before positioning to avoid flash
    root.overrideredirect(True)     # no title bar / window chrome
    root.attributes("-topmost", True)
    try:
        root.wm_attributes("-toolwindow", True)  # don't show in taskbar
    except Exception:
        pass

    root.configure(fg_color=BG)

    _initial_has_job = bool(state.get("active_job_id") or state.get("paused_job_id"))
    _initial_h = POPUP_H_ACTIVE if _initial_has_job else POPUP_H_IDLE
    _x, _y = _popup_position(root, _initial_h)
    root.geometry(f"{POPUP_W}x{_initial_h}+{_x}+{_y}")

    # ── Border + card wrappers ────────────────────────────────────────────────
    # We use radii that exactly match Windows 11 DWM native corner rounding (8px)
    # This prevents the OS boundary clipping from misaligning with the CTK drawing.
    outer = ctk.CTkFrame(root, fg_color=BORDER, corner_radius=8)
    outer.pack(fill="both", expand=True, padx=1, pady=1)

    card = ctk.CTkFrame(outer, fg_color=BG, corner_radius=7)
    card.pack(fill="both", expand=True, padx=1, pady=1)

    # ── Header ───────────────────────────────────────────────────────────────
    hdr = ctk.CTkFrame(card, fg_color="transparent")
    hdr.pack(fill="x", padx=14, pady=(12, 0))

    dot = ctk.CTkLabel(
        hdr, text="\u25cf", font=ctk.CTkFont(size=13),
        text_color=_status_color(state),
    )
    dot.pack(side="left")

    ctk.CTkLabel(
        hdr, text=f"  {APP_DISPLAY_NAME}",
        font=ctk.CTkFont(family="Inter", size=14, weight="bold"), text_color=TEXT,
    ).pack(side="left")

    def _hide_popup():
        _popup_visible.clear()
        root.withdraw()
        if on_closed:
            on_closed()

    ctk.CTkButton(
        hdr, text="\u2715", width=26, height=26,
        fg_color="transparent", hover_color="#2a2a4a",
        text_color=MUTED, font=ctk.CTkFont(size=11),
        corner_radius=6, command=_hide_popup,
    ).pack(side="right")

    def _open_setup():
        import subprocess, sys
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "--setup"])
        else:
            pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            subprocess.Popen([sys.executable, "-m", "agent.agent_main", "--setup"], cwd=pkg_dir)
        root.destroy()
        on_quit()

    ctk.CTkButton(
        hdr, text="\u2699", width=26, height=26,
        fg_color="transparent", hover_color="#2a2a4a",
        text_color=MUTED, font=ctk.CTkFont(size=14),
        corner_radius=6, command=_open_setup,
    ).pack(side="right", padx=(0, 4))

    # ── Separator ─────────────────────────────────────────────────────────────
    ctk.CTkFrame(card, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(10, 0))

    # ── Update banner (hidden by default) ─────────────────────────────────────
    update_banner = ctk.CTkButton(
        card, text="",
        height=28, corner_radius=6,
        fg_color="#2a1f00", hover_color="#3a2a00",
        text_color=WARNING, font=ctk.CTkFont(size=11, weight="bold"),
        anchor="center",
        command=lambda: webbrowser.open("https://rendermanager.com/download"),
    )
    # Not packed yet — shown by refresh() when update_available is set.

    # ── Status section ────────────────────────────────────────────────────────
    status_frame = ctk.CTkFrame(card, fg_color=SURFACE, corner_radius=10)
    status_frame.pack(fill="x", padx=10, pady=(10, 8))

    status_text_var = tk.StringVar(value="Ready")
    status_label = ctk.CTkLabel(
        status_frame, textvariable=status_text_var,
        font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        anchor="w",
    )
    status_label.pack(fill="x", padx=12, pady=(10, 0))

    # Frame counter (hidden when idle)
    frame_text_var = tk.StringVar(value="")
    frame_label = ctk.CTkLabel(
        status_frame, textvariable=frame_text_var,
        font=ctk.CTkFont(size=11), text_color=MUTED,
        anchor="w",
    )
    # Not packed yet — shown only when rendering

    # Progress bar (hidden when idle)
    progress_bar = ctk.CTkProgressBar(
        status_frame, height=6, corner_radius=3,
        fg_color=BORDER, progress_color=ACCENT,
    )
    # Not packed yet — shown only when rendering

    # ── Pause / Cancel — inside status_frame, shown only when rendering/paused
    ctrl_row = ctk.CTkFrame(status_frame, fg_color="transparent")
    # Not packed yet — _set_ctrl_visible() handles this.

    pause_var = tk.StringVar(value="\u23f8 Pause")

    def _do_pause_resume():
        act_id   = state.get("active_job_id")
        p_id     = state.get("paused_job_id")
        agent_id = state.get("agent_id")
        session  = state.get("session")
        if not agent_id or not session:
            return

        if act_id:
            # Immediate visual feedback — guard prevents refresh from overwriting
            _feedback_guard["action"] = "pausing"
            _feedback_guard["until"] = _time.time() + 10.0
            status_text_var.set("Pausing...")
            status_label.configure(text_color=MUTED)
            pause_btn.configure(state="disabled")
            # Primary signal: local event — render loop sees this within 0.25s.
            pause_ev = state.get("pause_event")
            if pause_ev:
                pause_ev.set()
            # Secondary: notify server in background (for DB consistency).
            def _p():
                try:
                    from .agent_backend import request_job_pause
                    request_job_pause(session, act_id, agent_id)
                except Exception:
                    pass
            threading.Thread(target=_p, daemon=True).start()
        elif p_id:
            # Immediate visual feedback — guard prevents refresh from overwriting
            _feedback_guard["action"] = "resuming"
            _feedback_guard["until"] = _time.time() + 10.0
            status_text_var.set("Resuming...")
            status_label.configure(text_color=WARNING)
            pause_btn.configure(state="disabled")
            # Instant: tell job loop to poll immediately
            state["has_queued_jobs"] = True
            def _r():
                try:
                    from .agent_backend import request_job_resume
                    request_job_resume(session, p_id, agent_id)
                    # Don't clear paused_job_id here — the job_loop clears it
                    # when it actually picks up the resumed job.  Clearing it
                    # early removes the guard that prevents the agent from
                    # picking up a different queued job.
                except Exception:
                    pass
            threading.Thread(target=_r, daemon=True).start()

    def _do_cancel():
        act_id   = state.get("active_job_id")
        p_id     = state.get("paused_job_id")
        agent_id = state.get("agent_id")
        session  = state.get("session")
        if not agent_id or not session:
            return
        job_id = act_id or p_id
        if not job_id:
            return

        # Primary signal: local event — render loop sees this within 0.25s.
        cancel_ev = state.get("cancel_event")
        if cancel_ev:
            cancel_ev.set()

        # Immediate visual feedback — guard prevents refresh from overwriting
        _feedback_guard["action"] = "cancelling"
        _feedback_guard["until"] = _time.time() + 10.0
        status_text_var.set("Cancelling...")
        status_label.configure(text_color=MUTED)
        pause_btn.configure(state="disabled")

        # Secondary: notify server in background (for DB consistency).
        def _c():
            try:
                from .agent_backend import request_job_cancel
                request_job_cancel(session, job_id, agent_id)
            except Exception:
                pass
        threading.Thread(target=_c, daemon=True).start()

    pause_btn = ctk.CTkButton(
        ctrl_row, textvariable=pause_var,
        height=28, corner_radius=6,
        fg_color="transparent", hover_color=SURFACE,
        border_width=1, border_color=BORDER, text_color=MUTED,
        font=ctk.CTkFont(size=11, weight="bold"),
        command=_do_pause_resume,
    )
    pause_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

    ctk.CTkButton(
        ctrl_row, text="\u2715 Cancel",
        height=28, corner_radius=6,
        fg_color="transparent", hover_color="#2a0f0f",
        border_width=1, border_color="#4a2020", text_color=ERROR,
        font=ctk.CTkFont(size=11, weight="bold"),
        command=_do_cancel,
    ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ── Separator ─────────────────────────────────────────────────────────────
    ctk.CTkFrame(card, fg_color=BORDER, height=1).pack(fill="x", padx=10)

    # ── Actions row ──────────────────────────────────────────────────────────
    actions_frame = ctk.CTkFrame(card, fg_color="transparent")
    actions_frame.pack(fill="x", padx=10, pady=(8, 0))

    def _open_web_app():
        import webbrowser
        base = cfg.get("backend_url", "http://localhost:8000")
        webbrowser.open(f"{base}/dashboard")

    def _open_output_folder():
        if output_root:
            try:
                os.makedirs(output_root, exist_ok=True)
                os.startfile(os.path.abspath(output_root))
            except Exception:
                pass

    def _add_blend_files():
        if not blend_root:
            messagebox.showerror(
                "Missing config", "blend_root is not configured.", parent=root
            )
            return
        root.attributes("-topmost", False)
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Select .blend files to add",
            filetypes=[("Blender Files", "*.blend")],
        )
        root.attributes("-topmost", True)
        root.lift()
        if not paths:
            return
        copied, errors = _copy_blend_files(list(paths), blend_root)
        msg = f"Copied {copied} file(s) to workspace."
        if errors:
            msg += "\n\nFailed:\n" + "\n".join(errors[:5])
        messagebox.showinfo("Add .blend files", msg, parent=root)

    ctk.CTkButton(
        actions_frame, text="Dashboard",
        height=30, corner_radius=7,
        fg_color="transparent", hover_color="#1e1e3a",
        border_width=1, border_color=BORDER,
        font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT, anchor="center",
        command=_open_web_app,
    ).pack(fill="x", side="left", expand=True, padx=(0, 3))

    ctk.CTkButton(
        actions_frame, text="Renders",
        height=30, corner_radius=7,
        fg_color=ACCENT, hover_color=ACCENT_HOVER,
        font=ctk.CTkFont(size=11, weight="bold"), text_color="#fff", anchor="center",
        command=_open_output_folder,
    ).pack(fill="x", side="left", expand=True, padx=(3, 0))

    # ── Add BlendFiles row ─────────────────────────────────────────────────────
    add_frame = ctk.CTkFrame(card, fg_color="transparent")
    add_frame.pack(fill="x", padx=10, pady=(6, 0))

    ctk.CTkButton(
        add_frame, text="+ Add Blend Files",
        height=30, corner_radius=7,
        fg_color="transparent", hover_color="#1e1e3a",
        border_width=1, border_color=BORDER,
        font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED, anchor="center",
        command=_add_blend_files,
    ).pack(fill="x")

    # ── Footer separator ──────────────────────────────────────────────────────
    ctk.CTkFrame(card, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(8, 0))

    # ── Footer ────────────────────────────────────────────────────────────────
    footer = ctk.CTkFrame(card, fg_color="transparent")
    footer.pack(fill="x", padx=10, pady=(8, 12))

    def _real_quit():
        global _popup_root
        _popup_visible.clear()
        _popup_root = None
        root.destroy()
        on_quit()

    ctk.CTkButton(
        footer, text="Quit",
        height=28, corner_radius=6,
        fg_color="transparent", hover_color="#2a0f0f",
        text_color=ERROR, font=ctk.CTkFont(size=11),
        command=_real_quit,
    ).pack(side="right")

    # ── Refresh loop ──────────────────────────────────────────────────────────
    _ctrl_shown = [None]   # None = uninitialised; True/False after first refresh
    _update_shown = [False]
    # When an action button is clicked, we show instant feedback and suppress
    # the refresh loop from overwriting it until the state actually transitions
    # or the guard expires (whichever comes first).
    import time as _time
    _feedback_guard = {"action": None, "until": 0.0}  # action: "pausing"|"resuming"|"cancelling"

    def _set_ctrl_visible(show: bool):
        """Show/hide progress + controls and resize the popup window to fit."""
        if _ctrl_shown[0] == show:
            return
        _ctrl_shown[0] = show
        extra = POPUP_H_UPDATE if _update_shown[0] else 0
        target_h = (POPUP_H_ACTIVE if show else POPUP_H_IDLE) + extra
        if show:
            frame_label.pack(fill="x", padx=12, pady=(2, 0))
            progress_bar.pack(fill="x", padx=12, pady=(6, 0))
            ctrl_row.pack(fill="x", padx=10, pady=(8, 10))
        else:
            frame_label.pack_forget()
            progress_bar.pack_forget()
            ctrl_row.pack_forget()
        extra = POPUP_H_UPDATE if _update_shown[0] else 0
        target_h = (POPUP_H_ACTIVE if show else POPUP_H_IDLE) + extra
        _x, _y = _popup_position(root, target_h)
        root.geometry(f"{POPUP_W}x{target_h}+{_x}+{_y}")
        root.after(60, lambda: _apply_rounded_corners(root))

    def _parse_progress(status_str: str) -> float:
        """Extract progress percentage from status string like 'Saved frame (47/250)'."""
        import re
        m = re.search(r'\((\d+)/(\d+)\)', status_str)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                return current / total
        return 0.0

    def refresh() -> None:
        if stop_event.is_set():
            global _popup_root
            _popup_root = None
            _popup_visible.clear()
            try:
                root.destroy()
            except Exception:
                pass
            return

        # Still refresh state even when hidden so it's up-to-date on show
        if not _popup_visible.is_set():
            root.after(500, refresh)
            return

        color = _status_color(state)
        dot.configure(text_color=color)

        # Show update banner when available
        if state.get("update_available") and not _update_shown[0]:
            ver = state.get("latest_version", "")
            update_banner.configure(text=f"\u2b06 Update available (v{ver}) - Click to download")
            update_banner.pack(fill="x", padx=10, pady=(8, 0), before=status_frame)
            _update_shown[0] = True
            # Force resize
            _ctrl_shown[0] = None

        act_id = state.get("active_job_id")
        p_id   = state.get("paused_job_id")
        filename = state.get("active_filename", "")

        # ── Feedback guard logic ───────────────────────────────────────────
        # When the user clicks pause/resume/cancel, we show instant feedback
        # and suppress the refresh loop from overwriting it.  The guard clears
        # when the underlying state actually transitions (proving the action
        # took effect) or when the timeout expires (safety net).
        guard_action = _feedback_guard["action"]
        guard_active = False
        if guard_action and _time.time() < _feedback_guard["until"]:
            # Check if the state has transitioned — if so, clear the guard
            if guard_action == "pausing" and not act_id:
                # Transitioned: no longer rendering (paused or cancelled)
                _feedback_guard["action"] = None
            elif guard_action == "resuming" and act_id:
                # Transitioned: resumed and now rendering
                _feedback_guard["action"] = None
            elif guard_action == "cancelling" and not act_id and not p_id:
                # Transitioned: job is gone
                _feedback_guard["action"] = None
            else:
                guard_active = True
        elif guard_action:
            # Timeout expired — clear guard so UI returns to normal
            _feedback_guard["action"] = None

        if not state.get("connected", False):
            # Offline always overrides everything
            _feedback_guard["action"] = None
            status_text_var.set("Offline \u2014 Reconnecting...")
            status_label.configure(text_color=ERROR)
            pause_btn.configure(state="normal")
            _set_ctrl_visible(False)
        elif guard_active:
            # Guard is active — keep the feedback text, but still update
            # progress bar and frame counter so the UI doesn't look frozen
            if act_id:
                raw_status = state.get("status", "")
                progress = _parse_progress(raw_status)
                progress_bar.set(progress)
                import re
                m = re.search(r'\((\d+)/(\d+)\)', raw_status)
                if m:
                    frame_text_var.set(f"Frame {m.group(1)} of {m.group(2)}")
            _set_ctrl_visible(True)
        elif act_id:
            status_text_var.set(f"Rendering {filename}" if filename else "Rendering...")
            status_label.configure(text_color=WARNING)
            # Update frame counter and progress
            raw_status = state.get("status", "")
            progress = _parse_progress(raw_status)
            progress_bar.set(progress)
            # Extract frame info
            import re
            m = re.search(r'\((\d+)/(\d+)\)', raw_status)
            if m:
                frame_text_var.set(f"Frame {m.group(1)} of {m.group(2)}")
            else:
                frame_text_var.set(raw_status)
            pause_var.set("\u23f8 Pause")
            pause_btn.configure(
                state="normal",
                fg_color="transparent", hover_color=SURFACE,
                text_color=MUTED, border_width=1, border_color=BORDER,
            )
            _set_ctrl_visible(True)
        elif p_id:
            display_name = filename or f"job {p_id[:8]}"
            status_text_var.set(f"Paused: {display_name}")
            status_label.configure(text_color=MUTED)
            frame_text_var.set("")
            pause_var.set("\u25b6 Resume")
            pause_btn.configure(
                state="normal",
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color="#ffffff", border_width=0, border_color=BORDER,
            )
            _set_ctrl_visible(True)
        else:
            status_text_var.set("Ready")
            status_label.configure(text_color=SUCCESS)
            pause_btn.configure(state="normal")
            _set_ctrl_visible(False)

        root.after(500, refresh)

    def _show_popup_impl():
        """Reposition, deiconify, and bring to front."""
        _ctrl_shown[0] = None  # force layout recalculation
        # Start at the correct height based on current state to avoid
        # a visible resize flash when a job is active.
        has_job = bool(state.get("active_job_id") or state.get("paused_job_id"))
        extra = POPUP_H_UPDATE if _update_shown[0] else 0
        target_h = (POPUP_H_ACTIVE if has_job else POPUP_H_IDLE) + extra
        _x, _y = _popup_position(root, target_h)
        root.geometry(f"{POPUP_W}x{target_h}+{_x}+{_y}")
        root.deiconify()
        root.lift()
        root.focus_force()
        root.after(60, lambda: _apply_rounded_corners(root))
        _popup_visible.set()

    # Attach as a method so show_existing_popup() can call it via root.after()
    root._show_popup = _show_popup_impl

    root.bind("<Escape>", lambda e: _hide_popup())

    # Pre-show controls if a job is already active so there's no expand flash
    if _initial_has_job:
        _set_ctrl_visible(True)

    root.after(50, root.deiconify)
    root.after(100, lambda: (root.lift(), root.focus_force()))
    root.after(150, lambda: _apply_rounded_corners(root))
    root.after(200, refresh)
    _popup_visible.set()

    root.mainloop()

    # mainloop exited — app is shutting down
    _popup_root = None
    _popup_visible.clear()

"""System tray icon for the Render Manager Agent.

Uses pystray to provide a persistent tray icon that serves as the
application lifecycle owner. The agent keeps running even when the
dashboard window is closed.
"""

import os
import threading
import webbrowser

from PIL import Image
import pystray

from agent.brand import APP_NAME, APP_DISPLAY_NAME
from .agent_config import get_bundle_dir

_ASSETS_DIR = os.path.join(get_bundle_dir(), "agent", "assets")

_ICON_IMAGES: dict[str, Image.Image] = {}


def _load_icon(name: str) -> Image.Image:
    """Load a tray icon PNG from the assets folder, with a fallback colored square."""
    if name not in _ICON_IMAGES:
        path = os.path.join(_ASSETS_DIR, name)
        try:
            _ICON_IMAGES[name] = Image.open(path).convert("RGBA")
        except Exception:
            # Fallback: tiny colored square so the tray still works
            _ICON_IMAGES[name] = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    return _ICON_IMAGES[name]


# Map agent states → asset filenames
_STATE_ICONS = {
    "idle":         "status_icon_green.png",
    "rendering":    "status_icon_yellow.png",
    "disconnected": "status_icon_red.png",
}


class TrayApp:
    """System tray application for the Render Manager Agent.

    Parameters
    ----------
    cfg : dict
        Agent configuration (workspace_root, output_root, config_path, etc.)
    state : dict
        Shared mutable dict with keys: status, connected, agent_id, last_error.
        Updated by worker threads, read by the tray for display.
    active_event : threading.Event
        Controls job polling. set() = polling, clear() = paused.
    stop_event : threading.Event
        Shutdown signal. Setting this stops all threads and the tray.
    """

    def __init__(
        self,
        cfg: dict,
        state: dict,
        active_event: threading.Event,
        stop_event: threading.Event,
    ):
        self.cfg = cfg
        self.state = state
        self.active_event = active_event
        self.stop_event = stop_event

        self._icon: pystray.Icon | None = None
        self._current_color = ""
        self._dashboard_thread: threading.Thread | None = None
        self._update_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the tray icon and its update loop in background threads."""
        self._icon = pystray.Icon(
            name=APP_NAME,
            icon=_load_icon(_STATE_ICONS["idle"]),
            title=f"{APP_DISPLAY_NAME} - Starting...",
            menu=self._build_menu(),
            on_activate=self._on_left_click,   # left-click opens popup
        )

        # pystray.Icon.run() blocks, so run it in a daemon thread.
        self._tray_thread = threading.Thread(
            target=self._icon.run, daemon=True, name="tray-icon",
        )
        self._tray_thread.start()

        # Periodic icon/tooltip refresh
        self._update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="tray-update",
        )
        self._update_thread.start()

    def stop(self):
        """Shut down the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                text=lambda item: self._tooltip_text(),
                action=self._on_left_click,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                text=lambda item: f"Download Update (v{self.state.get('latest_version', '')})",
                action=lambda: webbrowser.open("https://rendermanager.com/download"),
                visible=lambda item: bool(self.state.get("update_available")),
            ),
            pystray.MenuItem(text="Quit", action=self._quit),
        )

    # ------------------------------------------------------------------
    # Icon update loop
    # ------------------------------------------------------------------

    def _tooltip_text(self) -> str:
        connected = "Connected" if self.state.get("connected") else "Disconnected"
        status = self.state.get("status", "")
        text = f"{connected} - {status}"
        if self.state.get("update_available"):
            text += f" | Update available (v{self.state.get('latest_version', '')})"
        return text

    def _resolve_state(self) -> str:
        if not self.state.get("connected", False):
            return "disconnected"
        if self.state.get("active_job_id") or self.state.get("paused_job_id"):
            return "rendering"
        return "idle"

    def _update_loop(self):
        """Refresh the tray icon and tooltip every second."""
        while not self.stop_event.is_set():
            try:
                new_state = self._resolve_state()
                if new_state != self._current_color:
                    self._current_color = new_state
                    if self._icon:
                        self._icon.icon = _load_icon(_STATE_ICONS[new_state])
                if self._icon:
                    self._icon.title = f"{APP_DISPLAY_NAME} - {self._tooltip_text()}"
            except Exception:
                pass
            self.stop_event.wait(1.0)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _on_left_click(self, *_):
        """Open the floating popup panel above the tray icon."""
        if self._dashboard_thread and self._dashboard_thread.is_alive():
            return  # popup already open
        self._dashboard_thread = threading.Thread(
            target=self._run_popup, daemon=True, name="popup",
        )
        self._dashboard_thread.start()

    def _run_popup(self):
        try:
            from .agent_popup import open_tray_popup
            open_tray_popup(
                cfg=self.cfg,
                state=self.state,
                active_event=self.active_event,
                stop_event=self.stop_event,
                on_quit=self._quit,
                on_closed=self._on_popup_closed,
            )
        except Exception as e:
            print(f"[tray] Popup failed: {e}")
        finally:
            self._dashboard_thread = None

    def _on_popup_closed(self) -> None:
        """Called when the popup window closes — resets the thread reference."""
        self._dashboard_thread = None

    def _toggle_paused(self):
        if self.active_event.is_set():
            self.active_event.clear()
        else:
            self.active_event.set()

    def _open_dashboard(self):
        """Open the Tkinter dashboard in a separate thread."""
        if self._dashboard_thread and self._dashboard_thread.is_alive():
            # Dashboard already open — don't open a second one
            return
        self._dashboard_thread = threading.Thread(
            target=self._run_dashboard, daemon=True, name="dashboard",
        )
        self._dashboard_thread.start()

    def _run_dashboard(self):
        try:
            from .agent_ui import open_dashboard_window
            open_dashboard_window(
                self.cfg, self.state, self.active_event, self.stop_event,
            )
        except Exception as e:
            print(f"[tray] Dashboard failed: {e}")

    def _open_folder(self, path: str):
        if not path:
            return
        path = os.path.abspath(path)
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except Exception:
            pass

    def _quit(self):
        self.stop_event.set()
        self.stop()

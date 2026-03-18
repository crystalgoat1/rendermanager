"""Windows toast notifications for the Render Manager Agent.

Uses plyer for cross-platform notification support.
Falls back silently if plyer is not installed.
"""

from agent.brand import APP_DISPLAY_NAME

_APP_NAME = APP_DISPLAY_NAME


def _notify(title: str, message: str):
    """Show a Windows toast notification. Fails silently."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name=_APP_NAME,
            timeout=8,
        )
    except Exception:
        # plyer not installed or notification failed — not critical
        pass


def notify_render_complete(filename: str):
    _notify(
        "Render Complete",
        f"{filename} finished successfully.",
    )


def notify_render_failed(filename: str, reason: str = ""):
    short_reason = (reason[:80] + "\u2026") if len(reason) > 80 else reason
    _notify(
        "Render Failed",
        f"{filename} failed{': ' + short_reason if short_reason else '.'}",
    )


def notify_disconnected():
    _notify(
        "Server Disconnected",
        "Lost connection to the render server. Will keep retrying.",
    )

"""Windows auto-start integration for the Render Manager Agent.

Uses Task Scheduler to register a user-level task that starts the agent
on login. Does not require administrator privileges.
"""

import os
import subprocess
import sys

from agent.brand import APP_TASK_NAME

TASK_NAME = APP_TASK_NAME


def _get_exe_path() -> str:
    """Return the path to the agent executable.

    Works for both packaged (PyInstaller) and development (python -m) modes.
    """
    if getattr(sys, "frozen", False):
        # Running as a packaged exe (PyInstaller)
        return sys.executable
    else:
        # Running as a Python script — use the current interpreter
        return sys.executable


def _get_exe_args() -> list[str]:
    """Return the command-line arguments to start the agent."""
    if getattr(sys, "frozen", False):
        # Packaged exe — flag to suppress startup popup
        return ["--autostart"]
    else:
        # Development mode — need to invoke the module
        return ["-m", "agent.agent_main", "--run", "--autostart"]


def is_autostart_enabled() -> bool:
    """Check if the auto-start task is registered in Task Scheduler."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def enable_autostart() -> bool:
    """Register the agent to start automatically on Windows login.

    Creates a user-level Task Scheduler task (no admin required).
    Returns True on success.
    """
    exe_path = _get_exe_path()
    exe_args = _get_exe_args()

    # Build the command string for Task Scheduler
    if exe_args:
        command = f'"{exe_path}" {" ".join(exe_args)}'
    else:
        command = f'"{exe_path}"'

    try:
        # Remove existing task first (ignore errors if it doesn't exist)
        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        # Create the task: run on logon, user-level (LIMITED), no admin
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", TASK_NAME,
                "/TR", command,
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
                "/F",
            ],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            print(f"[autostart] Failed to create task: {result.stderr}")
            return False

        print(f"[autostart] Task '{TASK_NAME}' registered successfully.")
        return True

    except Exception as e:
        print(f"[autostart] Error: {e}")
        return False


def disable_autostart() -> bool:
    """Remove the auto-start task from Task Scheduler.

    Returns True on success or if the task didn't exist.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode == 0:
            print(f"[autostart] Task '{TASK_NAME}' removed.")
            return True

        # Task didn't exist — that's fine
        if "cannot find" in result.stderr.lower() or "not found" in result.stderr.lower():
            return True

        print(f"[autostart] Failed to remove task: {result.stderr}")
        return False

    except Exception as e:
        print(f"[autostart] Error: {e}")
        return False

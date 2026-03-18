# blender_addon/__init__.py
#
# Remote Render — submit render jobs directly from Blender.
# Requires the render agent to be running on the same machine.

from __future__ import annotations

bl_info = {
    "name": "Render Manager",
    "author": "Antigravity",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Render Manager",
    "description": "Submit render jobs to Render Manager",
    "category": "Render",
}

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

# Module-level config cache — read by progress.py and operators.py
_cached_config: dict | None = None


class RemoteRenderProperties(bpy.types.PropertyGroup):
    """Scene-level properties that drive the sidebar panel."""

    agent_running: BoolProperty(name="Agent Running", default=False)
    error_message: StringProperty(name="Error Message", default="")

    # Active job state
    active_job_id: StringProperty(name="Active Job ID", default="")
    job_status: StringProperty(name="Job Status", default="")
    job_progress: IntProperty(name="Job Progress", min=0, max=100, default=0)
    job_current_frame: IntProperty(name="Current Frame", default=0)
    job_total_frames: IntProperty(name="Total Frames", default=0)
    job_message: StringProperty(name="Job Message", default="")
    job_paused: BoolProperty(name="Job Paused", default=False)

    is_submitting: BoolProperty(name="Is Submitting", default=False)


# Deferred imports to avoid circular references at module level
_classes: list = []


def _get_classes():
    global _classes
    if _classes:
        return _classes

    from . import operators, panels

    _classes = [
        RemoteRenderProperties,
        operators.REMOTERENDER_OT_copy_and_submit,
        operators.REMOTERENDER_OT_copy_only,
        operators.REMOTERENDER_OT_confirm_overwrite,
        operators.REMOTERENDER_OT_pause_job,
        operators.REMOTERENDER_OT_resume_job,
        operators.REMOTERENDER_OT_cancel_job,
        operators.REMOTERENDER_OT_confirm_cancel_job,
        operators.REMOTERENDER_OT_open_dashboard,
        operators.REMOTERENDER_OT_refresh_connection,
        operators.REMOTERENDER_OT_download_app,
        operators.REMOTERENDER_OT_open_website,
        panels.REMOTERENDER_PT_main_panel,
    ]
    return _classes


def _load_config():
    """Load the agent config from disk and cache it."""
    global _cached_config
    from . import config

    path = config.find_config_path()
    if path:
        _cached_config = config.load_config(path)
    else:
        _cached_config = None


def _refresh_agent_status():
    """Update the agent-running flag on all scenes."""
    global _cached_config
    from . import config

    running = False
    if _cached_config:
        running = config.is_agent_running(_cached_config.get("workspace_root", ""))

    for scene in bpy.data.scenes:
        if hasattr(scene, "remote_render"):
            scene.remote_render.agent_running = running


def register():
    for cls in _get_classes():
        bpy.utils.register_class(cls)

    bpy.types.Scene.remote_render = bpy.props.PointerProperty(type=RemoteRenderProperties)

    # Add "Remote Render" to the top-bar Render menu
    from . import panels
    panels.register_menu()

    # Defer config loading — bpy.data is restricted during register()
    def _deferred_init():
        _load_config()
        _refresh_agent_status()
        return None  # don't repeat

    bpy.app.timers.register(_deferred_init, first_interval=0.1)


def unregister():
    global _classes

    # Stop any active polling
    from . import progress, panels

    progress.stop_polling()
    panels.unregister_menu()

    del bpy.types.Scene.remote_render

    for cls in reversed(_get_classes()):
        bpy.utils.unregister_class(cls)

    _classes = []  # reset so re-enable doesn't hit stale registrations


if __name__ == "__main__":
    register()

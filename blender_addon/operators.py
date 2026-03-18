# blender_addon/operators.py
#
# Operators for the Remote Render addon.

from __future__ import annotations

import os
import shutil
import threading
import webbrowser

import bpy

from . import api, progress


def _get_config():
    from . import _cached_config
    return _cached_config


# ── Copy & Submit ────────────────────────────────────────────────────────────


class REMOTERENDER_OT_copy_and_submit(bpy.types.Operator):
    """Copy the current .blend file to the workspace and submit a render job"""

    bl_idname = "remote_render.copy_and_submit"
    bl_label = "Render in Background"

    def execute(self, context):
        cfg = _get_config()
        if not cfg:
            self.report({"ERROR"}, "App not configured. Run app setup first.")
            return {"CANCELLED"}

        props = context.scene.remote_render
        if not props.agent_running:
            self.report({"ERROR"}, "App is not running. Start the app first.")
            return {"CANCELLED"}

        # Must have a saved file
        filepath = bpy.data.filepath
        if not filepath:
            self.report({"ERROR"}, "Save your .blend file first.")
            return {"CANCELLED"}

        # Auto-save if dirty
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()

        blend_root = cfg.get("blend_root", "")
        filename = os.path.basename(filepath)
        dest_path = os.path.join(blend_root, filename)

        # Check if file already exists in BlendFiles
        if os.path.exists(dest_path):
            # Store the paths for the confirmation dialog
            context.scene.remote_render.error_message = ""
            bpy.ops.remote_render.confirm_overwrite("INVOKE_DEFAULT", source=filepath, dest=dest_path)
            return {"FINISHED"}

        # No conflict — proceed directly
        _do_copy_and_submit(self, context, filepath, dest_path)
        return {"FINISHED"}


def _do_copy_only(op, context, source: str, dest: str):
    """Copy the file to BlendFiles without submitting a job."""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(source, dest)
        op.report({"INFO"}, f"Copied to {dest}")
    except Exception as e:
        op.report({"ERROR"}, f"Copy failed: {e}")


def _do_copy_and_submit(op, context, source: str, dest: str):
    """Copy the file and submit the job in a background thread."""
    cfg = _get_config()
    if not cfg:
        op.report({"ERROR"}, "App not configured.")
        return

    agent_id = cfg.get("agent_id")
    if not agent_id:
        op.report({"ERROR"}, "No computer ID in config. Run the app at least once first so it can register.")
        return

    props = context.scene.remote_render
    props.is_submitting = True
    props.error_message = ""
    props.job_status = ""
    props.active_job_id = ""

    scene = context.scene
    frame_start = scene.frame_start
    frame_end = scene.frame_end
    filename = os.path.basename(dest)

    def _background():
        try:
            # Check if there are already active/queued jobs
            try:
                check = api.get_active_jobs(
                    cfg["backend_url"], agent_id, cfg["agent_token"]
                )
                if check.get("has_active"):
                    def _busy():
                        props.is_submitting = False
                        props.error_message = "There are already jobs in the queue. Cancel or wait for them to finish first."
                        _redraw_panels()
                        return None
                    bpy.app.timers.register(_busy, first_interval=0.0)
                    return
            except Exception:
                pass  # If the check fails, proceed anyway
            # 1. Copy file
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(source, dest)

            # 2. Fire-and-forget rescan
            api.trigger_rescan(
                cfg["backend_url"], agent_id, cfg["agent_token"]
            )

            # 3. Submit job
            result = api.submit_job(
                cfg["backend_url"],
                agent_id,
                cfg["agent_token"],
                blend_relpath=filename,
                frame_start=frame_start,
                frame_end=frame_end,
            )

            job = result.get("job", {})
            job_id = job.get("job_id", "")

            # Update UI from main thread via timer
            def _on_done():
                props.is_submitting = False
                if job_id:
                    props.active_job_id = job_id
                    props.job_status = "queued"
                    props.job_progress = 0
                    props.job_current_frame = 0
                    props.job_total_frames = frame_end - frame_start + 1
                    props.job_message = ""
                    props.job_paused = False
                    progress.start_polling(job_id)
                else:
                    props.error_message = "Job created but no job_id returned."
                _redraw_panels()
                return None  # unregister timer

            bpy.app.timers.register(_on_done, first_interval=0.0)

        except Exception as e:
            def _on_error():
                props.is_submitting = False
                props.error_message = str(e)
                _redraw_panels()
                return None

            bpy.app.timers.register(_on_error, first_interval=0.0)

    t = threading.Thread(target=_background, daemon=True)
    t.start()


class REMOTERENDER_OT_confirm_overwrite(bpy.types.Operator):
    """Confirm overwriting an existing .blend file in the BlendFiles folder"""

    bl_idname = "remote_render.confirm_overwrite"
    bl_label = "Replace Existing File?"
    bl_options = {"INTERNAL"}

    source: bpy.props.StringProperty()  # type: ignore
    dest: bpy.props.StringProperty()    # type: ignore
    copy_only: bpy.props.BoolProperty(default=False)  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if self.copy_only:
            _do_copy_only(self, context, self.source, self.dest)
        else:
            _do_copy_and_submit(self, context, self.source, self.dest)
        return {"FINISHED"}


class REMOTERENDER_OT_copy_only(bpy.types.Operator):
    """Copy the current .blend file to the workspace without starting a render"""

    bl_idname = "remote_render.copy_only"
    bl_label = "Copy to Workspace"

    def execute(self, context):
        cfg = _get_config()
        if not cfg:
            self.report({"ERROR"}, "App not configured. Run app setup first.")
            return {"CANCELLED"}

        filepath = bpy.data.filepath
        if not filepath:
            self.report({"ERROR"}, "Save your .blend file first.")
            return {"CANCELLED"}

        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()

        blend_root = cfg.get("blend_root", "")
        filename = os.path.basename(filepath)
        dest_path = os.path.join(blend_root, filename)

        if os.path.exists(dest_path):
            bpy.ops.remote_render.confirm_overwrite("INVOKE_DEFAULT", source=filepath, dest=dest_path, copy_only=True)
            return {"FINISHED"}

        _do_copy_only(self, context, filepath, dest_path)
        return {"FINISHED"}


# ── Pause / Resume / Cancel ──────────────────────────────────────────────────


class REMOTERENDER_OT_pause_job(bpy.types.Operator):
    """Pause the active render job"""

    bl_idname = "remote_render.pause_job"
    bl_label = "Pause"

    def execute(self, context):
        cfg = _get_config()
        props = context.scene.remote_render
        job_id = props.active_job_id

        if not cfg or not job_id:
            self.report({"WARNING"}, "No active job to pause.")
            return {"CANCELLED"}

        # Optimistic UI update — show paused immediately
        props.job_paused = True
        progress.set_optimistic_guard()
        _redraw_panels()

        def _bg():
            try:
                api.pause_job(cfg["backend_url"], cfg["agent_id"], cfg["agent_token"], job_id)
            except Exception as e:
                def _err():
                    props.job_paused = False  # revert on failure
                    props.error_message = str(e)
                    _redraw_panels()
                    return None
                bpy.app.timers.register(_err, first_interval=0.0)

        threading.Thread(target=_bg, daemon=True).start()
        return {"FINISHED"}


class REMOTERENDER_OT_resume_job(bpy.types.Operator):
    """Resume a paused render job"""

    bl_idname = "remote_render.resume_job"
    bl_label = "Resume"

    def execute(self, context):
        cfg = _get_config()
        props = context.scene.remote_render
        job_id = props.active_job_id

        if not cfg or not job_id:
            self.report({"WARNING"}, "No active job to resume.")
            return {"CANCELLED"}

        # Optimistic UI update — show rendering immediately
        props.job_paused = False
        progress.set_optimistic_guard()
        _redraw_panels()

        def _bg():
            try:
                api.resume_job(cfg["backend_url"], cfg["agent_id"], cfg["agent_token"], job_id)
            except Exception as e:
                def _err():
                    props.job_paused = True  # revert on failure
                    props.error_message = str(e)
                    _redraw_panels()
                    return None
                bpy.app.timers.register(_err, first_interval=0.0)

        threading.Thread(target=_bg, daemon=True).start()
        return {"FINISHED"}


class REMOTERENDER_OT_cancel_job(bpy.types.Operator):
    """Cancel the active render job"""

    bl_idname = "remote_render.cancel_job"
    bl_label = "Cancel Job"

    def execute(self, context):
        cfg = _get_config()
        props = context.scene.remote_render
        job_id = props.active_job_id

        if not cfg or not job_id:
            self.report({"WARNING"}, "No active job to cancel.")
            return {"CANCELLED"}

        # Optimistic UI update — show canceled immediately and stop polling
        props.job_status = "canceled"
        progress.set_optimistic_guard()
        progress.stop_polling()
        _redraw_panels()

        def _bg():
            try:
                api.cancel_job(cfg["backend_url"], cfg["agent_id"], cfg["agent_token"], job_id)
            except Exception as e:
                def _err():
                    props.error_message = str(e)
                    _redraw_panels()
                    return None
                bpy.app.timers.register(_err, first_interval=0.0)

        threading.Thread(target=_bg, daemon=True).start()
        return {"FINISHED"}


class REMOTERENDER_OT_confirm_cancel_job(bpy.types.Operator):
    """Confirm before canceling the active render job"""

    bl_idname = "remote_render.confirm_cancel_job"
    bl_label = "Cancel this render job?"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        bpy.ops.remote_render.cancel_job()
        return {"FINISHED"}


# ── Utility ──────────────────────────────────────────────────────────────────


class REMOTERENDER_OT_open_dashboard(bpy.types.Operator):
    """Open the Remote Render web dashboard in a browser"""

    bl_idname = "remote_render.open_dashboard"
    bl_label = "Open Dashboard"

    def execute(self, context):
        cfg = _get_config()
        if cfg:
            url = cfg.get("backend_url", "")
            if url:
                # Dashboard is at the frontend URL, not the API URL.
                # Strip /api suffix if present and open the root.
                dashboard = url.rsplit("/api", 1)[0] if "/api" in url else url
                webbrowser.open(dashboard)
        return {"FINISHED"}


class REMOTERENDER_OT_refresh_connection(bpy.types.Operator):
    """Re-read agent config and refresh connection status"""

    bl_idname = "remote_render.refresh_connection"
    bl_label = "Refresh Connection"

    def execute(self, context):
        # Import the package-level helpers (defined in __init__.py)
        from . import _load_config, _refresh_agent_status

        _load_config()
        _refresh_agent_status()
        _redraw_panels()
        self.report({"INFO"}, "Connection refreshed.")
        return {"FINISHED"}


class REMOTERENDER_OT_download_app(bpy.types.Operator):
    """Download the Render Manager desktop app"""

    bl_idname = "remote_render.download_app"
    bl_label = "Download Render Manager App"

    def execute(self, context):
        webbrowser.open("https://rendermanager.com/download")
        return {"FINISHED"}


class REMOTERENDER_OT_open_website(bpy.types.Operator):
    """Open the Render Manager website"""

    bl_idname = "remote_render.open_website"
    bl_label = "Learn More"

    def execute(self, context):
        webbrowser.open("https://rendermanager.com")
        return {"FINISHED"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _redraw_panels():
    """Force the 3D viewport sidebar to redraw."""
    try:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass

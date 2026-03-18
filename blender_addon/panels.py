# blender_addon/panels.py
#
# Sidebar UI panel and Render menu entry for the Remote Render addon.

from __future__ import annotations

import bpy


def _get_config():
    from . import _cached_config
    return _cached_config


# ── Menu entries ──────────────────────────────────────────────────────────

def _draw_render_menu(self, context):
    """Appended to TOPBAR_MT_render — submit a background render."""
    self.layout.separator()
    self.layout.operator(
        "remote_render.copy_and_submit",
        text="Render Manager: Background Render",
        icon="RENDER_ANIMATION",
    )


def _draw_file_menu(self, context):
    """Appended to TOPBAR_MT_file — copy blend file to workspace."""
    self.layout.separator()
    self.layout.operator(
        "remote_render.copy_only",
        text="Render Manager: Copy to Workspace",
        icon="COPYDOWN",
    )


def register_menu():
    bpy.types.TOPBAR_MT_render.append(_draw_render_menu)
    bpy.types.TOPBAR_MT_file.append(_draw_file_menu)


def unregister_menu():
    bpy.types.TOPBAR_MT_render.remove(_draw_render_menu)
    bpy.types.TOPBAR_MT_file.remove(_draw_file_menu)


class REMOTERENDER_PT_main_panel(bpy.types.Panel):
    """Remote Render panel in the 3D Viewport sidebar"""

    bl_label = "Render Manager"
    bl_idname = "REMOTERENDER_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Render Manager"

    def draw(self, context):
        layout = self.layout
        cfg = _get_config()
        props = context.scene.remote_render

        # ── Not configured ───────────────────────────────────────────────
        if cfg is None:
            box = layout.box()
            box.label(text="Welcome to Render Manager!", icon="INFO")
            
            col = box.column(align=True)
            col.label(text="To use this addon, you need")
            col.label(text="the background app installed.")
            
            box.separator()

            req = box.column(align=True)
            req.label(text="(Requires a free account)", icon="USER")
            
            box.separator()
            
            sub = box.column(align=True)
            sub.scale_y = 1.4
            sub.operator("remote_render.download_app", icon="URL")
            
            box.separator()
            
            row = box.row(align=True)
            row.operator("remote_render.refresh_connection", text="I Installed It", icon="FILE_REFRESH")
            row.operator("remote_render.open_website", text="Learn More", icon="HELP")
            return

        # ── Agent status ─────────────────────────────────────────────────
        status_row = layout.row()
        if props.agent_running:
            status_row.label(text="App:  Running", icon="RADIOBUT_ON")
        else:
            status_row.label(text="App:  Not running", icon="RADIOBUT_OFF")

        if not props.agent_running:
            box = layout.box()
            box.label(text="Start the app first.", icon="INFO")
            layout.separator()
            layout.operator("remote_render.refresh_connection", icon="FILE_REFRESH")
            return

        layout.separator()

        # ── Frame range (read from scene) ────────────────────────────────
        scene = context.scene
        row = layout.row(align=True)
        row.label(text="Frames:")
        row.label(text=f"{scene.frame_start} - {scene.frame_end}")

        layout.separator()

        # ── Submit button ────────────────────────────────────────────────
        has_active_job = props.active_job_id != "" and props.job_status not in (
            "", "completed", "failed", "canceled",
        )

        # Info text
        layout.label(text="Starts a separate Blender process.", icon="INFO")

        submit_row = layout.row()
        submit_row.scale_y = 1.5
        submit_row.enabled = not props.is_submitting and not has_active_job
        if props.is_submitting:
            submit_row.operator("remote_render.copy_and_submit", text="Submitting...", icon="SORTTIME")
        else:
            submit_row.operator("remote_render.copy_and_submit", icon="RENDER_ANIMATION")

        # Copy-only button (add file without rendering)
        copy_row = layout.row()
        copy_row.operator("remote_render.copy_only", icon="COPYDOWN")

        # ── Error message ────────────────────────────────────────────────
        if props.error_message:
            box = layout.box()
            col = box.column(align=True)
            # Wrap long error messages
            for line in _wrap_text(props.error_message, 40):
                col.label(text=line, icon="ERROR" if line == props.error_message[:40] else "NONE")

        # ── Active job progress ──────────────────────────────────────────
        if has_active_job:
            layout.separator()
            box = layout.box()
            col = box.column(align=True)

            status = props.job_status
            is_paused = props.job_paused

            if is_paused:
                col.label(text="Paused", icon="PAUSE")
            elif status == "queued":
                col.label(text="Queued...", icon="SORTTIME")
            elif status == "in_progress":
                col.label(text="Rendering...", icon="RENDER_ANIMATION")
                # Progress bar (read-only)
                prog_row = col.row(align=True)
                prog_row.enabled = False
                prog_row.prop(props, "job_progress", text="Progress", slider=True)
                # Frame counter
                if props.job_total_frames > 0:
                    col.label(
                        text=f"Frame {props.job_current_frame} / {props.job_total_frames}"
                    )
                # Progress message from server
                if props.job_message:
                    col.label(text=props.job_message)

            # Pause / Resume / Cancel buttons
            row = box.row(align=True)
            if is_paused:
                row.operator("remote_render.resume_job", icon="PLAY")
                row.operator("remote_render.confirm_cancel_job", text="Cancel", icon="CANCEL")
            elif status == "in_progress":
                row.operator("remote_render.pause_job", icon="PAUSE")
                row.operator("remote_render.confirm_cancel_job", text="Cancel", icon="CANCEL")
            elif status == "queued":
                row.operator("remote_render.confirm_cancel_job", text="Cancel", icon="CANCEL")

        # ── Completed / Failed status ────────────────────────────────────
        if props.active_job_id and props.job_status == "completed":
            layout.separator()
            box = layout.box()
            box.label(text="Completed", icon="CHECKMARK")

        if props.active_job_id and props.job_status == "failed":
            layout.separator()
            box = layout.box()
            box.label(text="Failed", icon="ERROR")
            if props.job_message:
                for line in _wrap_text(props.job_message, 40):
                    box.label(text=line)

        if props.active_job_id and props.job_status == "canceled":
            layout.separator()
            box = layout.box()
            box.label(text="Canceled", icon="CANCEL")

        # ── Footer buttons ───────────────────────────────────────────────
        layout.separator()
        row = layout.row(align=True)
        row.operator("remote_render.open_dashboard", icon="URL")
        row.operator("remote_render.refresh_connection", icon="FILE_REFRESH")


def _wrap_text(text: str, width: int) -> list[str]:
    """Split text into lines of roughly *width* characters."""
    if len(text) <= width:
        return [text]
    lines = []
    while text:
        if len(text) <= width:
            lines.append(text)
            break
        # Find a good break point
        idx = text.rfind(" ", 0, width)
        if idx == -1:
            idx = width
        lines.append(text[:idx])
        text = text[idx:].lstrip()
    return lines

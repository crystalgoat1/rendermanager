# agent/agent_compile.py
#
# Compile rendered frames into an MP4 video.
# Supports PNG/JPG (via ffmpeg) and EXR (via Blender compositor).

import os
import subprocess
import tempfile
import textwrap

def _get_ffmpeg_path() -> str:
    """Return the path to the bundled ffmpeg if available, otherwise use system ffmpeg."""
    from .agent_config import get_bundle_dir
    bundled = os.path.join(get_bundle_dir(), 'agent', 'bin', 'ffmpeg.exe')
    if os.path.isfile(bundled):
        return bundled
    return "ffmpeg"



def _detect_frame_extension(output_dir: str, output_pattern: str, frame_start: int) -> str:
    """Find the file extension of the first rendered frame."""
    import glob
    base_name = os.path.basename(output_pattern)  # e.g. "render_####"
    frame_str = str(frame_start).zfill(4)
    base = os.path.join(output_dir, base_name.replace("####", frame_str))
    matches = glob.glob(base + ".*")
    if matches:
        return os.path.splitext(matches[0])[1]  # e.g. ".exr", ".png"
    raise RuntimeError(f"No rendered frame found at {base}.*")


def _compile_with_ffmpeg(
    output_dir: str,
    output_pattern: str,
    frame_start: int,
    frame_end: int,
    fps: int,
    ext: str,
) -> str:
    """Compile PNG/JPG frames into H.264 MP4 using ffmpeg."""
    output_mp4 = os.path.join(
        tempfile.gettempdir(),
        f"compile_{os.path.basename(output_dir)}_{frame_start}_{frame_end}.mp4",
    )

    base_name = os.path.basename(output_pattern)  # "render_####"
    ffmpeg_pattern = base_name.replace("####", "%04d")
    input_path = os.path.join(output_dir, ffmpeg_pattern + ext)

    # Scale filter: cap at 1920x1080 (HD) max, preserve aspect ratio.
    # Works with any resolution (4K→HD, 720p stays 720p, weird sizes proportional).
    # pad ensures even dimensions required by H.264.
    scale_filter = (
        "scale=w='min(1920,iw)':h='min(1080,ih)'"
        ":force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )

    cmd = [
        _get_ffmpeg_path(),
        "-y",
        "-framerate", str(fps),
        "-start_number", str(frame_start),
        "-i", input_path,
        "-frames:v", str(frame_end - frame_start + 1),
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-profile:v", "main",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-movflags", "+faststart",
        output_mp4,
    ]

    try:
        import sys
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. The bundled version is missing and it's not installed on your system. "
            "Please install it (e.g. 'winget install ffmpeg') and ensure it is on your PATH."
        )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[:500]}")

    if not os.path.isfile(output_mp4) or os.path.getsize(output_mp4) == 0:
        raise RuntimeError("ffmpeg produced no output")

    return output_mp4


def _compile_exr_with_blender(
    blender_path: str,
    output_dir: str,
    output_pattern: str,
    frame_start: int,
    frame_end: int,
    fps: int,
) -> str:
    """Compile multilayer EXR frames into H.264 MP4 using Blender compositor."""
    output_mp4 = os.path.join(
        tempfile.gettempdir(),
        f"compile_{os.path.basename(output_dir)}_{frame_start}_{frame_end}.mp4",
    )

    # Build the file path pattern Blender needs: /path/to/render_####.exr
    base_name = os.path.basename(output_pattern)  # "render_####"
    exr_pattern = os.path.join(output_dir, base_name + ".exr")
    # Blender wants the literal path with #### for the Image Sequence node
    # We pass it as a string and construct it in the Blender script

    # First frame path for setting up the node (Blender needs an actual file to load)
    first_frame = exr_pattern.replace("####", str(frame_start).zfill(4))
    if not os.path.isfile(first_frame):
        raise RuntimeError(f"First EXR frame not found: {first_frame}")

    # Blender Python script that sets up compositor for EXR→MP4
    script = textwrap.dedent(f"""\
        import bpy
        import os

        # Clear default scene
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        # Set frame range and fps
        scene.frame_start = {frame_start}
        scene.frame_end = {frame_end}
        scene.render.fps = {fps}

        first_exr = r"{first_frame}"

        # Use compositor
        scene.use_nodes = True
        tree = scene.node_tree
        tree.nodes.clear()

        # Image Sequence node
        img_node = tree.nodes.new("CompositorNodeImage")
        img = bpy.data.images.load(first_exr)
        img.source = "SEQUENCE"
        img_node.image = img
        img_node.frame_duration = {frame_end - frame_start + 1}
        img_node.frame_start = {frame_start}
        img_node.frame_offset = {frame_start - 1}

        # Get resolution from the loaded image
        scene.render.resolution_x = img.size[0] if img.size[0] > 0 else 1920
        scene.render.resolution_y = img.size[1] if img.size[1] > 0 else 1080
        scene.render.resolution_percentage = 100

        # Composite output node
        comp_node = tree.nodes.new("CompositorNodeComposite")
        tree.links.new(img_node.outputs["Image"], comp_node.inputs["Image"])

        # Configure output to H.264 MP4
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"

        # Set color management for proper EXR tonemapping
        # Blender 4.x defaults to AgX, 3.x to Filmic — both work well for EXR
        try:
            scene.view_settings.view_transform = "AgX"
        except Exception:
            try:
                scene.view_settings.view_transform = "Filmic"
            except Exception:
                pass  # Fall back to whatever default is set
        scene.view_settings.look = "None"

        # Output path
        output_path = r"{output_mp4}"
        scene.render.filepath = output_path

        # Render animation
        bpy.ops.render.render(animation=True)

        # Verify output
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Blender produced no output video")

        print(f"COMPILE_SUCCESS: {{output_path}}")
    """)

    script_path = os.path.join(tempfile.gettempdir(), f"compile_exr_{os.getpid()}.py")
    with open(script_path, "w") as f:
        f.write(script)

    try:
        cmd = [
            blender_path,
            "--background",
            "--python", script_path,
        ]

        import sys
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))

        if result.returncode != 0:
            raise RuntimeError(
                f"Blender compile failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )

        if not os.path.isfile(output_mp4) or os.path.getsize(output_mp4) == 0:
            raise RuntimeError("Blender produced no output video")

        return output_mp4
    finally:
        try:
            os.remove(script_path)
        except Exception:
            pass


def _compile_exr_via_extraction(
    output_dir: str,
    output_pattern: str,
    frame_start: int,
    frame_end: int,
    fps: int,
    pass_name: str,
    blender_path: str = "",
) -> str:
    """Compile EXR frames for a specific pass using OpenEXR extraction + ffmpeg.

    Extracts only the requested pass from each frame to temp JPEGs, then compiles
    with ffmpeg.
    """
    import shutil
    from .agent_exr_preview import extract_single_exr_pass

    base_name = os.path.basename(output_pattern)
    tmp_dir = tempfile.mkdtemp(prefix="compile_exr_extract_")

    try:
        extracted_count = 0
        for frame in range(frame_start, frame_end + 1):
            frame_str = str(frame).zfill(4)
            exr_path = os.path.join(output_dir, base_name.replace("####", frame_str) + ".exr")

            if not os.path.isfile(exr_path):
                # Stop at the first missing frame — render isn't done yet
                print(f"[compile] Frame {frame} not found, compiling up to frame {frame - 1}")
                break

            # Extract only the requested pass directly to the output JPEG
            dst = os.path.join(tmp_dir, f"frame_{frame_str}.jpg")
            if not extract_single_exr_pass(exr_path, pass_name, dst):
                print(f"[compile] Failed to extract frame {frame}, stopping")
                break

            extracted_count += 1

        if extracted_count < 2:
            raise RuntimeError(f"Not enough rendered frames to compile (found {extracted_count})")

        actual_end = frame_start + extracted_count - 1

        # Compile with ffmpeg
        output_mp4 = os.path.join(
            tempfile.gettempdir(),
            f"compile_{os.path.basename(output_dir)}_{frame_start}_{frame_end}.mp4",
        )
        input_path = os.path.join(tmp_dir, "frame_%04d.jpg")
        # Scale filter: cap at HD, preserve aspect ratio, ensure even dimensions
        scale_filter = (
            "scale=w='min(1920,iw)':h='min(1080,ih)'"
            ":force_original_aspect_ratio=decrease,"
            "pad=ceil(iw/2)*2:ceil(ih/2)*2"
        )

        cmd = [
            _get_ffmpeg_path(), "-y",
            "-framerate", str(fps),
            "-start_number", str(frame_start),
            "-i", input_path,
            "-frames:v", str(extracted_count),
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-profile:v", "main",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709",
            "-movflags", "+faststart",
            output_mp4,
        ]

        try:
            import sys
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found. The bundled version is missing and it's not installed on your system. "
                "Please install it (e.g. 'winget install ffmpeg') and ensure it is on your PATH."
            )

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[:500]}")
        if not os.path.isfile(output_mp4) or os.path.getsize(output_mp4) == 0:
            raise RuntimeError("ffmpeg produced no output")

        return output_mp4
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _detect_fps_from_blend(blender_path: str, blend_file: str) -> int:
    """Read the fps from a blend file using a quick Blender call."""
    if not blend_file or not os.path.isfile(blend_file):
        return 24
    try:
        import sys
        result = subprocess.run(
            [blender_path, "--background", blend_file,
             "--python-expr", "import bpy; print(f'FPS={bpy.context.scene.render.fps}')"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {})
        )
        for line in result.stdout.splitlines():
            if line.startswith("FPS="):
                fps = int(line.split("=")[1])
                if 1 <= fps <= 240:
                    return fps
    except Exception as e:
        print(f"[compile] Could not detect fps from blend file: {e}")
    return 24


def compile_animation(
    output_dir: str,
    output_pattern: str,
    frame_start: int,
    frame_end: int,
    fps: int = 0,
    blender_path: str = "blender",
    pass_name: str = None,
    blend_file: str = "",
) -> str:
    """Compile rendered frames into an H.264 MP4.

    Auto-detects frame format:
      - PNG/JPG → ffmpeg
      - EXR → OpenEXR extraction + ffmpeg

    FPS is auto-detected from the blend file. Falls back to 24 if not available.

    Args:
        output_dir: Directory containing rendered frames
        output_pattern: Blender-style pattern e.g. "/path/render_####"
        frame_start: First frame number
        frame_end: Last frame number
        fps: Output framerate (0 = auto-detect from blend file)
        blender_path: Path to Blender executable
        pass_name: Render pass to compile (EXR only, e.g. "Depth", "Normal")
        blend_file: Path to the blend file (for fps detection)

    Returns:
        Path to the output .mp4 file.
    """
    # Auto-detect fps from blend file if not explicitly provided
    if fps <= 0:
        fps = _detect_fps_from_blend(blender_path, blend_file)
    print(f"[compile] Using {fps} fps")

    ext = _detect_frame_extension(output_dir, output_pattern, frame_start)
    print(f"[compile] Detected frame extension: {ext}")

    if ext.lower() == ".exr":
        # Always use OpenEXR extraction + ffmpeg for EXR — it's lightweight
        # (no Blender needed) and doesn't contend with active renders.
        effective_pass = pass_name or "Combined"
        print(f"[compile] Using OpenEXR extraction + ffmpeg for EXR pass '{effective_pass}'")
        return _compile_exr_via_extraction(
            output_dir, output_pattern,
            frame_start, frame_end, fps, effective_pass,
            blender_path=blender_path,
        )
    else:
        print(f"[compile] Using ffmpeg for {ext} frames")
        return _compile_with_ffmpeg(
            output_dir, output_pattern,
            frame_start, frame_end, fps, ext,
        )


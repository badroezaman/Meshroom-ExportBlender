__version__ = "1.0.0"

import glob
import os
import shutil
from meshroom.core import desc


def find_blender_executable() -> str:
    """Find Blender executable dynamically across environment, PATH, and standard directories."""
    # 1. Environment variables
    for env_var in ("BLENDER_BIN", "BLENDER_PATH", "BLENDER_EXECUTABLE"):
        val = os.environ.get(env_var)
        if val and os.path.isfile(val):
            return val

    # 2. Check system PATH
    which_bin = shutil.which("blender") or shutil.which("blender.exe")
    if which_bin:
        return which_bin

    # 3. Standard Windows locations
    if os.name == "nt":
        search_dirs = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
            r"C:\Blender",
        ]
        candidates = []
        for base in search_dirs:
            if not base or not os.path.isdir(base):
                continue
            patterns = [
                os.path.join(base, "Blender Foundation", "Blender *", "blender.exe"),
                os.path.join(base, "blender-*-windows-*", "blender.exe"),
                os.path.join(base, "Blender *", "blender.exe"),
                os.path.join(base, "blender.exe"),
            ]
            for pat in patterns:
                for match in glob.glob(pat):
                    if os.path.isfile(match):
                        candidates.append(match)

        if candidates:
            # Sort by newest modification time to prefer the latest version
            candidates = list(dict.fromkeys(candidates))
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return candidates[0]

    # 4. Standard Linux / macOS locations
    linux_mac_candidates = [
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
        "/var/lib/flatpak/exports/bin/org.blender.Blender",
        os.path.expanduser("~/.local/share/flatpak/exports/bin/org.blender.Blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for std_path in linux_mac_candidates:
        if os.path.isfile(std_path):
            return std_path

    # Check Linux /opt/blender* directories
    for opt_match in glob.glob("/opt/blender*/blender"):
        if os.path.isfile(opt_match):
            return opt_match

    # Fallback to generic command
    return "blender"


class ExportBlender(desc.CommandLineNode):
    commandLine = '"{blenderExecutableValue}" -b --python "{scriptValue}" -- {allParams}'

    category = "Export"
    documentation = """
Export reconstructed 3D models, textures, point clouds, and camera views into a standalone Blender project file (.blend).
Supports OBJ/PLY meshes with textures, and SfM camera poses and point clouds (.abc, .sfm).
"""

    inputs = [
        desc.File(
            name="blenderExecutable",
            label="Blender Executable",
            description="Path to Blender executable (e.g. blender.exe or /usr/bin/blender). Can be selected via GUI, detected from PATH, or configured via BLENDER_BIN.",
            value=find_blender_executable(),
            invalidate=False,
            group="",
        ),
        desc.File(
            name="script",
            label="Blender Script",
            description="Script executed in Blender to assemble the .blend project.",
            value=os.path.join("{nodeSourceCodeFolder}", "scripts", "export_to_blend.py"),
            invalidate=False,
            group="",
            advanced=True,
        ),
        desc.File(
            name="model",
            label="Model (Mesh / Point Cloud)",
            description="3D mesh (.obj, .ply) or dense point cloud (.abc) to import into Blender.",
            value="",
        ),
        desc.File(
            name="sfmData",
            label="SfM Data / Cameras",
            description="SfM data (.abc or .sfm) containing camera poses and sparse point cloud.",
            value="",
        ),
        desc.BoolParam(
            name="importCameras",
            label="Import Cameras",
            description="Import camera poses and views from SfM data into Blender.",
            value=True,
        ),
        desc.BoolParam(
            name="packTextures",
            label="Pack Textures into .blend",
            description="Embed all image textures and external assets directly into the .blend file for complete portability.",
            value=True,
        ),
        desc.BoolParam(
            name="shadeSmooth",
            label="Shade Smooth",
            description="Apply smooth shading to the imported mesh geometry.",
            value=True,
        ),
        desc.BoolParam(
            name="setupLighting",
            label="Setup Scene Lighting",
            description="Add standard lighting (sun/key light) and basic environment.",
            value=True,
        ),
        desc.BoolParam(
            name="openInBlender",
            label="Open in Blender",
            description="Automatically launch Blender with the exported .blend file once Compute is finished.",
            value=True,
        ),
        desc.StringParam(
            name="blendName",
            label="Blend File Name",
            description="Filename for the exported Blender project file.",
            value="model_reconstruction.blend",
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Output Folder",
            description="Output directory where the .blend project is saved.",
            value="{nodeCacheFolder}",
        ),
        desc.File(
            name="outputBlend",
            label="Blender Project (.blend)",
            description="Resulting standalone Blender project file ready to open.",
            semantic="file",
            value="{nodeCacheFolder}/{blendNameValue}",
            group="",
        ),
    ]

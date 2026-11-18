#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
export_to_blend.py

Worker script executed inside Blender (headless mode) to assemble 3D photogrammetry
reconstruction assets (mesh, textures, cameras, point cloud) into a standalone .blend file.
"""

import sys
import os
import argparse
import json


def str_to_bool(val):
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "y", "on")


def parse_args():
    argv = sys.argv
    if "--" in argv:
        args_to_parse = argv[argv.index("--") + 1:]
    else:
        args_to_parse = []

    parser = argparse.ArgumentParser(description="Export Meshroom reconstruction to Blender .blend project")
    parser.add_argument("--model", type=str, default="", help="Path to 3D mesh (.obj, .ply) or point cloud (.abc)")
    parser.add_argument("--sfmData", type=str, default="", help="Path to SfM data (.abc or .sfm)")
    parser.add_argument("--importCameras", type=str_to_bool, default=True, help="Import cameras and poses")
    parser.add_argument("--packTextures", type=str_to_bool, default=True, help="Pack textures into .blend")
    parser.add_argument("--shadeSmooth", type=str_to_bool, default=True, help="Apply smooth shading to mesh")
    parser.add_argument("--setupLighting", type=str_to_bool, default=True, help="Setup basic scene lighting")
    parser.add_argument("--openInBlender", type=str_to_bool, default=True, help="Automatically open .blend in Blender GUI")
    parser.add_argument("--blendName", type=str, default="model_reconstruction.blend", help="Output .blend filename")
    parser.add_argument("--output", type=str, default=".", help="Output directory")

    return parser.parse_args(args_to_parse)


def get_or_create_collection(name, parent_col=None):
    import bpy
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
    else:
        col = bpy.data.collections.new(name)
        if parent_col:
            parent_col.children.link(col)
        else:
            bpy.context.scene.collection.children.link(col)
    return col


def move_objects_to_collection(objs, target_col):
    import bpy
    for obj in objs:
        for col in obj.users_collection:
            col.objects.unlink(obj)
        if obj.name not in target_col.objects:
            target_col.objects.link(obj)


def import_model(model_path, model_col, shade_smooth=True):
    import bpy
    if not model_path or not os.path.exists(model_path):
        print(f"[ExportBlender] Model path not found or empty: {model_path}")
        return []

    ext = os.path.splitext(model_path)[1].lower()
    print(f"[ExportBlender] Importing 3D model ({ext}): {model_path}")

    pre_objs = set(bpy.data.objects)

    if ext == ".obj":
        # Map AliceVision coordinates (OpenCV Y-down) to Blender world (Z-up),
        # matching Blender's native Alembic importer transform: (X_b = X_sfm, Y_b = Z_sfm, Z_b = -Y_sfm)
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=model_path, forward_axis='NEGATIVE_Z', up_axis='Y')
        elif hasattr(bpy.ops.import_scene, "obj"):
            # Fallback for Blender < 3.2 (legacy Python OBJ importer)
            bpy.ops.import_scene.obj(filepath=model_path, axis_forward='-Z', axis_up='Y')
        else:
            print(f"[ExportBlender] ERROR: No OBJ importer found in this Blender installation.")
            return []
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            # AliceVision PLY coordinates match OBJ; apply identical coordinate mapping
            bpy.ops.wm.ply_import(filepath=model_path, forward_axis='NEGATIVE_Z', up_axis='Y')
        else:
            bpy.ops.import_mesh.ply(filepath=model_path)
    elif ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=model_path, as_background_job=False)
    else:
        print(f"[ExportBlender] Unsupported model format '{ext}' for direct import.")
        return []

    imported_objs = [o for o in bpy.data.objects if o not in pre_objs]
    move_objects_to_collection(imported_objs, model_col)

    # Bake import rotation into mesh data so object transforms remain clean (Rotation: 0, 0, 0)
    for obj in imported_objs:
        if obj.type == 'MESH' and (obj.rotation_euler.x or obj.rotation_euler.y or obj.rotation_euler.z):
            try:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
                print(f"[ExportBlender] Applied import rotation to mesh data: {obj.name}")
            except Exception as e:
                print(f"[ExportBlender] Warning: could not apply rotation on {obj.name}: {e}")

    if shade_smooth:
        for obj in imported_objs:
            if obj.type == 'MESH':
                try:
                    for poly in obj.data.polygons:
                        poly.use_smooth = True
                except Exception:
                    pass

    print(f"[ExportBlender] Model imported successfully ({len(imported_objs)} object(s)).")
    return imported_objs


def import_sfm(sfm_path, cams_col, pointcloud_col, import_cameras=True):
    import bpy
    if not sfm_path or not os.path.exists(sfm_path):
        print(f"[ExportBlender] SfM path not found or empty: {sfm_path}")
        return []

    ext = os.path.splitext(sfm_path)[1].lower()
    print(f"[ExportBlender] Importing SfM data ({ext}): {sfm_path}")

    pre_objs = set(bpy.data.objects)

    if ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=sfm_path, as_background_job=False)
        sfm_objs = [o for o in bpy.data.objects if o not in pre_objs]

        cameras = []
        for obj in sfm_objs:
            if obj.type == 'CAMERA':
                cameras.append(obj)
                obj.data.clip_start = 0.01
                obj.data.clip_end = 1000.0
                move_objects_to_collection([obj], cams_col)
            elif obj.type in ('POINTCLOUD', 'MESH') or 'pointcloud' in obj.name.lower():
                move_objects_to_collection([obj], pointcloud_col)
            else:
                move_objects_to_collection([obj], cams_col)

        if cameras and not bpy.context.scene.camera:
            bpy.context.scene.camera = cameras[0]
            print(f"[ExportBlender] Set active scene camera to '{cameras[0].name}'.")

        print(f"[ExportBlender] SfM Alembic imported ({len(cameras)} cameras, {len(sfm_objs)} total objects).")
        return sfm_objs

    elif ext in (".sfm", ".json"):
        import mathutils

        try:
            with open(sfm_path, "r", encoding="utf-8") as f:
                sfm_data = json.load(f)
            views = sfm_data.get("views", [])
            poses = {p["poseId"]: p for p in sfm_data.get("poses", []) if "pose" in p}
            intrinsics = {i["intrinsicId"]: i for i in sfm_data.get("intrinsics", [])}

            # World space conversion: AliceVision Y-up -> Blender Z-up (90 deg rotation on X axis)
            # Resulting mapping: X_b = X_sfm, Y_b = Z_sfm, Z_b = -Y_sfm (matches native Alembic camera space)
            mat_world = mathutils.Matrix((
                (1.0,  0.0,  0.0, 0.0),
                (0.0,  0.0,  1.0, 0.0),
                (0.0, -1.0,  0.0, 0.0),
                (0.0,  0.0,  0.0, 1.0),
            ))

            # Optical axis conversion: OpenCV/AliceVision (+X right, +Y down, +Z forward)
            # -> Blender camera (+X right, +Y up, -Z forward)
            mat_cv_to_blend = mathutils.Matrix((
                (1.0,  0.0,  0.0, 0.0),
                (0.0, -1.0,  0.0, 0.0),
                (0.0,  0.0, -1.0, 0.0),
                (0.0,  0.0,  0.0, 1.0),
            ))

            created_cams = []
            for v in views:
                pose_id = v.get("poseId")
                if pose_id not in poses:
                    continue
                view_id = v.get("viewId")
                cam_name = f"Camera_{view_id}_{os.path.splitext(os.path.basename(v.get('path', '')))[0]}"
                cam_data = bpy.data.cameras.new(cam_name)
                cam_data.clip_start = 0.01
                cam_data.clip_end = 1000.0

                # --- Intrinsic parameters ---
                intrinsic_id = v.get("intrinsicId")
                if intrinsic_id in intrinsics:
                    int_info = intrinsics[intrinsic_id]

                    # Focal length & sensor width
                    sensor_width = float(int_info.get("sensorWidth", 36.0))
                    pixel_ratio = float(int_info.get("pixelRatio", 1.0))
                    fl = float(int_info.get("focalLength", 50.0))
                    cam_data.sensor_width = sensor_width
                    cam_data.lens = fl / pixel_ratio

                    # Principal point shift (normalized by largest image dimension)
                    img_width = float(int_info.get("width", 1920))
                    img_height = float(int_info.get("height", 1080))
                    max_dim = max(img_width, img_height)
                    pp = int_info.get("principalPoint", [0.0, 0.0])
                    cam_data.shift_x = -float(pp[0]) / max_dim
                    cam_data.shift_y = float(pp[1]) / max_dim

                # --- Extrinsic parameters: pose transform (rotation + center) ---
                tr = poses[pose_id]["pose"]["transform"]
                r = [float(x) for x in tr["rotation"]]
                c = [float(x) for x in tr["center"]]

                mat_pose = mathutils.Matrix((
                    (r[0], r[1], r[2], c[0]),
                    (r[3], r[4], r[5], c[1]),
                    (r[6], r[7], r[8], c[2]),
                    (0.0,  0.0,  0.0,  1.0),
                ))

                cam_obj = bpy.data.objects.new(cam_name, object_data=cam_data)
                cam_obj.matrix_world = mat_world @ mat_pose @ mat_cv_to_blend
                cams_col.objects.link(cam_obj)
                created_cams.append(cam_obj)

            if created_cams and not bpy.context.scene.camera:
                bpy.context.scene.camera = created_cams[0]

            print(f"[ExportBlender] Created {len(created_cams)} camera(s) from SfM JSON with full pose transforms.")
            return created_cams
        except Exception as e:
            print(f"[ExportBlender] Warning: Failed to parse SfM JSON ({e}).")
            return []

    return []


def setup_scene_lighting(lighting_col):
    import bpy
    print("[ExportBlender] Setting up scene lighting and environment...")

    # Sun Light
    sun_data = bpy.data.lights.new(name="SunLight", type='SUN')
    sun_data.energy = 2.5
    sun_obj = bpy.data.objects.new(name="SunLight", object_data=sun_data)
    sun_obj.location = (5.0, -5.0, 10.0)
    sun_obj.rotation_euler = (0.785, 0.3, 0.5)
    lighting_col.objects.link(sun_obj)

    # Fill Light
    fill_data = bpy.data.lights.new(name="FillLight", type='POINT')
    fill_data.energy = 150.0
    fill_obj = bpy.data.objects.new(name="FillLight", object_data=fill_data)
    fill_obj.location = (-5.0, 5.0, 6.0)
    lighting_col.objects.link(fill_obj)

    # World background
    if bpy.context.scene.world:
        world = bpy.context.scene.world
    else:
        world = bpy.data.worlds.new("MeshroomWorld")
        bpy.context.scene.world = world

    if world.use_nodes:
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs['Color'].default_value = (0.05, 0.05, 0.05, 1.0)
            bg.inputs['Strength'].default_value = 0.8


def pack_all_textures():
    import bpy
    print("[ExportBlender] Packing external textures and images into .blend file...")
    try:
        bpy.ops.file.pack_all()
        packed_count = sum(1 for img in bpy.data.images if img.packed_file is not None)
        print(f"[ExportBlender] Successfully packed {packed_count} image texture(s).")
    except Exception as e:
        print(f"[ExportBlender] Warning during texture packing: {e}")


def launch_blender_gui(blend_path, executable=None):
    import subprocess
    import sys
    import shutil
    import bpy

    blender_bin = executable or getattr(bpy.app, "binary_path", "")
    if not blender_bin or not os.path.isfile(blender_bin):
        blender_bin = (
            os.environ.get("BLENDER_BIN")
            or os.environ.get("BLENDER_PATH")
            or shutil.which("blender")
            or shutil.which("blender.exe")
            or "blender"
        )

    if not os.path.isfile(blender_bin) and not shutil.which(blender_bin):
        print(f"[ExportBlender] Warning: Blender executable not found: {blender_bin}")
        return False

    print(f"[ExportBlender] Launching Blender GUI: \"{blender_bin}\" \"{blend_path}\"")
    try:
        if sys.platform == "win32":
            # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
            creation_flags = 0x00000008 | 0x00000200
            subprocess.Popen(
                [blender_bin, blend_path],
                creationflags=creation_flags,
                close_fds=True
            )
        else:
            subprocess.Popen(
                [blender_bin, blend_path],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        print("[ExportBlender] Blender GUI successfully launched as detached background process.")
        return True
    except Exception as e:
        print(f"[ExportBlender] Warning: Failed to launch Blender GUI: {e}")
        return False


def main():
    args = parse_args()
    print("=" * 60)
    print("[ExportBlender] Starting Blender project assembly...")
    print(f"  Model:            {args.model}")
    print(f"  SfM Data:         {args.sfmData}")
    print(f"  Import Cameras:   {args.importCameras}")
    print(f"  Pack Textures:    {args.packTextures}")
    print(f"  Shade Smooth:     {args.shadeSmooth}")
    print(f"  Setup Lighting:   {args.setupLighting}")
    print(f"  Open in Blender:  {args.openInBlender}")
    print(f"  Blend Name:       {args.blendName}")
    print(f"  Output Dir:       {args.output}")
    print("=" * 60)

    import bpy

    # Clean default factory scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Create root hierarchy collections
    root_col = get_or_create_collection("Meshroom_Reconstruction")
    model_col = get_or_create_collection("Model", root_col)
    pointcloud_col = get_or_create_collection("PointCloud", root_col)
    cams_col = get_or_create_collection("Cameras", root_col)
    lighting_col = get_or_create_collection("Lighting", root_col)

    # 1. Import Model
    if args.model:
        import_model(args.model, model_col, shade_smooth=args.shadeSmooth)

    # 2. Import SfM Data (Cameras / Point Cloud)
    if args.sfmData and args.importCameras:
        import_sfm(args.sfmData, cams_col, pointcloud_col, import_cameras=args.importCameras)

    if not args.model and not args.sfmData:
        print("[ExportBlender] Warning: Neither '--model' nor '--sfmData' was provided. The created .blend file will contain no reconstruction assets.")

    # 3. Setup Scene Lighting
    if args.setupLighting:
        setup_scene_lighting(lighting_col)

    # 4. Pack Textures
    if args.packTextures:
        pack_all_textures()

    # 5. Save .blend file
    os.makedirs(args.output, exist_ok=True)
    blend_filename = args.blendName.strip() if args.blendName else "model_reconstruction.blend"
    if not blend_filename.lower().endswith(".blend"):
        blend_filename = f"{blend_filename}.blend"
    blend_path = os.path.abspath(os.path.join(args.output, blend_filename))
    print(f"[ExportBlender] Saving Blender project file: {blend_path}")

    bpy.ops.wm.save_as_mainfile(filepath=blend_path)

    if os.path.exists(blend_path):
        size_mb = os.path.getsize(blend_path) / (1024.0 * 1024.0)
        print(f"[ExportBlender] SUCCESS! Created .blend project ({size_mb:.2f} MB): {blend_path}")

        # Automatically launch GUI if requested
        if args.openInBlender:
            launch_blender_gui(blend_path)

        print("=" * 60)
        sys.exit(0)
    else:
        print(f"[ExportBlender] ERROR: Output file was not created at: {blend_path}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

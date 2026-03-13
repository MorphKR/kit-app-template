import asyncio
import datetime
import os

import carb
import omni.kit.app
import omni.kit.commands
import omni.kit.viewport.utility as vp_utils
import omni.usd

THUMBNAIL_RESOLUTION = (512, 512)
CAPTURE_WAIT_FRAMES = 30
THUMBNAIL_FRAME_ZOOM = 0.65


def _get_capture_folder() -> str:
    base = os.getcwd()
    folder = os.path.join(base, "captures")
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_thumbnail_folder() -> str:
    folder = os.path.join(_get_capture_folder(), "thumbnails")
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_selected_prim_paths() -> list[str]:
    ctx = omni.usd.get_context()
    if not ctx:
        return []

    try:
        sel = ctx.get_selection()
    except Exception:
        sel = None
    if not sel:
        return []

    try:
        if hasattr(sel, "get_selected_prim_paths"):
            return [str(p) for p in (sel.get_selected_prim_paths() or [])]
    except Exception:
        pass

    try:
        if hasattr(sel, "get_selected_prim_path_strings"):
            return [str(p) for p in (sel.get_selected_prim_path_strings() or [])]
    except Exception:
        pass

    return []


def _set_selected_prim_paths(paths: list[str]) -> bool:
    ctx = omni.usd.get_context()
    if not ctx:
        return False
    try:
        sel = ctx.get_selection()
    except Exception:
        sel = None
    if not sel or not hasattr(sel, "set_selected_prim_paths"):
        return False
    try:
        sel.set_selected_prim_paths(paths, False)
        return True
    except Exception:
        return False


def _get_world_first_child_prim_path() -> str | None:
    ctx = omni.usd.get_context()
    if not ctx:
        return None

    stage = ctx.get_stage()
    if not stage:
        return None

    world = stage.GetPrimAtPath("/World")
    if not world or not world.IsValid():
        return None

    for child in world.GetChildren():
        if child and child.IsValid():
            return str(child.GetPath())

    return None


def _get_active_viewport_api():
    try:
        if hasattr(vp_utils, "get_active_viewport"):
            vp = vp_utils.get_active_viewport()
            if vp:
                return vp
    except Exception:
        pass

    try:
        if hasattr(vp_utils, "get_active_viewport_window"):
            win = vp_utils.get_active_viewport_window()
            if not win:
                return None
            vp = getattr(win, "viewport_api", None)
            if vp is None and hasattr(win, "get_viewport_api"):
                vp = win.get_viewport_api()
            return vp
    except Exception:
        pass

    return None


def _get_active_camera_prim(viewport_api):
    if not viewport_api:
        return None

    ctx = omni.usd.get_context()
    if not ctx:
        return None
    stage = ctx.get_stage()
    if not stage:
        return None

    cam_path = None
    try:
        cam_path = getattr(viewport_api, "camera_path", None)
    except Exception:
        cam_path = None

    cam_path_str = None
    if cam_path is not None:
        cam_path_str = getattr(cam_path, "pathString", None)
        if not cam_path_str:
            cam_path_str = str(cam_path)

    if not cam_path_str:
        return None

    prim = stage.GetPrimAtPath(cam_path_str)
    if not prim or not prim.IsValid():
        return None

    return prim


def _xform_attr_names(prim) -> set[str]:
    names: set[str] = set()
    if not prim or not prim.IsValid():
        return names

    try:
        for attr in prim.GetAttributes():
            if not attr or not attr.IsValid():
                continue
            name = attr.GetName()
            if name == "xformOpOrder" or name.startswith("xformOp:"):
                names.add(name)
    except Exception:
        pass
    return names


def _snapshot_camera_xform(camera_prim) -> dict:
    if not camera_prim or not camera_prim.IsValid():
        return {}

    attrs = {}
    for name in _xform_attr_names(camera_prim):
        try:
            attr = camera_prim.GetAttribute(name)
            if not attr or not attr.IsValid():
                continue
            authored = bool(attr.HasAuthoredValueOpinion())
            attrs[name] = {"authored": authored, "value": attr.Get() if authored else None}
        except Exception:
            pass

    return {"attrs": attrs}


def _restore_camera_xform(camera_prim, snap: dict) -> bool:
    if not camera_prim or not camera_prim.IsValid() or not snap:
        return False

    saved_attrs = snap.get("attrs", {})
    if not isinstance(saved_attrs, dict):
        return False

    ok_any = False

    for name, state in saved_attrs.items():
        try:
            attr = camera_prim.GetAttribute(name)
            if not attr or not attr.IsValid():
                continue
            if state.get("authored"):
                attr.Set(state.get("value"))
            else:
                attr.Clear()
            ok_any = True
        except Exception:
            pass

    # Remove xform attrs that were introduced by framing.
    for name in _xform_attr_names(camera_prim):
        if name in saved_attrs:
            continue
        try:
            camera_prim.RemoveProperty(name)
            ok_any = True
        except Exception:
            pass

    return ok_any


def _snapshot_viewport_resolution(viewport_api) -> tuple[int, int] | None:
    if not viewport_api:
        return None
    try:
        res = viewport_api.resolution
        if isinstance(res, (tuple, list)) and len(res) >= 2:
            return (int(res[0]), int(res[1]))
    except Exception:
        pass
    return None


def _snapshot_viewport_flags(viewport_api) -> dict:
    snap = {}
    if not viewport_api:
        return snap
    try:
        snap["fill_frame"] = bool(viewport_api.fill_frame)
    except Exception:
        pass
    try:
        snap["resolution_scale"] = float(viewport_api.resolution_scale)
    except Exception:
        pass
    return snap


def _apply_thumbnail_viewport_flags(viewport_api) -> None:
    if not viewport_api:
        return
    try:
        viewport_api.fill_frame = False
    except Exception:
        pass
    try:
        viewport_api.resolution_scale = 1.0
    except Exception:
        pass


def _restore_viewport_flags(viewport_api, snap: dict) -> None:
    if not viewport_api or not snap:
        return
    if "fill_frame" in snap:
        try:
            viewport_api.fill_frame = bool(snap["fill_frame"])
        except Exception:
            pass
    if "resolution_scale" in snap:
        try:
            viewport_api.resolution_scale = float(snap["resolution_scale"])
        except Exception:
            pass


def _set_viewport_resolution(viewport_api, width: int, height: int) -> bool:
    if not viewport_api:
        return False
    try:
        if hasattr(viewport_api, "set_texture_resolution"):
            viewport_api.set_texture_resolution((int(width), int(height)))
        viewport_api.resolution = (int(width), int(height))
        return True
    except Exception as e:  # noqa: BLE001
        carb.log_warn(f"[capture_and_movie] failed to set viewport resolution to {width}x{height}: {e!r}")
        return False


def _snapshot_viewport_visibility_settings(viewport_api) -> dict:
    settings = carb.settings.get_settings()
    if not settings or not viewport_api:
        return {}

    viewport_id = str(getattr(viewport_api, "id", ""))
    keys = [
        f"/persistent/app/viewport/{viewport_id}/guide/grid/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/axis/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/origin/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/selection/visible",
        "/app/viewport/grid/enabled",
        "/app/viewport/outline/enabled",
    ]
    snap = {}
    for key in keys:
        try:
            snap[key] = settings.get(key)
        except Exception:
            pass
    return snap


def _set_clean_thumbnail_visibility(viewport_api) -> None:
    settings = carb.settings.get_settings()
    if not settings or not viewport_api:
        return

    viewport_id = str(getattr(viewport_api, "id", ""))
    keys_to_disable = [
        f"/persistent/app/viewport/{viewport_id}/guide/grid/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/axis/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/origin/visible",
        f"/persistent/app/viewport/{viewport_id}/guide/selection/visible",
        "/app/viewport/grid/enabled",
        "/app/viewport/outline/enabled",
    ]
    for key in keys_to_disable:
        try:
            settings.set(key, False)
        except Exception:
            pass


def _restore_settings_snapshot(snapshot: dict) -> None:
    settings = carb.settings.get_settings()
    if not settings or not snapshot:
        return

    for key, value in snapshot.items():
        try:
            if value is None and hasattr(settings, "destroy_item"):
                settings.destroy_item(key)
            else:
                settings.set(key, value)
        except Exception:
            pass


def _frame_prim_in_viewport(viewport_api, target_path: str) -> bool:
    if not target_path:
        return False
    try:
        cam_path = getattr(viewport_api, "camera_path", None)
        cam_path_str = getattr(cam_path, "pathString", None) if cam_path is not None else None
        if not cam_path_str and cam_path is not None:
            cam_path_str = str(cam_path)
        if not cam_path_str:
            return False

        result = omni.kit.commands.execute(
            "FramePrimsCommand",
            prim_to_move=cam_path_str,
            prims_to_frame=[str(target_path)],
            time_code=viewport_api.time,
            usd_context_name=viewport_api.usd_context_name,
            aspect_ratio=1.0,
            zoom=THUMBNAIL_FRAME_ZOOM,
        )
        return bool(result)
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] frame command failed for {target_path}: {e!r}")
        return False


async def _capture_viewport_file_async(viewport_api, file_path: str, *, is_hdr: bool = False) -> bool:
    try:
        capture_helper = vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=is_hdr)
        if hasattr(capture_helper, "wait_for_result"):
            await capture_helper.wait_for_result(completion_frames=CAPTURE_WAIT_FRAMES)
        else:
            app = omni.kit.app.get_app()
            await app.next_update_async()
        return True
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] capture_viewport_to_file failed: {e!r}")
        return False


async def _capture_thumbnail_for_target_path_async(target_path: str, *, settle_frames: int = 2) -> str | None:
    viewport_api = _get_active_viewport_api()
    if not viewport_api:
        carb.log_warn("[capture_and_movie] failed to get viewport API")
        return None

    camera_prim = _get_active_camera_prim(viewport_api)
    camera_snap = _snapshot_camera_xform(camera_prim)
    viewport_flags_snap = _snapshot_viewport_flags(viewport_api)
    resolution_snap = _snapshot_viewport_resolution(viewport_api)
    visibility_snap = _snapshot_viewport_visibility_settings(viewport_api)
    selection_snap = _get_selected_prim_paths()

    file_path: str | None = None
    try:
        _apply_thumbnail_viewport_flags(viewport_api)
        _set_viewport_resolution(viewport_api, THUMBNAIL_RESOLUTION[0], THUMBNAIL_RESOLUTION[1])
        _set_clean_thumbnail_visibility(viewport_api)
        _set_selected_prim_paths([])

        if not _frame_prim_in_viewport(viewport_api, target_path):
            return None

        app = omni.kit.app.get_app()
        for _ in range(max(0, int(settle_frames))):
            await app.next_update_async()

        folder = _get_thumbnail_folder()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        prim_name = target_path.rsplit("/", 1)[-1] or "prim"
        file_path = os.path.join(folder, f"thumb_{prim_name}_{timestamp}.png")

        ok = await _capture_viewport_file_async(viewport_api, file_path, is_hdr=False)
        if not ok:
            return None

        carb.log_info(f"[capture_and_movie] thumbnail capture completed: {file_path} (prim={target_path})")
        return file_path
    finally:
        try:
            if camera_prim and camera_snap:
                _restore_camera_xform(camera_prim, camera_snap)

            if resolution_snap:
                _set_viewport_resolution(viewport_api, resolution_snap[0], resolution_snap[1])
            _restore_viewport_flags(viewport_api, viewport_flags_snap)

            _restore_settings_snapshot(visibility_snap)
            _set_selected_prim_paths(selection_snap)

            app = omni.kit.app.get_app()
            await app.next_update_async()
        except Exception:
            pass


def capture_active_viewport_to_png() -> str | None:
    viewport_api = _get_active_viewport_api()
    if not viewport_api:
        carb.log_warn("[capture_and_movie] failed to get viewport API")
        return None

    folder = _get_capture_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(folder, f"viewport_{timestamp}.png")

    try:
        vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=False)
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] capture failed: {e!r}")
        return None

    carb.log_info(f"[capture_and_movie] capture completed: {file_path}")
    return file_path


async def capture_selected_prim_thumbnail_to_png_async(*, settle_frames: int = 2) -> str | None:
    selected = _get_selected_prim_paths()
    if not selected:
        carb.log_warn("[capture_and_movie] no selected prim")
        return None
    return await _capture_thumbnail_for_target_path_async(selected[0], settle_frames=settle_frames)


async def capture_world_first_prim_thumbnail_to_png_async(*, settle_frames: int = 2) -> str | None:
    target_path = _get_world_first_child_prim_path()
    if not target_path:
        carb.log_warn("[capture_and_movie] failed to find first child under /World")
        return None
    return await _capture_thumbnail_for_target_path_async(target_path, settle_frames=settle_frames)

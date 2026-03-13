"""
`morph.capture_and_movie` 캡처 유틸 모듈.

이 파일은 크게 2가지 기능을 제공합니다.

- **뷰포트 전체 캡처**: 현재 활성 뷰포트 화면을 그대로 PNG로 저장
- **Prim 썸네일 캡처**: 특정 prim을 프레이밍한 뒤, 중앙 정사각형으로 크롭/리사이즈하여 PNG 썸네일 저장

썸네일 캡처는 일시적으로 다음 상태를 변경합니다.
- 카메라(프레이밍으로 이동)
- 뷰포트 해상도/플래그
- 그리드/축/아웃라인 등 가이드 표시 설정
- USD selection(선택 하이라이트가 썸네일에 찍히지 않도록 비움)

따라서 캡처는 항상 `try/finally`로 원복을 보장합니다.
"""

import asyncio
import ctypes
import datetime
import os
import struct
import zlib

import carb
import omni.kit.app
import omni.kit.commands
import omni.kit.viewport.utility as vp_utils
import omni.ui as ui
import omni.usd

# 썸네일 PNG 출력 해상도(정사각)
THUMBNAIL_RESOLUTION = (512, 512)
# 캡처 결과를 기다릴 때 여유 프레임(Kit 버전에 따라 비동기 완료 방식이 다름)
CAPTURE_WAIT_FRAMES = 30
# FramePrimsCommand zoom 값(작을수록 대상이 더 크게 보이는 경향)
THUMBNAIL_FRAME_ZOOM = 0.65


def _get_capture_folder() -> str:
    """`./captures` 폴더를 보장하고 경로를 반환."""
    folder = os.path.join(os.getcwd(), "captures")
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_thumbnail_folder() -> str:
    """`./captures/thumbnails` 폴더를 보장하고 경로를 반환."""
    folder = os.path.join(_get_capture_folder(), "thumbnails")
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_selected_prim_paths() -> list[str]:
    """현재 USD selection의 prim path 목록을 문자열 리스트로 반환(없으면 빈 리스트)."""
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
    """USD selection을 `paths`로 설정한다. 성공 시 True."""
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
    """`/World` 아래 첫 번째 child prim의 path를 반환(없으면 None)."""
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
    """
    활성 viewport API를 반환한다.

    Kit 버전/앱 구성에 따라 다음 중 하나만 존재할 수 있어 방어적으로 처리한다.
    - `omni.kit.viewport.utility.get_active_viewport()`
    - `omni.kit.viewport.utility.get_active_viewport_window().viewport_api`
    """
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
    """
    `viewport_api.camera_path`를 이용해 stage에서 카메라 prim을 찾는다.
    반환값은 `pxr.Usd.Prim` 또는 None.
    """
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

    cam_path_str = getattr(cam_path, "pathString", None) if cam_path is not None else None
    if not cam_path_str and cam_path is not None:
        cam_path_str = str(cam_path)
    if not cam_path_str:
        return None

    prim = stage.GetPrimAtPath(cam_path_str)
    if not prim or not prim.IsValid():
        return None
    return prim


def _xform_attr_names(prim) -> set[str]:
    """prim에 존재하는 xform 관련 attribute 이름(`xformOp:*`, `xformOpOrder`)을 수집."""
    names: set[str] = set()
    if not prim or not prim.IsValid():
        return names
    try:
        for attr in prim.GetAttributes():
            if not attr or not attr.IsValid():
                continue
            n = attr.GetName()
            if n == "xformOpOrder" or n.startswith("xformOp:"):
                names.add(n)
    except Exception:
        pass
    return names


def _snapshot_camera_xform(camera_prim) -> dict:
    """
    카메라 prim의 xform 관련 속성 상태를 스냅샷한다.
    - authored 여부 + authored면 value를 저장
    - 프레이밍 과정에서 xformOp가 추가/변경될 수 있어 원복에 사용
    """
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
    """
    `_snapshot_camera_xform()` 스냅샷을 기반으로 카메라 xform을 원복한다.
    - 스냅샷에 없던 xformOp가 프레이밍 중 추가되었으면 제거까지 시도한다.
    """
    if not camera_prim or not camera_prim.IsValid() or not snap:
        return False
    saved = snap.get("attrs", {})
    if not isinstance(saved, dict):
        return False

    changed = False
    for name, state in saved.items():
        try:
            attr = camera_prim.GetAttribute(name)
            if not attr or not attr.IsValid():
                continue
            if state.get("authored"):
                attr.Set(state.get("value"))
            else:
                attr.Clear()
            changed = True
        except Exception:
            pass

    for name in _xform_attr_names(camera_prim):
        if name in saved:
            continue
        try:
            camera_prim.RemoveProperty(name)
            changed = True
        except Exception:
            pass

    return changed


def _snapshot_viewport_resolution(viewport_api) -> tuple[int, int] | None:
    """현재 viewport 해상도(resolution)를 (w, h)로 스냅샷한다. 읽을 수 없으면 None."""
    if not viewport_api:
        return None
    try:
        r = viewport_api.resolution
        if isinstance(r, (tuple, list)) and len(r) >= 2:
            return int(r[0]), int(r[1])
    except Exception:
        pass
    return None


def _snapshot_viewport_flags(viewport_api) -> dict:
    """썸네일 캡처 중 변경되는 viewport 플래그(fill_frame, resolution_scale)를 스냅샷."""
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
    """썸네일 캡처에 맞게 viewport 플래그를 일시 적용."""
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
    """`_snapshot_viewport_flags()`로 저장한 viewport 플래그를 원복."""
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
    """viewport 텍스처 해상도를 설정하고 성공 여부를 반환."""
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
    """
    썸네일에 불필요한 오버레이(그리드/축/선택 하이라이트/아웃라인 등) 관련 설정을 스냅샷한다.
    - viewport id 기반 persistent key + 전역 key를 함께 저장.
    """
    settings = carb.settings.get_settings()
    if not settings or not viewport_api:
        return {}
    vp_id = str(getattr(viewport_api, "id", ""))
    keys = [
        f"/persistent/app/viewport/{vp_id}/guide/grid/visible",
        f"/persistent/app/viewport/{vp_id}/guide/axis/visible",
        f"/persistent/app/viewport/{vp_id}/guide/origin/visible",
        f"/persistent/app/viewport/{vp_id}/guide/selection/visible",
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
    """썸네일 캡처를 위해 그리드/축/선택 표시/아웃라인 등을 끄도록 carb.settings를 일시 변경."""
    settings = carb.settings.get_settings()
    if not settings or not viewport_api:
        return
    vp_id = str(getattr(viewport_api, "id", ""))
    keys = [
        f"/persistent/app/viewport/{vp_id}/guide/grid/visible",
        f"/persistent/app/viewport/{vp_id}/guide/axis/visible",
        f"/persistent/app/viewport/{vp_id}/guide/origin/visible",
        f"/persistent/app/viewport/{vp_id}/guide/selection/visible",
        "/app/viewport/grid/enabled",
        "/app/viewport/outline/enabled",
    ]
    for key in keys:
        try:
            settings.set(key, False)
        except Exception:
            pass


def _restore_settings_snapshot(snapshot: dict) -> None:
    """`carb.settings` 스냅샷을 원복한다. (value가 None이면 item 삭제를 시도)"""
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
    """
    활성 뷰포트 카메라를 `target_path` prim이 잘 보이도록 프레이밍한다.
    - `FramePrimsCommand`를 사용해 aspect_ratio=1(정사각), zoom을 썸네일에 맞게 적용한다.
    """
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


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """PNG chunk(Length+Type+Data+CRC) 바이트를 조립한다."""
    return (
        struct.pack("!I", len(data))
        + chunk_type
        + data
        + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _encode_rgba_png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    """
    RGBA8 바이트를 PNG 바이너리로 인코딩한다(외부 이미지 라이브러리 없이).
    - scanline filter는 0(None)만 사용.
    """
    if width <= 0 or height <= 0:
        raise ValueError("invalid image size")
    if len(rgba) != width * height * 4:
        raise ValueError("invalid rgba byte length")

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        row = y * stride
        raw.extend(rgba[row : row + stride])

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _crop_center_square_rgba(width: int, height: int, rgba: bytes) -> tuple[int, bytes]:
    """RGBA 이미지에서 중앙 정사각형을 크롭하여 (side, rgba_bytes)로 반환."""
    side = min(width, height)
    x0 = (width - side) // 2
    y0 = (height - side) // 2
    out = bytearray(side * side * 4)
    src_stride = width * 4
    dst_stride = side * 4
    for y in range(side):
        src = (y0 + y) * src_stride + x0 * 4
        dst = y * dst_stride
        out[dst : dst + dst_stride] = rgba[src : src + dst_stride]
    return side, bytes(out)


def _resize_rgba_nearest(src_size: int, dst_size: int, rgba: bytes) -> bytes:
    """정사각 RGBA 이미지를 nearest-neighbor로 리사이즈한다(단순/빠름, 품질은 낮을 수 있음)."""
    if src_size == dst_size:
        return rgba
    out = bytearray(dst_size * dst_size * 4)
    src_stride = src_size * 4
    dst_stride = dst_size * 4
    for dy in range(dst_size):
        sy = (dy * src_size) // dst_size
        sy_row = sy * src_stride
        dy_row = dy * dst_stride
        for dx in range(dst_size):
            sx = (dx * src_size) // dst_size
            s = sy_row + sx * 4
            d = dy_row + dx * 4
            out[d : d + 4] = rgba[s : s + 4]
    return bytes(out)


def _pycapsule_to_address(capsule) -> int:
    """PyCapsule에서 raw pointer 주소를 추출한다(캡처 버퍼 타입 호환 목적)."""
    pyapi = ctypes.pythonapi
    get_name = pyapi.PyCapsule_GetName
    get_name.restype = ctypes.c_char_p
    get_name.argtypes = [ctypes.py_object]
    get_ptr = pyapi.PyCapsule_GetPointer
    get_ptr.restype = ctypes.c_void_p
    get_ptr.argtypes = [ctypes.py_object, ctypes.c_char_p]

    name = None
    try:
        name = get_name(capsule)
    except Exception:
        pass

    ptr = None
    try:
        ptr = get_ptr(capsule, name)
    except Exception:
        pass
    if not ptr:
        try:
            ptr = get_ptr(capsule, None)
        except Exception:
            pass
    if not ptr:
        raise TypeError("failed to extract pointer from PyCapsule")
    return int(ptr)


def _buffer_to_bytes(buffer, buffer_size) -> bytes:
    size = int(buffer_size)
    if size <= 0:
        raise ValueError("buffer_size must be > 0")

    if isinstance(buffer, (bytes, bytearray)):
        return bytes(buffer[:size])
    if isinstance(buffer, memoryview):
        return buffer.tobytes()[:size]
    if type(buffer).__name__ == "PyCapsule":
        return ctypes.string_at(_pycapsule_to_address(buffer), size)

    try:
        return memoryview(buffer).tobytes()[:size]
    except Exception:
        pass
    try:
        if isinstance(buffer, int):
            return ctypes.string_at(buffer, size)
    except Exception:
        pass
    try:
        addr = int(buffer)
        if addr:
            return ctypes.string_at(addr, size)
    except Exception:
        pass
    try:
        addr = ctypes.cast(buffer, ctypes.c_void_p).value
        if addr:
            return ctypes.string_at(addr, size)
    except Exception:
        pass

    raise TypeError(f"unsupported capture buffer type: {type(buffer)!r}")


async def _capture_center_square_to_png_async(
    viewport_api,
    file_path: str,
    *,
    output_size: int = 512,
    is_hdr: bool = False,
) -> bool:
    loop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()

    def _on_capture(buffer, buffer_size, width, height, byte_format):
        try:
            if byte_format != ui.TextureFormat.RGBA8_UNORM:
                raise RuntimeError(f"unsupported byte format for PNG crop: {byte_format}")
            raw = _buffer_to_bytes(buffer, buffer_size)
            side, square = _crop_center_square_rgba(int(width), int(height), raw)
            resized = _resize_rgba_nearest(side, int(output_size), square)
            png = _encode_rgba_png_bytes(int(output_size), int(output_size), resized)
            with open(file_path, "wb") as f:
                f.write(png)
            loop.call_soon_threadsafe(done.set_result, True)
        except Exception as e:  # noqa: BLE001
            carb.log_error(
                f"[capture_and_movie] buffer decode failed: type={type(buffer)!r}, "
                f"size={buffer_size}, width={width}, height={height}, format={byte_format}, err={e!r}"
            )
            loop.call_soon_threadsafe(done.set_exception, e)

    try:
        cap = vp_utils.capture_viewport_to_buffer(viewport_api, _on_capture, is_hdr=is_hdr)
        if hasattr(cap, "wait_for_result"):
            await cap.wait_for_result(completion_frames=CAPTURE_WAIT_FRAMES)
        await done
        return True
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] center-square capture failed: {e!r}")
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

        ok = await _capture_center_square_to_png_async(
            viewport_api,
            file_path,
            output_size=THUMBNAIL_RESOLUTION[0],
            is_hdr=False,
        )
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
            await omni.kit.app.get_app().next_update_async()
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

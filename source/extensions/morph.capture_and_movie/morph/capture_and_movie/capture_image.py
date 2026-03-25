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


import ctypes
import carb
import omni.kit.commands




# 썸네일 PNG 출력 해상도(정사각)
THUMBNAIL_RESOLUTION = (512, 512)
# 캡처 결과를 기다릴 때 여유 프레임(Kit 버전에 따라 비동기 완료 방식이 다름)
CAPTURE_WAIT_FRAMES = 30
# FramePrimsCommand zoom 값(작을수록 대상이 더 크게 보이는 경향)
THUMBNAIL_FRAME_ZOOM = 0.65


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
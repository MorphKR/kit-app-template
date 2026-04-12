import functools
import time
from typing import List, Set, Tuple

import carb.input
import omni.kit.raycast.query as rq
import omni.usd
from pxr import UsdGeom


class QuadViewportClickSync:
    """클릭 NDC 좌표를 모든 뷰포트로 브로드캐스트하고 카메라별 레이캐스트를 수행한다."""

    def __init__(self):
        self._rqi = rq.acquire_raycast_query_interface()
        self._entries: List[Tuple[object, object]] = []
        self._query_token = 0
        self._pending = 0
        self._hit_paths: Set[str] = set()
        self._source_had_hit = False
        self._zoom_min_focal = 5.0
        self._zoom_max_focal = 500.0
        self._last_zoom_ts = 0.0
        self._last_zoom_sign = 0
        self._input = carb.input.acquire_input_interface()
        self._input_sub_id = self._input.subscribe_to_input_events(self._on_input_event, order=0) if self._input else None

    def destroy(self):
        for _, click_target in self._entries:
            click_target.set_mouse_pressed_fn(None)
            click_target.set_mouse_wheel_fn(None)
        self._entries = []
        if self._input and self._input_sub_id is not None:
            self._input.unsubscribe_to_input_events(self._input_sub_id)
        self._input_sub_id = None
        self._input = None

    def register_viewport(self, viewport_widget, click_target):
        click_target.set_mouse_pressed_fn(
            lambda x, y, button, modifiers, target=click_target, source_vp=viewport_widget: self._on_mouse_pressed(
                source_vp, target, x, y, button, modifiers
            )
        )
        click_target.set_mouse_wheel_fn(
            lambda *args, target=click_target, source_vp=viewport_widget: self._on_mouse_wheel(
                source_vp, target, *args
            )
        )
        self._entries.append((viewport_widget, click_target))

    def _on_mouse_wheel(self, _source_viewport, _click_target, *args):
        wheel_delta = self._extract_wheel_delta(args)
        if abs(wheel_delta) <= 1e-6:
            return
        if not self._accept_zoom_delta(wheel_delta):
            return
        self._apply_zoom_to_all_cameras(wheel_delta)

    def _on_input_event(self, event, *args) -> bool:
        if not self._entries:
            return True
        if getattr(event, "deviceType", None) != carb.input.DeviceType.MOUSE:
            return True

        mouse_event = getattr(event, "event", None)
        if mouse_event is None:
            return True

        wheel_delta = self._extract_wheel_delta_from_mouse_event(mouse_event)
        if abs(wheel_delta) <= 1e-6:
            return True
        if not self._accept_zoom_delta(wheel_delta):
            return True

        self._apply_zoom_to_all_cameras(wheel_delta)
        return True

    def _on_mouse_pressed(self, source_viewport, click_target, x, y, button, _modifiers):
        # 좌클릭만 처리한다.
        if int(button) != 0:
            return

        width = float(max(1.0, click_target.computed_width))
        height = float(max(1.0, click_target.computed_height))
        local_xy = self._resolve_local_xy(click_target, float(x), float(y), width, height)
        if local_xy is None:
            return
        local_x, local_y = local_xy

        # 클릭된 뷰포트 영역 밖 좌표는 무시한다.
        if local_x < 0.0 or local_x > width or local_y < 0.0 or local_y > height:
            return

        # UI 픽셀 -> 정규화 좌표 [0, 1], 우하단이 (1, 1).
        norm_x = max(0.0, min(1.0, local_x / width))
        norm_y = max(0.0, min(1.0, local_y / height))
        self._raycast_all_viewports(norm_x, norm_y, source_viewport)

    def _raycast_all_viewports(self, norm_x: float, norm_y: float, source_viewport):
        self._query_token += 1
        token = self._query_token
        self._pending = 0
        self._hit_paths = set()
        self._source_had_hit = False

        # 정규화 좌표를 viewport NDC [-1, 1]로 변환한다.
        ndc_x = norm_x * 2.0 - 1.0
        ndc_y = 1.0 - norm_y * 2.0

        for viewport_widget, _ in self._entries:
            viewport_api = viewport_widget.viewport_api
            if not viewport_api or not viewport_api.stage:
                continue

            origin, direction, t_min, t_max = self._generate_picking_ray(viewport_api, ndc_x, ndc_y)
            ray = rq.Ray(origin, direction, t_min, t_max)
            self._pending += 1
            self._rqi.submit_raycast_query(
                ray, functools.partial(self._on_raycast_result, token, viewport_widget == source_viewport)
            )

        if self._pending == 0:
            return

    def _on_raycast_result(self, token: int, is_source_viewport: bool, *callback_args):
        if token != self._query_token:
            return

        result = None
        for arg in callback_args:
            if hasattr(arg, "valid") and hasattr(arg, "get_target_usd_path"):
                result = arg
                break

        if result and result.valid:
            prim_path = result.get_target_usd_path()
            if prim_path:
                self._hit_paths.add(str(prim_path))
                if is_source_viewport:
                    self._source_had_hit = True

        self._pending -= 1
        if self._pending <= 0:
            self._apply_selection()

    def _apply_selection(self):
        selection = omni.usd.get_context().get_selection()
        if not selection:
            return

        if self._source_had_hit and self._hit_paths:
            selection.set_selected_prim_paths(sorted(self._hit_paths), True)
        else:
            selection.clear_selected_prim_paths()

    @staticmethod
    def _generate_picking_ray(viewport_api, ndc_x: float, ndc_y: float):
        # camera_manipulator의 orbit_target ray 생성 방식과 동일한 접근.
        ndc_near = (ndc_x, ndc_y, -1.0)
        ndc_far = (ndc_x, ndc_y, 1.0)
        view_proj_inv = (viewport_api.view * viewport_api.projection).GetInverse()

        origin = view_proj_inv.Transform(ndc_near)
        direction = view_proj_inv.Transform(ndc_far) - origin
        direction = direction.GetNormalized()

        t_min = 0.0
        t_max = float("inf")
        return ((origin[0], origin[1], origin[2]), (direction[0], direction[1], direction[2]), t_min, t_max)

    @staticmethod
    def _resolve_local_xy(click_target, x: float, y: float, width: float, height: float):
        # 1차: 콜백 좌표가 parent/global 기준일 수 있으므로,
        # 이 UI 빌드에서 제공하는 위젯 원점이 있으면 먼저 원점을 빼서 local로 맞춘다.
        # 이 처리를 direct-range 체크보다 먼저 해야,
        # 좌측 타일에서 x가 우연히 [0, width]에 들어가 local로 오인되는 문제를 줄일 수 있다.
        origin_attr_pairs = (
            ("screen_position_x", "screen_position_y"),
            ("screen_x", "screen_y"),
            ("position_x", "position_y"),
            ("computed_left", "computed_top"),
            ("global_x", "global_y"),
        )
        for ax, ay in origin_attr_pairs:
            ox = getattr(click_target, ax, None)
            oy = getattr(click_target, ay, None)
            if callable(ox):
                ox = ox()
            if callable(oy):
                oy = oy()
            if ox is None or oy is None:
                continue
            try:
                local_x = x - float(ox)
                local_y = y - float(oy)
            except Exception:
                continue
            if 0.0 <= local_x <= width and 0.0 <= local_y <= height:
                return local_x, local_y

        # 2차: 콜백이 이미 위젯 local 좌표를 주는 경우.
        if 0.0 <= x <= width and 0.0 <= y <= height:
            return x, y

        # 2x2 분할 fallback:
        # 일부 UI 빌드는 좌표를 더 큰 parent 좌표계로 보고한다.
        # 모듈로 연산으로 타일 local 범위로 접어 넣는다.
        folded_x = x % width
        folded_y = y % height
        if 0.0 <= folded_x <= width and 0.0 <= folded_y <= height:
            return folded_x, folded_y

        # 어느 해석으로도 viewport 영역에 들어오지 않으면 miss 처리.
        return None

    @staticmethod
    def _extract_wheel_delta(args) -> float:
        # 일반적인 시그니처 예:
        # - (x, y, wheel_delta)
        # - (x, y, wheel_delta, modifiers)
        # - (x, y, (0.0, +/-1.0, 0))
        if len(args) >= 3:
            # 3번째 인자는 보통 wheel 정보다. scalar/tuple/vector 모두 가능.
            delta = QuadViewportClickSync._coerce_delta(args[1])
            if abs(delta) > 1e-6:
                return delta
            if isinstance(args[1], (int, float)) and not isinstance(args[1], bool):
                return float(args[1])

        # fallback: tuple/vector 형태 인자를 우선 순회해 추출한다.
        for arg in args:
            if isinstance(arg, (list, tuple)):
                delta = QuadViewportClickSync._coerce_delta(arg)
                if abs(delta) > 1e-6:
                    return delta
        return 0.0

    @staticmethod
    def _extract_wheel_delta_from_mouse_event(mouse_event) -> float:
        for attr in ("wheel", "wheelDelta", "scroll", "scrollDelta", "delta", "value", "z", "dz"):
            if not hasattr(mouse_event, attr):
                continue
            value = getattr(mouse_event, attr)
            delta = QuadViewportClickSync._coerce_delta(value)
            if abs(delta) > 1e-6:
                return delta
        return 0.0

    @staticmethod
    def _coerce_delta(value) -> float:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (int, float)):
                return float(value[1])
            if len(value) >= 1 and isinstance(value[0], (int, float)):
                return float(value[0])
            return 0.0
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    def _apply_zoom_to_all_cameras(self, wheel_delta: float):
        # Windows wheel tick(보통 +/-120)을 논리 step으로 정규화한다.
        steps = wheel_delta / 120.0 if abs(wheel_delta) > 10.0 else wheel_delta
        if abs(steps) <= 1e-6:
            return

        # wheel 양수 => 줌인(초점거리 증가).
        zoom_factor = 1.1 ** steps

        for viewport_widget, _ in self._entries:
            viewport_api = viewport_widget.viewport_api
            if not viewport_api or not viewport_api.stage:
                continue

            camera_path = str(viewport_api.camera_path) if viewport_api.camera_path else ""
            if not camera_path:
                continue

            camera_prim = viewport_api.stage.GetPrimAtPath(camera_path)
            if not camera_prim or not camera_prim.IsValid():
                continue

            camera = UsdGeom.Camera(camera_prim)
            focal_attr = camera.GetFocalLengthAttr()
            focal = focal_attr.Get()
            if focal is None:
                focal = 50.0

            new_focal = max(self._zoom_min_focal, min(self._zoom_max_focal, float(focal) * zoom_factor))
            focal_attr.Set(new_focal)

    def _accept_zoom_delta(self, wheel_delta: float) -> bool:
        sign = 1 if wheel_delta > 0 else -1
        now = time.perf_counter()
        if sign == self._last_zoom_sign and (now - self._last_zoom_ts) < 0.008:
            return False
        self._last_zoom_sign = sign
        self._last_zoom_ts = now
        return True

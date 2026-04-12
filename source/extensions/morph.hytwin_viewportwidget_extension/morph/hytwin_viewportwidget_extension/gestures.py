import functools
import time
from typing import Callable, Optional

import omni.kit.raycast.query as rq
from omni.ui import scene as sc
from pxr import UsdGeom

__all__ = [
    "ViewportInteractionController",
    "ViewportClickGesture",
    "ViewportDoubleClickGesture",
    "ViewportRightDragGesture",
    "ViewportZoomGesture",
]

_ANY_MODIFIERS = 0xFFFFFFFF


class ViewportInteractionController:
    """뷰포트 상호작용 동작(선택/줌)을 담당한다.

    - 클릭/더블클릭: 입력된 정규화 좌표로 4개 뷰포트에 동일 raycast 수행
    - 휠 줌: 4개 카메라 focal length를 같은 비율로 변경
    """

    def __init__(
        self,
        get_viewports_fn: Callable[[], list],
        raycast_query_interface,
        get_selection_fn: Callable,
        zoom_min_focal: float = 5.0,
        zoom_max_focal: float = 500.0,
    ):
        self._get_viewports_fn = get_viewports_fn
        self._rqi = raycast_query_interface
        self._get_selection_fn = get_selection_fn
        self._zoom_min_focal = zoom_min_focal
        self._zoom_max_focal = zoom_max_focal

        self._ray_query_token = 0
        self._ray_pending = 0
        self._ray_hit_paths = set()
        self._ray_source_had_hit = False

    def handle_click(self, payload: dict):
        # 클릭된 타일의 정규화 좌표(norm_x, norm_y) 기준으로
        # 4개 뷰포트에 동일한 위치 raycast를 수행한다.
        if not payload:
            return
        self._raycast_all_viewports(
            norm_x=payload["norm_x"],
            norm_y=payload["norm_y"],
            source_viewport=payload["source_viewport"],
        )

    def handle_double_click(self, payload: dict):
        # 현재 정책: 더블클릭은 클릭과 동일한 선택 동작을 사용한다.
        self.handle_click(payload)

    def handle_zoom(self, wheel_delta: float):
        # wheel delta를 step으로 정규화한 뒤 focal length를 같은 배율로 조정한다.
        steps = wheel_delta / 120.0 if abs(wheel_delta) > 10.0 else wheel_delta
        if abs(steps) <= 1e-6:
            return

        zoom_factor = 1.1 ** steps
        for viewport in self._get_viewports_fn() or []:
            viewport_api = getattr(viewport, "viewport_api", None)
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

    def _raycast_all_viewports(self, norm_x: float, norm_y: float, source_viewport):
        # 입력 이벤트마다 token을 올려 이전 비동기 콜백과 구분한다.
        self._ray_query_token += 1
        token = self._ray_query_token
        self._ray_pending = 0
        self._ray_hit_paths = set()
        self._ray_source_had_hit = False

        ndc_x = norm_x * 2.0 - 1.0
        ndc_y = 1.0 - norm_y * 2.0

        for viewport in self._get_viewports_fn() or []:
            viewport_api = getattr(viewport, "viewport_api", None)
            if not viewport_api or not viewport_api.stage:
                continue

            origin, direction, t_min, t_max = self._generate_picking_ray(viewport_api, ndc_x, ndc_y)
            ray = rq.Ray(origin, direction, t_min, t_max)
            self._ray_pending += 1
            self._rqi.submit_raycast_query(
                ray, functools.partial(self._on_raycast_result, token, viewport == source_viewport)
            )

    def _on_raycast_result(self, token: int, is_source_viewport: bool, *callback_args):
        # 최신 token이 아니면 오래된 결과이므로 버린다.
        if token != self._ray_query_token:
            return

        result = None
        for arg in callback_args:
            if hasattr(arg, "valid") and hasattr(arg, "get_target_usd_path"):
                result = arg
                break

        if result and result.valid:
            prim_path = result.get_target_usd_path()
            if prim_path:
                self._ray_hit_paths.add(str(prim_path))
                if is_source_viewport:
                    self._ray_source_had_hit = True

        self._ray_pending -= 1
        if self._ray_pending <= 0:
            # 모든 raycast 결과 수집 후 선택을 한 번에 반영한다.
            self._apply_selection_from_raycast()

    def _apply_selection_from_raycast(self):
        # 소스 뷰포트에서도 hit가 있어야 선택을 반영한다.
        # 경계/오버레이 영역 클릭으로 타 뷰포트만 맞는 경우를 방지한다.
        selection = self._get_selection_fn() if self._get_selection_fn else None
        if not selection:
            return
        if self._ray_source_had_hit and self._ray_hit_paths:
            selection.set_selected_prim_paths(sorted(self._ray_hit_paths), True)
        else:
            selection.clear_selected_prim_paths()

    @staticmethod
    def _generate_picking_ray(viewport_api, ndc_x: float, ndc_y: float):
        ndc_near = (ndc_x, ndc_y, -1.0)
        ndc_far = (ndc_x, ndc_y, 1.0)
        view_proj_inv = (viewport_api.view * viewport_api.projection).GetInverse()

        origin = view_proj_inv.Transform(ndc_near)
        direction = view_proj_inv.Transform(ndc_far) - origin
        direction = direction.GetNormalized()
        return ((origin[0], origin[1], origin[2]), (direction[0], direction[1], direction[2]), 0.0, float("inf"))


class ViewportClickGesture(sc.ClickGesture):
    """클릭 제스처 래퍼."""

    def __init__(
        self,
        interaction_controller: ViewportInteractionController,
        payload_builder: Callable,
        mouse_button: int = 0,
        manager=None,
    ):
        self._interaction_controller = interaction_controller
        self._payload_builder = payload_builder
        super().__init__(
            name="quad_click",
            mouse_button=mouse_button,
            modifiers=_ANY_MODIFIERS,
            on_ended_fn=self._on_ended,
            manager=manager,
        )

    def _on_ended(self, sender):
        # sender를 공통 payload로 변환해 컨트롤러에 전달한다.
        payload = self._payload_builder(sender)
        if payload is None:
            return
        self._interaction_controller.handle_click(payload)


class ViewportDoubleClickGesture(sc.DoubleClickGesture):
    """더블클릭 제스처 래퍼."""

    def __init__(
        self,
        interaction_controller: ViewportInteractionController,
        payload_builder: Callable,
        mouse_button: int = 0,
        manager=None,
    ):
        self._interaction_controller = interaction_controller
        self._payload_builder = payload_builder
        super().__init__(
            name="quad_double_click",
            mouse_button=mouse_button,
            modifiers=_ANY_MODIFIERS,
            on_ended_fn=self._on_ended,
            manager=manager,
        )

    def _on_ended(self, sender):
        # DoubleClickGesture 종료 콜백에서 선택 로직을 실행한다.
        payload = self._payload_builder(sender)
        if payload is None:
            return
        self._interaction_controller.handle_double_click(payload)


class ViewportRightDragGesture(sc.DragGesture):
    """우클릭 드래그 제스처.

    드래그 시작/변경/종료 시점의 로컬/누적 delta를 계산해 콜백으로 전달한다.
    """

    def __init__(
        self,
        payload_builder: Callable,
        on_begin: Optional[Callable] = None,
        on_changed: Optional[Callable] = None,
        on_end: Optional[Callable] = None,
        mouse_button: int = 1,
        manager=None,
    ):
        self._payload_builder = payload_builder
        self._on_begin = on_begin
        self._on_changed = on_changed
        self._on_end = on_end
        self._drag_state = None

        super().__init__(
            name="quad_right_drag",
            mouse_button=mouse_button,
            modifiers=_ANY_MODIFIERS,
            on_began_fn=self._on_began_sender,
            on_changed_fn=self._on_changed_sender,
            on_ended_fn=self._on_ended_sender,
            manager=manager,
        )

    def _on_began_sender(self, sender):
        # 드래그 기준점(start/last)을 저장한다.
        payload = self._payload_builder(sender)
        if payload is None:
            return

        self._drag_state = {
            "source_viewport": payload["source_viewport"],
            "source_target": payload["click_target"],
            "start_local": (payload["local_x"], payload["local_y"]),
            "last_local": (payload["local_x"], payload["local_y"]),
        }
        if self._on_begin:
            self._on_begin(dict(payload))

    def _on_changed_sender(self, sender):
        # 프레임마다 local/ndc delta를 계산한다.
        if not self._drag_state:
            return

        payload = self._payload_builder(sender)
        if payload is None:
            return

        if (
            self._drag_state["source_viewport"] != payload["source_viewport"]
            or self._drag_state["source_target"] != payload["click_target"]
        ):
            return

        last_x, last_y = self._drag_state["last_local"]
        start_x, start_y = self._drag_state["start_local"]

        payload["drag_dx"] = payload["local_x"] - last_x
        payload["drag_dy"] = payload["local_y"] - last_y
        payload["drag_total_dx"] = payload["local_x"] - start_x
        payload["drag_total_dy"] = payload["local_y"] - start_y
        payload["drag_ndc_dx"] = (payload["drag_dx"] / payload["width"]) * 2.0
        payload["drag_ndc_dy"] = -(payload["drag_dy"] / payload["height"]) * 2.0
        payload["drag_total_ndc_dx"] = (payload["drag_total_dx"] / payload["width"]) * 2.0
        payload["drag_total_ndc_dy"] = -(payload["drag_total_dy"] / payload["height"]) * 2.0

        self._drag_state["last_local"] = (payload["local_x"], payload["local_y"])
        if self._on_changed:
            self._on_changed(payload)

    def _on_ended_sender(self, sender):
        # 종료 시 누적 delta를 계산해 마지막 콜백을 호출한다.
        if not self._drag_state:
            return

        payload = self._payload_builder(sender)
        if payload is not None:
            start_x, start_y = self._drag_state["start_local"]
            payload["drag_total_dx"] = payload["local_x"] - start_x
            payload["drag_total_dy"] = payload["local_y"] - start_y
            payload["drag_total_ndc_dx"] = (payload["drag_total_dx"] / payload["width"]) * 2.0
            payload["drag_total_ndc_dy"] = -(payload["drag_total_dy"] / payload["height"]) * 2.0
            if self._on_end:
                self._on_end(payload)

        self._drag_state = None


class ViewportZoomGesture(sc.ScrollGesture):
    """휠 줌 제스처 래퍼."""

    def __init__(
        self,
        interaction_controller: ViewportInteractionController,
        wheel_delta_extractor: Callable,
        manager=None,
    ):
        self._interaction_controller = interaction_controller
        self._wheel_delta_extractor = wheel_delta_extractor
        self._debouncer = ZoomDebouncer(debounce_window_sec=0.008)

        super().__init__(
            name="quad_scroll",
            on_changed_fn=self._on_changed,
            manager=manager,
        )

    def _on_changed(self, sender):
        # 휠 이벤트는 debounce 후 컨트롤러로 전달한다.
        wheel_delta = self._wheel_delta_extractor(sender)
        if abs(wheel_delta) <= 1e-6:
            return
        if not self._debouncer.accept(wheel_delta):
            return
        self._interaction_controller.handle_zoom(wheel_delta)


class ZoomDebouncer:
    """휠 이벤트 폭주를 완화하는 보조 클래스."""

    def __init__(self, debounce_window_sec: float = 0.008):
        self._debounce_window_sec = debounce_window_sec
        self._last_zoom_ts = 0.0
        self._last_zoom_sign = 0

    def accept(self, wheel_delta: float) -> bool:
        # 같은 방향의 매우 짧은 간격 이벤트는 하나로 간주한다.
        sign = 1 if wheel_delta > 0 else -1
        now = time.perf_counter()
        if sign == self._last_zoom_sign and (now - self._last_zoom_ts) < self._debounce_window_sec:
            return False
        self._last_zoom_sign = sign
        self._last_zoom_ts = now
        return True

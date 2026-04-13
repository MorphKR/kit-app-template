from typing import Callable

import omni.kit.raycast.query as rq


class ViewportInteractionController:
    """4분할 뷰포트의 커스텀 상호작용(클릭/더블클릭/우클릭 드래그)을 담당한다."""

    def __init__(
        self,
        get_viewports_fn: Callable[[], list],
        raycast_query_interface,
        get_selection_fn: Callable,
    ):
        self._get_viewports_fn = get_viewports_fn
        self._rqi = raycast_query_interface
        self._get_selection_fn = get_selection_fn

        self._ray_query_token = 0
        self._ray_pending = 0
        self._ray_hit_paths = set()
        self._ray_source_had_hit = False

    def handle_click(self, payload: dict):
        """입력된 정규화 좌표를 기준으로 4개 뷰포트에 동일 raycast를 수행한다."""
        if not payload:
            return
        self._raycast_all_viewports(
            norm_x=payload["norm_x"],
            norm_y=payload["norm_y"],
            source_viewport=payload["source_viewport"],
        )

    def handle_double_click(self, payload: dict):
        """현재 정책상 더블클릭도 클릭과 동일한 선택 로직을 사용한다."""
        self.handle_click(payload)

    def handle_right_drag_delta(self, dndc_x: float, dndc_y: float):
        """우클릭 드래그 delta를 4개 카메라에 동일하게 적용한다."""
        if abs(dndc_x) <= 1e-6 and abs(dndc_y) <= 1e-6:
            return

        yaw_delta = -dndc_x * 120.0
        pitch_delta = dndc_y * 120.0

        # pxr는 extension 로딩 시점에 비용이 커서 지연 import한다.
        from pxr import Gf, UsdGeom

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

            xform = UsdGeom.Xformable(camera_prim)
            rotate_op = None
            for op in xform.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                    rotate_op = op
                    break

            if rotate_op is None:
                rotate_op = xform.AddRotateXYZOp(UsdGeom.XformOp.PrecisionDouble)

            rot = rotate_op.Get()
            if rot is None:
                rot = Gf.Vec3d(0.0, 0.0, 0.0)

            rotate_op.Set(
                Gf.Vec3d(
                    float(rot[0]) + pitch_delta,
                    float(rot[1]) + yaw_delta,
                    float(rot[2]),
                )
            )

    def _raycast_all_viewports(self, norm_x: float, norm_y: float, source_viewport):
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
                ray,
                lambda *args, _token=token, _is_source=(viewport == source_viewport): self._on_raycast_result(
                    _token, _is_source, *args
                ),
            )

    def _on_raycast_result(self, token: int, is_source_viewport: bool, *callback_args):
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

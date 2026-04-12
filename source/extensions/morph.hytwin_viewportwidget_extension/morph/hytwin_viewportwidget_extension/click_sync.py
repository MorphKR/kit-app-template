import functools
from typing import List, Set, Tuple

import omni.kit.raycast.query as rq
import omni.usd


class QuadViewportClickSync:
    """Broadcast a click NDC coordinate to all viewports and raycast per camera."""

    def __init__(self):
        self._rqi = rq.acquire_raycast_query_interface()
        self._entries: List[Tuple[object, object]] = []
        self._query_token = 0
        self._pending = 0
        self._hit_paths: Set[str] = set()
        self._source_had_hit = False

    def destroy(self):
        for _, click_target in self._entries:
            click_target.set_mouse_pressed_fn(None)
        self._entries = []

    def register_viewport(self, viewport_widget, click_target):
        click_target.set_mouse_pressed_fn(
            lambda x, y, button, modifiers, target=click_target, source_vp=viewport_widget: self._on_mouse_pressed(
                source_vp, target, x, y, button, modifiers
            )
        )
        self._entries.append((viewport_widget, click_target))

    def _on_mouse_pressed(self, source_viewport, click_target, x, y, button, _modifiers):
        # Left click only.
        if int(button) != 0:
            return

        width = float(max(1.0, click_target.computed_width))
        height = float(max(1.0, click_target.computed_height))
        local_xy = self._resolve_local_xy(click_target, float(x), float(y), width, height)
        if local_xy is None:
            return
        local_x, local_y = local_xy

        # Ignore coordinates outside the clicked viewport region.
        if local_x < 0.0 or local_x > width or local_y < 0.0 or local_y > height:
            return

        # UI pixel -> normalized coords [0, 1], where bottom-right is (1, 1).
        norm_x = max(0.0, min(1.0, local_x / width))
        norm_y = max(0.0, min(1.0, local_y / height))
        print(
            f"Mouse local ({local_x:.1f}, {local_y:.1f}) / ({width:.1f}, {height:.1f}) "
            f"-> norm ({norm_x:.4f}, {norm_y:.4f})"
        )
        self._raycast_all_viewports(norm_x, norm_y, source_viewport)

    def _raycast_all_viewports(self, norm_x: float, norm_y: float, source_viewport):
        self._query_token += 1
        token = self._query_token
        self._pending = 0
        self._hit_paths = set()
        self._source_had_hit = False

        # Convert normalized coords to viewport NDC [-1, 1].
        ndc_x = norm_x * 2.0 - 1.0
        ndc_y = 1.0 - norm_y * 2.0

        for viewport_widget, _ in self._entries:
            viewport_api = viewport_widget.viewport_api
            if not viewport_api or not viewport_api.stage:
                continue

            print(f"Submitting raycast for viewport '{viewport_widget.name}' at NDC ({ndc_x:.3f}, {ndc_y:.3f})")
            origin, direction, t_min, t_max = self._generate_picking_ray(viewport_api, ndc_x, ndc_y)
            ray = rq.Ray(origin, direction, t_min, t_max)
            self._pending += 1
            self._rqi.submit_raycast_query(
                ray, functools.partial(self._on_raycast_result, token, viewport_widget == source_viewport)
            )

        if self._pending == 0:
            return

    def _on_raycast_result(self, token: int, is_source_viewport: bool, *callback_args):
        print(f"Received raycast callback with token {token} and args: {callback_args}")
        if token != self._query_token:
            print("Discarding raycast result from stale query token")
            return

        result = None
        for arg in callback_args:
            if hasattr(arg, "valid") and hasattr(arg, "get_target_usd_path"):
                result = arg
                break

        if result and result.valid:
            print(f"Raycast hit: {result.get_target_usd_path()}")
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
        # Same approach used by camera_manipulator orbit_target ray generation.
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
        # First: when callback coordinates are in a parent/global space,
        # subtract widget position if exposed by this ui build.
        # This must run before the direct-range check, otherwise left-side tiles
        # can be misinterpreted as already-local (because x still falls in [0, width]).
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

        # Next: callback already provides local widget coordinates.
        if 0.0 <= x <= width and 0.0 <= y <= height:
            return x, y

        # 2x2 split fallback:
        # Some ui builds report coordinates in a larger parent space.
        # Fold them back into the local tile range.
        folded_x = x % width
        folded_y = y % height
        if 0.0 <= folded_x <= width and 0.0 <= folded_y <= height:
            print(
                f"Using folded local coord from raw ({x:.1f}, {y:.1f}) "
                f"-> ({folded_x:.1f}, {folded_y:.1f})"
            )
            return folded_x, folded_y

        # If neither interpretation matches the viewport region, treat as miss.
        print(
            f"Ignoring click: unresolved local coord from raw ({x:.1f}, {y:.1f}) "
            f"for target size ({width:.1f}, {height:.1f})"
        )
        return None

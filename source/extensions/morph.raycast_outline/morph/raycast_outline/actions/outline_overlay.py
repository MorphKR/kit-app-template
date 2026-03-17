# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
뷰포트 아웃라인 Overlay 모듈

이벤트(Hover/Click)에 연결된 동작으로, events 모듈에서 prim_path를 받아
아웃라인을 그립니다.
"""

from typing import List, Optional, Tuple

import omni.kit.raycast.query
import omni.ui as ui
import omni.usd
from omni.ui import scene as sc
from omni.kit.viewport.utility import get_active_viewport_window

from .outline_draw import (
    HoverOutlineManipulator,
    OutlineModel,
    get_silhouette_edges,
)
from ..events.viewport_raycast_events import ViewportEventContext, ViewportEventManager


class OutlineOverlay(ViewportEventContext):
    """
    뷰포트 아웃라인 overlay를 관리하는 클래스.

    events 모듈에서 Hover 시 prim_path를 받아 실루엣 아웃라인을 그립니다.
    """

    def __init__(self, ext_id: str):
        self._ext_id = ext_id
        self._viewport_window = None
        self._scene_view = None
        self._raycast_query = None
        self._event_manager: Optional[ViewportEventManager] = None
        self._current_hover_prim_path: Optional[str] = None
        self._outline_model: Optional[OutlineModel] = None
        self._outline_manipulator: Optional[HoverOutlineManipulator] = None
        self._retry_sub = None
        self._pending_event_manager: Optional[ViewportEventManager] = None

    def get_viewport_api(self):
        vw = getattr(self, "_viewport_window", None)
        return vw.viewport_api if vw else None

    def get_raycast_query(self):
        return getattr(self, "_raycast_query", None)

    def register_handlers(self, manager: ViewportEventManager) -> None:
        """
        이 overlay용 Hover/Click 핸들러를 이벤트 매니저에 등록합니다.

        events 모듈은 독립적이므로, overlay 관련 로직은 여기서 등록합니다.
        """
        def on_hover(prim_path: Optional[str]) -> None:
            if prim_path:
                self.set_hover_outline(prim_path)
            else:
                self.clear_hover_outline()

        manager.register_hover(on_hover)

    def setup(self, event_manager: Optional[ViewportEventManager] = None) -> bool:
        """
        뷰포트 overlay를 설정합니다.

        extension.py에서 setup_overlay_events()로 생성한 event_manager를 전달받아
        이벤트와 연동된 overlay를 구성합니다.
        Screen은 scene 컨텍스트 내부에서 build_screen()으로 생성해야 합니다.

        Args:
            event_manager: ViewportEventManager (setup_overlay_events에서 반환)
        """
        viewport_window = get_active_viewport_window()
        if not viewport_window:
            if event_manager is not None:
                self._pending_event_manager = event_manager
            self._retry_viewport_setup()
            return False

        self._viewport_window = viewport_window
        self._raycast_query = omni.kit.raycast.query.acquire_raycast_query_interface()

        if event_manager is not None:
            self._event_manager = event_manager
        else:
            from ..events.viewport_raycast_events import ViewportEventManager
            self._event_manager = ViewportEventManager(self)
            self.register_handlers(self._event_manager)

        with viewport_window.get_frame(self._ext_id):
            with ui.ZStack():
                self._scene_view = sc.SceneView()
                with self._scene_view.scene:
                    # Screen은 scene 컨텍스트 내부에서 생성해야 제대로 등록됨
                    self._screen = self._event_manager.build_screen()
                    self._outline_model = OutlineModel()
                    self._outline_manipulator = HoverOutlineManipulator(model=self._outline_model)

            viewport_window.viewport_api.add_scene_view(self._scene_view)

        self._pending_event_manager = None
        return True

    def destroy(self) -> None:
        self.clear_hover_outline()
        self._destroy_overlay()
        if hasattr(self, "_retry_sub") and self._retry_sub:
            self._retry_sub = None

    def invalidate_outline(self) -> None:
        manip = getattr(self, "_outline_manipulator", None)
        if manip is not None:
            manip.invalidate()

    def get_event_manager(self) -> Optional[ViewportEventManager]:
        return getattr(self, "_event_manager", None)

    def set_hover_outline(self, prim_path: str) -> None:
        self._set_hover_outline(prim_path)

    def clear_hover_outline(self) -> None:
        self._clear_hover_outline()

    def _retry_viewport_setup(self) -> None:
        self._retry_count = 0
        self._max_retries = 300

        def on_update(event):
            if self._viewport_window:
                self._retry_sub = None
                return
            self._retry_count += 1
            if self._retry_count > self._max_retries:
                self._retry_sub = None
                return
            viewport_window = get_active_viewport_window()
            if viewport_window:
                em = getattr(self, "_pending_event_manager", None)
                self.setup(event_manager=em)
                self._retry_sub = None

        from omni.kit.app import get_app
        self._retry_sub = get_app().get_update_event_stream().create_subscription_to_pop(
            on_update, name="raycast_outline_viewport_retry"
        )

    def _get_camera_position(self, viewport_api) -> Optional[Tuple[float, float, float]]:
        try:
            view = viewport_api.view
            view_inv = view.GetInverse()
            origin = view_inv.Transform((0, 0, 0))
            return (float(origin[0]), float(origin[1]), float(origin[2]))
        except Exception:
            return None

    def _get_bbox_center(self, prim_path: str) -> Optional[Tuple[float, float, float]]:
        try:
            ctx = omni.usd.get_context()
            min_pt, max_pt = ctx.compute_path_world_bounding_box(prim_path)
            if min_pt is None or max_pt is None:
                return None
            cx = (float(min_pt[0]) + float(max_pt[0])) / 2
            cy = (float(min_pt[1]) + float(max_pt[1])) / 2
            cz = (float(min_pt[2]) + float(max_pt[2])) / 2
            return (cx, cy, cz)
        except Exception:
            return None

    def _get_view_direction(
        self, viewport_api, prim_path: str
    ) -> Optional[Tuple[float, float, float]]:
        cam = self._get_camera_position(viewport_api)
        center = self._get_bbox_center(prim_path)
        if not cam or not center:
            return None
        dx = center[0] - cam[0]
        dy = center[1] - cam[1]
        dz = center[2] - cam[2]
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length < 1e-8:
            return None
        return (dx / length, dy / length, dz / length)

    def _set_hover_outline(self, prim_path: str) -> None:
        if self._current_hover_prim_path == prim_path:
            return

        self._clear_hover_outline()
        self._current_hover_prim_path = prim_path

        viewport_window = getattr(self, "_viewport_window", None)
        viewport_api = viewport_window.viewport_api if viewport_window else None
        if not viewport_api:
            self._set_edges_immediate(prim_path, [])
            return

        view_dir = self._get_view_direction(viewport_api, prim_path)
        if not view_dir:
            self._set_edges_immediate(prim_path, [])
            return

        silhouette = get_silhouette_edges(prim_path, view_dir)
        self._set_edges_immediate(prim_path, silhouette)

    def _set_edges_immediate(
        self,
        prim_path: str,
        edges: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]],
    ) -> None:
        outline_model = getattr(self, "_outline_model", None)
        if outline_model is not None and self._current_hover_prim_path == prim_path:
            outline_model.set_edges(edges)

    def _clear_hover_outline(self) -> None:
        if not self._current_hover_prim_path:
            return

        outline_model = getattr(self, "_outline_model", None)
        if outline_model is not None:
            outline_model.set_edges([])

        self._current_hover_prim_path = None

    def _destroy_overlay(self) -> None:
        if self._viewport_window and self._scene_view:
            try:
                self._viewport_window.viewport_api.remove_scene_view(self._scene_view)
            except Exception:
                pass
            self._scene_view = None
        self._viewport_window = None
        self._raycast_query = None
        self._event_manager = None

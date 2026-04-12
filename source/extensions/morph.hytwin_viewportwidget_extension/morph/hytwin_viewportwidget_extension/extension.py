# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import asyncio

import omni.ext
import omni.ui as ui
import omni.usd
from omni.kit.widget.viewport import ViewportWidget
from pxr import Gf, UsdGeom

from .click_sync import QuadViewportClickSync
from .viewport_bridge import register_viewport_host, unregister_viewport_host


class MyExtension(omni.ext.IExt):
    """ViewportWidget 기반 2x2 분할 뷰포트를 구성한다."""

    def on_startup(self, _ext_id):
        print("[morph.hytwin_viewportwidget_extension] Extension startup")

        self._stage_sub = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event, name="morph.hytwin_viewportwidget_extension.stage_events"
        )
        self._window = None
        self._viewports = []
        self._viewport_host_keys = []
        self._ui_init_task = None
        self._click_sync = QuadViewportClickSync()
        self._click_sync.set_double_click_handler(self._on_viewport_double_click)
        self._click_sync.set_right_drag_handlers(
            on_begin=self._on_viewport_right_drag_begin,
            on_changed=self._on_viewport_right_drag_changed,
            on_end=self._on_viewport_right_drag_end,
        )
        self._camera_specs = (
            ("/World/Cam_1", Gf.Vec3d(-500.0, 350.0, 500.0), Gf.Vec3d(-25.0, -45.0, 0.0)),
            ("/World/Cam_2", Gf.Vec3d(500.0, 350.0, 500.0), Gf.Vec3d(-25.0, 45.0, 0.0)),
            ("/World/Cam_3", Gf.Vec3d(-500.0, 350.0, -500.0), Gf.Vec3d(-25.0, -135.0, 0.0)),
            ("/World/Cam_4", Gf.Vec3d(500.0, 350.0, -500.0), Gf.Vec3d(-25.0, 135.0, 0.0)),
        )

        if omni.usd.get_context().get_stage():
            event = type("StageEvent", (), {"type": int(omni.usd.StageEventType.OPENED)})()
            self._on_stage_event(event)

    def _on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.OPENED):
            self._schedule_ui_init()

    def _schedule_ui_init(self):
        if self._ui_init_task:
            return
        self._ui_init_task = asyncio.ensure_future(self._deferred_init_ui())

    async def _deferred_init_ui(self):
        try:
            # UI 지연 초기화 진입점만 5초 지연한다.
            await asyncio.sleep(5.0)

            self._ensure_stage_y_up()
            self._ensure_quad_cameras()
            self._create_ui_if_needed()
            self._bind_viewport_cameras()
            await self._dock_to_main_viewport_async()
        finally:
            self._ui_init_task = None

    def _ensure_stage_y_up(self):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        if UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.y:
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    def _ensure_quad_cameras(self):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        for camera_path, translate, rotate in self._camera_specs:
            camera_prim = UsdGeom.Camera.Define(stage, camera_path)
            xform = UsdGeom.Xformable(camera_prim)
            xform.ClearXformOpOrder()
            xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(translate)
            xform.AddRotateXYZOp(UsdGeom.XformOp.PrecisionDouble).Set(rotate)

    def _create_ui_if_needed(self):
        if self._window:
            return

        divider_size = 1
        divider_color = ui.color(0.25, 0.25, 0.25, 1.0)
        self._window = ui.Window("Quad Camera Panel", width=1200, height=800)
        with self._window.frame:
            with ui.VStack(spacing=0, height=ui.Fraction(1.0)):
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_interactive_viewport(self._camera_specs[0][0], "quad_0")
                    ui.Rectangle(width=divider_size, style={"background_color": divider_color})
                    self._create_interactive_viewport(self._camera_specs[1][0], "quad_1")
                ui.Rectangle(height=divider_size, style={"background_color": divider_color})
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_interactive_viewport(self._camera_specs[2][0], "quad_2")
                    ui.Rectangle(width=divider_size, style={"background_color": divider_color})
                    self._create_interactive_viewport(self._camera_specs[3][0], "quad_3")
        # 시작 시 안정성을 위해 도킹은 _dock_to_main_viewport_async에서 처리한다.

    async def _dock_to_main_viewport_async(self):
        if not self._window:
            return

        # 우선: 타겟 윈도우가 준비되면 Kit의 deferred dock 경로를 사용한다.
        self._window.deferred_dock_in("Viewport", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
        # fallback: Viewport 윈도우가 이미 열려 있으면 즉시 도킹한다.
        for window_name in ("Viewport", "Viewport 1"):
            main_viewport_window = ui.Workspace.get_window(window_name)
            if main_viewport_window:
                main_viewport_window.dock_tab_bar_visible = False
                main_viewport_window.dock_tab_bar_enabled = False
                self._window.dock_in(main_viewport_window, ui.DockPosition.SAME, 1.0)
                break

    def _bind_viewport_cameras(self):
        for viewport, (camera_path, _, _) in zip(self._viewports, self._camera_specs):
            viewport.viewport_api.camera_path = camera_path

    def _create_interactive_viewport(self, camera_path: str, host_key: str):
        click_target = ui.ZStack(width=ui.Fraction(1.0), height=ui.Fraction(1.0), skip_draw_when_clipped=True)
        with click_target:
            viewport = ViewportWidget(
                resolution="fill_frame",
                camera_path=camera_path,
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
            )
            # scene 기반 도구(예: section tool)가 오버레이 위젯을 붙일 frame.
            section_overlay_frame = ui.ScrollingFrame(
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                skip_draw_when_clipped=True,
                style={"ScrollingFrame": {"background_color": 0x00000000}},
            )
            # UI 빌드별 차이를 고려한 best-effort clipping 힌트.
            for attr_name in ("content_clipping", "clip_children", "clip_to_bounds"):
                try:
                    setattr(section_overlay_frame, attr_name, True)
                except Exception:
                    pass
            # 거의 투명한 rect로 hit-test는 유지하고 화면에는 보이지 않게 한다.
            hit_rect = ui.Rectangle(
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
                style={"background_color": ui.color(0.0, 0.0, 0.0, 0.001)},
            )

        # 컨테이너가 아니라 실제 overlay rect에 클릭을 연결한다.
        # 이렇게 해야 사분면별 local x/y 좌표가 더 안정적으로 들어온다.
        self._click_sync.register_viewport(viewport, hit_rect)
        register_viewport_host(host_key, viewport.viewport_api, section_overlay_frame)
        self._viewport_host_keys.append(host_key)
        self._viewports.append(viewport)

    def _on_viewport_double_click(self, event_payload: dict):
        # TODO: 원하는 더블클릭 동작을 이 함수에 구현하면 된다.
        # event_payload 예시 키: norm_x, norm_y, ndc_x, ndc_y, source_viewport
        pass

    def _on_viewport_right_drag_begin(self, event_payload: dict):
        # TODO: 우클릭 드래그 시작 시점 동작을 여기에 구현한다.
        # camera_manipulator와 유사하게 began 단계에서 기준 상태를 저장하는 용도.
        pass

    def _on_viewport_right_drag_changed(self, event_payload: dict):
        # TODO: 우클릭 드래그 중 동작을 여기에 구현한다.
        # 사용 가능한 delta 키: drag_dx, drag_dy, drag_ndc_dx, drag_ndc_dy
        pass

    def _on_viewport_right_drag_end(self, event_payload: dict):
        # TODO: 우클릭 드래그 종료 시점 동작을 여기에 구현한다.
        pass

    def on_shutdown(self):
        print("[morph.hytwin_viewportwidget_extension] Extension shutdown")

        self._stage_sub = None
        if self._ui_init_task:
            self._ui_init_task.cancel()
            self._ui_init_task = None
        if self._click_sync:
            self._click_sync.destroy()
            self._click_sync = None

        for viewport in self._viewports:
            viewport.destroy()
        self._viewports = []
        for host_key in self._viewport_host_keys:
            unregister_viewport_host(host_key)
        self._viewport_host_keys = []

        if self._window:
            self._window = None

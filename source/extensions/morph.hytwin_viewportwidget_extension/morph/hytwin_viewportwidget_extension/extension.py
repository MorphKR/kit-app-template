# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import asyncio

import carb.settings
import omni.ext
import omni.ui as ui
import omni.usd
from omni.kit.viewport.navigation.core import NAVIGATION_TOOL_OPERATION_ACTIVE
from omni.kit.viewport.navigation.camera_manipulator.navigation_scene import NavigationScene
from omni.kit.widget.viewport import ViewportWidget
from omni.ui import scene as sc
from pxr import Gf, UsdGeom

from .viewport_bridge import register_viewport_host, unregister_viewport_host


class MyExtension(omni.ext.IExt):
    """4분할 ViewportWidget 확장.

    이 확장은 ViewportWidget만 구성하고,
    카메라 제스처는 camera_manipulator의 NavigationScene을
    ViewportWidget overlay SceneView에 수동 attach해서 사용한다.
    """

    _UI_INIT_DELAY_SEC = 5.0
    _WINDOW_TITLE = "Quad Camera Panel"
    _WINDOW_WIDTH = 1200
    _WINDOW_HEIGHT = 800
    _DIVIDER_SIZE = 1

    _CAMERA_SPECS = (
        ("/World/Cam_1", Gf.Vec3d(-500.0, 350.0, 500.0), Gf.Vec3d(-25.0, -45.0, 0.0)),
        ("/World/Cam_2", Gf.Vec3d(500.0, 350.0, 500.0), Gf.Vec3d(-25.0, 45.0, 0.0)),
        ("/World/Cam_3", Gf.Vec3d(-500.0, 350.0, -500.0), Gf.Vec3d(-25.0, -135.0, 0.0)),
        ("/World/Cam_4", Gf.Vec3d(500.0, 350.0, -500.0), Gf.Vec3d(-25.0, 135.0, 0.0)),
    )

    # ------------------------------------------------------------------
    # 확장 생명주기
    # ------------------------------------------------------------------
    def on_startup(self, _ext_id):
        print("[morph.hytwin_viewportwidget_extension] Extension startup")

        # 상태/핸들 초기화
        self._window = None
        self._viewports = []
        self._overlay_frames = []
        self._navigation_entries = []
        self._viewport_host_keys = []
        self._ui_init_task = None

        self._stage_sub = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event,
            name="morph.hytwin_viewportwidget_extension.stage_events",
        )

        # 이미 stage가 열린 상태면 즉시 초기화 루틴을 시작한다.
        if omni.usd.get_context().get_stage():
            event = type("StageEvent", (), {"type": int(omni.usd.StageEventType.OPENED)})()
            self._on_stage_event(event)

    def on_shutdown(self):
        print("[morph.hytwin_viewportwidget_extension] Extension shutdown")

        # 비동기 초기화 태스크가 남아 있으면 먼저 정리한다.
        self._stage_sub = None
        if self._ui_init_task:
            self._ui_init_task.cancel()
            self._ui_init_task = None

        self._destroy_navigation_scenes()

        for viewport in self._viewports:
            viewport.destroy()
        self._viewports = []
        self._overlay_frames = []

        for host_key in self._viewport_host_keys:
            unregister_viewport_host(host_key)
        self._viewport_host_keys = []

        self._window = None

    def _on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.OPENED):
            self._schedule_ui_init()

    def _schedule_ui_init(self):
        if self._ui_init_task:
            return
        self._ui_init_task = asyncio.ensure_future(self._deferred_init_ui())

    async def _deferred_init_ui(self):
        try:
            # 앱 로딩 안정화를 위해 UI 생성을 약간 지연한다.
            await asyncio.sleep(self._UI_INIT_DELAY_SEC)
            self._ensure_stage_y_up()
            self._ensure_quad_cameras()
            self._create_ui_if_needed()
            self._bind_viewport_cameras()
            self._attach_navigation_scenes()
            await self._dock_to_main_viewport_async()
        finally:
            self._ui_init_task = None

    # ------------------------------------------------------------------
    # 카메라 설정
    # ------------------------------------------------------------------
    def _ensure_stage_y_up(self):
        # stage up-axis를 Y로 고정한다.
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return
        if UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.y:
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    def _ensure_quad_cameras(self):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        for camera_path, translate, rotate in self._CAMERA_SPECS:
            camera_prim = UsdGeom.Camera.Define(stage, camera_path)
            xform = UsdGeom.Xformable(camera_prim)
            xform.ClearXformOpOrder()
            xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(translate)
            xform.AddRotateXYZOp(UsdGeom.XformOp.PrecisionDouble).Set(rotate)

    def _bind_viewport_cameras(self):
        for viewport, (camera_path, _, _) in zip(self._viewports, self._CAMERA_SPECS):
            viewport.viewport_api.camera_path = camera_path

    def _attach_navigation_scenes(self):
        """각 ViewportWidget에 NavigationScene을 SceneView 기반으로 수동 attach한다."""
        self._destroy_navigation_scenes()
        """카메라 제스처가 작동하려면 NavigationScene이 활성화되어야 하는데, 이를 위해서는 먼저 NavigationTool의 operation이 orbit으로 설정되어야 한다."""
        carb.settings.get_settings().set(NAVIGATION_TOOL_OPERATION_ACTIVE, "orbit")

        for viewport, overlay_frame in zip(self._viewports, self._overlay_frames):
            viewport_api = getattr(viewport, "viewport_api", None)
            if viewport_api is None:
                continue
            with overlay_frame:
                scene_view = sc.SceneView()
                with scene_view.scene:
                    navigation_scene = NavigationScene(self._build_navigation_factory_args(viewport_api))
            viewport_api.add_scene_view(scene_view)
            self._navigation_entries.append(
                {
                    "viewport_api": viewport_api,
                    "scene_view": scene_view,
                    "navigation_scene": navigation_scene,
                }
            )

    def _build_navigation_factory_args(self, viewport_api):
        """NavigationScene 생성에 필요한 기본 인자만 구성한다."""
        return {
            "viewport_api": viewport_api,
            "usd_context_name": getattr(viewport_api, "usd_context_name", ""),
            "layer_provider": None,
        }

    def _destroy_navigation_scenes(self):
        for entry in self._navigation_entries:
            viewport_api = entry.get("viewport_api")
            scene_view = entry.get("scene_view")
            navigation_scene = entry.get("navigation_scene")
            try:
                if viewport_api and scene_view:
                    viewport_api.remove_scene_view(scene_view)
            except Exception:
                pass
            try:
                if navigation_scene:
                    navigation_scene.destroy()
            except Exception:
                pass
            try:
                if scene_view:
                    scene_view.destroy()
            except Exception:
                pass
        self._navigation_entries = []

    def _create_ui_if_needed(self):
        if self._window:
            return

        divider_color = ui.color(0.25, 0.25, 0.25, 1.0)
        self._window = ui.Window(self._WINDOW_TITLE, width=self._WINDOW_WIDTH, height=self._WINDOW_HEIGHT)

        with self._window.frame:
            with ui.VStack(spacing=0, height=ui.Fraction(1.0)):
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_viewport_tile(self._CAMERA_SPECS[0][0], "quad_0")
                    ui.Rectangle(width=self._DIVIDER_SIZE, style={"background_color": divider_color})
                    self._create_viewport_tile(self._CAMERA_SPECS[1][0], "quad_1")
                ui.Rectangle(height=self._DIVIDER_SIZE, style={"background_color": divider_color})
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_viewport_tile(self._CAMERA_SPECS[2][0], "quad_2")
                    ui.Rectangle(width=self._DIVIDER_SIZE, style={"background_color": divider_color})
                    self._create_viewport_tile(self._CAMERA_SPECS[3][0], "quad_3")

    def _create_viewport_tile(self, camera_path: str, host_key: str):
        tile = ui.ZStack(width=ui.Fraction(1.0), height=ui.Fraction(1.0), skip_draw_when_clipped=True)
        with tile:
            viewport = ViewportWidget(
                resolution="fill_frame",
                camera_path=camera_path,
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
            )
            overlay_frame = ui.ScrollingFrame(
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                skip_draw_when_clipped=True,
                style={"ScrollingFrame": {"background_color": 0x00000000}},
            )
            for attr_name in ("content_clipping", "clip_children", "clip_to_bounds"):
                try:
                    # 빌드별 속성 차이를 고려해 가능한 clipping 속성만 설정한다.
                    setattr(overlay_frame, attr_name, True)
                except Exception:
                    pass

        register_viewport_host(host_key, viewport.viewport_api, overlay_frame)

        self._viewport_host_keys.append(host_key)
        self._viewports.append(viewport)
        self._overlay_frames.append(overlay_frame)

    async def _dock_to_main_viewport_async(self):
        if not self._window:
            return

        # 메인 Viewport 탭에 같은 위치로 도킹한다.
        self._window.deferred_dock_in("Viewport", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)

        # fallback: 이미 열려 있는 viewport 창을 찾아 즉시 도킹한다.
        for window_name in ("Viewport", "Viewport 1"):
            main_viewport_window = ui.Workspace.get_window(window_name)
            if not main_viewport_window:
                continue
            # main_viewport_window.dock_tab_bar_visible = False
            # main_viewport_window.dock_tab_bar_enabled = False
            # self._window.dock_in(main_viewport_window, ui.DockPosition.SAME, 1.0)
            break

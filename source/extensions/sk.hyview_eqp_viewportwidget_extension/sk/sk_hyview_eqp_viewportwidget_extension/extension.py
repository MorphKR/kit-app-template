# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import asyncio

import omni.ext
import omni.ui as ui
import omni.usd
from omni.kit.widget.viewport import ViewportWidget
from pxr import Gf, UsdGeom

from .viewport_service import (
    ViewportService,
    ViewportWidgetHost,
)


class ViewportWidgetExtension(omni.ext.IExt):
    """4분할 ViewportWidget 확장.

    이 확장은 ViewportWidget 구성을 담당한다.
    """

    _UI_INIT_DELAY_SEC = 5.0
    _WINDOW_TITLE = "Quad Camera Panel"
    _WINDOW_WIDTH = 1200
    _WINDOW_HEIGHT = 800
    _DIVIDER_SIZE = 1

    _CAMERA_SPECS = (
        (0, "/camera_prims/Cam_1", Gf.Vec3d(10000.0, 0.0, 0.0), Gf.Vec3d(0.0, 180.0, 0.0)),
        (1, "/camera_prims/Cam_2", Gf.Vec3d(20000.0, 0.0, 0.0), Gf.Vec3d(0.0, 180.0, 0.0)),
        (2, "/camera_prims/Cam_3", Gf.Vec3d(30000.0, 0.0, 0.0), Gf.Vec3d(0.0, 180.0, 0.0)),
        (3, "/camera_prims/Cam_4", Gf.Vec3d(40000.0, 0.0, 0.0), Gf.Vec3d(0.0, 180.0, 0.0)),
    )

    # ------------------------------------------------------------------
    # 확장 생명주기
    # ------------------------------------------------------------------
    def on_startup(self, _ext_id):
        print("[sk.hyview_eqp_viewportwidget_extension] Extension startup")
        ViewportService.register_viewport_widget(self)

        self._section_ui_active = False
        # 상태/핸들 초기화
        self._viewports = []
        self._overlay_frames = []
        self._viewport_host_keys = []
        self._tab_payloads = {}
        self._ui_init_task = None

    def on_shutdown(self):
        print("[sk.hyview_eqp_viewportwidget_extension] Extension shutdown")
        ViewportService.unregister_viewport_widget()

        # 비동기 초기화 태스크가 남아 있으면 먼저 정리한다.
        if self._ui_init_task:
            self._ui_init_task.cancel()
            self._ui_init_task = None

        for viewport in self._viewports:
            viewport.destroy()
        self._viewports = []
        self._overlay_frames = []

        for host_key in self._viewport_host_keys:
            ViewportService.unregister_viewport_host(host_key)
        self._viewport_host_keys = []
        for payload in self._tab_payloads.values():
            window = payload.get("window")
            if window is not None:
                window.visible = False
        self._tab_payloads = {}

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

    def _ensure_quad_cameras(self, root_prim_path: str):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        for _, camera_path, translate, rotate in self._CAMERA_SPECS:
            camera_prim = UsdGeom.Camera.Define(stage, root_prim_path + camera_path)
            xform = UsdGeom.Xformable(camera_prim)
            xform.ClearXformOpOrder()
            xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(translate)
            xform.AddRotateXYZOp(UsdGeom.XformOp.PrecisionDouble).Set(rotate)

    def create_tab_viewport_hosts(self, tab_id: str, root_prim_path: str) -> list[ViewportWidgetHost]:
        existing = self._tab_payloads.get(tab_id)
        if existing:
            return existing["hosts"]

        self._ensure_stage_y_up()
        self._ensure_quad_cameras(root_prim_path)

        window, local_viewports, local_overlay_frames, local_host_keys = self._create_quad_window_payload(
            f"{self._WINDOW_TITLE} - {tab_id}", f"{tab_id}", f"{tab_id}_quad" , root_prim_path
        )

        hosts: list[ViewportWidgetHost] = []
        for host_key in local_host_keys:
            host = ViewportService.get_registered_viewport_host(host_key)
            if host:
                hosts.append(host)
            self._viewport_host_keys.append(host_key)

        self._viewports.extend(local_viewports)
        self._overlay_frames.extend(local_overlay_frames)
        self._tab_payloads[tab_id] = {"window": window, "hosts": hosts}

        self._dock_to_main_viewport(window)
        return hosts

    def _create_quad_window_payload(self, window_title: str, tab_id: str, host_prefix: str, root_prim_path: str):
        window = ui.Window(window_title, width=self._WINDOW_WIDTH, height=self._WINDOW_HEIGHT)
        local_viewports = []
        local_overlay_frames = []
        local_host_keys = []

        def _create_tile(camera_path: str, host_key: str):
            with ui.ZStack(
                width=ui.Fraction(1.0),
                height=ui.Fraction(1.0),
                skip_draw_when_clipped=True,
            ):
                viewport = ViewportWidget(
                    resolution="fill_frame",
                    camera_path=camera_path,
                    width=ui.Fraction(1.0),
                    height=ui.Fraction(1.0),
                )

                # A layer: orbit / clipping layer
                with ui.Frame(width=ui.Fraction(1.0), height=ui.Fraction(1.0)):
                    with ui.ZStack(width=ui.Fraction(1.0), height=ui.Fraction(1.0), content_clipping=True):
                        self.section_panel = ui.Frame(width=ui.Fraction(1.0),height=ui.Fraction(1.0))
                        overlay_frame = ui.ScrollingFrame(
                            width=ui.Fraction(1.0),
                            height=ui.Fraction(1.0),
                            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                            skip_draw_when_clipped=True,
                            style={"ScrollingFrame": {"background_color": 0x00000000}},
                            mouse_pressed_fn=self._on_a_mouse_pressed,
                            mouse_released_fn=self._on_a_mouse_released,
                            mouse_moved_fn=self._on_a_mouse_moved,
                        )

                        # overlay_frame 자체에는 mouse callback을 달지 말고
                        # 내부 input frame에 달아둡니다.


                # section layer: section plane / section UI layer
                # self.section_panel = ui.Frame(width=ui.Fraction(1.0),height=ui.Fraction(1.0),)
                # with self.section_panel:
                #     self.section_scene_view = sc.SceneView( width=ui.Fraction(1.0), height=ui.Fraction(1.0), child_windows_input=False,)


            prim_pos = self._CAMERA_SPECS[int(host_key.split("_")[-1]) - 1][2]
            prim_pos = Gf.Vec3d(prim_pos[0], prim_pos[1], prim_pos[2] + 500.0)  # 카메라 위치를 약간 뒤로 이동시켜 겹침 방지
            ViewportService.register_viewport_host(ViewportWidgetHost(key=host_key, viewport_api=viewport.viewport_api, frame=overlay_frame, ui_frame=self.section_panel, prim_pos=prim_pos))
            local_viewports.append(viewport)
            local_overlay_frames.append(overlay_frame)
            local_host_keys.append(host_key)

        divider_color = ui.color(0.25, 0.25, 0.25, 1.0)
        with window.frame:
            with ui.VStack(spacing=0, height=ui.Fraction(1.0)):
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    _create_tile(root_prim_path + self._CAMERA_SPECS[0][1], f"{host_prefix}_0")
                    ui.Rectangle(width=self._DIVIDER_SIZE, style={"background_color": divider_color})
                    _create_tile(root_prim_path + self._CAMERA_SPECS[1][1], f"{host_prefix}_1")
                ui.Rectangle(height=self._DIVIDER_SIZE, style={"background_color": divider_color})
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    _create_tile(root_prim_path + self._CAMERA_SPECS[2][1], f"{host_prefix}_2")
                    ui.Rectangle(width=self._DIVIDER_SIZE, style={"background_color": divider_color})
                    _create_tile(root_prim_path + self._CAMERA_SPECS[3][1], f"{host_prefix}_3")

        return window, local_viewports, local_overlay_frames, local_host_keys

    def _dock_to_main_viewport(self, window: ui.Window):
        if not window:
            return

        # 메인 Viewport 탭에 같은 위치로 도킹한다.
        window.deferred_dock_in("Viewport", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)

        # fallback: 이미 열려 있는 viewport 창을 찾아 즉시 도킹한다.
        for window_name in ("Viewport", "Viewport 1"):
            main_viewport_window = ui.Workspace.get_window(window_name)
            if not main_viewport_window:
                continue
            # main_viewport_window.dock_tab_bar_visible = False
            # main_viewport_window.dock_tab_bar_enabled = False
            # self._window.dock_in(main_viewport_window, ui.DockPosition.SAME, 1.0)
            break

    def _on_a_mouse_pressed(self, x, y, button, modifier):
        if self._section_ui_active:
            return

        print("[A] orbit pressed")
        # orbit 시작 로직


    def _on_a_mouse_released(self, x, y, button, modifier):
        if self._section_ui_active:
            return

        print("[A] orbit released")
        # orbit 종료 로직


    def _on_a_mouse_moved(self, x, y, button, modifier):
        if self._section_ui_active:
            return
        print("[A] orbit moved")
        # orbit drag 로직


    def _on_a_mouse_wheel(self, x, y, modifier):
        if self._section_ui_active:
            return

        print("[A] orbit wheel")
        # zoom 로직

    def _on_section_ui_mouse_pressed(self, x, y, button, modifier):
        self._section_ui_active = True
        print("[B UI] pressed")


    def _on_section_ui_mouse_released(self, x, y, button, modifier):
        print("[B UI] released")
        self._section_ui_active = False

    def _on_section_ui_mouse_wheel(self, x, y, modifier):
        self._section_ui_active = True
        print("[B UI] wheel")


    def _on_section_enable_clicked(self):
        print("Section Enable Clicked")


    def _on_section_ui_mouse_pressed(self, x, y, button, modifier):
        print("[B PANEL] pressed", x, y, button)
        self._section_ui_active = True


    def _on_section_ui_mouse_released(self, x, y, button, modifier):
        print("[B PANEL] released", x, y, button)
        self._section_ui_active = False


    def _on_section_button_pressed(self, x, y, button, modifier):
        print("[B BUTTON] pressed", x, y, button)
        self._section_ui_active = True


    def _on_section_button_released(self, x, y, button, modifier):
        print("[B BUTTON] released", x, y, button)


    def _on_section_enable_clicked(self):
        print("[B BUTTON] clicked")
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
import omni.kit.app
import omni.ui as ui
import omni.usd
from omni.kit.widget.viewport import ViewportWidget
from pxr import Gf, UsdGeom


class MyExtension(omni.ext.IExt):
    """Show a 2x2 viewport layout backed by ViewportWidget."""

    def on_startup(self, _ext_id):
        print("[morph.hytwin_viewportwidget_extension] Extension startup")

        self._stage_sub = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event, name="morph.hytwin_viewportwidget_extension.stage_events"
        )
        self._window = None
        self._viewports = []
        self._click_overlays = []
        self._ui_init_task = None
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
            # Delay only the deferred UI init entrypoint by 5 second.
            await asyncio.sleep(3.0)

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

        self._window = ui.Window("Quad Camera Panel", width=1200, height=800)
        with self._window.frame:
            with ui.VStack(spacing=0, height=ui.Fraction(1.0)):
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_pickable_viewport(self._camera_specs[0][0])
                    self._create_pickable_viewport(self._camera_specs[1][0])
                with ui.HStack(spacing=0, height=ui.Fraction(1.0)):
                    self._create_pickable_viewport(self._camera_specs[2][0])
                    self._create_pickable_viewport(self._camera_specs[3][0])
        # Docking is deferred to _dock_to_main_viewport_async for startup safety.

    async def _dock_to_main_viewport_async(self):
        if not self._window:
            return

        # Preferred: let Kit dock when target window becomes active/ready.
        self._window.deferred_dock_in("Viewport", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)

        # Fallback: if Viewport is already available now, dock immediately.
        for window_name in ("Viewport"):
            main_viewport_window = ui.Workspace.get_window(window_name)
            if main_viewport_window:
                main_viewport_window.flags = (
                    ui.WINDOW_FLAGS_NO_TITLE_BAR
                    | ui.WINDOW_FLAGS_NO_COLLAPSE
                    | ui.WINDOW_FLAGS_NO_MOVE
                    | ui.WINDOW_FLAGS_NO_RESIZE
                    | ui.WINDOW_FLAGS_NO_SCROLLBAR
                )
                self._window.dock_in(main_viewport_window, ui.DockPosition.SAME, 1.0)
                break

    def _bind_viewport_cameras(self):
        for viewport, (camera_path, _, _) in zip(self._viewports, self._camera_specs):
            viewport.viewport_api.camera_path = camera_path

    def _create_pickable_viewport(self, camera_path: str):
        click_target = ui.ZStack(width=ui.Fraction(1.0), height=ui.Fraction(1.0))
        with click_target:
            viewport = ViewportWidget(resolution="fill_frame", camera_path=camera_path)
            ui.Rectangle(style={"background_color": ui.color(0.0, 0.0, 0.0, 0.0)})

        click_target.set_mouse_pressed_fn(
            lambda x, y, button, modifiers, vp=viewport, overlay=click_target: self._on_viewport_pressed(
                vp, overlay, x, y, button, modifiers
            )
        )
        self._viewports.append(viewport)
        self._click_overlays.append(click_target)

    def _on_viewport_pressed(self, viewport: ViewportWidget, overlay: ui.Widget, x, y, button, _modifiers):
        width = float(max(1.0, overlay.computed_width))
        height = float(max(1.0, overlay.computed_height))
        ndc_x = (float(x) / width) * 2.0 - 1.0
        ndc_y = 1.0 - (float(y) / height) * 2.0

        pixel, mapped_viewport = viewport.viewport_api.map_ndc_to_texture_pixel((ndc_x, ndc_y))

        print(f"Clicked pixel: {pixel} on viewport with camera {viewport.viewport_api.camera_path}")
        print(f"Mapped pixel: {pixel} on viewport {mapped_viewport if mapped_viewport else 'None'}")
        if mapped_viewport is None:
            return

        picking_mode = getattr(omni.usd, "PickingMode", None)
        print(f"Using picking mode: {picking_mode}")
        replace_mode = getattr(picking_mode, "REPLACE", None) if picking_mode else None
        print(f"Using replace mode: {replace_mode}")
        if replace_mode is None:
            viewport.viewport_api.request_pick(pixel, pixel)
            return

        viewport.viewport_api.request_pick(pixel, pixel, replace_mode)

    def on_shutdown(self):
        print("[morph.hytwin_viewportwidget_extension] Extension shutdown")

        self._stage_sub = None
        if self._ui_init_task:
            self._ui_init_task.cancel()
            self._ui_init_task = None

        for viewport in self._viewports:
            viewport.destroy()
        self._viewports = []
        self._click_overlays = []

        if self._window:
            self._window = None

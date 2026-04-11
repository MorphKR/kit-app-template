# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import omni.ext
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
        self._viewports = []
        self._camera_specs = (
            ("/World/Cam_1", Gf.Vec3d(-500.0, 500.0, 350.0), Gf.Vec3f(55.0, 0.0, -135.0)),
            ("/World/Cam_2", Gf.Vec3d(500.0, 500.0, 350.0), Gf.Vec3f(55.0, 0.0, 135.0)),
            ("/World/Cam_3", Gf.Vec3d(-500.0, -500.0, 350.0), Gf.Vec3f(55.0, 0.0, -45.0)),
            ("/World/Cam_4", Gf.Vec3d(500.0, -500.0, 350.0), Gf.Vec3f(55.0, 0.0, 45.0)),
        )

        self._window = ui.Window("Quad Camera Panel", width=1200, height=800)
        with self._window.frame:
            with ui.VStack(spacing=2):
                with ui.HStack(spacing=2, height=ui.Fraction(1.0)):
                    self._viewports.append(ViewportWidget(resolution="fill_frame", camera_path=self._camera_specs[0][0]))
                    self._viewports.append(ViewportWidget(resolution="fill_frame", camera_path=self._camera_specs[1][0]))
                with ui.HStack(spacing=2, height=ui.Fraction(1.0)):
                    self._viewports.append(ViewportWidget(resolution="fill_frame", camera_path=self._camera_specs[2][0]))
                    self._viewports.append(ViewportWidget(resolution="fill_frame", camera_path=self._camera_specs[3][0]))

        self._ensure_quad_cameras()
        self._bind_viewport_cameras()

    def _on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.OPENED):
            self._ensure_quad_cameras()
            self._bind_viewport_cameras()

    def _ensure_quad_cameras(self):
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        for camera_path, translate, rotate in self._camera_specs:
            if stage.GetPrimAtPath(camera_path):
                continue

            camera_prim = UsdGeom.Camera.Define(stage, camera_path)
            xform = UsdGeom.XformCommonAPI(camera_prim)
            xform.SetTranslate(translate)
            xform.SetRotate(rotate, UsdGeom.XformCommonAPI.RotationOrderXYZ)

    def _bind_viewport_cameras(self):
        for viewport, (camera_path, _, _) in zip(self._viewports, self._camera_specs):
            viewport.viewport_api.camera_path = camera_path

    def on_shutdown(self):
        print("[morph.hytwin_viewportwidget_extension] Extension shutdown")

        self._stage_sub = None

        for viewport in self._viewports:
            viewport.destroy()
        self._viewports = []

        if self._window:
            self._window = None

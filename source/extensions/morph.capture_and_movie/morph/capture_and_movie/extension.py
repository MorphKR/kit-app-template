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
import omni.kit.async_engine
import omni.ui as ui
from pxr import Gf, UsdGeom

from .capture_image import (
    capture_active_viewport_to_png,
    capture_world_first_prim_thumbnail_to_png_async,
)
from .viewport_movie import ViewportMovieRecorder


class MyExtension(omni.ext.IExt):
    """Simple UI for viewport capture and /World first-prim thumbnail."""

    def on_startup(self, _ext_id):
        print("[morph.capture_and_movie] Extension startup")
        self._movie_recorder: ViewportMovieRecorder | None = None
        self._stage_sub = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event, name="wait_stage"
        )

        self._window = ui.Window("Create Capture And Movie", width=720, height=200)
        with self._window.frame:
            with ui.VStack(spacing=8):
                self._status_label = ui.Label("Capture viewport image or /World first prim thumbnail.")

                def on_click_capture():
                    path = capture_active_viewport_to_png()
                    if path:
                        self._status_label.text = f"Capture complete:\n{path}"
                    else:
                        self._status_label.text = "Capture failed (check logs)"

                async def _do_capture_thumbnail():
                    self._status_label.text = "Capturing thumbnail... (/World first prim frame)"
                    path = await capture_world_first_prim_thumbnail_to_png_async(settle_frames=2)
                    if path:
                        self._status_label.text = f"Thumbnail capture complete:\n{path}"
                    else:
                        self._status_label.text = "Thumbnail capture failed (/World prim or logs)"

                def on_click_capture_thumbnail():
                    _schedule_coroutine(_do_capture_thumbnail())

                def on_click_start_recording():
                    if self._movie_recorder and self._movie_recorder.is_recording:
                        self._status_label.text = "Recording is already in progress."
                        return
                    self._movie_recorder = ViewportMovieRecorder(fps=30, file_prefix="viewport_movie")
                    ok = self._movie_recorder.start()
                    if ok:
                        self._status_label.text = "Recording started..."
                    else:
                        self._status_label.text = "Failed to start recording (check logs)."

                async def _do_stop_recording():
                    if not self._movie_recorder:
                        self._status_label.text = "No active recording."
                        return
                    self._status_label.text = "Stopping recording..."
                    result = await self._movie_recorder.stop_async(encode_mp4=True)
                    self._movie_recorder = None
                    if not result:
                        self._status_label.text = "Recording stop failed (check logs)."
                        return
                    if result.mp4_path:
                        self._status_label.text = f"Recording complete:\n{result.mp4_path}"
                    else:
                        self._status_label.text = f"Frames saved:\n{result.frame_dir}"

                def on_click_stop_recording():
                    _schedule_coroutine(_do_stop_recording())

                with ui.HStack(spacing=8):
                    ui.Button("Capture Viewport Image", clicked_fn=on_click_capture)
                    ui.Button("Capture /World First Prim Thumbnail", clicked_fn=on_click_capture_thumbnail, width=260)
                    ui.Button("Start Recording", clicked_fn=on_click_start_recording, width=140)
                    ui.Button("Stop Recording", clicked_fn=on_click_stop_recording, width=140)

    def on_shutdown(self):
        if self._movie_recorder and self._movie_recorder.is_recording:
            _schedule_coroutine(self._movie_recorder.stop_async(encode_mp4=True))
            self._movie_recorder = None
        print("[morph.capture_and_movie] Extension shutdown")

    def _on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.OPENED):
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return

            self._create_camera(stage)

            # 한번만 실행
            self._stage_sub = None

    # 카메라 생성 함수
    def _create_camera(self, stage):
        if stage.GetPrimAtPath("/World/CaptureCamera"):
            return  # 이미 카메라가 존재하면 생성하지 않음
        camera = UsdGeom.Camera.Define(stage, "/World/CaptureCamera")
        xform = UsdGeom.XformCommonAPI(camera)
        xform.SetTranslate(Gf.Vec3d(500, 100, 500))
        xform.SetRotate((0.0, 45.0, 0.0), UsdGeom.XformCommonAPI.RotationOrderXYZ)


    def get_world_position(self, prim):
        xformable = UsdGeom.Xformable(prim)
        mat = xformable.ComputeLocalToWorldTransform(0)
        return mat.ExtractTranslation()

    # 카메라가 특정 위치를 바라보도록 설정하는 함수
    def _look_at(self, target_pos):
        camera = omni.usd.get_context().get_stage().GetPrimAtPath("/World/CaptureCamera")
        if not camera:
            print("Capture camera not found, cannot set look_at.")
            return
        xform = UsdGeom.Xformable(camera)
        mat = Gf.Matrix4d()
        mat.SetLookAt(
            self.get_world_position(camera),
            self.get_world_position(target_pos),
            Gf.Vec3d(0, 1, 0),
        )
        xform.ClearXformOpOrder()
        xform.AddTransformOp().Set(mat)


def _schedule_coroutine(coro):
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)
    except RuntimeError:
        return omni.kit.async_engine.run_coroutine(coro)

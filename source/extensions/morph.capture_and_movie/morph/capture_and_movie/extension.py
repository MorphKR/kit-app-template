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
import os

import omni.ext
import omni.kit.async_engine
import omni.kit.renderer_capture
import omni.kit.viewport.utility as vp_utils
import omni.ui as ui
from pxr import Gf, UsdGeom

from .capture_image import (
    capture_active_viewport_to_png,
    capture_world_first_prim_thumbnail_to_png_async,
)
from .viewport_movie import ViewportMovieRecorder

import omni.usd
import carb
import omni.kit.hydra_texture
from omni.kit.hydra_texture import acquire_hydra_texture_factory_interface
import omni.kit.app

class MyExtension(omni.ext.IExt):
    """Simple UI for viewport capture and /World first-prim thumbnail."""

    def on_startup(self, _ext_id):
        print("[morph.capture_and_movie] Extension startup")
        self.hydra = None
        self.hydra_camera_path = "/World/CaptureCamera"
        # Prefer a different Hydra engine than the main viewport to reduce visible interference.
        self.hydra_engine_candidates = ("pxr", "rtx")
        self.hydra_engine_name = None
        self._sub = None
        self._frame_future: asyncio.Future | None = None
        self._last_result_handle = None

        self._movie_recorder: ViewportMovieRecorder | None = None
        self._stage_sub = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event, name="wait_stage"
        )

        self._window = ui.Window("Create Capture And Movie", width=720, height=200)
        with self._window.frame:
            with ui.VStack(spacing=8):
                self._status_label = ui.Label("Capture viewport image or /World first prim thumbnail.")

                def on_click_capture():

                    asyncio.ensure_future(self.run())

                    """
                    path = capture_active_viewport_to_png()
                    if path:
                        self._status_label.text = f"Capture complete:\n{path}"
                    else:
                        self._status_label.text = "Capture failed (check logs)"
                    """
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
        self._sub = None
        self._frame_future = None
        if self.hydra is not None:
            self.hydra.updates_enabled = False
            self.hydra = None
        print("[morph.capture_and_movie] Extension shutdown")

    def _on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.OPENED):
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return

            self._create_camera(stage)

            # ?쒕쾲留??ㅽ뻾
            self._stage_sub = None

    # 移대찓???앹꽦 ?⑥닔
    def _create_camera(self, stage):
        if stage.GetPrimAtPath("/World/CaptureCamera"):
            return  # ?대? 移대찓?쇨? 議댁옱?섎㈃ ?앹꽦?섏? ?딆쓬
        camera = UsdGeom.Camera.Define(stage, "/World/CaptureCamera")
        xform = UsdGeom.XformCommonAPI(camera)
        xform.SetTranslate(Gf.Vec3d(500, 100, 500))
        xform.SetRotate((0.0, 45.0, 0.0), UsdGeom.XformCommonAPI.RotationOrderXYZ)


    def get_world_position(self, prim):
        xformable = UsdGeom.Xformable(prim)
        mat = xformable.ComputeLocalToWorldTransform(0)
        return mat.ExtractTranslation()

    # 移대찓?쇨? ?뱀젙 ?꾩튂瑜?諛붾씪蹂대룄濡??ㅼ젙?섎뒗 ?⑥닔
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

    def _ensure_hydra(self):
        # ?대? ?덉쑝硫??ъ궗??
        if self.hydra is not None:
            return self.hydra

        # 移대찓???놁쑝硫??앹꽦(?먮뒗 李얘린)
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return None
        if not stage.GetPrimAtPath(self.hydra_camera_path):
            UsdGeom.Camera.Define(stage, self.hydra_camera_path)

        # ?ш린??????踰??앹꽦
        self.hydra = self.create_offscreen(self.hydra_camera_path)
        return self.hydra

    def create_offscreen(self, camera_path):

        factory = acquire_hydra_texture_factory_interface()
        factory.startup()

        engine_name = self._choose_hydra_engine_name()
        self.hydra_engine_name = engine_name
        usd_context_name = ""

        usd_context = omni.usd.get_context(usd_context_name)

        if engine_name not in usd_context.get_attached_hydra_engine_names():
            omni.usd.add_hydra_engine(engine_name, usd_context)

        hydra_texture = factory.create_hydra_texture(
            name="capture_texture",
            width=1024,
            height=1024,
            usd_context_name=usd_context_name,
            usd_camera_path=camera_path,
            hydra_engine_name=engine_name,
            is_async=True
        )

        hydra_texture.is_async = True
        hydra_texture.updates_enabled = False  # Enable only while we wait for a frame.
        carb.log_info(f"[capture_and_movie] hydra offscreen engine: {engine_name}")

        return hydra_texture

    def _choose_hydra_engine_name(self) -> str:
        usd_context = omni.usd.get_context("")
        if not usd_context:
            return "rtx"

        try:
            attached = set(usd_context.get_attached_hydra_engine_names() or [])
        except Exception:
            attached = set()

        for name in self.hydra_engine_candidates:
            if name in attached:
                return name

        # If none are currently attached, try candidates in order; creation may still fail for unsupported engines.
        for name in self.hydra_engine_candidates:
            return name
        return "rtx"

    def attach_callback(self):
        if self.hydra is None or self._sub is not None:
            return

        stream = self.hydra.get_event_stream()

        def on_frame(event):
            payload = getattr(event, "payload", None) or {}
            result_handle = payload.get("result_handle", None)
            if result_handle is None:
                return
            self._last_result_handle = result_handle
            if self._frame_future and not self._frame_future.done():
                self._frame_future.set_result(result_handle)

        self._sub = stream.create_subscription_to_pop(on_frame, name="hydra_capture")

    async def capture_to_numpy(self):
        viewport_state = self._snapshot_active_viewport_state()
        hydra = self._ensure_hydra()
        if hydra is None:
            print("Hydra texture not initialized.")
            return None
        self.attach_callback()

        hydra.updates_enabled = True
        self._frame_future = asyncio.get_running_loop().create_future()
        print("Waiting for drawable frame...")

        try:
            result_handle = await asyncio.wait_for(self._frame_future, timeout=3.0)
            aov_info = hydra.get_aov_info(result_handle, "LdrColor", include_texture=True) or []

            drawable = None
            if aov_info and isinstance(aov_info[0], dict):
                texture_info = aov_info[0].get("texture")
                if isinstance(texture_info, dict):
                    drawable = texture_info.get("rp_resource")

            if drawable is None:
                drawable = hydra.get_drawable_ldr_resource(result_handle)

            if not drawable:
                print("LdrColor drawable is not available.")
                return None

            width = hydra.get_width()
            height = hydra.get_height()
            print("Drawable is ready (GPU resource acquired).")
            print("RpResource cannot be converted to numpy directly in this API.")
            return {
                "result_handle": result_handle,
                "width": width,
                "height": height,
                "rp_resource": drawable,
            }
        except asyncio.TimeoutError:
            print("Timed out waiting for Hydra drawable frame.")
            return None
        finally:
            hydra.updates_enabled = False
            self._frame_future = None
            self._restore_active_viewport_state(viewport_state)

    async def run(self):
        capture_info = await self.capture_to_numpy()
        if capture_info is None:
            print("Capture failed.")
            return
        print(
            f"Capture ready: result_handle={capture_info['result_handle']}, "
            f"size={capture_info['width']}x{capture_info['height']}"
        )
        png_path = os.path.join(os.getcwd(), "captures", "hydra_capture.png")
        ok = await self._save_capture_info_to_png(capture_info, png_path)
        if ok:
            print(f"PNG saved from rp_resource: {png_path}")
        else:
            print("PNG save failed from rp_resource.")

    async def _save_capture_info_to_png(self, capture_info: dict, file_path: str) -> bool:
        resource = capture_info.get("rp_resource") if isinstance(capture_info, dict) else None
        if resource is None:
            return False

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        capture_iface = omni.kit.renderer_capture.acquire_renderer_capture_interface()
        if not capture_iface:
            return False

        try:
            capture_iface.capture_next_frame_rp_resource_to_file(file_path, resource, None, None)
            await omni.kit.app.get_app().next_update_async()
            capture_iface.wait_async_capture(None)
            return os.path.exists(file_path)
        except Exception as e:  # noqa: BLE001
            carb.log_error(f"[capture_and_movie] failed to save rp_resource to png: {e!r}")
            return False

    def _snapshot_active_viewport_state(self) -> dict:
        vp = self._get_active_viewport_api()
        if not vp:
            return {}
        snap: dict = {"vp": vp}
        try:
            snap["camera_path"] = getattr(vp, "camera_path", None)
        except Exception:
            snap["camera_path"] = None
        try:
            snap["resolution"] = tuple(vp.resolution)
        except Exception:
            snap["resolution"] = None
        try:
            snap["render_product_path"] = getattr(vp, "render_product_path", None)
        except Exception:
            snap["render_product_path"] = None
        return snap

    def _restore_active_viewport_state(self, snap: dict) -> None:
        vp = snap.get("vp") if isinstance(snap, dict) else None
        if not vp:
            return
        try:
            cam = snap.get("camera_path", None)
            if cam is not None:
                vp.camera_path = cam
        except Exception:
            pass
        try:
            res = snap.get("resolution", None)
            if isinstance(res, (tuple, list)) and len(res) >= 2:
                vp.resolution = (int(res[0]), int(res[1]))
        except Exception:
            pass
        try:
            rp = snap.get("render_product_path", None)
            if rp is not None and hasattr(vp, "render_product_path"):
                vp.render_product_path = rp
        except Exception:
            pass

    @staticmethod
    def _get_active_viewport_api():
        try:
            if hasattr(vp_utils, "get_active_viewport"):
                vp = vp_utils.get_active_viewport()
                if vp:
                    return vp
        except Exception:
            pass
        try:
            if hasattr(vp_utils, "get_active_viewport_window"):
                win = vp_utils.get_active_viewport_window()
                if not win:
                    return None
                vp = getattr(win, "viewport_api", None)
                if vp is None and hasattr(win, "get_viewport_api"):
                    vp = win.get_viewport_api()
                return vp
        except Exception:
            pass
        return None


def _schedule_coroutine(coro):
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)
    except RuntimeError:
        return omni.kit.async_engine.run_coroutine(coro)

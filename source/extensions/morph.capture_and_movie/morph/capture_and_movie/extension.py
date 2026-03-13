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

from .capture_image import (
    capture_active_viewport_to_png,
    capture_world_first_prim_thumbnail_to_png_async,
)


class MyExtension(omni.ext.IExt):
    """Simple UI for viewport capture and /World first-prim thumbnail."""

    def on_startup(self, _ext_id):
        print("[morph.capture_and_movie] Extension startup")

        self._window = ui.Window("Create Capture And Movie", width=560, height=160)
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
                    asyncio.ensure_future(_do_capture_thumbnail())

                with ui.HStack(spacing=8):
                    ui.Button("Capture Viewport Image", clicked_fn=on_click_capture)
                    ui.Button("Capture /World First Prim Thumbnail", clicked_fn=on_click_capture_thumbnail, width=260)

    def on_shutdown(self):
        print("[morph.capture_and_movie] Extension shutdown")

# Copyright (c) 2018-2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

import carb
import omni.kit.app
import omni.kit.viewport.utility as vp_utils
import omni.ui as ui

from ..common import SectionManager, Singleton
from .section_scene import SectionScene


@Singleton
class SectionTool:
    # 확장 전역에서 공유하는 섹션 씬 관리자.
    # 여러 뷰포트가 열려 있는 경우 viewport별 SectionScene을 생성/동기화한다.
    def __init__(self):
        self._scenes = {}
        self._ext_id = None
        self._visible = False
        self._post_update_sub = None

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):
        # 뷰포트 감시를 중지하고 생성된 모든 scene 리소스를 해제한다.
        self._stop_viewport_watch()
        for scene in self._scenes.values():
            scene.destroy()
        self._scenes.clear()

    def reset(self):
        # 모든 viewport scene의 모델 상태를 초기화한다.
        for scene in self._scenes.values():
            scene.refresh()

    @property
    def visible(self):  # pragma: no cover
        return bool(self._scenes)

    @property
    def scene(self):
        # Backward-compatible accessor used by legacy call sites.
        for scene in self._scenes.values():
            return scene
        return None

    @property
    def scenes(self):
        return list(self._scenes.values())

    def _get_viewport_key(self, viewport_window):
        if viewport_window is None:
            return None
        # Do not depend on viewport name/title: names may change by locale/user.
        return f"id:{id(viewport_window)}"

    def _get_visible_viewport_windows(self):
        windows = []

        # Utility API names differ by Kit version, so probe defensively.
        try:
            if hasattr(vp_utils, "get_viewport_window_instances"):
                windows = list(vp_utils.get_viewport_window_instances() or [])
            elif hasattr(vp_utils, "get_viewport_windows"):
                windows = list(vp_utils.get_viewport_windows() or [])
            elif hasattr(vp_utils, "get_num_viewports") and hasattr(vp_utils, "get_viewport_window"):
                count = int(vp_utils.get_num_viewports() or 0)
                windows = [vp_utils.get_viewport_window(i) for i in range(count)]
        except Exception:
            windows = []

        # Workspace fallback for builds where utility API returns only active viewport.
        try:
            if hasattr(ui.Workspace, "get_windows"):
                for win in ui.Workspace.get_windows() or []:
                    if win and hasattr(win, "viewport_api") and hasattr(win, "get_frame"):
                        windows.append(win)
        except Exception:
            pass

        if not windows:
            active = vp_utils.get_active_viewport_window()
            if active:
                windows = [active]

        # Unique by object id.
        unique = {}
        for win in windows:
            if win:
                unique[id(win)] = win
        windows = list(unique.values())

        filtered = []
        for win in windows:
            if not win:
                continue
            try:
                if hasattr(win, "visible") and not bool(win.visible):
                    continue
            except Exception:
                pass
            filtered.append(win)
        return filtered

    def _sync_viewport_scenes(self):
        # 현재 보이는 뷰포트 목록과 _scenes를 맞춰 생성/삭제를 동기화한다.
        if not self._ext_id:
            return

        live_keys = set()
        for viewport_window in self._get_visible_viewport_windows():
            key = self._get_viewport_key(viewport_window)
            if not key:
                continue
            live_keys.add(key)
            if key not in self._scenes:
                # 섹션 위젯 prim을 viewport 키 단위로 보장한 뒤 scene을 생성한다.
                SectionManager().get_section_widget_prim(create_if_not_exist=True, viewport_key=key)
                self._scenes[key] = SectionScene(self._ext_id, viewport_window=viewport_window, viewport_key=key)
                carb.log_info(f"[SectionTool] Section scene created for viewport: {key}")
            self._scenes[key].show(True)

        stale_keys = [k for k in self._scenes.keys() if k not in live_keys]
        for key in stale_keys:
            self._scenes[key].destroy()
            del self._scenes[key]
            carb.log_info(f"[SectionTool] Section scene removed for viewport: {key}")

    def _start_viewport_watch(self):
        # 매 프레임 post-update에서 viewport 변화(생성/닫힘/표시)를 감시한다.
        if self._post_update_sub is not None:
            return
        stream = omni.kit.app.get_app().get_update_event_stream()
        self._post_update_sub = stream.create_subscription_to_pop(self._on_post_update, name="hytwin_section_vp_sync")

    def _stop_viewport_watch(self):
        try:
            if self._post_update_sub:
                self._post_update_sub.unsubscribe()
        except Exception:
            pass
        self._post_update_sub = None

    def _on_post_update(self, _):
        # 섹션이 표시 상태일 때만 viewport 동기화를 수행해 비용을 줄인다.
        if self._visible:
            self._sync_viewport_scenes()

    # 섹션 활성화 시 보이는 모든 viewport에 scene을 붙이고,
    # 비활성화 시 scene은 유지하되 표시/기즈모만 끈다.
    def set_visibility(self, value: bool, ext_id: str) -> None:
        self._visible = bool(value)
        self._ext_id = ext_id
        if value:
            self._sync_viewport_scenes()
            self._start_viewport_watch()
        else:
            self._stop_viewport_watch()
            for scene in self._scenes.values():
                scene.show(False)

        self.show_section_gizmo(value)

    def show_section_gizmo(self, value: bool):
        # 모든 viewport scene에 동일한 gizmo 표시 상태를 전달한다.
        for scene in self._scenes.values():
            scene.show_section_gizmo(value)

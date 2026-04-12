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
    """뷰포트 기반 섹션 도구의 생명주기를 관리한다."""
    def __init__(self):
        """인스턴스의 초기 상태를 구성한다."""
        self._scenes = {}
        self._ext_id = None
        self._visible = False
        self._post_update_sub = None

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):
        self._stop_viewport_watch()
        for scene in self._scenes.values():
            scene.destroy()
        self._scenes.clear()

    def reset(self):
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
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return list(self._scenes.values())

    def _get_viewport_key(self, viewport_window):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        if viewport_window is None:
            return None
        host_key = getattr(viewport_window, "host_key", None)
        if host_key:
            return f"host:{host_key}"
        # Do not depend on viewport name/title: names may change by locale/user.
        return f"id:{id(viewport_window)}"

    def _get_external_viewport_hosts(self):
        hosts = []
        try:
            from morph.hytwin_viewportwidget_extension.viewport_bridge import get_registered_viewport_hosts

            for host in get_registered_viewport_hosts() or []:
                if host and hasattr(host, "viewport_api") and hasattr(host, "get_frame"):
                    hosts.append(host)
        except Exception:
            pass
        return hosts

    def _get_visible_viewport_windows(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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

        # Add custom viewport hosts (e.g. ViewportWidget tiles).
        windows.extend(self._get_external_viewport_hosts())

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
        """해당 함수의 핵심 로직을 수행한다."""
        if not self._ext_id:
            return

        live_keys = set()
        for viewport_window in self._get_visible_viewport_windows():
            key = self._get_viewport_key(viewport_window)
            if not key:
                continue
            live_keys.add(key)
            if key not in self._scenes:
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
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        if self._visible:
            self._sync_viewport_scenes()

    def set_visibility(self, value: bool, ext_id: str) -> None:
        """입력값을 내부 상태와 설정에 반영한다."""
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
        """표시 상태를 변경하고 연관 상태를 동기화한다."""
        for scene in self._scenes.values():
            scene.show_section_gizmo(value)

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

from ..common import SectionManager
from .section_scene import SectionScene


class SectionTool:
    """뷰포트별 섹션 씬과 표시 라이프사이클을 관리한다."""
    _instance = None

    @classmethod
    def get_instance(cls):
        """외부 호출용 단일 인스턴스를 반환한다."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_scenes(cls):
        """외부 호출용으로 현재 활성 scene 목록을 반환한다."""
        return cls.get_instance().scenes

    def __init__(self):
        """섹션 도구 상태를 초기화한다."""
        self._scenes = {}
        self._ext_id = None
        self._visible = False
        self._post_update_sub = None

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):
        self._stop_viewport_watch()
        self._destroy_all_scenes()

    def reset(self):
        for scene in self._scenes.values():
            scene.refresh()

    def _destroy_all_scenes(self):
        for scene in self._scenes.values():
            scene.destroy()
        self._scenes.clear()

    @property
    def visible(self):  # pragma: no cover
        return bool(self._scenes)

    @property
    def scene(self):
        # 레거시 호출부 호환을 위한 단일 scene 접근자
        for scene in self._scenes.values():
            return scene
        return None

    @property
    def scenes(self):
        """현재 활성화된 섹션 씬 목록을 반환한다."""
        return list(self._scenes.values())

    def _get_viewport_key(self, viewport_window):
        """viewport 인스턴스를 안정적인 키 문자열로 변환한다."""
        if viewport_window is None:
            return None
        # ViewportWidget bridge host는 host_key를 제공한다.
        # ViewportWindow ID와 충돌하지 않게 별도 네임스페이스를 사용한다.
        host_key = getattr(viewport_window, "host_key", None)
        if host_key:
            return f"host:{host_key}"
        # viewport 이름/타이틀은 환경에 따라 달라질 수 있으므로 사용하지 않는다.
        return f"id:{id(viewport_window)}"

    def _get_external_viewport_hosts(self):
        hosts = []
        try:
            # bridge extension에 등록된 ViewportWidget host 목록을 조회한다.
            # 각 host는 viewport_api/get_frame 인터페이스를 제공해야 한다.
            from morph.hytwin_viewportwidget_extension.viewport_bridge import get_registered_viewport_hosts

            for host in get_registered_viewport_hosts() or []:
                if host and hasattr(host, "viewport_api") and hasattr(host, "get_frame"):
                    hosts.append(host)
        except Exception:
            pass
        return hosts

    def _get_visible_viewport_windows(self):
        """현재 표시 중인 viewport window/host를 수집한다."""
        windows = []

        # Kit 버전에 따라 utility API 이름이 달라 방어적으로 조회한다.
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

        # 일부 빌드에서 utility API가 active viewport만 반환하는 경우를 대비한 fallback
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

        # 사용자 정의 viewport host(예: ViewportWidget 타일) 추가
        windows.extend(self._get_external_viewport_hosts())

        # 객체 id 기준으로 중복 제거
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
        """실제 viewport 목록과 섹션 씬 목록을 동기화한다."""
        if not self._ext_id:
            return

        live_keys = set()
        for viewport_window in self._get_visible_viewport_windows():
            key = self._get_viewport_key(viewport_window)
            if not key:
                continue
            live_keys.add(key)
            if key not in self._scenes:
                # viewport_key별로 section prim/scene를 분리 관리한다.
                SectionManager.get_instance().get_section_widget_prim(create_if_not_exist=True, viewport_key=key)
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
        """도구가 표시 중일 때 프레임마다 씬 동기화를 수행한다."""
        if self._visible:
            self._sync_viewport_scenes()

    @classmethod
    def set_visibility(cls, value: bool, ext_id: str) -> None:
        """섹션 도구 표시 상태를 전환한다."""
        cls.get_instance()._set_visibility(value, ext_id)

    def _set_visibility(self, value: bool, ext_id: str) -> None:
        """섹션 도구 표시 상태를 전환한다."""
        self._visible = bool(value)
        self._ext_id = ext_id
        if value:
            # 비활성화에서 재활성화될 때 현재 viewport 상태 기준으로 sceneview를 다시 생성한다.
            self._sync_viewport_scenes()
            self._start_viewport_watch()
        else:
            self._stop_viewport_watch()
            # 입력 충돌 방지를 위해 숨김(show=False) 대신 sceneview를 완전히 제거한다.
            self._destroy_all_scenes()

        self._show_section_gizmo(value)

    @classmethod
    def show_section_gizmo(cls, value: bool):
        """모든 활성 섹션 씬의 기즈모 표시 상태를 전환한다."""
        cls.get_instance()._show_section_gizmo(value)

    def _show_section_gizmo(self, value: bool):
        """모든 활성 섹션 씬의 기즈모 표시 상태를 전환한다."""
        for scene in self._scenes.values():
            scene.show_section_gizmo(value)

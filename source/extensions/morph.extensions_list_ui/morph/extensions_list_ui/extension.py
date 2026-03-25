# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import traceback
from pathlib import Path
from typing import List

import carb.input
import omni.ext
import omni.kit.app
import omni.ui as ui

# -----------------------------------------------------------------------------
# morph.extensions_list_ui
# -----------------------------------------------------------------------------
# 이 확장은 `config/extension.toml`의 `dependencies`에서 `morph.*` 형태의
# 의존 확장 목록을 읽고,
# 전역 단축키(`F8`)를 통해 해당 의존 확장들의 "UI window 가시성"을
# 일괄 토글합니다.


class MyExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        """OmniKit 확장 시작 훅.

        1) config에서 morph 의존 확장 목록을 로드
        2) 의존 확장을 로드/활성 상태로 만들어둠
        3) 전역 입력(F8) 구독을 등록
        """
        print("[morph.extensions_list_ui] Extension startup")

        ui.Workspace.get_window("Viewport").dock_tab_bar_visible = False
        ui.Workspace.get_window("Viewport").dock_tab_bar_enabled = False

        self._alive = True
        self._config_toml_path = (Path(__file__).resolve().parents[2] / "config" / "extension.toml")
        self._input = None
        self._input_sub_id = None
        self._m_combo_latched = False
        self._deps_ui_visible = False
        self._morph_dependencies = self._load_morph_dependencies()

        self._ensure_all_morph_dependencies_enabled()
        # 시작 시에는 모든 의존 확장의 UI window를 숨김 상태로 둡니다.
        # (F8 토글 전 기본 상태 보장)
        self._deps_ui_visible = False
        for dep_id in self._morph_dependencies:
            try:
                dep_window = self._find_dep_window(dep_id)
                if dep_window is not None:
                    dep_window.visible = False
            except Exception:
                traceback.print_exc()
        self._register_shortcut_listener()

    def on_shutdown(self):
        """OmniKit 확장 종료 훅: 입력 구독 해제 및 상태 정리."""
        print("[morph.extensions_list_ui] Extension shutdown")
        self._deregister_shortcut_listener()
        self._alive = False

    def _load_morph_dependencies(self) -> List[str]:
        """`config/extension.toml`에서 `dependencies`의 `morph.*` 항목을 읽습니다."""
        try:
            if not self._config_toml_path.exists():
                return []

            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore

            with self._config_toml_path.open("rb") as f:
                data = tomllib.load(f)

            deps = data.get("dependencies", {})
            print(f"[morph.extensions_list_ui] Loaded morph dependencies: {deps}")
            if isinstance(deps, dict):
                # `dependencies`의 key를 extension id로 가정하고, morph.*만 대상으로 제한합니다.
                return sorted(dep for dep in deps.keys() if dep.startswith("morph."))
        except Exception:
            traceback.print_exc()

        return []

    def _get_extension_manager(self):
        """extension enable/disable을 제어하는 OmniKit Extension Manager를 가져옵니다."""
        try:
            app = omni.kit.app.get_app()
            if app is None:
                return None
            return app.get_extension_manager()
        except Exception:
            traceback.print_exc()
            return None

    def _set_extension_enabled(self, dep_id: str, enabled: bool) -> bool:
        """특정 의존 확장을 enabled/disabled 상태로 전환합니다(가능하면 immediate 적용)."""
        em = self._get_extension_manager()
        if em is None:
            return False

        try:
            if hasattr(em, "set_extension_enabled_immediate"):
                em.set_extension_enabled_immediate(dep_id, enabled)
            else:
                em.set_extension_enabled(dep_id, enabled)
            return True
        except Exception:
            traceback.print_exc()
            return False

    def _ensure_all_morph_dependencies_enabled(self):
        """빠른 토글을 위해 morph 의존 확장들을 모두 로드(활성) 상태로 만듭니다."""
        for dep_id in self._morph_dependencies:
            self._set_extension_enabled(dep_id, True)

    def _all_morph_dependencies_enabled(self) -> bool:
        # 의존 확장 자체는 유지(loaded)하고, UI는 window.visible로만 토글합니다.
        return bool(self._deps_ui_visible)

    def _register_shortcut_listener(self):
        """전역 입력 인터페이스를 구독해서 F8 핫키를 감지합니다."""
        try:
            self._input = carb.input.acquire_input_interface()
            self._input_sub_id = self._input.subscribe_to_input_events(self._on_input_event, order=0)
            print("[morph.extensions_list_ui] global shortcut registered: F8")
        except Exception:
            traceback.print_exc()
            return

    def _deregister_shortcut_listener(self):
        """전역 입력 구독을 해제합니다(종료 시 누수 방지)."""
        try:
            if self._input is not None and self._input_sub_id is not None:
                self._input.unsubscribe_to_input_events(self._input_sub_id)
        except Exception:
            traceback.print_exc()
        self._input_sub_id = None
        self._input = None

    def _on_input_event(self, event, *_) -> bool:
        """입력 이벤트 콜백: F8를 누르면 모든 morph 의존 window 가시성을 토글합니다."""
        try:
            if event.deviceType != carb.input.DeviceType.KEYBOARD:
                return True

            key_event = event.event
            if not isinstance(key_event, carb.input.KeyboardEvent):
                return True

            key_press = carb.input.KeyboardEventType.KEY_PRESS
            key_repeat = carb.input.KeyboardEventType.KEY_REPEAT
            key_release = carb.input.KeyboardEventType.KEY_RELEASE

            f8_keys = (carb.input.KeyboardInput.F8,)
            key_is_f8 = key_event.input in f8_keys

            if not key_is_f8:
                return True

            if key_event.type == key_release:
                # KEY_RELEASE에서 latch를 풀어 다음 입력을 정상적으로 감지할 수 있게 합니다.
                self._m_combo_latched = False
                return True

            if key_event.type not in (key_press, key_repeat):
                return True

            if key_is_f8 and not self._m_combo_latched:
                # KEY_REPEAT로 인해 같은 키가 여러 번 들어올 수 있으므로 latch로 중복 토글을 방지합니다.
                self._m_combo_latched = True
                self._toggle_all_dependencies()
        except Exception:
            traceback.print_exc()
        return True

    def _toggle_all_dependencies(self):
        """F8 핫키 처리: UI 가시성 상태를 반전하고 의존 window를 일괄 토글합니다."""
        target_enabled = not self._all_morph_dependencies_enabled()
        self._deps_ui_visible = target_enabled
        print(f"[morph.extensions_list_ui] Hotkey pressed -> set all morph dependencies: {target_enabled}")
        if not self._alive:
            return

        for dep_id in self._morph_dependencies:
            try:
                # enabled=True일 때만 extension을 enabled 상태로 맞춰둡니다.
                # (startup에서 미리 켜두긴 하지만, 외부에서 disable 되었을 때 복구를 위해서입니다.)
                if target_enabled:
                    self._set_extension_enabled(dep_id, True)

                dep_window = self._find_dep_window(dep_id)
                if dep_window is not None:
                    dep_window.visible = target_enabled
            except Exception:
                traceback.print_exc()

    def _window_name_candidates(self, dep_id: str) -> List[str]:
        """의존 확장의 window 이름 후보를 여러 포맷으로 생성합니다."""
        base = dep_id.split(".")[-1]
        spaced = base.replace("_", " ")
        return [dep_id, base, spaced, spaced.title(), f"Create {spaced.title()}"]

    def _find_dep_window(self, dep_id: str):
        """Workspace에서 의존 확장의 UI window를 찾아 반환합니다(없으면 None)."""
        if not hasattr(ui, "Workspace"):
            return None
        workspace = ui.Workspace

        for name in self._window_name_candidates(dep_id):
            try:
                dep_window = workspace.get_window(name)
                if dep_window is not None:
                    return dep_window
            except Exception:
                continue
        return None

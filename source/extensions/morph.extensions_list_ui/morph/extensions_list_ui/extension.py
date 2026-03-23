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
from typing import List, Optional

import omni.ext
import omni.ui as ui


# Functions and vars are available to other extensions as usual in python:
# `morph.extensions_list_ui.some_public_function(x)`
def some_public_function(x: int):
    """This is a public function that can be called from other extensions."""
    print(f"[morph.extensions_list_ui] some_public_function was called with {x}")
    return x ** x


class MyExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        print("[morph.extensions_list_ui] Extension startup")

        self._alive = True
        self._window: Optional[ui.Window] = None
        self._ext_id = ext_id
        self._config_toml_path = (Path(__file__).resolve().parents[2] / "config" / "extension.toml")
        self._window = ui.Window("Extension List UI", width=560, height=260, visible=True)

        self._render()

    def on_shutdown(self):
        print("[morph.extensions_list_ui] Extension shutdown")
        self._alive = False
        self._window = None

    def _load_morph_dependencies(self) -> List[str]:
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
            if isinstance(deps, dict):
                return sorted(dep for dep in deps.keys() if dep.startswith("morph."))
        except Exception:
            traceback.print_exc()

        return []

    def _window_name_candidates(self, dep_id: str) -> List[str]:
        base = dep_id.split(".")[-1]
        spaced = base.replace("_", " ")
        return [dep_id, base, spaced, spaced.title(), f"Create {spaced.title()}"]

    def _find_dep_window(self, dep_id: str):
        workspace = getattr(ui, "Workspace", None)
        if workspace is None or not hasattr(workspace, "get_window"):
            return None, None

        for name in self._window_name_candidates(dep_id):
            try:
                dep_window = workspace.get_window(name)
                if dep_window is not None:
                    return dep_window
            except Exception:
                continue
        return None, None

    def _dep_window_visible(self, dep_id: str):
        dep_window = self._find_dep_window(dep_id)
        if dep_window is None:
            return None
        return bool(getattr(dep_window, "visible", False))

    def _on_toggle(self, dep_id: str, enabled: bool):
        if not getattr(self, "_alive", False):
            return

        try:
            dep_window = self._find_dep_window(dep_id)
            if dep_window is None:
                pass
            else:
                dep_window.visible = enabled
        except Exception:
            traceback.print_exc()

        self._render()


    def _render(self):
        if not getattr(self, "_alive", False):
            return

        window = getattr(self, "_window", None)
        if window is None:
            return

        deps = self._load_morph_dependencies()

        with window.frame:
            with ui.VStack(spacing=8):
                with ui.ScrollingFrame(height=220):
                    with ui.VStack():
                        if not deps:
                            ui.Label("No morph.* dependencies found.")

                        for dep_id in deps:
                            visible = self._dep_window_visible(dep_id)
                            status = (
                                "Visible"
                                if visible is True
                                else "Hidden"
                                if visible is False
                                else "Window Missing"
                            )
                            with ui.HStack(spacing=8, height=36):
                                ui.Label(dep_id, width=256)
                                ui.Label(status, width=128)
                                ui.Button("On", width=64, height=32, clicked_fn=lambda _=None, _dep_id=dep_id: self._on_toggle(_dep_id, True),)
                                ui.Button("Off", width=64, height=32, clicked_fn=lambda _=None, _dep_id=dep_id: self._on_toggle(_dep_id, False),)
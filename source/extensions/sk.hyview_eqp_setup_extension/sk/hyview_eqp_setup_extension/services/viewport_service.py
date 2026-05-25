from __future__ import annotations

from typing import Any

from omni.kit.viewport.utility import get_viewport_from_window_name


class ViewportService:
    def get_viewport_window(self) -> Any:
        viewport_api = self.get_viewport_api("Viewport")
        return getattr(viewport_api, "viewport_window", None)

    def get_viewport_api(self, window_name: str = "Viewport") -> Any:
        return get_viewport_from_window_name(window_name)

    def create_scene_view(self) -> Any:
        # Optional integration point for app-specific scene_view creation.
        return None

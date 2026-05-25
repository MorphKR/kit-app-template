from __future__ import annotations

import carb.settings
import omni.ext
import omni.kit.app

from .events import get_event_bus
from .setup_service import SetupService
from .services.background_service import BackgroundService
from .services.stage_service import StageService


class SetupExtension(omni.ext.IExt):
    """Setup-only extension: creates tab resources and publishes tab lifecycle events."""

    def on_startup(self, ext_id):
        self._settings = carb.settings.get_settings()

        self._event_bus = get_event_bus()
        self._stage_service = StageService()

        self._setup_service = SetupService(event_bus=self._event_bus)

        BackgroundService.initialize()

        if self._settings and self._settings.get("/app/warmupMode"):
            return

    async def open_stage_and_create_tab(self, stage_url: str) -> None:
        await self._stage_service.open_stage(stage_url)
        await omni.kit.app.get_app().next_update_async()
        self._setup_service.create_tab()

    async def create_empty_tab(self) -> str:
        await omni.kit.app.get_app().next_update_async()
        return self._setup_service.create_tab()

    def change_active_tab(self, tab_id: str) -> None:
        self._setup_service.change_active_tab(tab_id)

    def on_shutdown(self):
        if hasattr(self, "_setup_service"):
            self._setup_service.clear()

        if hasattr(self, "_event_bus"):
            self._event_bus.clear()

        BackgroundService.shutdown()

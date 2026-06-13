from __future__ import annotations

import carb.settings
import omni.ext
import omni.kit.app
import omni.usd

from .events import get_event_bus
from .setup_service import SetupService
from .services.background_service import BackgroundService
from .services.stage_service import StageService


class SetupExtension(omni.ext.IExt):
    """Setup-only extension: creates tab resources and publishes tab lifecycle events."""

    def on_startup(self, ext_id):
        self._app_ready_subscription = None
        self._rendering_subscription = None
        self._render_frame_count = 0
        self._settings = carb.settings.get_settings()

        self._event_bus = get_event_bus()
        self._stage_service = StageService()

        self._setup_service = SetupService(event_bus=self._event_bus)

        BackgroundService.initialize()
        app = omni.kit.app.get_app()

        self._subscribe_rendering_event()

        print("SetupExtension started")


    def _subscribe_rendering_event(self):
        self._rendering_subscription = (
            omni.usd.get_context()
            .get_rendering_event_stream()
            .create_subscription_to_pop_by_type(
                int(omni.usd.StageRenderingEventType.NEW_FRAME),
                self._on_render_frame,
                name="my_extension.rtx_ready",
            )
        )



    def _on_render_frame(self, event):
        self._rendering_subscription = None

        print("RTX READY")
        self._setup_service.create_tab()



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

        self._app_ready_subscription = None
        self._rendering_subscription = None
        BackgroundService.shutdown()

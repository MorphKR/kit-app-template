from __future__ import annotations

from pathlib import Path
from typing import Optional

import carb
import carb.tokens
import omni.kit.app
import omni.usd


class StageService:
    async def open_stage(self, url: str, frame_delay: int = 5) -> Optional[object]:
        resolved = self._resolve_stage_url(url)
        if frame_delay:
            app = omni.kit.app.get_app()
            for _ in range(frame_delay):
                await app.next_update_async()

        usd_context = omni.usd.get_context()
        for _ in range(100):
            if usd_context.can_open_stage():
                break
            await omni.kit.app.get_app().next_update_async()
        else:
            carb.log_warn(f"StageService: timed out waiting to open stage {resolved}")
            return None

        await usd_context.open_stage_async(resolved, omni.usd.UsdContextInitialLoadSet.LOAD_ALL)
        return usd_context.get_stage()

    def get_stage(self):
        return omni.usd.get_context().get_stage()

    def get_usd_context_name(self) -> str:
        return "default"

    def _resolve_stage_url(self, stage_url: str) -> str:
        stage_url = carb.tokens.get_tokens_interface().resolve(stage_url)
        try:
            path = Path(stage_url)
            if path.exists():
                return str(path.resolve())
        except (OSError, RuntimeError):
            return stage_url
        return stage_url

# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import carb.settings
import omni.kit.raycast.query
from omni.kit.viewport.utility import get_active_viewport_window
from pxr import Sdf

from ...common import MeasureMode, MeasureState, SnapMode, SnapTo
from ...manager import ReferenceManager, StateMachine
from .mesh_provider import (
    CenterSnapProvider,
    EdgeSnapProvider,
    MidPointSnapProvider,
    PivotSnapProvider,
    SurfaceSnapProvider,
    VertexSnapProvider,
)
from .provider import MeasureSnapProvider
from .registry import MeasureSnapProviderRegistry


class MeasureSnapProviderManager:
    """MeasureSnapProviderManager 클래스 설명입니다."""
    def __singleton_init__(self):
        """싱글턴 초기화. provider 등록/상태 구독/UI 연동을 한 번에 구성한다."""
        self._settings = carb.settings.get_settings()
        self._enabled: bool = False
        self._window = get_active_viewport_window()
        self._api = self._window.viewport_api if self._window else None

        self._registry: MeasureSnapProviderRegistry = MeasureSnapProviderRegistry()

        self._providers: Dict[str, MeasureSnapProvider] = {}
        self._enabled_providers: List[MeasureSnapProvider] = []
        self._provider_registry_sub = self._registry.add_on_registry_changed_fn(self._on_registry_changed)
        self._enabled_providers_sub = None  # TODO Create event for when providers change in the UI panel

        self._registry.register(CenterSnapProvider)
        self._registry.register(PivotSnapProvider)
        self._registry.register(EdgeSnapProvider)
        self._registry.register(MidPointSnapProvider)
        self._registry.register(SurfaceSnapProvider)
        self._registry.register(VertexSnapProvider)

        self._on_registry_changed()

        # State machine Callbacks
        self._state_sub = StateMachine().add_tool_state_changed_fn(self._on_state_changed)

        # UI panel Callbacks
        placement_panel = ReferenceManager().ui_placement_panel
        if placement_panel and placement_panel.snap_group:
            placement_panel.snap_group.add_on_snaps_changed_fn(self._on_ui_snaps_changed)

    def __new__(cls, *args, **kwargs):
        """싱글턴 인스턴스를 반환한다."""
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.__singleton_init__()
        return cls._instance

    def __del__(self):
        """소멸 시 구독과 내부 참조를 정리한다."""
        self.destroy()

    @property
    def enabled(self) -> bool:
        """스냅 매니저 활성 여부."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """
        활성 상태를 변경한다.
        상태가 바뀌면 현재 UI에서 선택된 snap 모드 기준으로 provider 목록을 재계산한다.
        """
        self._enabled = value
        snaps = ReferenceManager().ui_placement_panel.snap_group.snaps
        self._on_ui_snaps_changed(snaps)

    def destroy(self):
        """등록/구독 자원을 안전하게 해제한다."""
        if self._provider_registry_sub:
            self._registry.remove_on_registry_changed_fn(self._provider_registry_sub)
            self._provider_registry_sub = None
        if self._enabled_providers_sub:
            # TODO: Unsubscribe to event tracking enabled providers in the UI panel
            self._enabled_providers_sub = None
        if self._value_cache is not None:
            self._value_cache.destroy()
            self._value_cache = None

    def _on_state_changed(self, state: MeasureState, mode: MeasureMode):
        """툴 상태 변경 콜백. 측정 상태가 NONE이 아니면 스냅을 켠다."""
        self.enabled = state != MeasureState.NONE

    def _on_ui_snaps_changed(self, snap_modes: List[SnapMode]) -> None:
        """UI에서 snap 모드가 바뀌면 활성 provider 목록을 갱신한다."""
        self._update_enabled_providers(snap_modes)

    def _on_registry_changed(self):
        """레지스트리 변경 시 provider 인스턴스를 재생성한다."""
        for provider in self._providers.values():
            provider.destroy()
        self._providers.clear()

        providers = self._registry.providers
        for name, provider_class in providers.items():
            self._providers[name] = provider_class(viewport_api=self._api)

        # self._update_enabled_providers()

    def on_began(self, excluded_paths: List[Union[str, Sdf.Path]], **kwargs):
        """스냅 계산 시작 훅을 활성 provider 전체에 전달한다."""
        for provider in self._enabled_providers:
            provider.on_began(excluded_paths, **kwargs)

    def on_ended(self, **kwargs):
        """스냅 계산 종료 훅을 활성 provider 전체에 전달한다."""
        for provider in self._enabled_providers:
            provider.on_ended(**kwargs)

    def get_snap_position(
        self, ndc_location: Sequence[float], result: omni.kit.raycast.query.RayQueryResult
    ) -> Optional[Dict[str, Any]]:
        """
        활성 provider를 우선순위 순으로 순회해 첫 번째 유효 snap payload를 반환한다.

        Args:
            ndc_location: 커서 NDC 좌표.
            result: raycast 결과.

        Returns:
            스냅 성공 payload 또는 `None`.
        """

        for provider in self._enabled_providers:
            # Perpendicular 모드에서는 Surface 스냅만 허용한다.
            snap_to_mode = ReferenceManager().ui_placement_panel.snap_to
            if snap_to_mode == SnapTo.PERPENDICULAR and not isinstance(provider, SurfaceSnapProvider):
                continue

            # provider별 시작 훅.
            provider.on_began([])

            snap_data: Tuple[bool, Optional[Dict[str, Any]]] = provider.on_snap(
                ndc_location, result, want_orient=isinstance(provider, SurfaceSnapProvider), want_keep_spacing=True
            )

            # provider별 종료 훅.
            provider.on_ended()
            if snap_data[0]:
                # 첫 성공 결과를 즉시 반환한다.
                return snap_data[1]
        return None

    def _on_enabled_providers_changed(self):
        """향후 확장용 훅(현재 미사용)."""
        pass
        # self._update_enabled_providers()

    def _geometry_snap_enabled(self) -> bool:
        """Geometry 기반 스냅(Vertex/Edge/Midpoint) 허용 여부를 설정값으로 반환한다."""
        return bool(self._settings.get("/rtx-transient/scenedb/useUniformsReindexing"))

    def _update_enabled_providers(self, snap_modes: List[SnapMode]) -> None:
        """
        현재 snap 모드 + 런타임 설정을 바탕으로 활성 provider 목록을 재구성한다.
        `useUniformsReindexing=false`이면 Vertex/Edge/Midpoint provider는 제외한다.
        """
        if not self.enabled:
            self._enabled_providers = []
            return

        mode_names = [snap.name.title() for snap in snap_modes]
        enable_geometry_snap = self._geometry_snap_enabled()
        self._enabled_providers = []
        for provider in self._providers.values():
            if not provider or provider.get_display_name() not in mode_names:
                continue
            if not enable_geometry_snap and isinstance(provider, (VertexSnapProvider, EdgeSnapProvider, MidPointSnapProvider)):
                continue
            self._enabled_providers.append(provider)
        self._enabled_providers.sort(key=lambda provider: provider.get_order())

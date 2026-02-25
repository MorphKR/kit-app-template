# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

import sys
from typing import Callable, Dict, Optional, Type

from carb import settings

from .provider import MeasureSnapProvider


class MeasureSnapProviderRegistry:
    """MeasureSnapProviderRegistry 클래스 설명입니다."""
    def __singleton_init__(self):
        """싱글턴 초기화. provider 클래스 맵과 변경 구독자를 준비한다."""
        self._providers: Dict[str, Type[MeasureSnapProvider]] = {}
        self._change_subscribers: Dict[int, Callable] = {}
        self._next_change_subscriber_id: int = 1
        self._settings = settings.get_settings()

    def __new__(cls, *args, **kwargs):
        """싱글턴 인스턴스를 반환한다."""
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.__singleton_init__()
        return cls._instance

    def __del__(self):
        """소멸 시 싱글턴 참조를 정리한다."""
        self.destroy()

    def destroy(self):
        """현재 싱글턴 인스턴스 참조를 제거한다."""
        MeasureSnapProviderRegistry._instance = None

    @property
    def providers(self) -> Dict[str, Type[MeasureSnapProvider]]:
        """
        등록된 provider 클래스 전체를 반환한다.
        """
        return self._providers

    def get_provider_class_by_name(self, name: str) -> Optional[Type[MeasureSnapProvider]]:
        """
        이름으로 provider 클래스를 조회한다. 없으면 `None`.
        """
        return self._providers.get(name, None)

    def register(self, provider: Type[MeasureSnapProvider]):
        """
        provider 클래스를 레지스트리에 등록한다.

        Args:
            provider: 등록할 provider 클래스.
        """
        id = provider.get_name()
        if id in self._providers:
            raise ValueError(f"{id} already exists")

        self._providers[id] = provider
        self._notify_registry_changed()

    def unregister(self, provider: Type[MeasureSnapProvider]):
        """
        provider 클래스를 레지스트리에서 제거한다.

        Args:
            provider: 제거할 provider 클래스.
        """
        id = provider.get_name()
        self._providers.pop(id, None)
        self._notify_registry_changed()

    def add_on_registry_changed_fn(self, callback: Callable[[], None]) -> int:
        """레지스트리 변경 구독 콜백을 추가하고 구독 ID를 반환한다."""
        id = self._next_change_subscriber_id
        self._next_change_subscriber_id += 1
        self._change_subscribers[id] = callback
        self._notify_registry_changed(callback)
        return id

    def remove_on_registry_changed_fn(self, id: int):
        """구독 ID로 변경 콜백을 제거한다."""
        self._change_subscribers.pop(id)

    def _notify_registry_changed(self, callback: Optional[Callable[[], None]] = None):
        """특정 콜백 또는 전체 구독자에게 레지스트리 변경 이벤트를 알린다."""
        if callback:
            callback()
        else:
            for sub in self._change_subscribers.values():
                sub()

# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

from typing import Any

import carb.events
import omni.timeline
import omni.usd as ou
from pxr import Sdf, Usd

from ...manager.state_machine import StateMachine


# AttributeValueCache가 필요한 이유:
# 고밀도 메시에서는 face/vertex 관련 USD 속성 조회만으로도 비용이 크다.
# 스냅 후보 탐색은 프레임마다 반복되므로, 값을 캐시하고 USD 변경/시간 변경 시 무효화해 성능을 유지한다.
class AttributeValueCache:
    """AttributeValueCache 클래스 설명입니다."""
    def __singleton_init__(self):
        """싱글턴 초기화. stage/timeline 구독을 연결하고 캐시를 준비한다."""
        self.__usd_context = ou.get_context()
        self.__timeline = omni.timeline.get_timeline_interface()
        self.__stage: Usd.Stage = None
        self.__time_code = Usd.TimeCode.Default()
        self.__attribute_value_cache: dict[Sdf.Path, Any] = {}

        self.__opened_id: int = StateMachine().subscribe_to_stage_event(
            self.__on_stage_opened, ou.StageEventType.OPENED
        )

        self.__stage_sub = StateMachine().subscribe_to_stage_listener(self.__on_objects_changed)

        self.__timeline_sub = self.__timeline.get_timeline_event_stream().create_subscription_to_pop(
            self.__on_timeline_event
        )

        self.__on_stage_opened()

    def __new__(cls):
        """싱글턴 인스턴스를 반환한다."""
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
            cls._instance.__singleton_init__()
        return cls._instance

    def __del__(self):
        """구독 해제 및 캐시 정리를 수행한다."""
        if self.__stage_sub is not None:
            StateMachine().unsubscribe_to_stage_listener(self.__stage_sub)
            self.__stage_sub = None

        if self.__opened_id is not None:
            StateMachine().unsubscribe_to_stage_event(self.__opened_id, ou.StageEventType.OPENED)
            self.__opened_id = None

        self.__timeline_sub = None
        self.__attribute_value_cache.clear()

    def destroy(self):
        """외부에서 명시적으로 정리할 때 사용한다."""
        self.__del__()

    @classmethod
    def deinit(cls):
        """싱글턴 인스턴스를 파기한다."""
        cls._instance.destroy()
        del cls._instance

    def get_value(self, path: Sdf.Path) -> Any:
        """
        attribute 경로 값을 캐시에서 조회한다.
        캐시에 없으면 현재 timeCode 기준으로 stage에서 읽어 캐시에 저장한다.
        """
        if path not in self.__attribute_value_cache:
            attribute = self.__stage.GetAttributeAtPath(path)
            if attribute.IsValid():
                value = attribute.Get(self.__time_code)
                self.__attribute_value_cache[path] = value
                return value

        return self.__attribute_value_cache.get(path, None)

    def __on_stage_opened(self):
        """stage 오픈 이벤트 시 stage 참조를 갱신하고 캐시를 초기화한다."""
        self.__stage = self.__usd_context.get_stage()
        self.__attribute_value_cache.clear()

    def __on_timeline_event(self, e: carb.events):
        """타임라인 시간이 바뀌면 캐시 값을 무효화한다."""
        time_code = Usd.TimeCode(self.__timeline.get_current_time() * self.__timeline.get_time_codes_per_seconds())
        if time_code != self.__time_code:
            self.__time_code = time_code
            self.__attribute_value_cache.clear()

    def __on_objects_changed(self, notice) -> None:
        """USD 객체 변경/리싱크 경로에 해당하는 캐시 항목만 부분 무효화한다."""
        if not notice:
            return

        for path in notice.GetChangedInfoOnlyPaths():
            self.__attribute_value_cache.pop(path, None)

        for path in notice.GetResyncedPaths():
            self.__attribute_value_cache.pop(path, None)

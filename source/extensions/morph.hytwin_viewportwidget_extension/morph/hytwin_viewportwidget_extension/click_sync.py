from typing import Callable, List, Optional

from omni.ui import scene as sc

from .gestures import (
    ViewportClickGesture,
    ViewportDoubleClickGesture,
    ViewportInteractionController,
    ViewportRightDragGesture,
    ViewportZoomGesture,
)

PointerPayload = dict


class QuadViewportClickSync:
    """Scene Gesture 연결과 payload 변환을 담당한다."""

    _LEFT_BUTTON = 0
    _RIGHT_BUTTON = 1

    def __init__(self):
        # entry 하나는 타일 1개의 SceneView/Screen 등록 정보다.
        self._entries: List[dict] = []
        self._interaction_controller: Optional[ViewportInteractionController] = None
        self._on_right_drag_begin_fn: Optional[Callable[[PointerPayload], None]] = None
        self._on_right_drag_changed_fn: Optional[Callable[[PointerPayload], None]] = None
        self._on_right_drag_end_fn: Optional[Callable[[PointerPayload], None]] = None

    # ------------------------------------------------------------------
    # 설정 API
    # ------------------------------------------------------------------
    def set_interaction_controller(self, controller: ViewportInteractionController):
        # 실제 선택/줌 로직은 controller에서 수행한다.
        self._interaction_controller = controller

    def set_right_drag_handlers(
        self,
        on_begin: Optional[Callable[[PointerPayload], None]] = None,
        on_changed: Optional[Callable[[PointerPayload], None]] = None,
        on_end: Optional[Callable[[PointerPayload], None]] = None,
    ):
        self._on_right_drag_begin_fn = on_begin
        self._on_right_drag_changed_fn = on_changed
        self._on_right_drag_end_fn = on_end

    # ------------------------------------------------------------------
    # 뷰포트 등록/해제
    # ------------------------------------------------------------------
    def register_viewport(self, viewport_widget, overlay_frame):
        # overlay frame 위에 SceneView를 붙여 타일 단위로 제스처를 수신한다.
        viewport_api = getattr(viewport_widget, "viewport_api", None)
        if viewport_api is None or self._interaction_controller is None:
            return

        # 좌클릭/더블클릭 payload
        payload_builder_left = lambda sender, sv=viewport_widget, frame=overlay_frame: self._build_payload(
            sender, sv, frame, self._LEFT_BUTTON, None
        )
        # 우클릭 드래그 payload
        payload_builder_right = lambda sender, sv=viewport_widget, frame=overlay_frame: self._build_payload(
            sender, sv, frame, self._RIGHT_BUTTON, None
        )
        # 휠 delta 추출기
        wheel_delta_extractor = lambda sender: self._extract_wheel_delta_from_sender(sender)

        with overlay_frame:
            scene_view = sc.SceneView()
            with scene_view.scene:
                screen = sc.Screen(
                    gestures=[
                        ViewportClickGesture(
                            interaction_controller=self._interaction_controller,
                            payload_builder=payload_builder_left,
                            mouse_button=self._LEFT_BUTTON,
                        ),
                        ViewportDoubleClickGesture(
                            interaction_controller=self._interaction_controller,
                            payload_builder=payload_builder_left,
                            mouse_button=self._LEFT_BUTTON,
                        ),
                        ViewportRightDragGesture(
                            payload_builder=payload_builder_right,
                            on_begin=self._on_right_drag_begin_fn,
                            on_changed=self._on_right_drag_changed_fn,
                            on_end=self._on_right_drag_end_fn,
                            mouse_button=self._RIGHT_BUTTON,
                        ),
                        ViewportZoomGesture(
                            interaction_controller=self._interaction_controller,
                            wheel_delta_extractor=wheel_delta_extractor,
                        ),
                    ]
                )

        viewport_api.add_scene_view(scene_view)
        self._entries.append(
            {
                "viewport_widget": viewport_widget,
                "overlay_frame": overlay_frame,
                "viewport_api": viewport_api,
                "scene_view": scene_view,
                "screen": screen,
            }
        )

    def destroy(self):
        # 등록했던 SceneView를 모두 제거하고 리소스를 해제한다.
        for entry in self._entries:
            viewport_api = entry.get("viewport_api")
            scene_view = entry.get("scene_view")

            if viewport_api and scene_view:
                try:
                    viewport_api.remove_scene_view(scene_view)
                except Exception:
                    pass

            if scene_view:
                try:
                    scene_view.destroy()
                except Exception:
                    pass

        self._entries = []

    # ------------------------------------------------------------------
    # payload/좌표 유틸리티
    # ------------------------------------------------------------------
    def _build_payload(self, sender, source_viewport, overlay_frame, button, modifiers) -> Optional[PointerPayload]:
        # Scene Gesture mouse(NDC)를 공통 payload(norm/local) 형식으로 변환한다.
        ndc = self._extract_mouse_ndc_from_sender(sender)
        if ndc is None:
            return None
        ndc_x, ndc_y = ndc

        viewport_api = getattr(source_viewport, "viewport_api", None)
        if viewport_api is None:
            return None

        mapped = viewport_api.map_ndc_to_texture((ndc_x, ndc_y))
        if not mapped or mapped[-1] is None:
            # 현재 타일의 실제 렌더 영역 밖 입력은 무시한다.
            return None

        norm_x = max(0.0, min(1.0, (ndc_x + 1.0) * 0.5))
        norm_y = max(0.0, min(1.0, (1.0 - ndc_y) * 0.5))
        width = float(max(1.0, getattr(overlay_frame, "computed_width", 1.0)))
        height = float(max(1.0, getattr(overlay_frame, "computed_height", 1.0)))

        return {
            "source_viewport": source_viewport,
            "click_target": overlay_frame,
            "local_x": norm_x * width,
            "local_y": norm_y * height,
            "width": width,
            "height": height,
            "norm_x": norm_x,
            "norm_y": norm_y,
            "ndc_x": ndc_x,
            "ndc_y": ndc_y,
            "button": button,
            "modifiers": modifiers,
        }

    @staticmethod
    def _extract_mouse_ndc_from_sender(sender) -> Optional[tuple]:
        # 빌드 차이를 고려해 sender.mouse와 payload.mouse를 모두 시도한다.
        payload = getattr(sender, "gesture_payload", None)
        mouse = getattr(payload, "mouse", None) if payload is not None else None
        if mouse is None:
            mouse = getattr(sender, "mouse", None)
        if mouse is None:
            return None

        try:
            return float(mouse[0]), float(mouse[1])
        except Exception:
            return None

    @staticmethod
    def _extract_wheel_delta_from_sender(sender) -> float:
        # ScrollGesture에서 주로 sender.scroll 또는 payload.direction을 사용한다.
        candidates = (
            getattr(sender, "scroll", None),
            getattr(getattr(sender, "gesture_payload", None), "direction", None),
        )
        for value in candidates:
            if value is None:
                continue
            delta = QuadViewportClickSync._coerce_delta(value)
            if abs(delta) > 1e-6:
                return delta
        return 0.0

    @staticmethod
    def _coerce_delta(value) -> float:
        # tuple/list/vector-like 값을 float delta로 변환한다.
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (int, float)):
                return float(value[1])
            if len(value) >= 1 and isinstance(value[0], (int, float)):
                return float(value[0])
            return 0.0

        if hasattr(value, "__getitem__"):
            try:
                y = value[1]
                if isinstance(y, (int, float)):
                    return float(y)
            except Exception:
                pass
            try:
                x = value[0]
                if isinstance(x, (int, float)):
                    return float(x)
            except Exception:
                pass

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

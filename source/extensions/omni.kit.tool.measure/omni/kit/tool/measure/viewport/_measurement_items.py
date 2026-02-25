# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
import asyncio
from abc import abstractmethod
from math import cos, pi, sin
from typing import List, Union

import omni.kit.app as app
import omni.usd as ou
from carb.dictionary import get_dictionary
from carb.settings import get_settings
from carb.windowing import CursorStandardShape
from omni import ui
from omni.kit.window.cursor import get_main_window_cursor
from omni.ui import scene as sc
from pxr import Gf, Sdf, UsdGeom
from pxr.Gf import Vec3d

from ..common import (
    LABEL_SCALE_MAPPING,
    SELECTION_LINE_COLOR,
    SELECTION_LINE_WIDTH,
    LabelSize,
    MeasureMode,
    MeasureState,
    Precision,
    UserSettings,
    convert_distance_and_units,
)
from ..common.utils import flatten
from ..interface.style import get_icon_path
from ..manager import MeasurementManager, ReferenceManager, StateMachine
from ..system import MeasurePrim
from ._drawing import draw_display_axis
from .gesture_manager import PreventOthers
from .tools import MeasureAxisStackLabel  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

HOVER_COLOR = [1, 1, 0, 1]  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
SELECTED_COLOR = [0, 1, 0, 1]  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

# TODO: BBoxWireframeOverlayItem - 흰색 AABB 와이어프레임 박스 (추후 구현)


class _MeasurementItem(sc.AbstractManipulatorItem):
    """동작 설명입니다."""

    def __init__(self):
        self.__settings = get_settings()
        self.__dict = get_dictionary()

        super().__init__()
        self._visible: bool = True  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        self._hovered: bool = False
        self._selected: bool = False
        self._selection_enabled = None
        self._manager = PreventOthers()

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        self._root: sc.Transform = None  # sc.Transform()
        self._lbl_root: sc.Transform = None
        self._payload: "MeasurePayload"

        self._gestures = [
            sc.ClickGesture(name="MeasureClick", on_ended_fn=self._on_clicked, manager=self._manager),
            sc.HoverGesture(
                name="MeasureHover",
                on_began_fn=self._on_hover_start,
                on_ended_fn=self._on_hover_end,
                manager=self._manager,
            ),
        ]

        self._delete_gestures = [
            sc.ClickGesture(name="MeasureDelete", on_ended_fn=self._on_delete, manager=self._manager),
            sc.HoverGesture(
                name="MeasureHover",
                on_began_fn=self._on_hover_start,
                on_ended_fn=self._on_hover_end,
                manager=self._manager,
            ),
        ]

    @property
    def visible(self) -> bool:
        return self._payload.visible and UserSettings().visible

    @property
    def uuid(self) -> int:
        return self._payload.uuid or -1

    @property
    def payload(self):
        return self._payload

    @payload.setter
    def payload(self, value):
        self._payload = value

    @property
    def selected(self) -> bool:
        return self._selected

    # TODO: Create this as a normal function, set_selected(self, value: bool, update_treeview: bool=False)
    # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
    @selected.setter
    def selected(self, value: bool) -> None:
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        if self._selected == value:
            return

        self._selected = value
        if not value:
            get_main_window_cursor().clear_overridden_cursor_shape()

        ReferenceManager().ui_manage_panel.update_selection()

        self._on_selection_state_changed()

    @property
    def _selected_line_color(self) -> List[float]:
        return self.__settings.get(SELECTION_LINE_COLOR)[-4:]  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

    @property
    def _selected_line_width(self) -> int:
        return 3 + (self.__settings.get_as_int(SELECTION_LINE_WIDTH) * 2)

    @property
    def hovered(self) -> bool:
        return self._hovered

    @abstractmethod
    def _on_selection_state_changed(self):
        raise NotImplementedError

    def _on_clicked(self, _sender: sc.AbstractShape):
        if not self._hovered:
            return
        self.selected = not self._selected
        self.draw()

    def _on_delete(self, _sender: sc.AbstractShape):
        if self.selected and self.uuid != -1:
            MeasurementManager().delete(self.uuid)

    def _on_hover_start(self, _sender):
        if not ReferenceManager().selection_state.enabled or StateMachine().tool_state != MeasureState.NONE:
            return
        self._selection_enabled = ReferenceManager().selection_state.enabled
        ReferenceManager().selection_state.enabled = False

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        if _sender is None:  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

            async def set_selection_group():
                await app.get_app().next_update_async()
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                for path in self.payload.prim_paths:
                    ou.get_context().set_selection_group(ReferenceManager().selection_group, Sdf.Path(path).pathString)

            asyncio.ensure_future(set_selection_group())
        else:
            for path in self.payload.prim_paths:
                ou.get_context().set_selection_group(ReferenceManager().selection_group, Sdf.Path(path).pathString)

        self._hovered = True
        get_main_window_cursor().override_cursor_shape(CursorStandardShape.HAND)
        self.draw(False)

    def _on_hover_end(self, _sender):
        if self._selection_enabled is not None:
            ReferenceManager().selection_state.enabled = self._selection_enabled
            self._selection_enabled = None

        for path in self.payload.prim_paths:
            ou.get_context().set_selection_group(0, Sdf.Path(path).pathString)

        self._hovered = False
        get_main_window_cursor().clear_overridden_cursor_shape()
        self.draw(False)

    def clear(self):
        self.selected = False
        self._on_hover_end(None)  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        self._root.clear()
        self._lbl_root.clear()

    def compute(self):
        is_visible = self._visible
        self.draw() if is_visible else self._root.clear()
        self.__lbl_root.clear()

    def draw(self, label_dirty: bool = True):
        if not self._root:
            self._root = sc.Transform()
        if not self._lbl_root:
            self._lbl_root = sc.Transform()
        self._draw(label_dirty)

    @abstractmethod
    def _draw(self, label_dirty: bool = True):
        raise NotImplementedError

    @abstractmethod
    def _draw_label(self):
        raise NotImplementedError


class LinearMeasurementItem(_MeasurementItem):
    """동작 설명입니다."""

    def __init__(self, measure_prim: MeasurePrim):
        super().__init__()
        self._prim: MeasurePrim = measure_prim
        self._payload = self._prim.payload
        self._label_position: Gf.Vec3d = None  # 라벨 위치 저장 (선분 투명 처리용)

    def _on_selection_state_changed(self):
        pass

    def _draw(self, label_dirty: bool = True):
        color_list = [*self.payload.label_color]
        interact_color = self._selected_line_color if self._selected else HOVER_COLOR if self._hovered else [0, 0, 0, 0]
        pts = self._payload.computed_points
        is_mesh_6 = (
            self._payload.tool_mode == MeasureMode.MESH
            and len(pts) >= 6
            and self._payload.axis_display.value == 0
        )
        if is_mesh_6:
            segments = [(pts[0], pts[1]), (pts[2], pts[3]), (pts[4], pts[5])]
        else:
            segments = [(pts[0], pts[1])] if len(pts) >= 2 else []
        start, end = [[*vec] for vec in (segments[0] if segments else (Gf.Vec3d(0, 0, 0), Gf.Vec3d(0, 0, 0)))]

        is_mesh_mode = self._payload.tool_mode == MeasureMode.MESH
        self._root.clear()
        with self._root:
            # Click line (제스처용; 6 points일 때는 첫 번째 세그먼트)
            if segments:
                click_line = sc.Line(
                    start,
                    end,
                    color=interact_color,
                    thickness=self._selected_line_width,
                    visible=self.visible,
                    gestures=self._gestures,
                )

            if is_mesh_mode and self._payload.axis_display.value == 0:
                raw_sub = getattr(self._payload, "tool_sub_mode", -1)
                dimension_level = (raw_sub // 10) if raw_sub >= 10 else 0
                self._label_position = [] if is_mesh_6 else None
                stage = ou.get_context().get_stage()
                is_y_up = (not stage) or (UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y)
                MESH_LINE_THICKNESS = 1
                for seg_idx, (s_vec, e_vec) in enumerate(segments):
                    start_vec = Gf.Vec3d(*s_vec) if not isinstance(s_vec, Gf.Vec3d) else s_vec
                    end_vec = Gf.Vec3d(*e_vec) if not isinstance(e_vec, Gf.Vec3d) else e_vec
                    axis_index = seg_idx
                    line_dir = (end_vec - start_vec).GetNormalized()
                    line_length = (end_vec - start_vec).GetLength()

                    # 축별 연장 방향: Stage up axis에 따라 달라짐
                    # Y-up (my_editor.kit): Y가 지면 수직. Z-up (my_usd_explorer.kit): Z가 지면 수직
                    if is_y_up:
                        # Y-up: Y가 높이. X,Z는 수평. 연장선은 수평축 측정 시 Y방향, Y측정 시 X방향
                        if axis_index == 0:
                            offset_dir = Gf.Vec3d(1, 0, 0)
                        elif axis_index == 1:
                            offset_dir = Gf.Vec3d(0, 0, -1)
                        elif axis_index == 2:
                            offset_dir = Gf.Vec3d(-1, 0, 0)
                        else:
                            offset_dir = Gf.Vec3d(0, 0, 1)
                    else:
                        # Z-up: Z가 높이. X,Y는 수평. 연장선은 수평축 측정 시 Z방향, Z측정 시 X방향
                        if axis_index == 0:
                            offset_dir = Gf.Vec3d(1, 0, 0)
                        elif axis_index == 1:
                            offset_dir = Gf.Vec3d(0, 1, 0)
                        elif axis_index == 2:
                            offset_dir = Gf.Vec3d(-1, 0, 0)
                        else:
                            offset_dir = Gf.Vec3d(0, 1, 0)

                    # 오프셋 거리: level 0=최상위(더 바깥), 1+=하위(더 안쪽, 겹치지 않게)
                    if dimension_level == 0:
                        offset_ratio = 0.12  # 최상위 치수선: 바깥쪽
                    else:
                        offset_ratio = max(0.02, 0.07 - dimension_level * 0.015)  # 하위: 안쪽으로
                    offset_dist = max(line_length * offset_ratio, 0.015)
                    ext_start = start_vec + offset_dir * offset_dist
                    ext_end = end_vec + offset_dir * offset_dist

                    # 연장선 2개 (객체 모서리 → 치수선)
                    sc.Line([*start_vec], [*ext_start], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)
                    sc.Line([*end_vec], [*ext_end], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)
                    # 치수선 (연장선 끝 연결)
                    sc.Line([*ext_start], [*ext_end], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)

                    # CAD 스타일 화살표: 치수선 양끝에 V자형 화살표 (치수선 쪽으로 열림)
                    _arrow_len = max(line_length * 0.2, 0.005)
                    line_cm = getattr(self._payload, "primary_value", None)
                    if line_cm is not None and line_cm >= 50:
                        _arrow_len = min(_arrow_len, 5)
                    _arrow_angle = 15 * pi / 180
                    _arrow_base_1 = line_dir * (_arrow_len * cos(_arrow_angle))
                    _arrow_base_2 = -line_dir * (_arrow_len * cos(_arrow_angle))
                    _arrow_side = offset_dir * (_arrow_len * sin(_arrow_angle))
                    _a1_left = ext_start + _arrow_base_1 + _arrow_side
                    _a1_right = ext_start + _arrow_base_1 - _arrow_side
                    sc.Line([*ext_start], [*_a1_left], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)
                    sc.Line([*ext_start], [*_a1_right], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)
                    _a2_left = ext_end + _arrow_base_2 + _arrow_side
                    _a2_right = ext_end + _arrow_base_2 - _arrow_side
                    sc.Line([*ext_end], [*_a2_left], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)
                    sc.Line([*ext_end], [*_a2_right], color=color_list, thickness=MESH_LINE_THICKNESS, visible=self.visible)

                    # 라벨 위치: 치수선 중앙 (6 points일 때 리스트에 추가)
                    mid = (ext_start + ext_end) * 0.5
                    if is_mesh_6:
                        self._label_position.append(mid)
                    else:
                        self._label_position = mid
                    # 객체 모서리 포인트 (작게, 연장선 시작점 표시)
                    sc.Points([[*start_vec], [*end_vec]], sizes=[2, 2], colors=[color_list, color_list], visible=self.visible)
            else:
                # 일반 모드: 전체 선분을 그림
                line = sc.Line(start, end, color=color_list, thickness=3, visible=self.visible)
                points = sc.Points([start, end], sizes=[5, 5], colors=[color_list, color_list], visible=self.visible)

        if label_dirty:
            if self._payload.axis_display.value != 0:
                self._lbl_root.clear()
                with self._lbl_root:
                    self._stack_label = MeasureAxisStackLabel(
                        self._payload.tool_mode,
                        selected=self.selected,
                        delete_fn=self._on_delete,
                        delete_gestures=self._delete_gestures,
                    )
            else:
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                self._draw_label()

        with self._root:
            if self._payload.axis_display.value != 0:
                if self._stack_label:
                    draw_display_axis(
                        self._payload.prim_paths[0],
                        self._payload.computed_points[0],
                        self._payload.computed_points[1],
                        self._payload.axis_display,
                        self._stack_label,
                        self._payload.unit_type.value,
                        list(Precision).index(self._payload.precision),
                        hide_unit=(self._payload.tool_mode == MeasureMode.MESH),
                    )

    def _draw_label(self) -> sc.Transform:
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        precision = list(Precision).index(self._payload.precision.value)
        secondary_vals = getattr(self._payload, "secondary_values", None) or []

        # MESH 연장선 모드: 라벨은 치수선 중앙 (_draw에서 설정됨)
        is_mesh_ext = self._payload.tool_mode == MeasureMode.MESH and self._payload.axis_display.value == 0
        if is_mesh_ext and hasattr(self, "_label_position") and self._label_position is not None:
            label_pos = self._label_position
        else:
            label_pos = (self._payload.computed_points[0] + self._payload.computed_points[1]) * 0.5
            self._label_position = label_pos
        # MESH 6 points: 3개 축 라벨 (X, Y, Z 값)
        is_mesh_3_labels = (
            self._payload.tool_mode == MeasureMode.MESH
            and isinstance(label_pos, (list, tuple))
            and len(label_pos) == 3
            and len(secondary_vals) == 3
        )
        is_mesh_mode = self._payload.tool_mode == MeasureMode.MESH
        label_text = (
            f"{self._payload.primary_value:.{precision}f}"
            if is_mesh_mode
            else f"{self._payload.primary_value:.{precision}f} {self._payload.unit_type.value}"
        )
        text_size = self._payload.label_size
        size_bias = LABEL_SCALE_MAPPING[text_size]

        self._lbl_root.clear()
        with self._lbl_root:
            if is_mesh_3_labels:
                # 3개 위치에 X, Y, Z 값 라벨 (단위 없음)
                text_color = [1.0, 1.0, 1.0, 1.0]
                stroke_color = [0.0, 0.0, 0.0, 1.0]
                stroke_offset = 1.5
                offsets = [
                    (-stroke_offset, -stroke_offset), (-stroke_offset, 0), (-stroke_offset, stroke_offset),
                    (0, -stroke_offset), (0, stroke_offset),
                    (stroke_offset, -stroke_offset), (stroke_offset, 0), (stroke_offset, stroke_offset),
                ]
                last_xform = None
                for i in range(3):
                    pos = label_pos[i]
                    seg_text = f"{secondary_vals[i]:.{precision}f}"
                    xform = sc.Transform(
                        look_at=sc.Transform.LookAt.CAMERA,
                        transform=sc.Matrix44.get_translation_matrix(*pos),
                        visible=False,
                    )
                    with xform:
                        with sc.Transform(scale_to=sc.Space.SCREEN):
                            for dx, dy in offsets:
                                with sc.Transform(transform=sc.Matrix44.get_translation_matrix(dx, dy, 0)):
                                    sc.Label(seg_text, size=text_size.value, color=stroke_color, alignment=ui.Alignment.CENTER)
                            _label_kw = dict(size=text_size.value, color=text_color, alignment=ui.Alignment.CENTER)
                            if i == 0:
                                _label_kw["gestures"] = self._gestures
                            sc.Label(seg_text, **_label_kw)
                    xform.visible = self.visible
                    last_xform = xform
                return last_xform
            xform = sc.Transform(
                look_at=sc.Transform.LookAt.CAMERA,
                transform=sc.Matrix44.get_translation_matrix(*label_pos),
                visible=False,
            )

            with xform:
                with sc.Transform(scale_to=sc.Space.SCREEN):
                    if is_mesh_mode:
                        """

                        # MESH 모드: 아이콘 및 배경 없이 텍스트만 표시, 보색 스트로크 추가
                        text_color = [*self._payload.label_color[:3], 1.0]  # 텍스트 색상 = label_color
                        # 보색 계산 (RGB 반전)
                        stroke_color = [
                            1.0 - text_color[0],
                            1.0 - text_color[1],
                            1.0 - text_color[2],
                            1.0
                        ]

                        """
                        # MESH 모드: 아이콘 및 배경 없이 텍스트만 표시, 검은색 스트로크 추가
                        text_color = [1.0, 1.0, 1.0, 1.0]  # 흰색 텍스트
                        stroke_color = [0.0, 0.0, 0.0, 1.0]  # 검은색 스트로크

                        # 스트로크 효과를 위해 여러 레이어로 텍스트 그리기
                        stroke_offset = 1.5  # 스트로크 오프셋 (픽셀)
                        offsets = [
                            (-stroke_offset, -stroke_offset),  # 좌상
                            (-stroke_offset, 0),              # 좌
                            (-stroke_offset, stroke_offset),  # 좌하
                            (0, -stroke_offset),               # 상
                            (0, stroke_offset),                # 하
                            (stroke_offset, -stroke_offset),   # 우상
                            (stroke_offset, 0),                # 우
                            (stroke_offset, stroke_offset),   # 우하
                        ]

                        # 스트로크 레이어 (검은색)
                        for dx, dy in offsets:
                            with sc.Transform(transform=sc.Matrix44.get_translation_matrix(dx, dy, 0)):
                                sc.Label(
                                    label_text,
                                    size=text_size.value,
                                    color=stroke_color,
                                    alignment=ui.Alignment.CENTER,
                                )

                        # 메인 텍스트 레이어 (흰색)
                        sc.Label(
                            label_text,
                            size=text_size.value,
                            color=text_color,
                            alignment=ui.Alignment.CENTER,
                            gestures=self._gestures,  # 제스처는 텍스트에 연결
                        )
                    else:
                        # 일반 모드: 기존 렌더링 (아이콘 및 배경 포함)
                        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                        char_len = len(label_text)
                        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

                        # 라벨
                        with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, 0, 0)):
                            sc.Label(
                                label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.LEFT_CENTER
                            )
                        # 배경
                        sc.Rectangle(
                            width=rect_width, height=45, color=[1, 1, 1, 1], wireframe=False, gestures=self._gestures
                        )
                        # 아이콘
                        with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, 0, 0)):
                            # 아이콘 배경
                            sc.Rectangle(
                                width=45, height=45, color=[0, 0, 0, 0], wireframe=False, gestures=self._delete_gestures
                            )
                            # 아이콘 이미지
                            mode_name = self._payload.tool_mode.name.lower()
                            icon_path = (
                                get_icon_path("scene_icon_tool_delete")
                                if self.selected
                                else get_icon_path(f"scene_icon_tool_{mode_name}")
                            )
                            self._tool_image = sc.Image(source_url=icon_path, width=45, height=45)

            xform.visible = self.visible
        return xform


class MultiPointMeasurementItem(_MeasurementItem):
    """동작 설명입니다."""

    def __init__(self, measure_prim: MeasurePrim):
        super().__init__()
        self._prim: MeasurePrim = measure_prim
        self._payload = self._prim.payload

    def _on_selection_state_changed(self):
        pass

    def _draw_sub_label(self, start: Gf.Vec3d, end: Gf.Vec3d, distance: float) -> sc.Transform:
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        precision = list(Precision).index(self._payload.precision.value)

        label_text: str = f"{distance:.{precision}f} {self._payload.unit_type.value}"
        label_position = (start + end) * 0.5
        text_size = LabelSize(self._payload.label_size)
        size_bias = LABEL_SCALE_MAPPING[text_size]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        char_len = len(label_text)
        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        xform = sc.Transform(
            look_at=sc.Transform.LookAt.CAMERA,
            transform=sc.Matrix44.get_translation_matrix(*label_position),
            visible=False,
        )

        with xform:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                sc.Label(label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.CENTER)
                rect_width = 14 * len(label_text) * size_bias
                sc.Rectangle(width=rect_width, height=45, color=[1, 1, 1, 1], wireframe=False)

        xform.visible = self.visible
        return xform

    # TODO: 후속 구현 및 정리가 필요합니다.
    def _draw_label(self) -> sc.Transform:
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        precision = list(Precision).index(self._payload.precision.value)

        centroid = [sum(vec) for vec in zip(*self._payload.computed_points)]
        centroid = [vec / len(self._payload.computed_points) for vec in centroid]

        label_pos: Gf.Vec3d = centroid
        label_text = f"{self._payload.primary_value:.{precision}f} {self._payload.unit_type.value}"
        text_size: LabelSize = LabelSize(self._payload.label_size)
        size_bias: float = LABEL_SCALE_MAPPING[text_size]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        char_len = len(label_text)
        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

        xform = sc.Transform(
            look_at=sc.Transform.LookAt.CAMERA, transform=sc.Matrix44.get_translation_matrix(*label_pos), visible=False
        )

        with xform:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                # 라벨
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, 0, 0)):
                    sc.Label(label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.LEFT_CENTER)
                # 배경
                sc.Rectangle(width=rect_width, height=45, color=[1, 1, 1, 1], wireframe=False)
                # 아이콘
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, 0, 0)):
                    # 아이콘 배경
                    sc.Rectangle(
                        width=45, height=45, color=[0, 0, 0, 1], wireframe=False, gestures=self._delete_gestures
                    )
                    # 아이콘 이미지
                    mode_name = self._payload.tool_mode.name.lower()
                    icon_path = get_icon_path("tool_delete") if self.selected else get_icon_path(f"tool_{mode_name}")
                    sc.Image(source_url=icon_path, width=45, height=45)

        xform.visible = self.visible
        return xform

    def _draw(self, label_dirty: bool = True):
        """동작 설명입니다."""
        color_list = [*self.payload.label_color]
        interact_color = self._selected_line_color if self._selected else HOVER_COLOR if self._hovered else [0, 0, 0, 0]

        points = self._payload.computed_points  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

        self._root.clear()
        with self._root:
            # 선 그리기
            for i in range(len(points) - 1):
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                sc.Line(
                    [*points[i]],
                    [*points[i + 1]],
                    color=interact_color,
                    thickness=self._selected_line_width,
                    visible=self.visible,
                    gestures=self._gestures,
                )
                # 선
                sc.Line(
                    [*points[i]],
                    [*points[i + 1]],
                    color=color_list,
                    thickness=3,
                    visible=self.visible,
                )

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            sc.Points(
                [[*vec] for vec in self._payload.computed_points],
                sizes=[5] * len(points),
                colors=[color_list] * len(points),
                visible=self.visible,
            )

        if label_dirty:
            self._lbl_root.clear()
            with self._lbl_root:
                # 메인 라벨 그리기
                self._draw_label()

                for i in range(len(points) - 1):
                    # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                    if len(points) > 2:
                        self._draw_sub_label(points[i], points[i + 1], self._payload.secondary_values[i])


class AngleMeasurementItem(_MeasurementItem):
    """동작 설명입니다."""

    def __init__(self, measure_prim: MeasurePrim):
        super().__init__()
        self._prim: MeasurePrim = measure_prim
        self._payload = self._prim.payload

    def _on_selection_state_changed(self):
        pass

    def _draw(self, label_dirty: bool = True):
        # define the widget line color(s)
        color_list = [*self.payload.label_color]
        interact_color = self._selected_line_color if self._selected else HOVER_COLOR if self._hovered else [0, 0, 0, 0]
        start, axis, end = (
            self._payload.computed_points[0],
            self._payload.computed_points[1],
            self._payload.computed_points[2],
        )

        self._root.clear()
        with self._root:
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            gesture_leg_a = sc.Line(
                [*start],
                [*axis],
                color=interact_color,
                thickness=self._selected_line_width,
                visible=self.visible,
                gestures=self._gestures,
            )
            gesture_leg_b = sc.Line(
                [*end],
                [*axis],
                color=interact_color,
                thickness=self._selected_line_width,
                visible=self.visible,
                gestures=self._gestures,
            )

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            leg_a = sc.Line([*start], [*axis], color=color_list, thickness=3, visible=self.visible)
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            leg_b = sc.Line([*end], [*axis], color=color_list, thickness=3, visible=self.visible)
            # 포인트
            angle_points = sc.Points(
                [[*start], [*axis], [*end]], sizes=[5] * 3, colors=[color_list] * 3, visible=self.visible
            )
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            angle = Gf.DegreesToRadians(self._payload.primary_value)
            with sc.Transform(transform=flatten(self._calculate_arc_matrix(start, axis, end))):
                sc.Arc(
                    begin=-angle / 2,
                    end=angle / 2,
                    radius=80,
                    axis=1,
                    thickness=2,
                    color=ui.color.white,
                    wireframe=True,
                    sector=False,
                    visible=self.visible,
                )

                sc.Arc(
                    begin=-angle / 2,
                    end=angle / 2 - 2 * pi,
                    radius=50,
                    axis=1,
                    thickness=2,
                    color=ui.color.red,
                    wireframe=True,
                    sector=False,
                    visible=self.visible,
                )

        if label_dirty:
            self._lbl_root.clear()
            with self._lbl_root:
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                primary_label_pos = axis + Gf.Vec3d(0, 22.5, 0)
                self._draw_label([*primary_label_pos])

    def _calculate_arc_matrix(self, start: Gf.Vec3d, mid: Gf.Vec3d, end: Gf.Vec3d) -> Gf.Matrix4d:
        dir_start = (start - mid).GetNormalized()
        dir_end = (end - mid).GetNormalized()

        up = Gf.Cross(dir_start, dir_end).GetNormalized()
        front = (dir_start + dir_end).GetNormalized()
        side = Gf.Cross(up, front).GetNormalized()
        rot_mtx = Gf.Matrix4d(1.0)
        rot_mtx.SetRow3(0, side)
        rot_mtx.SetRow3(1, up)
        rot_mtx.SetRow3(2, front)
        rot_mtx.SetTranslateOnly(mid)

        return rot_mtx

    # TODO: 후속 구현 및 정리가 필요합니다.
    def _draw_label(self, position: Union[Vec3d, List[float]]):
        precision = list(Precision).index(self._payload.precision.value)

        label_text = f"{self._payload.primary_value:.{precision}f}°"
        secondary_label_text = f"{self._payload.secondary_values[0]:.{precision}f}°"
        text_size = self._payload.label_size
        size_bias = LABEL_SCALE_MAPPING[text_size]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        char_len = max(len(label_text) - 3, len(secondary_label_text) - 3)  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

        xform = sc.Transform(
            look_at=sc.Transform.LookAt.CAMERA, transform=sc.Matrix44.get_translation_matrix(*position), visible=False
        )

        with xform:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, 22.5, 0)):
                    sc.Label(label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.LEFT_CENTER)
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, -22.5, 0)):
                    sc.Label(
                        secondary_label_text,
                        size=text_size.value,
                        color=[0, 0, 0, 1],
                        alignment=ui.Alignment.LEFT_CENTER,
                    )
                # 배경
                sc.Rectangle(width=rect_width, height=90, color=[1, 1, 1, 1], wireframe=False, gestures=self._gestures)

                mode_name = self._payload.tool_mode.name.lower()
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, 22.5, 0)):
                    sc.Rectangle(
                        width=45, height=45, color=[0, 0, 0, 1], wireframe=False, gestures=self._delete_gestures
                    )
                    # 아이콘 이미지

                    icon_path = get_icon_path("tool_delete") if self.selected else get_icon_path(f"tool_{mode_name}")
                    self._tool_image = sc.Image(source_url=icon_path, width=45, height=45)
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, -22.5, 0)):
                    sc.Rectangle(width=45, height=45, color=[0, 0, 0, 1], wireframe=False)
                    # 아이콘 이미지
                    icon_path = get_icon_path(f"tool_{mode_name}")
                    self._tool_image = sc.Image(source_url=icon_path, width=45, height=45, color=ui.color.red)

        xform.visible = self.visible
        return xform


class DiameterMeasurementItem(_MeasurementItem):
    """동작 설명입니다."""

    def __init__(self, measure_prim: MeasurePrim):
        super().__init__()
        self._prim: MeasurePrim = measure_prim
        self._payload = self._prim.payload

    def _on_selection_state_changed(self):
        pass

    def _draw(self, label_dirty: bool = True):
        color_list = [*self.payload.label_color]
        interact_color = self._selected_line_color if self._selected else HOVER_COLOR if self._hovered else [0, 0, 0, 0]

        # 데이터 수집
        start, mid, end, center = self._payload.computed_points[:4]
        diameter = (start - center).GetLength() * 2

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        dir_start = (start - center).GetNormalized()
        dir_end = (end - center).GetNormalized()

        up = Gf.Cross(dir_start, dir_end).GetNormalized()
        front = (dir_start + dir_end).GetNormalized()
        side = Gf.Cross(up, front).GetNormalized()
        xform_mtx = Gf.Matrix4d(1.0)
        xform_mtx.SetRow3(0, side)
        xform_mtx.SetRow3(1, up)
        xform_mtx.SetRow3(2, front)
        xform_mtx.SetTranslateOnly(center)

        self._root.clear()
        with self._root:
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            with sc.Transform(flatten(xform_mtx)):
                sc.Arc(diameter * 0.5, axis=1, thickness=2, color=[1, 1, 1, 1], wireframe=True, visible=self.visible)

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            d_end = (center - start).GetNormalized() * diameter + start

            click_line = sc.Line(
                [*start],
                [*d_end],
                color=interact_color,
                thickness=self._selected_line_width,
                visible=self.visible,
                gestures=self._gestures,
            )
            sc.Line([*start], [*d_end], color=color_list, thickness=3, visible=self.visible)
            sc.Points([[*start], [*d_end]], sizes=[5] * 2, colors=[[1, 1, 1, 1]] * 2, visible=self.visible)

        if label_dirty:
            self._lbl_root.clear()
            with self._lbl_root:
                self._draw_label()

    def _draw_label(self):
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        precision = list(Precision).index(self._payload.precision.value)

        start, mid, end, center = self._payload.computed_points[:4]

        label_pos = center + -(Gf.Cross(start - mid, end - mid).GetNormalized() * 10)
        label_text = f"{self._payload.primary_value:.{precision}f} {self._payload.unit_type.value}"
        text_size = self._payload.label_size
        size_bias = LABEL_SCALE_MAPPING[text_size]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        char_len = len(label_text)
        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

        xform = sc.Transform(
            look_at=sc.Transform.LookAt.CAMERA,
            transform=sc.Matrix44.get_translation_matrix(*label_pos),
            visible=self.visible,
        )

        with xform:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                # 라벨
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, 0, 0)):
                    sc.Label(label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.LEFT_CENTER)
                # 배경
                sc.Rectangle(width=rect_width, height=45, color=[1, 1, 1, 1], wireframe=False, gestures=self._gestures)
                # 아이콘
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, 0, 0)):
                    # 아이콘 배경
                    sc.Rectangle(
                        width=45, height=45, color=[0, 0, 0, 1], wireframe=False, gestures=self._delete_gestures
                    )
                    # 아이콘 이미지
                    mode_name = self._payload.tool_mode.name.lower()
                    icon_path = get_icon_path("tool_delete") if self.selected else get_icon_path(f"tool_{mode_name}")
                    self._tool_image = sc.Image(source_url=icon_path, width=45, height=45)

        xform.visible = self.visible
        return xform


class AreaMeasurementItem(_MeasurementItem):
    """동작 설명입니다."""

    def __init__(self, measure_prim: MeasurePrim):
        super().__init__()
        self._prim: MeasurePrim = measure_prim
        self._payload = self._prim.payload

    def _on_selection_state_changed(self):
        pass

    def _draw(self, label_dirty: bool = True):
        color_list = [*self.payload.label_color]
        interact_color = self._selected_line_color if self._selected else HOVER_COLOR if self._hovered else [0, 0, 0, 0]

        # 데이터 수집
        points = [[*vec] for vec in self._payload.computed_points]

        self._root.clear()
        with self._root:
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            for i in range(len(points) - 1):
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                sc.Line(
                    points[i],
                    points[i + 1],
                    color=interact_color,
                    thickness=self._selected_line_width,
                    visible=self.visible,
                    gestures=self._gestures,
                )
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                sc.Line(points[i], points[i + 1], color=color_list, thickness=3, visible=self.visible)

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            if points[0] != points[-1]:
                sc.Line(
                    points[-1],
                    points[0],
                    color=interact_color,
                    thickness=self._selected_line_width,
                    visible=self.visible,
                    gestures=self._gestures,
                )
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            if points[0] != points[-1]:
                sc.Line(points[-1], points[0], color=color_list, thickness=3, visible=self.visible)
            # 포인트 그리기
            sc.Points(points, sizes=[5] * len(points), colors=[color_list] * len(points), visible=self.visible)

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            # triangle_indices = triangulate_face(self._payload.computed_points)

            # colors = [[0,1,1,0.2]] * sum([len(triangle) for triangle in triangle_indices])
            # vertex_count = [3] * len(triangle_indices)
            # vertex_indices = [idx for tri in triangle_indices for idx in tri]

            # sc.PolygonMesh(
            #     points,  # List[List[float]]
            #     주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            #     vertex_count,  # List[int]
            #     vertex_indices,  # List[int]
            #     wireframe=False,  # Polygons!
            #     intersection_thickness = 0
            # )

        if label_dirty:
            self._lbl_root.clear()
            with self._lbl_root:
                # 메인 라벨 그리기
                self._draw_label()

    # TODO: 후속 구현 및 정리가 필요합니다.
    def _draw_label(self) -> sc.Transform:
        precision = list(Precision).index(self._payload.precision.value)

        centroid = [sum(val) for val in zip(*self._payload.computed_points)]
        centroid = [val / len(self._payload.computed_points) for val in centroid]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        label_pos: List[float] = centroid
        label_text: str = f"{self._payload.primary_value:.{precision}f} {self._payload.unit_type.value}²"
        text_size: LabelSize = LabelSize(self._payload.label_size)
        size_bias: float = LABEL_SCALE_MAPPING[text_size]

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        char_len = len(label_text)
        rect_width = int((45 * 1.5 * size_bias) + (10 * char_len))

        xform = sc.Transform(
            look_at=sc.Transform.LookAt.CAMERA, transform=sc.Matrix44.get_translation_matrix(*label_pos), visible=False
        )

        with xform:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                # 라벨
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) + 22.5, 0, 0)):
                    sc.Label(label_text, size=text_size.value, color=[0, 0, 0, 1], alignment=ui.Alignment.LEFT_CENTER)
                # 배경
                sc.Rectangle(width=rect_width, height=45, color=[1, 1, 1, 1], wireframe=False, gestures=self._gestures)
                # 아이콘
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix((rect_width * -0.5) - 22.5, 0, 0)):
                    # 아이콘 배경
                    sc.Rectangle(
                        width=45, height=45, color=[0, 0, 0, 1], wireframe=False, gestures=self._delete_gestures
                    )
                    # 아이콘 이미지
                    mode_name = self._payload.tool_mode.name.lower()
                    icon_path = get_icon_path("tool_delete") if self.selected else get_icon_path(f"tool_{mode_name}")
                    self._tool_image = sc.Image(source_url=icon_path, width=45, height=45)

        xform.visible = self.visible
        return xform

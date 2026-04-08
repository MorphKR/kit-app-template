# Copyright (c) 2018-2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["SectionManipulator"]

import asyncio

import omni.kit.app
from carb.windowing import CursorStandardShape
from omni.kit.window.cursor import get_main_window_cursor
from omni.ui import scene as sc

from ..common import SECTION_COLOR, SectionManager, SelectionState, WidgetAlignment

PI = 3.1415926
SECTION_WIDTH = 1200
SECTION_HEIGHT = 1200

ARROW_P = [
    [3, 3, 0],
    [-3, 3, 0],
    [0, 0, 15],
    [3, -3, 0],
    [-3, -3, 0],
    [0, 0, 15],
    [3, 3, 0],
    [3, -3, 0],
    [0, 0, 15],
    [-3, 3, 0],
    [-3, -3, 0],
    [0, 0, 15],
]
ARROW_VC = [3, 3, 3, 3]
ARROW_VI = [i for i in range(sum(ARROW_VC))]


# TODO: Suspect unused code; remove if so
def flatten(transform):  # pragma: no cover
    """2차원 배열을 1차원 배열로 평탄화한다."""
    return [item for sublist in transform for item in sublist]


def change_color(sender, changed):  # pragma: no cover
    sender.color = [channel + changed for channel in sender.color]


class SectionManipulator(sc.Manipulator):
    # TODO: Suspect unused code; remove if so
    class ArcRotateTransform(sc.DragGesture):  # pragma: no cover
        def __init__(self):
            super().__init__()
            self._begin_angle = 0

        def on_began(self):
            self._begin_angle = self.sender.gesture_payload.angle

        def on_changed(self):
            angle = self.sender.gesture_payload.angle - self._begin_angle
            axis = self.sender.axis
            if axis == 0:
                align = WidgetAlignment.X
            elif axis == 1:
                align = WidgetAlignment.Y
            else:
                align = WidgetAlignment.Z

            degree = angle * 180 / PI
            SectionManager().rotate_widget(align, degree)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._handle_offset = SECTION_HEIGHT + SECTION_WIDTH * 0.5

        self.__selection_state: SelectionState = SelectionState(kwargs.get("viewport_window", None))
        self._viewport_key = kwargs.get("viewport_key", None)
        self._selection = omni.usd.get_context().get_selection()
        self._section = None

        self._hover_gesture = sc.HoverGesture(
            on_began_fn=lambda sender: change_color(sender, 0.1), on_ended_fn=lambda sender: change_color(sender, -0.1)
        )
        # self._move_gesture = sc.DragGesture(on_changed_fn=self._on_move)
        self._rotate_gesture = self.ArcRotateTransform()

        self.__in_hover = False

    def destroy(self):
        self.__selection_state.destroy()
        self.__selection_state = None

    def show(self, visible: bool):
        if not visible and self.__in_hover:
            # OMPE-1444: When hidden, must clear selection state, otherwise viewport context menu may not work
            self._on_hover_end(None)

    def on_build(self):
        """모델이 변경될 때 섹션 평면 도형을 다시 구성한다."""
        if not self.model:  # pragma: no cover
            return

        # 섹션 평면 본체와 테두리 라인을 구성한다.
        self._section = sc.Transform()
        with self._section:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                self._body = sc.Rectangle(
                    height=SECTION_HEIGHT,
                    width=SECTION_WIDTH,
                    color=0x33FFFFFF,
                    axis=2,
                    gestures=[
                        sc.ClickGesture(name="SectionClick", on_ended_fn=self._on_click_section),
                        sc.HoverGesture(
                            name="SectionHover", on_began_fn=self._on_hover_start, on_ended_fn=self._on_hover_end
                        ),
                    ],
                )

                # 테두리 라인(추후 RectangleLine 클래스로 분리 가능)
                points = [
                    [-SECTION_HEIGHT * 0.5, SECTION_WIDTH * 0.5, 0.0],  # -,+
                    [SECTION_HEIGHT * 0.5, SECTION_WIDTH * 0.5, 0.0],  # +,+
                    [SECTION_HEIGHT * 0.5, -SECTION_WIDTH * 0.5, 0.0],  # +,-
                    [-SECTION_HEIGHT * 0.5, -SECTION_WIDTH * 0.5, 0.0],  # -,-
                ]

                sc.Line(points[0], points[1], color=SECTION_COLOR, thickness=4)
                sc.Line(points[1], points[2], color=SECTION_COLOR, thickness=4)
                sc.Line(points[2], points[3], color=SECTION_COLOR, thickness=4)
                sc.Line(points[3], points[0], color=SECTION_COLOR, thickness=4)

        self._update_transforms()

    def _update_transforms(self):
        transform = self._get_model_transform()
        if self._section:
            self._section.transform = transform

    def on_model_updated(self, item):
        self._update_transforms()

    def _get_model_transform(self):
        transform = self.model.get_as_floats(self.model.get_item("transform"))
        if transform is None:  # pragma: no cover
            scTransform = sc.Matrix44.get_translation_matrix(0, 0, 0)
        else:
            scTransform = sc.Matrix44(
                transform[0][0],
                transform[0][1],
                transform[0][2],
                transform[0][3],
                transform[1][0],
                transform[1][1],
                transform[1][2],
                transform[1][3],
                transform[2][0],
                transform[2][1],
                transform[2][2],
                transform[2][3],
                transform[3][0],
                transform[3][1],
                transform[3][2],
                transform[3][3],
            )

        return scTransform

    def _on_click_section(self, shape: sc.AbstractShape):
        # 기본 선택 오퍼레이터와 충돌을 피하기 위해 다음 프레임에 선택을 반영한다.
        asyncio.ensure_future(self.delay_show())

    def _on_hover_start(self, _sender):
        # 호버 중에는 섹션 조작 우선권을 위해 선택/컨텍스트 메뉴 레이어를 잠시 비활성화한다.
        self.__in_hover = True
        if self.__selection_state:
            self.__selection_state.reserve()
            self.__selection_state.enabled = False
        get_main_window_cursor().override_cursor_shape(CursorStandardShape.HAND)

    def _on_hover_end(self, _sender):
        # 입력 레이어를 원래 상태로 복구한다.
        if self.__selection_state:
            self.__selection_state.restore()
        get_main_window_cursor().clear_overridden_cursor_shape()
        self.__in_hover = False

    async def delay_show(self):
        # 몇 프레임 대기 후 gizmo를 표시해 클릭 직후 상태 경쟁을 완화한다.
        for i in range(10):
            await omni.kit.app.get_app().next_update_async()

        self.show_gizmo(True)

    def show_gizmo(self, value):
        widget_prim = SectionManager().get_section_widget_prim(viewport_key=self._viewport_key)
        if value and widget_prim:
            widget_prim_path = widget_prim.GetPath().pathString
            self._selection.set_selected_prim_paths([widget_prim_path], True)
        else:
            self._selection.clear_selected_prim_paths()

        #### 네이티브 매니퓰레이터 사용
        #### 참고용으로 이전 구현 스케치를 보존한다.

        # if not value:
        #     self._gizmo.clear()
        #     return

        # # the gizmo to move/rotate the section
        # with self._gizmo:
        #     # Axes
        #     sc.Line(
        #         [0, 0, 0],
        #         [SECTION_HEIGHT * 5, 0, 0],
        #         color=cl(0.9, 0.0, 0.0, 0.9),
        #         thickness=3,
        #         gestures=[self._hover_gesture, self._move_gesture]
        #     )
        #     sc.Line(
        #         [0, 0, 0],
        #         [0, SECTION_HEIGHT * 5, 0],
        #         color=cl(0.0, 0.9, 0.0, 0.9),
        #         thickness=3,
        #         gestures=[self._hover_gesture, self._move_gesture]
        #     )
        #     sc.Line(
        #         [0, 0, 0],
        #         [0, 0, SECTION_HEIGHT * 5],
        #         color=cl(0.0, 0.0, 0.9, 0.9),
        #         thickness=3,
        #         gestures=[self._hover_gesture, self._move_gesture]
        #     )

        #     # Arrows
        #     vert_count = len(ARROW_VI)
        #     one = Gf.Matrix4d(1)
        #     with sc.Transform(
        #         transform=flatten(
        #             one.SetTransform(Gf.Rotation(Gf.Vec3d(0, 1, 0), 90), Gf.Vec3d(SECTION_HEIGHT * 5, 0, 0))
        #         )
        #     ):
        #         sc.PolygonMesh(ARROW_P, [ui.color.red] * vert_count, ARROW_VC, ARROW_VI)
        #     with sc.Transform(
        #         transform=flatten(
        #             one.SetTransform(Gf.Rotation(Gf.Vec3d(1, 0, 0), -90), Gf.Vec3d(0, SECTION_HEIGHT * 5, 0))
        #         )
        #     ):
        #         sc.PolygonMesh(ARROW_P, [ui.color.green] * vert_count, ARROW_VC, ARROW_VI)
        #     with sc.Transform(transform=flatten(one.SetTranslate(Gf.Vec3d(0, 0, SECTION_HEIGHT * 5)))):
        #         sc.PolygonMesh(ARROW_P, [ui.color.blue] * vert_count, ARROW_VC, ARROW_VI)

        #     # Arc
        #     sc.Arc(
        #         SECTION_HEIGHT * 2,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.5, 0.5, 0.0, 0.5),
        #         axis=2,
        #         gestures=[self._hover_gesture, self._move_gesture],
        #     )

        #     sc.Arc(
        #         SECTION_HEIGHT * 3,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.5, 0.5, 0.0, 0.5),
        #         axis=2,
        #         wireframe=True,
        #         thickness=8,
        #         gestures=[self._hover_gesture, self._rotate_gesture]
        #     )

        #     sc.Arc(
        #         SECTION_HEIGHT * 2,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.5, 0.0, 0.5, 0.5),
        #         axis=1,
        #         gestures=[self._hover_gesture, self._move_gesture],
        #     )

        #     sc.Arc(
        #         SECTION_HEIGHT * 3,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.5, 0.0, 0.5, 0.5),
        #         axis=1,
        #         wireframe=True,
        #         thickness=8,
        #         gestures=[self._hover_gesture, self._rotate_gesture]
        #     )

        #     sc.Arc(
        #         SECTION_HEIGHT * 2,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.0, 0.5, 0.5, 0.5),
        #         axis=0,
        #         gestures=[self._hover_gesture, self._move_gesture],
        #     )

        #     sc.Arc(
        #         SECTION_HEIGHT * 3,
        #         begin=0,
        #         end=PI * 0.5,
        #         color=cl(0.0, 0.5, 0.5, 0.5),
        #         axis=0,
        #         wireframe=True,
        #         thickness=8,
        #         gestures=[self._hover_gesture, self._rotate_gesture]
        #     )

# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

from abc import abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

import carb.input
import carb.settings
import omni.kit.raycast.query
from carb.input import KeyboardInput
from omni import ui
from omni.ui import scene as sc

from ...common import (
    MeasureCreationState,
    MeasureMode,
    MeasureState,
    Precision,
    SnapMode,
    UnitType,
    convert_area_to_units,
    convert_distance_and_units,
    get_stage_units,
)
from ...manager import ReferenceManager, StateMachine
from ..manipulator_items import *
from ..snap.manager import MeasureSnapProviderManager


class GesturePreventionManager(sc.GestureManager):
    """동작 설명입니다."""

    def __init__(self):
        super().__init__()

    def __del__(self):
        pass

    def can_be_prevented(self, gesture: sc.AbstractGesture) -> bool:
        return True

    def should_prevent(self, gesture: sc.AbstractGesture, preventer: sc.AbstractGesture) -> bool:
        if StateMachine().tool_state == MeasureState.NONE or StateMachine().tool_mode == MeasureMode.NONE:
            return True
        if gesture.name.endswith(StateMachine().tool_mode.name):
            return False
        return True


class CameraManipModeWatcher:
    __instance = None

    CAMERA_MANIP_MODE = "/exts/omni.kit.manipulator.camera/viewportMode"

    def __init__(self):
        self._camera_manip_mode_active = False

        self._settings = carb.settings.get_settings()
        self._camera_manip_mode_sub_0 = self._settings.subscribe_to_node_change_events(
            f"{CameraManipModeWatcher.CAMERA_MANIP_MODE}/0", self._cam_manip_mode_changed
        )
        self._camera_manip_mode_sub_1 = self._settings.subscribe_to_node_change_events(
            f"{CameraManipModeWatcher.CAMERA_MANIP_MODE}/1", self._cam_manip_mode_changed
        )
        self._input = carb.input.acquire_input_interface()
        self._check_current_state()

    def __del__(self):
        self.destroy()

    def destroy(self):
        if self._camera_manip_mode_sub_0:
            self._settings.unsubscribe_to_change_events(self._camera_manip_mode_sub_0)
            self._camera_manip_mode_sub_0 = None

        if self._camera_manip_mode_sub_1:
            self._settings.unsubscribe_to_change_events(self._camera_manip_mode_sub_1)
            self._camera_manip_mode_sub_1 = None

    def _cam_manip_mode_changed(self, item, event_type):
        self._check_current_state()

    def _check_current_state(self):
        cam_manip_active = self._settings.get(CameraManipModeWatcher.CAMERA_MANIP_MODE)
        if cam_manip_active and len(cam_manip_active) > 1:
            self._camera_manip_mode_active = cam_manip_active[1] != ""

    def is_camera_manip_mode_active(self):
        if self._camera_manip_mode_active:
            return True

        # Backup, if for whatever reason the settings listener doesn't work
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        #
        # But just in case there are more such cases .. let's keep this as a backup for now :)
        #
        for key in [carb.input.KeyboardInput.LEFT_ALT, carb.input.KeyboardInput.RIGHT_ALT]:
            if bool(self._input.get_keyboard_button_flags(None, key) & carb.input.BUTTON_FLAG_DOWN):
                return True

        return False

    @staticmethod
    def get_instance():
        if not CameraManipModeWatcher.__instance:
            CameraManipModeWatcher.__instance = CameraManipModeWatcher()
        return CameraManipModeWatcher.__instance

    @staticmethod
    def delete_instance():
        if CameraManipModeWatcher.__instance is not None:
            CameraManipModeWatcher.__instance.destroy()
        CameraManipModeWatcher.__instance = None


class ViewportModeModel(sc.AbstractManipulatorModel):
    """동작 설명입니다."""

    def __init__(self, viewport_api, mode: MeasureMode = MeasureMode.NONE):
        from ._scene_widget import SnapMarker  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

        super().__init__()
        self._api = viewport_api
        self._snap: MeasureSnapProviderManager = MeasureSnapProviderManager()
        self._snap_data: Optional[Dict[str, Any]] = {}
        self._raycast_query = omni.kit.raycast.query.acquire_raycast_query_interface()
        self._camera_manip_mode_watcher = CameraManipModeWatcher.get_instance()
        self._ignore_current_drag = False

        self._mode: MeasureMode = mode
        self._state: ui.SimpleIntModel = ui.SimpleIntModel()
        self._creation_state: ui.SimpleIntModel = ui.SimpleIntModel()
        self._enabled_model: ui.SimpleBoolModel = ui.SimpleBoolModel()

        self._state.add_value_changed_fn(self.__on_tool_state_changed)
        self._creation_state.add_value_changed_fn(self.__on_creation_state_changed)
        self._enabled_model.add_value_changed_fn(self.__on_enabled_changed)

        # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        self.__base: sc.Transform = sc.Transform()
        with self.__base:
            self._snap_marker: SnapMarker = SnapMarker()
            self._screen: sc.Screen = self.__build_screen()
            self._root: sc.Transform = sc.Transform()
            self._label_root: sc.Transform = sc.Transform()

        ReferenceManager().gesture_screen = self._screen

        self._key_sub = StateMachine().subscribe_to_key_pressed_event(self.__on_key_pressed)

    def __build_screen(self) -> sc.Screen:
        gesture_manager: GesturePreventionManager = GesturePreventionManager()

        move_gesture = sc.HoverGesture(
            name=f"move_{self._mode.name}",
            on_changed_fn=lambda sender: self.__on_moved(sender),
            manager=gesture_manager,
        )
        drag_gesture = sc.DragGesture(
            name=f"drag_{self._mode.name}",
            on_began_fn=lambda sender: self.__on_begin_drag(sender),
            on_changed_fn=lambda sender: self.__on_drag(sender),
            on_ended_fn=lambda sender: self.__on_end_drag(sender),
            manager=gesture_manager,
        )

        #주석 정리: 구현 의도는 코드 흐름을 참고하세요.
        ## ClickGesture for the left mouse button, but are instead using the DragGesture's on_ended and treat
        ## that one as a left click :)
        ##

        # left_click_gesture = sc.ClickGesture(
        #     name=f"left_click_{self._mode.name}",
        #     mouse_button=0,
        #     on_ended_fn=lambda sender: self.__on_clicked(sender, 0),
        #     manager=gesture_manager
        # )

        right_click_gesture = sc.ClickGesture(
            name=f"right_click_{self._mode.name}",
            mouse_button=1,
            on_ended_fn=lambda sender: self.__on_clicked(sender, 1),
            manager=gesture_manager,
        )
        middle_click_gesture = sc.ClickGesture(
            name=f"middle_click_{self._mode.name}",
            mouse_button=2,
            on_ended_fn=lambda sender: self.__on_clicked(sender, 2),
            manager=gesture_manager,
        )

        return sc.Screen(
            gestures=[
                move_gesture,
                drag_gesture,
                # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
                right_click_gesture,
                middle_click_gesture,
            ]
        )

    @property
    def enabled(self) -> bool:
        return self._enabled_model.as_bool

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled_model.as_bool = value

    @property
    def state(self) -> MeasureState:
        return MeasureState(self._state.as_int)

    @state.setter
    def state(self, state: MeasureState) -> None:
        self._state.as_int = state.value

    @property
    def creation_state(self) -> MeasureCreationState:
        return MeasureCreationState(self._creation_state.as_int)

    @creation_state.setter
    def creation_state(self, state: MeasureCreationState) -> None:
        self._creation_state.as_int = state.value

    # 모델 콜백
    def __on_tool_state_changed(self, model: ui.AbstractValueModel) -> None:
        tool_state: MeasureState = MeasureState(model.as_int)
        if tool_state == MeasureState.CREATE:
            self.creation_state = MeasureCreationState.START_SELECTION
        elif tool_state == MeasureState.EDIT:
            pass
        else:
            self.reset()

    def __on_creation_state_changed(self, model: ui.AbstractValueModel) -> None:
        creation_state: MeasureCreationState = MeasureCreationState(model.as_int)
        StateMachine().tool_creation_state = creation_state
        if creation_state == MeasureCreationState.NONE:  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            self.reset()
            return

        if creation_state == MeasureCreationState.START_SELECTION:
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            MeasureSnapProviderManager().enabled = True
            ReferenceManager().ui_placement_panel.lock_properties(False)
            ReferenceManager().ui_display_panel.lock_properties(False)
        elif creation_state in [MeasureCreationState.INTERMEDIATE_SELECTION, MeasureCreationState.END_SELECTION]:
            ReferenceManager().ui_placement_panel.lock_properties(True)
            ReferenceManager().ui_display_panel.lock_properties(True)
            self.draw()
        elif creation_state == MeasureCreationState.FINALIZE:
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            MeasureSnapProviderManager().enabled = False
            self.draw()

    def __on_enabled_changed(self, model: ui.AbstractValueModel) -> None:
        value = model.as_bool
        self._root.clear() if value else self.draw()

    def _set_snap_marker_position(self, coord: Optional[Gf.Vec3d], mode: SnapMode = SnapMode.SURFACE):
        self._snap_marker.set_snap_marker(coord, mode)
        # self._snap_marker.positions = [[*coord]] if coord else []

    # 제스처 콜백
    def __coords_in_viewport(self, coords: Sequence[float]) -> bool:
        return self._api.map_ndc_to_texture(coords)[-1] is not None

    def __on_moved(self, sender):
        if self._camera_manip_mode_watcher.is_camera_manip_mode_active():
            return

        def query(ray, result: omni.kit.raycast.query.RayQueryResult, *args, **kwargs):
            prim_path = result.get_target_usd_path() if result.valid else ""
            if prim_path == "" or None:
                return
            self._on_moved(sender.gesture_payload.mouse, result)

        if self.__coords_in_viewport(sender.gesture_payload.mouse):
            coords = self._api.map_ndc_to_texture_pixel(sender.gesture_payload.mouse)[0]
            if coords:
                origin, dir, dist = self._generate_picking_ray(sender.gesture_payload.mouse)

                ray = omni.kit.raycast.query.Ray(origin, dir)
                self._raycast_query.submit_raycast_query(ray, query)

    def _generate_picking_ray(self, ndc_location: Sequence[float]) -> Tuple[Sequence[float], Sequence[float], float]:
        """동작 설명입니다."""
        ndc_near = (ndc_location[0], ndc_location[1], -1)
        ndc_far = (ndc_location[0], ndc_location[1], 1)
        view = self._api.view
        proj = self._api.projection
        view_proj_inv = (view * proj).GetInverse()

        origin = view_proj_inv.Transform(ndc_near)
        dir = view_proj_inv.Transform(ndc_far) - origin
        dist = dir.Normalize()

        # Don't use (*origin) to unpack Gf Types. Very Slow
        return ((origin[0], origin[1], origin[2]), (dir[0], dir[1], dir[2]), dist)

    def __on_begin_drag(self, sender):
        if self._camera_manip_mode_watcher.is_camera_manip_mode_active():
            self._ignore_current_drag = True
            return

        self._ignore_current_drag = False
        ndc_coord = sender.gesture_payload.mouse
        if self.__coords_in_viewport(ndc_coord):
            self._on_begin_drag(ndc_coord)

    def __on_drag(self, sender):
        if self._camera_manip_mode_watcher.is_camera_manip_mode_active():
            self._ignore_current_drag = True
            return

        if self._ignore_current_drag:
            return

        ndc_coord = sender.gesture_payload.mouse
        if self.__coords_in_viewport(ndc_coord):
            self._on_drag(ndc_coord)

    def __on_end_drag(self, sender):
        if self._camera_manip_mode_watcher.is_camera_manip_mode_active():
            return

        if self._ignore_current_drag:
            # The Camera Manipulation Gesture's drag ends before ours, so we have to check if it was
            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            return

        ndc_coord = sender.gesture_payload.mouse
        if self.__coords_in_viewport(ndc_coord):
            self._on_end_drag(ndc_coord)

            # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
            self._on_clicked(ndc_coord, 0)

    def __on_clicked(self, sender, mouse_button: int):
        if self._camera_manip_mode_watcher.is_camera_manip_mode_active():
            return

        ndc_coord = sender.gesture_payload.mouse
        if self.__coords_in_viewport(ndc_coord):
            self._on_clicked(ndc_coord, mouse_button)

    def __on_key_pressed(self, key: KeyboardInput):
        match key:
            case KeyboardInput.ENTER | KeyboardInput.NUMPAD_ENTER:
                self._try_auto_complete_and_save()
        return

    # 공통 함수
    def _get_unit_type(self) -> UnitType:
        disp_panel = ReferenceManager().ui_display_panel
        return disp_panel.unit or get_stage_units(as_enum=True)

    def _value_to_unit(self, value, is_area: bool = False) -> Tuple[float, str]:
        unit_type = self._get_unit_type().value.lower()
        if is_area:
            return convert_area_to_units(value, unit_type), unit_type
        return convert_distance_and_units(value, unit_type)

    def _get_precision_value(self) -> int:
        disp_panel = ReferenceManager().ui_display_panel
        return list(Precision).index(disp_panel.precision.value)

    def _get_display_color(self) -> List[float]:
        color = ReferenceManager().ui_display_panel.color
        return [color[0], color[1], color[2], color[3]]  # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.

    # 추상 메서드
    @abstractmethod
    def reset(self):
        """동작 설명입니다."""
        self.state = MeasureState.NONE
        self.creation_state = MeasureCreationState.NONE
        self._set_snap_marker_position(None, SnapMode.SURFACE)

    @abstractmethod
    def draw(self):
        """동작 설명입니다."""
        return

    def _try_auto_complete_and_save(self):
        return

    @abstractmethod
    def _on_save(self):
        """동작 설명입니다."""
        return

    @abstractmethod
    def _on_moved(self, coords: Sequence[float], prim_path: str):
        return

    @abstractmethod
    def _on_clicked(self, coords: Sequence[float], mouse_button: int = 0):
        return

    # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
    # 주석 정리: 구현 의도는 코드 흐름을 참고하세요.
    # so slightly moved during mouse down and up, we aren't using these
    # and instead handle on_drag_end as a click :)
    def _on_begin_drag(self, coords: Sequence[float]):
        return

    def _on_drag(self, coords: Sequence[float]):
        return

    def _on_end_drag(self, coords: Sequence[float]):
        return

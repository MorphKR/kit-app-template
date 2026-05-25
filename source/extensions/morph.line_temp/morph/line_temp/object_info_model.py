from pxr import Tf
from pxr import Usd
from pxr import UsdGeom
from pxr import Gf

from omni.ui import scene as sc
import omni.usd


class ObjInfoModel(sc.AbstractManipulatorModel):
    """
    The model tracks object info for either USD selection or a manually supplied target.

    Manual target mode does not modify usd_context selection.
    Call set_manual_target(...) to display label, dot, and leader line independently
    from omni.usd selection state.
    """

    class PositionItem(sc.AbstractManipulatorItem):
        def __init__(self) -> None:
            super().__init__()
            self.value = [0, 0, 0]

    def __init__(self) -> None:
        super().__init__()

        self.prim = None
        self.current_path = ""
        self.stage_listener = None
        self.position = ObjInfoModel.PositionItem()

        self.manual_enabled = False
        self.manual_name = ""
        self.manual_position = None
        self.manual_bbox_min = None
        self.manual_bbox_max = None

        self.usd_context = omni.usd.get_context()
        self.events = self.usd_context.get_stage_event_stream()
        self.stage_event_delegate = self.events.create_subscription_to_pop(
            self.on_stage_event,
            name="Object Info Selection Update",
        )

    def on_stage_event(self, event):
        if event.type == int(omni.usd.StageEventType.SELECTION_CHANGED):
            if self.manual_enabled:
                return

            prim_path = self.usd_context.get_selection().get_selected_prim_paths()

            if not prim_path:
                self.current_path = ""
                self._item_changed(self.position)
                return

            stage = self.usd_context.get_stage()
            prim = stage.GetPrimAtPath(prim_path[0])

            if not prim.IsA(UsdGeom.Imageable):
                self.prim = None
                if self.stage_listener:
                    self.stage_listener.Revoke()
                    self.stage_listener = None
                return

            if not self.stage_listener:
                self.stage_listener = Tf.Notice.Register(
                    Usd.Notice.ObjectsChanged,
                    self.notice_changed,
                    stage,
                )

            self.prim = prim
            self.current_path = prim_path[0]
            self._item_changed(self.position)

    def set_manual_target(self, name="", position=None, bbox_min=None, bbox_max=None, prim_path=None):
        """
        Display an object info target without using usd_context selection.
        """
        self.manual_enabled = True
        self.manual_name = str(name or prim_path or "Manual Target")

        if bbox_min is None or bbox_max is None:
            computed_min, computed_max = self._compute_bbox_from_prim_path(prim_path)
            bbox_min = bbox_min if bbox_min is not None else computed_min
            bbox_max = bbox_max if bbox_max is not None else computed_max

        self.manual_bbox_min = self._to_vec3(bbox_min)
        self.manual_bbox_max = self._to_vec3(bbox_max)

        if position is not None:
            self.manual_position = self._to_vec3(position)
        else:
            direction = self._get_direction_from_bounds(self.manual_bbox_min, self.manual_bbox_max)
            self.manual_position = self._get_anchor_center_from_bounds(
                self.manual_bbox_min,
                self.manual_bbox_max,
                direction,
            )

        self._item_changed(self.position)

    def clear_manual_target(self):
        self.manual_enabled = False
        self.manual_name = ""
        self.manual_position = None
        self.manual_bbox_min = None
        self.manual_bbox_max = None
        self._item_changed(self.position)

    def get_item(self, identifier):
        if identifier == "name":
            return self.manual_name if self.manual_enabled else self.current_path
        elif identifier == "position":
            return self.position
        elif identifier == "manual_enabled":
            return self.manual_enabled
        return None

    def get_as_floats(self, item):
        if item == self.position:
            return self.get_position()
        if item:
            return item.value
        return []

    def get_position(self):
        if self.manual_enabled:
            if self.manual_position is not None:
                return [self.manual_position[0], self.manual_position[1], self.manual_position[2]]
            return [0, 0, 0]

        bbox_min, bbox_max = self.get_selected_bounds()
        direction = self.get_line_direction()
        anchor_center = self._get_anchor_center_from_bounds(bbox_min, bbox_max, direction)
        if anchor_center is None:
            return [0, 0, 0]
        return [anchor_center[0], anchor_center[1], anchor_center[2]]

    def get_selected_bounds(self):
        if self.manual_enabled:
            return self.manual_bbox_min, self.manual_bbox_max

        return self._compute_bbox_from_prim_path(self.current_path)

    def get_line_direction(self):
        """
        Returns "up" or "down" by comparing selected child prim Y against
        the top-level prim AABB center Y.

        If the result is "down", get_position() returns selected AABB bottom-center.
        If the result is "up", get_position() returns selected AABB top-center.
        """
        if self.manual_enabled:
            return self._get_direction_from_bounds(self.manual_bbox_min, self.manual_bbox_max)

        bbox_min, bbox_max = self.get_selected_bounds()
        selected_top_center = self._get_top_center_from_bounds(bbox_min, bbox_max)
        if selected_top_center is None:
            return "up"

        root_min, root_max = self.get_top_level_bounds()
        if root_min is None or root_max is None:
            return "up"

        root_center_y = (root_min[1] + root_max[1]) * 0.5
        selected_y = selected_top_center[1]

        return "up" if selected_y >= root_center_y else "down"

    def get_top_level_bounds(self):
        if self.manual_enabled:
            return self.manual_bbox_min, self.manual_bbox_max

        stage = self.usd_context.get_stage()
        if not stage or self.current_path == "":
            return None, None

        selected_prim = stage.GetPrimAtPath(self.current_path)
        if not selected_prim or not selected_prim.IsValid():
            return None, None

        top_prim = self._get_top_level_prim_excluding_default(stage, selected_prim)
        return self._compute_bbox(top_prim)

    def _get_top_level_prim_excluding_default(self, stage, selected_prim):
        selected_path = selected_prim.GetPath()
        default_prim = stage.GetDefaultPrim()

        if default_prim and default_prim.IsValid():
            default_path = default_prim.GetPath()

            if selected_path == default_path:
                return selected_prim

            if selected_path.HasPrefix(default_path):
                relative_path = selected_path.MakeRelativePath(default_path)
                parts = str(relative_path).split("/")

                if parts and parts[0] not in ("", "."):
                    return stage.GetPrimAtPath(default_path.AppendChild(parts[0]))

        parts = str(selected_path).strip("/").split("/")
        if parts and parts[0]:
            return stage.GetPrimAtPath("/" + parts[0])

        return selected_prim

    def _compute_bbox_from_prim_path(self, prim_path):
        stage = self.usd_context.get_stage()
        if not stage or not prim_path:
            return None, None

        prim = stage.GetPrimAtPath(prim_path)
        return self._compute_bbox(prim)

    def _compute_bbox(self, prim):
        if not prim or not prim.IsValid():
            return None, None

        box_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            includedPurposes=[
                UsdGeom.Tokens.default_,
                UsdGeom.Tokens.render,
                UsdGeom.Tokens.proxy,
            ],
        )
        bound = box_cache.ComputeWorldBound(prim)
        aligned_range = bound.ComputeAlignedBox()

        if aligned_range.IsEmpty():
            return None, None

        return aligned_range.GetMin(), aligned_range.GetMax()

    def _get_direction_from_bounds(self, bbox_min, bbox_max):
        if bbox_min is None or bbox_max is None:
            return "up"
        bounds_center_y = (bbox_min[1] + bbox_max[1]) * 0.5
        selected_top_y = bbox_max[1]
        return "up" if selected_top_y >= bounds_center_y else "down"

    def _get_anchor_center_from_bounds(self, bbox_min, bbox_max, direction):
        if direction == "down":
            return self._get_bottom_center_from_bounds(bbox_min, bbox_max)
        return self._get_top_center_from_bounds(bbox_min, bbox_max)

    def _get_top_center_from_bounds(self, bbox_min, bbox_max):
        if bbox_min is None or bbox_max is None:
            return None
        return Gf.Vec3d(
            (bbox_min[0] + bbox_max[0]) * 0.5,
            bbox_max[1],
            (bbox_min[2] + bbox_max[2]) * 0.5,
        )

    def _get_bottom_center_from_bounds(self, bbox_min, bbox_max):
        if bbox_min is None or bbox_max is None:
            return None
        return Gf.Vec3d(
            (bbox_min[0] + bbox_max[0]) * 0.5,
            bbox_min[1],
            (bbox_min[2] + bbox_max[2]) * 0.5,
        )

    def _to_vec3(self, value):
        if value is None:
            return None
        if isinstance(value, (Gf.Vec3d, Gf.Vec3f)):
            return Gf.Vec3d(value[0], value[1], value[2])
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return Gf.Vec3d(float(value[0]), float(value[1]), float(value[2]))
        return None

    def notice_changed(self, notice: Usd.Notice, stage: Usd.Stage) -> None:
        if self.manual_enabled:
            return
        for p in notice.GetChangedInfoOnlyPaths():
            if self.current_path in str(p.GetPrimPath()):
                self._item_changed(self.position)

    def destroy(self):
        self.events = None
        self.stage_event_delegate.unsubscribe()
        if self.stage_listener:
            self.stage_listener.Revoke()
            self.stage_listener = None

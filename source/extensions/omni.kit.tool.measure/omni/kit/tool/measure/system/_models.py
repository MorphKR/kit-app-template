# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

__all__ = ["MeasurementModel", "PointPrimRelationshipModel"]

from typing import Dict, List, Optional, Set, Union

import carb.profiler
import omni.usd as ou
import usdrt
from omni import ui
from pxr import Gf, Sdf, Usd

from ..common import MeasureMode
from ..system import MeasurePayload


class MeasurementModel(ui.AbstractItemModel):
    """MeasurementModel 클래스 설명입니다."""
    def __init__(self):
        """__init__ 동작을 수행합니다."""
        super().__init__()
        self._measurements: Dict[int, "MeasurePrim"] = {}
        self.__search_query: str = ""
        self.__filter_types: Set[MeasureMode] = set()

        # A sorted list containing tuples of affected prim_path -> measure prim
        # Using bisect_left, it emulates std::set::lower_bound to quickly find out what MeasurePrims are affected by a
        # changed path.
        # i.e.
        #   if `/foo`'s transform has changed, you can find out measurements that are associated with `/foo` or `/foo/bar`
        #   prims quickly with bisect_left. See usage in MeasurementManager._process_pending_changed_path

    @property
    def __measure_scene(self):
        """__measure_scene 동작을 수행합니다."""
        from ..manager import ReferenceManager

        return ReferenceManager().measure_scene

    @property
    def prim_paths_to_measure_map(self) -> list[tuple[Sdf.Path, "MeasurePrim"]]:
        """prim_paths_to_measure_map 동작을 수행합니다."""
        prim_paths_to_measure_map: list[tuple[Sdf.Path, "MeasurePrim"]] = []

        for measure_prim in self._measurements.values():
            for prim_path in measure_prim.payload.prim_paths:
                prim_paths_to_measure_map.append((Sdf.Path(prim_path), measure_prim))
        prim_paths_to_measure_map.sort(key=lambda m: m[0])

        return prim_paths_to_measure_map

    def get_item_value_model_count(self, item: ui.AbstractItem) -> int:
        """get_item_value_model_count 동작을 수행합니다."""
        return 6

    def get_item_children(self, item: ui.AbstractItem):
        """get_item_children 동작을 수행합니다."""
        if item == None:
            measurements = []
            if len(self.__filter_types) != 0:
                measurements = [prim for prim in self._measurements.values() if prim.mode in self.__filter_types]
            else:
                measurements = list(self._measurements.values())

            if self.__search_query != "":
                measurements = [prim for prim in measurements if self.__search_query in prim.name.lower()]

            return measurements
        return item.children

    def add(self, uuid: int, measure_prim: "MeasurePrim") -> None:
        """add 동작을 수행합니다."""
        if self.get_item(uuid) == None:
            self._measurements[uuid] = measure_prim
            super()._item_changed(None)

    def remove(self, uuid: int) -> bool:
        """remove 동작을 수행합니다."""
        if not uuid in self._measurements:
            return False

        self._measurements.pop(uuid)
        super()._item_changed(None)
        return True

    # TODO: Use this function to call the prim refresh and item change versus split in Manager.
    @carb.profiler.profile
    def update(self, measure_prim: "MeasurePrim") -> "MeasurePrim":
        """update 동작을 수행합니다."""
        if measure_prim.uuid in self._measurements:
            measure_prim.refresh_payload()
            self.__measure_scene.update(measure_prim.payload)
            super()._item_changed(measure_prim)
            return measure_prim

    def clear(self):
        """clear 동작을 수행합니다."""
        self._measurements = {}
        super()._item_changed(None)

    def get_item(self, uuid: int) -> "MeasurePrim":
        """get_item 동작을 수행합니다."""
        return self._measurements.get(uuid)

    def get_items(self) -> List["MeasurePrim"]:
        """get_items 동작을 수행합니다."""
        return list(self._measurements.values())

    def get_selected(self) -> List["MeasurePrim"]:
        """get_selected 동작을 수행합니다."""
        return [self.get_item(uuid) for uuid in self.__measure_scene.selected]

    def set_search(self, query: str) -> None:
        """set_search 동작을 수행합니다."""
        self.__search_query = query.lower()
        super()._item_changed(None)

    def reset_filters(self) -> None:
        """reset_filters 동작을 수행합니다."""
        self.__filter_types.clear()
        super()._item_changed(None)

    def set_filter_type(self, filter_type: MeasureMode, add_or_remove: bool):
        """set_filter_type 동작을 수행합니다."""
        if add_or_remove:
            self.__filter_types.add(filter_type)
        else:
            if filter_type in self.__filter_types:
                self.__filter_types.remove(filter_type)
        super()._item_changed(None)

    @property
    def paths(self) -> List[str]:
        """paths 동작을 수행합니다."""
        return [m_prim.path for m_prim in self._measurements.values()]


class PointPrimRelationshipModel:
    """
    Custom model that handles the individual point-to-primitive relationship
    retaining its created transform offset from the prims local transform matrix.
    This way, as a primitive moves, rotates, scales the computed output will
    adapt and update.

     -------              -------
    |       |     ROT    |       |
    |   >   P    ====>   |   v   |
    |       |            |       |
     -------              ---P---
    """

    def __init__(self, point: Gf.Vec3d, measure_prim: Usd.Prim, prim_path_index: int):
        """__init__ 동작을 수행합니다."""
        self.__stage: Usd.Stage = ou.get_context().get_stage()
        self.__rt_stage: usdrt.Usd.Stage = usdrt.Usd.Stage.Attach(ou.get_context().get_stage_id())
        self.__point: Gf.Vec3d = point
        self.__measure_prim: Usd.Prim = measure_prim
        self.__prim_path_index = prim_path_index

    @property
    def point(self) -> Gf.Vec3d:
        """point 동작을 수행합니다."""
        return self.__point

    @point.setter
    def point(self, value: Gf.Vec3d) -> None:
        """point 동작을 수행합니다."""
        self.__point = value

    @property
    def computed_point(self) -> Gf.Vec3d:
        """computed_point 동작을 수행합니다."""
        return self.compute()

    @property
    def prim(self) -> Usd.Prim:
        """prim 동작을 수행합니다."""
        return self.__stage.GetPrimAtPath(self.prim_path)

    @property
    def prim_path(self) -> Sdf.Path:
        """prim_path 동작을 수행합니다."""
        prim_paths = MeasurePayload.read_prim_paths(self.__measure_prim)
        return prim_paths[self.__prim_path_index]

    @property
    def data(self) -> Dict:
        """data 동작을 수행합니다."""
        return {"point": self.point, "prim_path": self.prim_path}

    @staticmethod
    def from_data(data: Dict) -> Optional["PointPrimRelationshipModel"]:
        """from_data 동작을 수행합니다."""
        point = data.get("point", None)
        if not isinstance(point, Gf.Vec3d):
            return None

        prim_path = data.get("prim_path", None)
        if prim_path == None or not isinstance(prim_path, str):
            return None

        prim = ou.get_context().get_stage().GetPrimAtPath(prim_path)
        if prim == None:
            return None

        return PointPrimRelationshipModel(point, prim)

    def compute(self) -> Gf.Vec3d:  # Computed point
        # Need to attempt to compute fabric prim first and if that fails use the pxr.Usd / omni.ui method
        """compute 동작을 수행합니다."""
        prim_path = usdrt.Sdf.Path(self.prim_path.pathString)
        if (
            self.__rt_stage
            and (prim := self.__rt_stage.GetPrimAtPath(prim_path))
            and prim.IsValid()
            and prim.HasAttribute("omni:fabric:worldMatrix")
        ):
            wtm = prim.GetAttribute("omni:fabric:worldMatrix").Get()
            return Gf.Vec3d(*wtm.Transform(usdrt.Gf.Vec3d(*self.__point)))

        return ou.get_world_transform_matrix(self.prim).Transform(self.__point)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import omni.usd


@dataclass
class TabPrimState:
    create_path: Optional[str] = None
    prim_paths: List[str] = field(default_factory=list)


class LoaderServices:
    _tab_prim_paths: Dict[str, TabPrimState] = {}

    @classmethod
    async def load_usd(cls, usd_path: str, tab_id: Optional[str] = None, create_path: Optional[str] = None) -> bool:
        if not usd_path:
            return False
        if not usd_path.lower().endswith((".usd", ".usda", ".usdc")):
            return False

        omni.usd.get_context().open_stage(usd_path)

        if tab_id and create_path:
            cls.set_tab_create_path(tab_id, create_path)
            stage = omni.usd.get_context().get_stage()
            if stage and stage.GetPrimAtPath(create_path):
                cls.add_tab_prim_path(tab_id, create_path)
        return True

    @classmethod
    def set_tab_create_path(cls, tab_id: str, create_path: str) -> None:
        state = cls._tab_prim_paths.setdefault(tab_id, TabPrimState())
        state.create_path = create_path.strip() if create_path else None

    @classmethod
    def get_tab_create_path(cls, tab_id: str) -> Optional[str]:
        state = cls._tab_prim_paths.get(tab_id)
        return state.create_path if state else None

    @classmethod
    def add_tab_prim_path(cls, tab_id: str, prim_path: str) -> None:
        if not tab_id or not prim_path:
            return
        state = cls._tab_prim_paths.setdefault(tab_id, TabPrimState())
        if prim_path not in state.prim_paths:
            state.prim_paths.append(prim_path)

    @classmethod
    def get_tab_prim_paths(cls, tab_id: str) -> List[str]:
        state = cls._tab_prim_paths.get(tab_id)
        return list(state.prim_paths) if state else []

    @classmethod
    def get_tab_prims(cls, tab_id: str) -> List[Any]:
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return []
        prims = []
        for prim_path in cls.get_tab_prim_paths(tab_id):
            prim = stage.GetPrimAtPath(prim_path)
            if prim:
                prims.append(prim)
        return prims

    @classmethod
    def get_tab_prims_and_paths(cls, tab_id: str) -> Dict[str, List[Any]]:
        return {
            "create_path": cls.get_tab_create_path(tab_id),
            "prim_paths": cls.get_tab_prim_paths(tab_id),
            "prims": cls.get_tab_prims(tab_id),
        }

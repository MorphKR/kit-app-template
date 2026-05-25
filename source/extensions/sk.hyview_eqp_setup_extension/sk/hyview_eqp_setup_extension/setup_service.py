from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import omni.usd
from omni.kit.viewport.utility import get_viewport_from_window_name
from pxr import Sdf

from .events import APP_TAB_CHANGED, APP_TAB_CREATED, APP_TAB_REMOVED, EventBus


@dataclass
class TabContext:
    tab_id: str
    tab_index: int
    viewport_widgets: list[Any]
    scene_view: Any
    usd_context_name: str
    stage: Any
    root_prim_path: str


class SetupService:
    _event_bus: Optional[EventBus] = None
    _tab_contexts: Dict[str, TabContext] = {}
    _active_tab_id: Optional[str] = None

    def __init__(self, event_bus: EventBus) -> None:
        SetupService._event_bus = event_bus
        SetupService._tab_contexts = {}
        SetupService._active_tab_id = None

    @classmethod
    def create_tab(cls) -> TabContext:
        stage = omni.usd.get_context().get_stage()
        default_root = stage.GetDefaultPrim()

        tab_index = _compute_next_tab_index()
        tab_id = f"tab_{tab_index}"
        root_prim_path = f"/{default_root}/{tab_id}"
        viewport_widgets = _create_viewport_widgets()
        stage = omni.usd.get_context().get_stage()
        context = TabContext(
            tab_id=tab_id,
            tab_index=tab_index,
            viewport_widgets=viewport_widgets,
            scene_view=_create_scene_view(),
            usd_context_name=_get_usd_context_name(),
            stage=stage,
            root_prim_path=root_prim_path,
        )

        _ensure_tab_prim(root_prim_path)

        cls._tab_contexts[tab_id] = context
        cls._active_tab_id = tab_id
        _publish(APP_TAB_CREATED, {"tab_id": tab_id, "tab_index": tab_index, "context": context})
        _publish(APP_TAB_CHANGED, {"active_tab_id": tab_id, "active_tab_index": tab_index, "context": context})
        return context

    @classmethod
    def change_active_tab(cls, tab_id: str) -> None:
        if tab_id not in cls._tab_contexts:
            return
        cls._active_tab_id = tab_id
        context = cls._tab_contexts[tab_id]
        _publish(APP_TAB_CHANGED, {"active_tab_id": tab_id, "active_tab_index": context.tab_index, "context": context})

    @classmethod
    def remove_tab(cls, tab_id: str) -> None:
        if tab_id not in cls._tab_contexts:
            return
        removed_context = cls._tab_contexts.pop(tab_id, None)
        _publish(
            APP_TAB_REMOVED,
            {"tab_id": tab_id, "tab_index": removed_context.tab_index if removed_context else None},
        )

        if cls._active_tab_id == tab_id:
            cls._active_tab_id = next(iter(cls._tab_contexts.keys()), None)
            active_context = cls._tab_contexts.get(cls._active_tab_id) if cls._active_tab_id else None
            _publish(
                APP_TAB_CHANGED,
                {
                    "active_tab_id": cls._active_tab_id,
                    "active_tab_index": active_context.tab_index if active_context else None,
                    "context": active_context,
                },
            )

    @classmethod
    def clear(cls) -> None:
        tab_ids = list(cls._tab_contexts.keys())
        for tab_id in tab_ids:
            cls.remove_tab(tab_id)


def _publish(event_name: str, payload: Dict) -> None:
    if SetupService._event_bus:
        SetupService._event_bus.publish(event_name, payload)


def _ensure_tab_prim(root_prim_path: str) -> None:
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return

    if not stage.GetPrimAtPath(root_prim_path):
        stage.DefinePrim(root_prim_path, "Xform")


def _create_viewport_widgets() -> list[Any]:
    viewport_api = get_viewport_from_window_name("Viewport")
    if viewport_api and hasattr(viewport_api, "fill_frame"):
        viewport_api.fill_frame = True
    if viewport_api is None:
        return []
    return [viewport_api]


def _create_scene_view():
    return None


def _get_usd_context_name() -> str:
    return "default"


def _compute_next_tab_index() -> int:
    used = set()
    for tab_id in SetupService._tab_contexts.keys():
        if tab_id.startswith("tab_"):
            suffix = tab_id[4:]
            if suffix.isdigit():
                used.add(int(suffix))

    index = 1
    while index in used:
        index += 1
    return index

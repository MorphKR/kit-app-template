from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import omni.usd
from pxr import Gf, UsdGeom
from sk.sk_hyview_eqp_viewportwidget_extension.viewport_service import ViewportService, ViewportWidgetHost

from .events import APP_TAB_CHANGED, APP_TAB_CREATED, APP_TAB_REMOVED, EventBus

TAB_Z_SPACING = 10000.0


@dataclass
class TabContext:
    tab_id: str
    tab_index: int
    viewport_widgets: list[ViewportWidgetHost]
    root_prim_path: str


class SetupService:
    _event_bus: Optional[EventBus] = None
    _tab_contexts: Dict[str, TabContext] = {}
    _active_tab_id: Optional[str] = None
    _tab_viewports_by_id: Dict[str, Dict[str, Any]] = {}

    def __init__(self, event_bus: EventBus) -> None:
        SetupService._event_bus = event_bus
        SetupService._tab_contexts = {}
        SetupService._active_tab_id = None
        SetupService._tab_viewports_by_id = {}

    @classmethod
    def create_tab(cls) -> TabContext:
        stage = omni.usd.get_context().get_stage()
        default_root = str(stage.GetDefaultPrim().GetPath())
        print(f"Default root prim path: {default_root}")

        tab_index = _compute_next_tab_index()
        tab_id = f"tab_{tab_index}"
        root_prim_path = default_root + f"/{tab_id}"
        _ensure_tab_prim(root_prim_path, tab_index)

        viewport_widgets = _create_viewport_widgets(tab_id, root_prim_path)
        selected_viewport_api_id = None
        if viewport_widgets:
            selected_viewport_api_id = getattr(getattr(viewport_widgets[0], "viewport_api", None), "id", None)

        context = TabContext(
            tab_id=tab_id,
            tab_index=tab_index,
            viewport_widgets=viewport_widgets,
            root_prim_path=root_prim_path,
        )

        print(f"Created tab context: {context}")

        cls._tab_contexts[tab_id] = context
        cls._tab_viewports_by_id[tab_id] = {
            "selected_viewport_api_id": selected_viewport_api_id,
            "viewport_widgets": viewport_widgets,
        }
        cls._active_tab_id = tab_id
        _publish(
            APP_TAB_CREATED,
            {
                "tab_id": tab_id,
                "tab_index": tab_index,
                "selected_viewport_api_id": selected_viewport_api_id,
                "context": context,
            },
        )
        _publish(
            APP_TAB_CHANGED,
            {
                "active_tab_id": tab_id,
                "active_tab_index": tab_index,
                "selected_viewport_api_id": selected_viewport_api_id,
                "context": context,
            },
        )
        return context

    @classmethod
    def change_active_tab(cls, tab_id: str) -> None:
        if tab_id not in cls._tab_contexts:
            return
        cls._active_tab_id = tab_id
        context = cls._tab_contexts[tab_id]
        selected_viewport_api_id = cls._tab_viewports_by_id.get(tab_id, {}).get("selected_viewport_api_id")
        _publish(
            APP_TAB_CHANGED,
            {
                "active_tab_id": tab_id,
                "active_tab_index": context.tab_index,
                "selected_viewport_api_id": selected_viewport_api_id,
                "context": context,
            },
        )

    @classmethod
    def remove_tab(cls, tab_id: str) -> None:
        if tab_id not in cls._tab_contexts:
            return
        removed_context = cls._tab_contexts.pop(tab_id, None)
        cls._tab_viewports_by_id.pop(tab_id, None)
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


def _ensure_tab_prim(root_prim_path: str, tab_index: int) -> None:
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return

    print(f"Ensuring root prim at path: {root_prim_path}")
    prim = stage.GetPrimAtPath(root_prim_path)
    if not prim:
        prim = stage.DefinePrim(root_prim_path, "Xform")

    # tab_1=0, tab_2=TAB_Z_SPACING, tab_3=TAB_Z_SPACING*2 ...
    z_offset = float((tab_index - 1) * TAB_Z_SPACING)
    xformable = UsdGeom.Xformable(prim)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(0.0, 0.0, z_offset))


def _create_viewport_widgets(tab_id: str, root_prim_path: str) -> list[ViewportWidgetHost]:
    return ViewportService.create_tab_viewport_hosts(tab_id, root_prim_path)

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

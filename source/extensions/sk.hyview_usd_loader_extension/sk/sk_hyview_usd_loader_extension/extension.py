from __future__ import annotations

import re

import omni.ext
import omni.ui as ui

from sk.sk_hyview_eqp_viewportwidget_extension.viewport_service import ViewportService

from .loader_services import LoaderServices

_EXT_INSTANCE = None


def get_instance():
    return _EXT_INSTANCE


class UsdLoaderExtension(omni.ext.IExt):
    """Loader-side utility extension.

    No automatic UI is created on startup.
    Use `show_tab_prim_selector_ui()` when needed.
    """

    def on_startup(self, ext_id):
        global _EXT_INSTANCE
        _EXT_INSTANCE = self
        self._ext_id = ext_id
        self._selector_windows = {}
        self.show_tab_prim_selector_ui()

    def on_shutdown(self):
        global _EXT_INSTANCE
        _EXT_INSTANCE = None
        for window in self._selector_windows.values():
            if window:
                window.visible = False
        self._selector_windows = {}
        self._ext_id = None

    def show_tab_prim_selector_ui(self):
        tab_ids = self._collect_tab_ids()
        if not tab_ids:
            self._show_refresh_only_ui()
            return
        refresh_only = self._selector_windows.get("__refresh_only__")
        if refresh_only:
            refresh_only.visible = False
            self._selector_windows.pop("__refresh_only__", None)
        for tab_id in tab_ids:
            self._show_single_tab_selector(tab_id)

    def _show_refresh_only_ui(self):
        window_key = "__refresh_only__"
        old_window = self._selector_windows.get(window_key)
        if old_window:
            old_window.visible = False

        window = ui.Window("Tab Prim Selector", width=420, height=120)
        with window.frame:
            with ui.VStack(spacing=8, padding=8):
                ui.Label("No tab_id found yet.", height=20)
                ui.Button("Refresh", height=24, clicked_fn=self.show_tab_prim_selector_ui)
        self._selector_windows[window_key] = window

    def _collect_tab_ids(self):
        tab_ids = set(LoaderServices._tab_prim_paths.keys())
        for host in ViewportService.get_registered_viewport_hosts():
            key = host.host_key
            match = re.match(r"^(tab_\d+)", key)
            if match:
                tab_ids.add(match.group(1))
        return sorted(tab_ids)

    def _show_single_tab_selector(self, tab_id: str):
        old_window = self._selector_windows.get(tab_id)
        if old_window:
            old_window.visible = False

        prim_paths = LoaderServices.get_tab_prim_paths(tab_id)
        create_path = LoaderServices.get_tab_create_path(tab_id)

        # fallback: show viewport host keys when prim paths are not registered yet
        if not prim_paths:
            hosts = [
                host
                for host in ViewportService.get_registered_viewport_hosts()
                if host.host_key.startswith(f"{tab_id}_")
            ]
            prim_paths = [host.host_key for host in hosts]

        window = ui.Window(f"{tab_id} Prim Selector", width=500, height=150)
        with window.frame:
            with ui.VStack(spacing=8, padding=8):
                selected_label = ui.Label("Selected: ", height=20)
                ui.Label(f"create_path: {create_path or '-'}", height=20)
                ui.Button("Refresh", height=24, clicked_fn=lambda t=tab_id: self._show_single_tab_selector(t))
                with ui.HStack(spacing=6, height=0):
                    for path in prim_paths:
                        ui.Button(path, clicked_fn=lambda p=path: self._set_selected(selected_label, p))

        self._selector_windows[tab_id] = window

    def _set_selected(self, label_widget: ui.Label, value: str):
        label_widget.text = f"Selected: {value}"

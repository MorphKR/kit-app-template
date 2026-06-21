from typing import Dict, List, Optional

class ViewportWidgetHost:
    """다른 확장에서 ViewportWidget 타일을 viewport window처럼 다루기 위한 어댑터."""

    def __init__(self, key: str, viewport_api=None, frame=None, ui_frame=None, scene_view=None, prim_pos=None):
        self._key = key
        self.viewport_api = viewport_api
        self._frame = frame
        self._ui_frame = ui_frame
        self.scene_view = scene_view
        self.prim_pos = prim_pos
        self.prim = None

    @property
    def host_key(self) -> str:
        return self._key

    def update(self, viewport_api=None, frame=None, scene_view=None):
        if viewport_api is not None:
            self.viewport_api = viewport_api
        if frame is not None:
            self._frame = frame
        if scene_view is not None:
            self.scene_view = scene_view
    def get_frame(self, _ext_id: str):
        return self._frame


class ViewportService:
    _hosts: Dict[str, ViewportWidgetHost] = {}
    _viewport_widget = None

    @classmethod
    def register_viewport_host(cls, host: ViewportWidgetHost) -> ViewportWidgetHost:
        cls._hosts[host.host_key] = host
        return host

    @classmethod
    def unregister_viewport_host(cls, key: str):
        cls._hosts.pop(key, None)

    @classmethod
    def get_registered_viewport_hosts(cls) -> List[ViewportWidgetHost]:
        return list(cls._hosts.values())

    @classmethod
    def get_registered_viewport_host(cls, key: str) -> Optional[ViewportWidgetHost]:
        return cls._hosts.get(key)

    @classmethod
    def register_viewport_widget(cls, service) -> None:
        cls._viewport_widget = service

    @classmethod
    def unregister_viewport_widget(cls) -> None:
            cls._viewport_widget = None

    @classmethod
    def create_tab_viewport_hosts(cls, tab_id: str, root_prim_path: str) -> List[ViewportWidgetHost]:
        if cls._viewport_widget is None:
            return []
        return cls._viewport_widget.create_tab_viewport_hosts(tab_id, root_prim_path)

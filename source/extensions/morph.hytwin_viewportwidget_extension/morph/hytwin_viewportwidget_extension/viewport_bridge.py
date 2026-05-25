from typing import Dict, List, Optional


class ViewportWidgetHost:
    """다른 확장에서 ViewportWidget 타일을 viewport window처럼 다루기 위한 어댑터."""

    def __init__(self, key: str, viewport_api=None, frame=None, scene_view=None, navigation_scene=None):
        self._key = key
        self.viewport_api = viewport_api
        self._frame = frame
        self.scene_view = scene_view
        self.navigation_scene = navigation_scene
        self.visible = True

    @property
    def host_key(self) -> str:
        return self._key

    def update(self, viewport_api=None, frame=None, scene_view=None, navigation_scene=None):
        if viewport_api is not None:
            self.viewport_api = viewport_api
        if frame is not None:
            self._frame = frame
        if scene_view is not None:
            self.scene_view = scene_view
        if navigation_scene is not None:
            self.navigation_scene = navigation_scene

    def get_frame(self, _ext_id: str):
        return self._frame


_HOSTS: Dict[str, ViewportWidgetHost] = {}


def register_viewport_host(key: str, viewport_api, frame, scene_view=None, navigation_scene=None) -> ViewportWidgetHost:
    host = _HOSTS.get(key)
    if host is None:
        host = ViewportWidgetHost(
            key=key,
            viewport_api=viewport_api,
            frame=frame,
            scene_view=scene_view,
            navigation_scene=navigation_scene,
        )
        _HOSTS[key] = host
    else:
        host.update(
            viewport_api=viewport_api,
            frame=frame,
            scene_view=scene_view,
            navigation_scene=navigation_scene,
        )
    return host


def unregister_viewport_host(key: str):
    _HOSTS.pop(key, None)


def get_registered_viewport_hosts() -> List[ViewportWidgetHost]:
    return list(_HOSTS.values())


def get_registered_viewport_host(key: str) -> Optional[ViewportWidgetHost]:
    return _HOSTS.get(key)

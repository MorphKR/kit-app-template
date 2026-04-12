from typing import Dict, List, Optional


class ViewportWidgetHost:
    """다른 확장에서 ViewportWidget 타일을 viewport window처럼 다루기 위한 어댑터."""

    def __init__(self, key: str, viewport_api=None, frame=None):
        self._key = key
        self.viewport_api = viewport_api
        self._frame = frame
        self.visible = True

    @property
    def host_key(self) -> str:
        return self._key

    def update(self, viewport_api=None, frame=None):
        if viewport_api is not None:
            self.viewport_api = viewport_api
        if frame is not None:
            self._frame = frame

    def get_frame(self, _ext_id: str):
        return self._frame


_HOSTS: Dict[str, ViewportWidgetHost] = {}


def register_viewport_host(key: str, viewport_api, frame) -> ViewportWidgetHost:
    host = _HOSTS.get(key)
    if host is None:
        host = ViewportWidgetHost(key=key, viewport_api=viewport_api, frame=frame)
        _HOSTS[key] = host
    else:
        host.update(viewport_api=viewport_api, frame=frame)
    return host


def unregister_viewport_host(key: str):
    _HOSTS.pop(key, None)


def get_registered_viewport_hosts() -> List[ViewportWidgetHost]:
    return list(_HOSTS.values())

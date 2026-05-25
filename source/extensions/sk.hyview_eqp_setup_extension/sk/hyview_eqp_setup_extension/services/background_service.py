from __future__ import annotations

from typing import Any, Optional


class BackgroundService:
    _enabled = False
    _color: Optional[Any] = None
    _texture_path: Optional[str] = None

    @classmethod
    def initialize(cls) -> None:
        cls._enabled = False
        cls._color = None
        cls._texture_path = None

    @classmethod
    def shutdown(cls) -> None:
        cls._enabled = False
        cls._color = None
        cls._texture_path = None

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        cls._enabled = bool(enabled)

    @classmethod
    def set_color(cls, color: Any) -> None:
        cls._color = color

    @classmethod
    def set_texture(cls, texture_path: str) -> None:
        cls._texture_path = texture_path


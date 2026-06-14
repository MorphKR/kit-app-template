# -*- coding: utf-8 -*-
"""외부 Python 코드에서 viewport별 PointInstancer Thickness UI를 관리합니다."""

from omni import ui

class PointInstancerThicknessService:
    """Width Ratio UI의 외부 호출 lifecycle을 관리합니다."""
    _thickness_uis = {}
    _extension_instance = None

    @classmethod
    def show(cls, viewport_id: str, frame: ui.Frame, target_root: str, verbose: bool = False,):
        """지정 viewport frame의 우하단에 Width Ratio UI를 표시합니다."""
        if frame is None:
            raise ValueError("PointInstancer Thickness UI를 배치할 viewport frame이 필요합니다.")

        cls.close([viewport_id])

        cls._thickness_uis[viewport_id] = cls._extension_instance.show(frame=frame, target_root=target_root, verbose=verbose)


    @classmethod
    def hide(cls, viewport_ids: list[str]) -> None:
        """Width Ratio UI를 숨깁니다."""
        for viewport_id in viewport_ids:
            if viewport_id in cls._thickness_uis:
                cls._extension_instance.hide(cls._thickness_uis[viewport_id])

    @classmethod
    def close(cls, viewport_ids: list[str] = None) -> None:
        """표시 중인 Width Ratio UI를 종료합니다."""
        if viewport_ids is None:
            viewport_ids = list(cls._thickness_uis.keys())

        for viewport_id in list(viewport_ids):
            thickness_ui = cls._thickness_uis.pop(viewport_id, None)
            if thickness_ui is not None:
                cls._extension_instance.close(thickness_ui)

# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
Hover 아웃라인 설정 UI 빌더

색상(R,G,B) 및 두께 슬라이더를 포함한 설정 창 UI를 구성합니다.
설정 데이터는 outline_settings 모듈에서 관리합니다.
"""

import omni.ui as ui
from omni.ui import color as cl

from .outline_settings import (
    get_outline_color,
    get_outline_thickness,
    set_outline_color,
    set_outline_thickness,
)


# -----------------------------------------------------------------------------
# UI 스타일 상수 (ui_gradient_window 예제 기반)
# -----------------------------------------------------------------------------
LABEL_WIDTH = 80
SPACING = 10
cl_attribute_red = cl("#ac6060")
cl_attribute_green = cl("#60ab7c")
cl_attribute_blue = cl("#35889e")
cl_text = cl("#a1a1a1")
cl_widget_background = cl("#1f2123")
cl_slider = cl("#383b3e")


def _rgba_to_hex(r: float, g: float, b: float, a: float = 1.0) -> int:
    """RGBA(0-1) 값을 omni.ui Rectangle용 0xAABBGGRR 정수로 변환합니다. (BGR 순서)"""
    return (
        (int(max(0, min(1, a)) * 255) << 24)
        | (int(max(0, min(1, b)) * 255) << 16)
        | (int(max(0, min(1, g)) * 255) << 8)
        | int(max(0, min(1, r)) * 255)
    )


def build_outline_settings_ui(window: ui.Window, on_settings_changed=None) -> None:
    """
    Hover 아웃라인 설정 UI를 window에 구축합니다.

    Color 미리보기, R/G/B 슬라이더, Thickness 슬라이더를 포함합니다.
    outline_settings 모듈과 연동되어 값을 읽고 씁니다.

    Args:
        window: omni.ui.Window 인스턴스 (frame에 UI가 추가됨)
        on_settings_changed: 색상/두께 변경 시 호출할 콜백 (선택)
    """
    color = get_outline_color()
    thickness = get_outline_thickness()

    def _notify_changed():
        if callable(on_settings_changed):
            try:
                on_settings_changed()
            except Exception:
                pass

    # ui_gradient_window 스타일 적용
    _window_style = {
        "Slider::float_slider": {
            "background_color": cl_widget_background,
            "secondary_color": cl_slider,
            "border_radius": 3,
            "corner_flag": ui.CornerFlag.ALL,
            "draw_mode": ui.SliderDrawMode.FILLED,
        },
        "Label::attribute_name": {
            "alignment": ui.Alignment.RIGHT_CENTER,
            "color": cl_text,
        },
        "Label::attribute_color": {
            "alignment": ui.Alignment.LEFT_CENTER,
            "color": cl_text,
        },
        "Label::attribute_r": {"alignment": ui.Alignment.LEFT_CENTER, "color": cl_attribute_red},
        "Label::attribute_g": {"alignment": ui.Alignment.LEFT_CENTER, "color": cl_attribute_green},
        "Label::attribute_b": {"alignment": ui.Alignment.LEFT_CENTER, "color": cl_attribute_blue},
    }

    window.frame.style = _window_style
    with window.frame:
        with ui.ScrollingFrame(name="main_frame"):
            with ui.VStack(height=0, spacing=SPACING):
                ui.Spacer(height=5)
                ui.Label("Hover Outline Settings", height=24)

                # Color 섹션
                with ui.VStack(height=0, spacing=SPACING):
                    ui.Spacer(height=2)

                    r_model = ui.SimpleFloatModel(color[0])
                    g_model = ui.SimpleFloatModel(color[1])
                    b_model = ui.SimpleFloatModel(color[2])

                    def _build_preview():
                        r = max(0, min(1, r_model.as_float))
                        g = max(0, min(1, g_model.as_float))
                        b = max(0, min(1, b_model.as_float))
                        hex_val = _rgba_to_hex(r, g, b, 1.0)
                        ui.Rectangle(
                            width=200,
                            height=22,
                            style={"Rectangle": {"background_color": hex_val}},
                        )

                    def _refresh_preview():
                        preview_frame.rebuild()

                    def _on_rgb_changed(*_):
                        r = max(0, min(1, r_model.as_float))
                        g = max(0, min(1, g_model.as_float))
                        b = max(0, min(1, b_model.as_float))
                        set_outline_color(r, g, b, 1.0)
                        _refresh_preview()
                        _notify_changed()

                    with ui.HStack():
                        ui.Label("Color", name="attribute_color", width=LABEL_WIDTH)
                        preview_frame = ui.Frame(width=200, height=22)
                        preview_frame.set_build_fn(_build_preview)

                    for m in (r_model, g_model, b_model):
                        m.add_value_changed_fn(_on_rgb_changed)

                    def _build_rgb_slider_row(label: str, model, label_name: str):
                        with ui.HStack():
                            ui.Label(label, name=label_name, width=LABEL_WIDTH)
                            with ui.ZStack():
                                with ui.VStack():
                                    ui.Spacer(height=1.5)
                                    with ui.HStack():
                                        ui.FloatSlider(
                                            model=model,
                                            min=0,
                                            max=1,
                                            step=1/255,
                                            height=0,
                                            name="float_slider",
                                        )
                                    ui.Spacer(width=1.5)
                                ui.Spacer(width=4)

                    _build_rgb_slider_row("R", r_model, "attribute_r")
                    _build_rgb_slider_row("G", g_model, "attribute_g")
                    _build_rgb_slider_row("B", b_model, "attribute_b")

                # Thickness
                with ui.HStack():
                    ui.Label("Thickness", name="attribute_color", width=LABEL_WIDTH)
                    with ui.ZStack():
                        with ui.VStack():
                            ui.Spacer(height=1.5)
                            with ui.HStack():
                                thickness_model = ui.SimpleFloatModel(thickness)
                                ui.FloatSlider(
                                    model=thickness_model,
                                    min=0.5,
                                    max=10.0,
                                    step=0.5,
                                    height=0,
                                    name="float_slider",
                                )
                            ui.Spacer(width=1.5)
                        ui.Spacer(width=4)

                    def _on_thickness_changed(m):
                        v = m.as_float
                        if 0.5 <= v <= 10.0:
                            set_outline_thickness(v)
                            _notify_changed()

                    thickness_model.add_value_changed_fn(_on_thickness_changed)

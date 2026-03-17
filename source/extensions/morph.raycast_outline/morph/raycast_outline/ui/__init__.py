# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
UI 모듈

아웃라인 설정 관련 UI (창, 슬라이더, 색상 피커 등)를 제공합니다.
"""

from .outline_settings import (
    get_outline_color,
    get_outline_thickness,
    set_outline_color,
    set_outline_thickness,
)
from .outline_settings_window import OutlineSettingsWindowManager

__all__ = [
    "get_outline_color",
    "get_outline_thickness",
    "set_outline_color",
    "set_outline_thickness",
    "OutlineSettingsWindowManager",
]

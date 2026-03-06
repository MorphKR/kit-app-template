# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import json
from pathlib import Path

import omni.ext
import omni.ui as ui
from omni.kit.window.filepicker import FilePickerDialog


# 일반 파이썬 모듈과 동일하게 함수/변수는 다른 익스텐션에서도 사용 가능합니다.
# `morph.simul_parameter_ui_extension.some_public_function(x)`
def some_public_function(x: int):
    """This is a public function that can be called from other extensions."""
    print(f"[morph.simul_parameter_ui_extension] some_public_function was called with {x}")
    return x ** x


class MyExtension(omni.ext.IExt):
    """Simul 파라미터 편집 및 JSON 저장 UI."""

    # 값 타입 옵션
    _TYPE_STRING = 0
    _TYPE_NUMBER = 1
    _TYPE_LABELS = ("string", "number")

    # 문자열 상수
    _EXTENSION_NAME = "morph.simul_parameter_ui_extension"
    _WINDOW_TITLE = "Simul Parameter UI Extension"
    _SAVE_BUTTON_LABEL = "Save JSON"
    _ADD_BUTTON_LABEL = "+"
    _REMOVE_BUTTON_LABEL = "-"
    _FILEPICKER_TITLE = "Save Simul Parameter JSON"
    _FILEPICKER_APPLY_LABEL = "Save"
    _DEFAULT_JSON_FILENAME = "simul_parameter.json"

    _WARNING_WINDOW_TITLE = "Warning"
    _WARNING_OK_BUTTON_LABEL = "OK"
    _WARNING_DUPLICATE_KEYS = "중복된 key가 있습니다"
    _WARNING_INVALID_NUMBER = "숫자 타입 value가 올바르지 않습니다"

    _TOP_BUTTONS = ("ansys", "simul_1", "sinul_2")

    # 레이아웃/크기 상수
    _WINDOW_WIDTH = 640
    _WINDOW_HEIGHT = 480

    _MAIN_VSTACK_HEIGHT = 460
    _MAIN_VSTACK_SPACING = 8

    _TOP_ROW_HEIGHT = 28
    _TOP_ROW_SPACING = 6
    _SAVE_ROW_HEIGHT = 28
    _ADD_BUTTON_HEIGHT = 28

    _SCROLL_FRAME_HEIGHT = 360
    _SCROLL_CONTENT_HEIGHT = 360
    _SCROLL_CONTENT_SPACING = 4

    _ROW_HEIGHT = 30
    _ROW_SPACING = 4
    _FIELD_HEIGHT = 28
    _REMOVE_BUTTON_WIDTH = 24
    _REMOVE_BUTTON_HEIGHT = 28
    _TYPE_COMBO_WIDTH = 110
    _TYPE_COMBO_HEIGHT = 28

    _WARNING_WINDOW_WIDTH = 380
    _WARNING_WINDOW_HEIGHT = 152
    _WARNING_CONTENT_HEIGHT = 120
    _WARNING_CONTENT_SPACING = 8
    _WARNING_OK_BUTTON_HEIGHT = 28

    def on_startup(self, _ext_id):
        print(f"[{self._EXTENSION_NAME}] Extension startup")

        # UI 리빌드 시 입력값이 유지되도록 행 상태를 model로 보관합니다.
        self._rows = []
        self._pending_json_data = {}

        # 경고 팝업 창과 메시지 모델입니다.
        self._warning_window = None
        self._warning_message_model = ui.SimpleStringModel("")

        # 저장 경로/파일명을 선택하는 파일 피커입니다.
        self._filepicker = FilePickerDialog(
            self._FILEPICKER_TITLE,
            allow_multi_selection=False,
            apply_button_label=self._FILEPICKER_APPLY_LABEL,
            click_apply_handler=self._on_save_path_picked,
        )
        self._filepicker.hide()

        self._window = ui.Window(self._WINDOW_TITLE, width=self._WINDOW_WIDTH, height=self._WINDOW_HEIGHT)
        self._window.frame.set_build_fn(self._build_ui)

        self._add_row()

    def _build_ui(self):
        with self._window.frame:
            with ui.VStack(spacing=self._MAIN_VSTACK_SPACING, height=self._MAIN_VSTACK_HEIGHT):
                # 1번째 줄: 실행 버튼
                with ui.HStack(height=self._TOP_ROW_HEIGHT, spacing=self._TOP_ROW_SPACING):
                    for button_name in self._TOP_BUTTONS:
                        ui.Button(button_name, clicked_fn=lambda name=button_name: self._on_top_button_clicked(name))

                # 2번째 줄: JSON 저장 버튼
                with ui.HStack(height=self._SAVE_ROW_HEIGHT):
                    ui.Button(self._SAVE_BUTTON_LABEL, clicked_fn=self._on_save_json_clicked)

                # Save JSON 아래에 행 추가 버튼 배치
                ui.Button(self._ADD_BUTTON_LABEL, height=self._ADD_BUTTON_HEIGHT, clicked_fn=self._on_add_row_clicked)

                # 3번째 줄: 스크롤 가능한 key/value/type 행 목록
                with ui.ScrollingFrame(height=self._SCROLL_FRAME_HEIGHT):
                    with ui.VStack(spacing=self._SCROLL_CONTENT_SPACING, height=self._SCROLL_CONTENT_HEIGHT):
                        for row in self._rows:
                            self._build_row(row)

    def _build_row(self, row):
        with ui.HStack(height=self._ROW_HEIGHT, spacing=self._ROW_SPACING):
            ui.Button(
                self._REMOVE_BUTTON_LABEL,
                width=self._REMOVE_BUTTON_WIDTH,
                height=self._REMOVE_BUTTON_HEIGHT,
                clicked_fn=lambda r=row: self._remove_row(r),
            )
            ui.StringField(model=row["key_model"], height=self._FIELD_HEIGHT)
            ui.StringField(model=row["value_model"], height=self._FIELD_HEIGHT)

            # 타입 선택에 따라 JSON 저장 시 값 직렬화 방식이 달라집니다.
            type_combo = ui.ComboBox(
                row["type_index"],
                *self._TYPE_LABELS,
                width=self._TYPE_COMBO_WIDTH,
                height=self._TYPE_COMBO_HEIGHT,
            )
            type_combo.model.add_item_changed_fn(lambda model, item, r=row: self._on_type_changed(r, model, item))

    def _on_top_button_clicked(self, button_name: str):
        print(button_name)

    def _on_add_row_clicked(self):
        self._add_row()

    def _add_row(self):
        self._rows.append(
            {
                "key_model": ui.SimpleStringModel(""),
                "value_model": ui.SimpleStringModel(""),
                "type_index": self._TYPE_STRING,
            }
        )
        if self._window:
            self._window.frame.rebuild()

    def _remove_row(self, row):
        self._rows = [item for item in self._rows if item is not row]
        if self._window:
            self._window.frame.rebuild()

    def _on_save_json_clicked(self):
        # 중복 key가 있으면 저장을 막고 경고를 표시합니다.
        duplicate_keys = self._get_duplicate_keys()
        if duplicate_keys:
            keys_text = ", ".join(sorted(duplicate_keys))
            self._show_warning_popup(f"{self._WARNING_DUPLICATE_KEYS}:\n{keys_text}")
            return

        self._pending_json_data = self._collect_json_data()
        if self._pending_json_data is None:
            return

        self._filepicker.show(str(Path.cwd()))

    @staticmethod
    def _get_model_text(model) -> str:
        try:
            return (model.get_value_as_string() or "").strip()
        except AttributeError:
            return (model.as_string or "").strip()

    def _collect_json_data(self):
        parameters = {}
        for index, row in enumerate(self._rows, start=1):
            key_text = self._get_model_text(row["key_model"])
            value_text = self._get_model_text(row["value_model"])

            if not key_text:
                key_text = f"item_{index}"

            converted_value = self._convert_value_by_type(value_text, row["type_index"], key_text)
            if converted_value is None and row["type_index"] == self._TYPE_NUMBER:
                self._show_warning_popup(
                    f"{self._WARNING_INVALID_NUMBER}:\nkey = {key_text}, value = {value_text}"
                )
                return None

            parameters[key_text] = converted_value

        return {"parameters": parameters}

    def _convert_value_by_type(self, value_text: str, type_index: int, key_text: str):
        # number 타입은 int/float로 저장하고, string 타입은 문자열 그대로 저장합니다.
        if type_index == self._TYPE_NUMBER:
            raw = value_text.strip()
            if raw == "":
                print(f"invalid number value for key '{key_text}': empty")
                return None

            try:
                number = float(raw)
                if "." not in raw and "e" not in raw.lower():
                    return int(number)
                return number
            except ValueError:
                print(f"invalid number value for key '{key_text}': {value_text}")
                return None

        return value_text

    def _on_type_changed(self, row, model: ui.AbstractItemModel, _item: ui.AbstractItem):
        row["type_index"] = model.get_item_value_model().as_int

    def _get_duplicate_keys(self) -> set:
        key_counts = {}
        for row in self._rows:
            key_text = self._get_model_text(row["key_model"])
            if not key_text:
                continue
            key_counts[key_text] = key_counts.get(key_text, 0) + 1
        return {key for key, count in key_counts.items() if count > 1}

    def _show_warning_popup(self, message: str):
        # 최신 메시지를 항상 반영하기 위해 팝업을 다시 생성합니다.
        if self._warning_window:
            self._warning_window.visible = False
            self._warning_window = None

        self._warning_message_model.set_value(message)
        self._warning_window = ui.Window(
            self._WARNING_WINDOW_TITLE,
            width=self._WARNING_WINDOW_WIDTH,
            height=self._WARNING_WINDOW_HEIGHT,
            flags=ui.WINDOW_FLAGS_NO_RESIZE | ui.WINDOW_FLAGS_NO_COLLAPSE,
        )

        with self._warning_window.frame:
            with ui.VStack(spacing=self._WARNING_CONTENT_SPACING, height=self._WARNING_CONTENT_HEIGHT):
                ui.Label(self._warning_message_model.get_value_as_string(), word_wrap=True)
                ui.Button(
                    self._WARNING_OK_BUTTON_LABEL,
                    height=self._WARNING_OK_BUTTON_HEIGHT,
                    clicked_fn=self._hide_warning_popup,
                )

        self._warning_window.visible = True

    def _hide_warning_popup(self):
        if self._warning_window:
            self._warning_window.visible = False

    def _on_save_path_picked(self, file_name: str, directory: str):
        dir_text = (directory or "").strip()
        file_text = (file_name or "").strip()

        if not dir_text or dir_text.lower().startswith("bookmarks:"):
            return

        if not file_text:
            file_text = self._DEFAULT_JSON_FILENAME

        selected_path = Path(file_text)
        if selected_path.parent.as_posix() != ".":
            output_path = selected_path
        else:
            output_path = Path(dir_text) / file_text

        if output_path.suffix.lower() != ".json":
            output_path = output_path.with_suffix(".json")

        # 파일 쓰기 전에 대상 디렉터리를 먼저 생성합니다.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file:
            json.dump(self._pending_json_data, file, ensure_ascii=False, indent=2)

        print(f"saved json: {output_path}")
        self._filepicker.hide()

    def on_shutdown(self):
        print(f"[{self._EXTENSION_NAME}] Extension shutdown")
        self._rows = []
        self._pending_json_data = {}
        self._warning_window = None
        self._warning_message_model = None
        self._filepicker = None
        self._window = None

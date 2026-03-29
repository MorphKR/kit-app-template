"""
BasisCurves가 포함된 USD 자산을 레퍼런스로 가져올 때,
import 전에 purpose 오버라이드를 미리 작성하는 흐름을 UI에서 실행하는 확장 모듈.
실제 import·purpose 사전 작성 로직은 basiscurve_override_utils.run_pre_authored_reference_import 에 있다.
"""

import asyncio

import omni.ext
import omni.ui as ui
import omni.usd

from .basiscurve_override_utils import run_pre_authored_reference_import


class ConvertBasisCurvesExtension(omni.ext.IExt):
    """USD 스테이지에 자산 경로를 입력해 'purpose를 미리 작성한 뒤 레퍼런스'하는 변환 UI를 제공한다."""

    def on_startup(self, _ext_id):
        self._usd_context = omni.usd.get_context()

        self._window = None
        self._asset_path_field = None
        self._status_label = None

        # 동시에 두 번 import 하지 않도록 추적; 종료 시 취소에 사용
        self._import_task = None
        self._is_shutting_down = False

        self._build_ui()
        print("[ConvertBasisCurvesExtension] startup")

    def on_shutdown(self):
        self._is_shutting_down = True

        # 진행 중인 비동기 import 가 있으면 취소
        if self._import_task and not self._import_task.done():
            self._import_task.cancel()
        self._import_task = None

        if self._window:
            self._window.destroy()
        self._window = None
        self._asset_path_field = None
        self._status_label = None
        self._usd_context = None

        print("[ConvertBasisCurvesExtension] shutdown")

    def _build_ui(self):
        """임포트할 USD 경로 입력 필드와 실행 버튼을 띄운다."""
        self._window = ui.Window("BasisCurves Import Converter", width=560, height=180)
        with self._window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label("USD/USDA/USDC path to import")
                self._asset_path_field = ui.StringField()
                self._asset_path_field.model.set_value("C:/Users/JeongGuHyeon/Downloads/layer_temp.usd")

                self._status_label = ui.Label("")

                ui.Button(
                    "Import With Purpose Override",
                    height=28,
                    clicked_fn=lambda: asyncio.ensure_future(self._on_click_import()),
                )

    async def _on_click_import(self):
        """버튼 클릭: 이미 실행 중이면 무시하고, 아니면 사전 purpose 오버라이드 포함 import 를 시작한다."""
        if self._import_task and not self._import_task.done():
            self._set_status("Already running. Wait for current import.")
            return

        self._import_task = asyncio.ensure_future(self._import_with_pre_authored_override())

    async def _import_with_pre_authored_override(self):
        try:
            asset_path = self._asset_path_field.model.get_value_as_string().strip()
            result = await run_pre_authored_reference_import(
                usd_context=self._usd_context,
                asset_path=asset_path,
                is_shutting_down=lambda: self._is_shutting_down,
            )
            self._set_status(result["message"])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._set_status(f"Import failed: {e}")
        finally:
            self._import_task = None

    def _set_status(self, text: str):
        if self._status_label:
            self._status_label.text = text
        print(f"[ConvertBasisCurvesExtension] {text}")

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List

import omni.ext
import omni.ui as ui
import omni.usd
from pxr import Gf, Usd, UsdGeom

from .pointinstancer_thickness_service import PointInstancerThicknessService


DEFAULT_TARGET_ROOT = "/World"
VIEWPORT_MARGIN = 16
WIDTH_RATIO_OP_SUFFIX = "widthRatio"
WIDTH_RATIO_OP_NAME = "xformOp:scale:" + WIDTH_RATIO_OP_SUFFIX


@dataclass
class PointInstancerThicknessUI:
    """viewport 하나에 대응하는 PointInstancer Thickness UI 상태입니다."""

    _target_root: str = DEFAULT_TARGET_ROOT
    _min_ratio: float = 0.05
    _max_ratio: float = 1.0
    _debounce_seconds: float = 0.03
    _batch_size: int = 8
    _verbose: bool = False

    _parent_frame: ui.Frame = None
    _container_frame: ui.Frame = None # viewport에 배치되는 최상위 프레임입니다. UI 전체를 숨길 때 사용합니다.
    _panel_frame: ui.Frame = None # 실제 UI 요소가 배치되는 프레임입니다. 패널 디자인 변경 시 사용합니다.
    _model: object = None # ui.FloatSlider에 연결되는 모델입니다. 변경 시점마다 모델의 값을 읽어서 prototype에 적용합니다.
    _sub: object = None
    _prototype_paths: List[str] = field(default_factory=list)
    _is_destroying: bool = False

    _apply_task: asyncio.Task = None

class PointInstancerThicknessLifecycleExtension(omni.ext.IExt):
    """Kit lifecycle과 복수 PointInstancer Thickness UI 기능을 관리합니다."""

    def on_startup(self, _ext_id):
        PointInstancerThicknessService._extension_instance = self
        print("[sk.hyview_eqp_pointinstancer_thickness_extension] Extension startup")

    def on_shutdown(self):
        PointInstancerThicknessService.close()
        PointInstancerThicknessService._extension_instance = None
        print("[sk.hyview_eqp_pointinstancer_thickness_extension] Extension shutdown")

    def show(self, frame: ui.Frame, target_root: str, verbose: bool = False,) -> PointInstancerThicknessUI:
        """새 UI 상태를 만들고 전달받은 viewport frame에 표시합니다."""
        if frame is None:
            raise ValueError("PointInstancer Thickness UI를 배치할 viewport frame이 필요합니다.")

        ui_state = PointInstancerThicknessUI()
        ui_state._parent_frame = frame
        ui_state._target_root = target_root or DEFAULT_TARGET_ROOT
        ui_state._debounce_seconds = ui_state._debounce_seconds
        ui_state._batch_size = ui_state._batch_size
        ui_state._verbose = bool(verbose)
        ui_state._model = ui.SimpleFloatModel(1)
        ui_state._is_destroying = False
        self._build(ui_state)
        return ui_state

    def hide(self, ui_state: PointInstancerThicknessUI) -> None:
        if ui_state._container_frame is not None:
            ui_state._container_frame.visible = False

    def close(self, ui_state: PointInstancerThicknessUI) -> None:
        ui_state._is_destroying = True

        if ui_state._apply_task and not ui_state._apply_task.done():
            ui_state._apply_task.cancel()

        ui_state._apply_task = None

        self._restore_ratio(ui_state)

        if ui_state._sub:
            try:
                ui_state._model.remove_value_changed_fn(ui_state._sub)
            except Exception:
                pass
            ui_state._sub = None

        ui_state._container_frame.visible = False
        ui_state._container_frame.clear()
        ui_state._container_frame = None
        ui_state._panel_frame = None
        ui_state._parent_frame = None
        ui_state._prototype_paths.clear()
        ui_state._model = None
        ui_state._is_destroying = False
        print("[WidthRatioUI] destroyed and restored prototype ratio=1.0")

    def _build(self, ui_state: PointInstancerThicknessUI) -> None:
        self._collect_prototype_paths(ui_state)
        self._build_viewport_overlay(ui_state)

        ui_state._sub = ui_state._model.add_value_changed_fn(lambda model: self._on_ratio_changed(ui_state, model))
        self._apply_ratio_blocking(ui_state, 1.0)

    def _restore_ratio(self, ui_state: PointInstancerThicknessUI) -> None:
        """수집된 prototype을 원본 굵기 비율로 복구합니다."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        updated = 0
        for prototype_path in ui_state._prototype_paths:
            prim = stage.GetPrimAtPath(prototype_path)
            if not prim.IsValid():
                continue
            self._set_prototype_ratio(prim, 1.0)
            updated += 1
        print(f"[WidthRatioUI] restored prototype ratio=1.000, updated={updated}")

    def _clamp_ratio(self, ui_state: PointInstancerThicknessUI, ratio: float) -> float:
        return max(ui_state._min_ratio, min(ui_state._max_ratio, float(ratio)))

    def _get_or_create_width_ratio_scale_op(self, prim: Usd.Prim):
        """prototype에 굵기 비율을 제어하는 xformOp이 이미 있으면 가져오고, 없으면 새로 만듭니다."""
        xformable = UsdGeom.Xformable(prim)

        attr = prim.GetAttribute(WIDTH_RATIO_OP_NAME)
        if attr and attr.IsValid():
            return UsdGeom.XformOp(attr)

        try:
            return xformable.AddScaleOp(precision=UsdGeom.XformOp.PrecisionFloat, opSuffix=WIDTH_RATIO_OP_SUFFIX,)
        except TypeError:
            try:
                return xformable.AddScaleOp(UsdGeom.XformOp.PrecisionFloat, WIDTH_RATIO_OP_SUFFIX)
            except TypeError:
                return xformable.AddScaleOp()

    def _on_ratio_changed(self, ui_state: PointInstancerThicknessUI, model) -> None:
        """UI 변경 시점마다 호출됩니다. 빠르게 연속 변경 시 마지막 상태만 적용되도록 debounce 처리합니다."""
        if not ui_state._is_destroying:
            pending_ratio = self._clamp_ratio(ui_state, model.as_float)

            if ui_state._apply_task and not ui_state._apply_task.done():
                ui_state._apply_task.cancel()

            ui_state._apply_task = asyncio.ensure_future(self._apply_ratio_async(ui_state, pending_ratio))

    async def _apply_ratio_async(self, ui_state: PointInstancerThicknessUI, ratio: float,):
        """비동기로 prototype의 굵기 비율을 변경합니다. 대상이 많을 경우에도 UI가 멈추지 않도록 batch 단위로 잠시 대기합니다."""
        current_task = asyncio.current_task()
        try:
            if ui_state._debounce_seconds > 0.0:
                await asyncio.sleep(ui_state._debounce_seconds)

            if current_task is not ui_state._apply_task:
                return

            stage = omni.usd.get_context().get_stage()

            ratio = self._clamp_ratio(ui_state, ratio)
            updated = 0
            for index, prototype_path in enumerate(list(ui_state._prototype_paths)):
                # UI 변경이 여러 번 빠르게 일어날 때 마지막 변경만 적용되도록 합니다.
                if current_task is not ui_state._apply_task:
                    return
                prim = stage.GetPrimAtPath(prototype_path)
                if not prim.IsValid():
                    continue
                self._set_prototype_ratio(prim, ratio)
                updated += 1
                if (index + 1) % ui_state._batch_size == 0:
                    await asyncio.sleep(0)
            if ui_state._verbose:
                print(f"[WidthRatioUI] applied prototype ratio={ratio:.3f}, updated={updated}")
        except asyncio.CancelledError:
            return
        finally:
            if current_task is ui_state._apply_task:
                ui_state._apply_task = None

    def _set_prototype_ratio(self, prototype_prim: Usd.Prim, ratio: float) -> None:
        scale_op = self._get_or_create_width_ratio_scale_op(prototype_prim)
        scale_op.Set(Gf.Vec3f(1.0, float(ratio), float(ratio)))

    def _collect_prototype_paths(self, ui_state: PointInstancerThicknessUI) -> None:
        """UI 표시 전에 대상 PointInstancer의 prototype 경로를 수집합니다."""
        ui_state._prototype_paths.clear()

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            print("[WidthRatioUI] 활성 USD Stage가 없습니다.")
            return

        root = stage.GetPrimAtPath(ui_state._target_root)
        if not root.IsValid():
            print(f"[WidthRatioUI] 대상 Root가 없습니다: {ui_state._target_root}")
            return

        seen = set()
        instancer_count = 0

        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.PointInstancer):
                continue

            instancer_count += 1
            instancer = UsdGeom.PointInstancer(prim)

            for target in instancer.GetPrototypesRel().GetTargets():
                prototype_prim = stage.GetPrimAtPath(target)
                if not prototype_prim.IsValid():
                    continue

                path_text = str(prototype_prim.GetPath())
                if path_text in seen:
                    continue

                seen.add(path_text)
                ui_state._prototype_paths.append(path_text)

        print(f"[WidthRatioUI] collected PointInstancers={instancer_count}, " f"prototypes={len(ui_state._prototype_paths)}" )

    def _build_viewport_overlay(self, ui_state: PointInstancerThicknessUI) -> None:
        """Viewport 우하단에 간단한 패널 형태로 UI를 배치합니다."""
        with ui_state._parent_frame:
            ui_state._container_frame = ui.Frame( width=ui.Fraction(1.0),height=ui.Fraction(1.0),)

        with ui_state._container_frame:
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=ui.Pixel(92)):
                    ui.Spacer()
                    ui_state._panel_frame = ui.Frame( width=ui.Pixel(340), height=ui.Pixel(92),)
                    ui.Spacer(width=ui.Pixel(VIEWPORT_MARGIN))
                ui.Spacer(height=ui.Pixel(VIEWPORT_MARGIN))

        with ui_state._panel_frame:
            with ui.VStack(spacing=8):
                ui.Label("Width Ratio")
                ui.FloatSlider(model=ui_state._model, min=ui_state._min_ratio, max=ui_state._max_ratio, step=0.05,)

    def _apply_ratio_blocking(self, ui_state: PointInstancerThicknessUI, ratio: float) -> None:
        """UI 변경 시점에 바로 적용이 필요한 초기 상태에 사용합니다. 대상이 많을 경우 잠시 UI가 멈출 수 있습니다."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        ratio = self._clamp_ratio(ui_state, ratio)
        updated = 0

        for prototype_path in ui_state._prototype_paths:
            prim = stage.GetPrimAtPath(prototype_path)
            if not prim.IsValid():
                continue

            self._set_prototype_ratio(prim, ratio)
            updated += 1

        print(f"[WidthRatioUI] applied prototype ratio={ratio:.3f}, updated={updated}, blocking=True")

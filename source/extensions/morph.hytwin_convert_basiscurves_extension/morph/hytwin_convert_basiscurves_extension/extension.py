import omni.ext
import omni.ui as ui
import omni.usd
import omni.kit.app
from pxr import Usd, UsdGeom, Gf, Vt, Sdf, UsdShade
import asyncio


# 이 확장은 사용자가 USD 경로를 입력하면 해당 파일을 현재 USD stage에 reference로 불러온 뒤,
# 새로 생긴 `UsdGeom.BasisCurves` prim들을 "clean" prim으로 변환(geometry/xform/material 복사)합니다.
# 변환 로직은 `_build_clean_curve_once()`에서 단일 prim 단위로 수행합니다.

# True:
#   source prim을 제거하고 같은 경로에 clean prim을 생성
# False:
#   source prim 기준으로 "{source_path}_Clean" clean prim 생성
REPLACE_SOURCE_WITH_CLEAN = False

class ConvertBasisCurvesExtension(omni.ext.IExt):
    def on_startup(self, _ext_id):
        # UI/상태 초기화
        self._usd_context = omni.usd.get_context()
        self._window = None
        self._asset_path_field = None
        self._target_path_field = None
        self._status_label = None
        self._import_task = None
        self._is_shutting_down = False
        self._build_ui()
        print("[ConvertBasisCurvesExtension] startup")

    def on_shutdown(self):
        # 실행 중인 비동기 작업을 중단하고 UI/참조를 해제
        self._is_shutting_down = True

        if self._import_task and not self._import_task.done():
            self._import_task.cancel()
        self._import_task = None

        if self._window:
            self._window.destroy()
        self._window = None
        self._asset_path_field = None
        self._target_path_field = None
        self._status_label = None
        self._usd_context = None
        print("[ConvertBasisCurvesExtension] shutdown")

    def _build_ui(self):
        # 확장 UI: 경로 입력 + "Import And Convert" 버튼
        self._window = ui.Window("BasisCurves Import Converter", width=560, height=180)
        with self._window.frame:
            with ui.VStack(spacing=8, padding=10):
                ui.Label("USD/USDA/USDC path to import")
                self._asset_path_field = ui.StringField()
                ui.Label("Target prim path")
                self._target_path_field = ui.StringField()
                self._target_path_field.model.set_value("")

                self._status_label = ui.Label("")

                ui.Button(
                    "Import And Convert",
                    height=28,
                    clicked_fn=lambda: asyncio.ensure_future(self._on_click_import_and_convert()),
                )

    async def _on_click_import_and_convert(self):
        # 버튼 연타 방지: 이미 수행 중이면 상태만 갱신
        if self._import_task and not self._import_task.done():
            self._set_status("Already running. Wait for current import.")
            return
        self._import_task = asyncio.ensure_future(self._import_and_convert())

    async def _import_and_convert(self):
        try:
            # 입력값 읽기/정규화
            asset_path = self._asset_path_field.model.get_value_as_string().strip()
            target_path = self._target_path_field.model.get_value_as_string().strip()
            if not target_path:
                target_path = self._suggest_import_target_path(asset_path)

            # 입력 검증(파일 확장자)
            if not asset_path or not asset_path.lower().endswith((".usd", ".usda", ".usdc")):
                self._set_status("Invalid import path. Use .usd/.usda/.usdc")
                return

            # 현재 stage 존재 여부 확인
            stage = self._usd_context.get_stage()
            if not stage:
                self._set_status("No stage opened.")
                return

            # 임포트 전/후 비교를 위해 변환 대상 prim 경로를 스냅샷
            before_paths = set(self._collect_basis_curve_paths(stage))
            import_prim_path = self._make_unique_prim_path(stage, target_path)

            # stage에 reference를 걸기 위한 컨테이너 Xform prim 생성
            import_prim = UsdGeom.Xform.Define(stage, import_prim_path).GetPrim()
            import_prim.GetReferences().AddReference(asset_path)
            self._set_status(f"Imported reference: {asset_path} -> {import_prim_path}")

            # reference 로딩/구성 완료까지 프레임 단위로 대기하면서,
            # "새로 생긴" BasisCurves를 탐지합니다.
            app = omni.kit.app.get_app()
            new_paths = []
            for _ in range(20):
                await app.next_update_async()
                if self._is_shutting_down:
                    return

                current_paths = set(self._collect_basis_curve_paths(stage))
                candidates = sorted(p for p in (current_paths - before_paths) if p.startswith(import_prim_path))
                if candidates:
                    new_paths = candidates
                    break

            if not new_paths:
                self._set_status("No new BasisCurves found in imported file.")
                return

            # 탐지된 각 source prim을 clean prim으로 1회 변환
            updated_count = 0
            for source_path in new_paths:
                ok = self._build_clean_curve_once(
                    stage=stage,
                    source_path=source_path,
                    clean_path=self._make_clean_path(source_path),
                    replace_source=REPLACE_SOURCE_WITH_CLEAN,
                )
                if ok:
                    updated_count += 1

            self._set_status(
                f"Import done. New BasisCurves={len(new_paths)}, converted={updated_count}"
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._set_status(f"Import failed: {e}")
        finally:
            self._import_task = None

    def _collect_basis_curve_paths(self, stage: Usd.Stage):
        # stage traversal로 현재 존재하는 BasisCurves prim path 수집
        paths = []
        for prim in stage.Traverse():
            if prim and prim.IsValid() and prim.IsA(UsdGeom.BasisCurves):
                paths.append(str(prim.GetPath()))
        return paths

    def _make_unique_prim_path(self, stage: Usd.Stage, base_path: str):
        # 같은 stage에서 target 경로가 충돌하면 suffix를 붙여 유일 경로 생성
        base = base_path if base_path.startswith("/") else f"/{base_path}"
        candidate = base
        index = 1
        while True:
            prim = stage.GetPrimAtPath(candidate)
            if not prim or not prim.IsValid():
                return candidate
            candidate = f"{base}_{index}"
            index += 1

    def _set_status(self, text: str):
        # UI label + 콘솔 출력 동시 반영
        if self._status_label:
            self._status_label.text = text
        print(f"[ConvertBasisCurvesExtension] {text}")

    def _suggest_import_target_path(self, asset_path: str):
        # asset 파일명(경로/확장자 제거) 기반으로 /World/<Name> 제안
        base_name = "ImportedUsd"
        if asset_path:
            candidate = asset_path.replace("\\", "/").rstrip("/")
            if "/" in candidate:
                candidate = candidate.rsplit("/", 1)[-1]
            if "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
            if candidate:
                safe = []
                for ch in candidate:
                    if ch.isalnum() or ch == "_":
                        safe.append(ch)
                    else:
                        safe.append("_")
                base_name = "".join(safe).strip("_") or base_name
        return f"/World/{base_name}"

    def _make_clean_path(self, source_path: str):
        # source_path_/_clean naming 규칙
        return f"{source_path}_Clean"

    def _build_clean_curve_once(
        self,
        stage: Usd.Stage,
        source_path: str,
        clean_path: str,
        replace_source: bool = False,
    ) -> bool:
        # 단일 BasisCurves prim을 "clean" prim으로 복사/변환합니다.
        # - geometry(points/counts/attrs) 복사
        # - normals는 새로 불일치가 생길 수 있으므로 authored value를 제거
        # - xform ops 및 bound material(목적별)을 복사
        src_prim = stage.GetPrimAtPath(source_path)
        if not src_prim or not src_prim.IsValid() or not src_prim.IsA(UsdGeom.BasisCurves):
            print(f"[ConvertBasisCurvesExtension] invalid source prim: {source_path}")
            return False

        src_curves = UsdGeom.BasisCurves(src_prim)
        points = src_curves.GetPointsAttr().Get()
        counts = src_curves.GetCurveVertexCountsAttr().Get()

        if not points or not counts:
            print(f"[ConvertBasisCurvesExtension] source missing points/counts: {source_path}")
            return False

        # 원본 prim에 바인딩된 material과 xform ops를 그대로 복사하기 위한 정보 수집
        bound_materials = self._get_bound_materials(src_prim)
        xform_data = self._read_xform_ops(src_prim)

        # replace_source가 켜져 있으면 source 경로에 덮어쓰기(원본 제거 후 생성),
        # 그렇지 않으면 별도 clean_path에 생성합니다.
        dst_path = source_path if replace_source else clean_path

        # replace_source=True 모드에서는 원본을 먼저 제거합니다.
        if replace_source:
            removed = stage.RemovePrim(source_path)
            print(f"[ConvertBasisCurvesExtension] removed source prim={removed} path={source_path}")

        # destination 경로에 이미 prim이 있으면 중복 생성 방지
        dst_prim_existing = stage.GetPrimAtPath(dst_path)
        if dst_prim_existing and dst_prim_existing.IsValid():
            print(f"[ConvertBasisCurvesExtension] destination already exists: {dst_path}")
            return False

        # 새 BasisCurves prim 생성 후 geometry/attrs 설정
        dst_curves = UsdGeom.BasisCurves.Define(stage, dst_path)
        dst_prim = dst_curves.GetPrim()

        # geometry: points/counts는 원본을 그대로 복사
        dst_curves.CreatePointsAttr(points)
        dst_curves.CreateCurveVertexCountsAttr(counts)
        dst_curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        dst_curves.GetWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
        dst_curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)

        # normals: authored value가 있으면 제거(원본 normals가 clean 변환과 불일치할 수 있음)
        normals_attr = dst_curves.GetNormalsAttr()
        if normals_attr and normals_attr.HasAuthoredValue():
            normals_attr.Clear()

        # extent: points 기반 bbox를 계산해 표시 범위를 맞춥니다.
        extent = self._compute_extent_from_points_and_widths(points)
        if extent:
            dst_curves.GetExtentAttr().Set(extent)

        # display / visibility: 기본 목적(purpose=default)으로 보이게 처리
        dst_img = UsdGeom.Imageable(dst_prim)
        dst_img.MakeVisible()
        dst_img.GetPurposeAttr().Set(UsdGeom.Tokens.default_)

        # xform ops 복사
        self._apply_xform_ops(dst_prim, xform_data)

        # bound material 복사(목적별 all/preview/full)
        self._apply_bound_materials(dst_prim, bound_materials)
        return True

    def _compute_extent_from_points_and_widths(self, points):
        # widths를 따로 고려하지 않고 points 좌표만으로 extent bbox를 생성합니다.
        if not points:
            return None

        min_x = min(float(p[0]) for p in points)
        min_y = min(float(p[1]) for p in points)
        min_z = min(float(p[2]) for p in points)

        max_x = max(float(p[0]) for p in points)
        max_y = max(float(p[1]) for p in points)
        max_z = max(float(p[2]) for p in points)

        return Vt.Vec3fArray([
            Gf.Vec3f(min_x, min_y, min_z),
            Gf.Vec3f(max_x, max_y, max_z),
        ])

    def _read_xform_ops(self, prim: Usd.Prim):
        # 원본 prim의 xformOpOrder와 각 op의 (name/type/value)를 읽어서 보관합니다.
        data = {
            "order": None,
            "order_type_name": None,
            "ops": [],
        }

        order_attr = prim.GetAttribute("xformOpOrder")
        if not order_attr or not order_attr.HasAuthoredValue():
            return data

        data["order"] = order_attr.Get()
        data["order_type_name"] = order_attr.GetTypeName()

        for op_name in data["order"]:
            src_attr = prim.GetAttribute(op_name)
            if not src_attr or not src_attr.IsValid():
                continue

            data["ops"].append({
                "name": op_name,
                "type_name": src_attr.GetTypeName(),
                "value": src_attr.Get(),
            })

        return data

    def _apply_xform_ops(self, prim: Usd.Prim, xform_data):
        # 저장해 둔 xform op들을 목적지 prim에 그대로 재작성합니다.
        if not xform_data or not xform_data.get("order"):
            return

        for item in xform_data.get("ops", []):
            dst_attr = prim.CreateAttribute(item["name"], item["type_name"], custom=False)
            dst_attr.Set(item["value"])

        order_attr = prim.CreateAttribute(
            "xformOpOrder",
            xform_data["order_type_name"],
            custom=False,
        )
        order_attr.Set(xform_data["order"])

    def _get_bound_materials(self, prim: Usd.Prim):
        # material binding을 목적별(all/preview/full)로 찾아 리스트로 반환합니다.
        results = []

        binding_api = UsdShade.MaterialBindingAPI(prim)
        purposes = [
            UsdShade.Tokens.allPurpose,
            UsdShade.Tokens.preview,
            UsdShade.Tokens.full,
        ]

        for purpose in purposes:
            try:
                material, rel = binding_api.ComputeBoundMaterial(purpose)
            except Exception:
                material, rel = None, None

            if material and material.GetPrim() and material.GetPrim().IsValid():
                results.append((purpose, material))
                print(
                    f"[ConvertBasisCurvesExtension] found bound material "
                    f"purpose={purpose} path={material.GetPath()}"
                )

        return results

    def _apply_bound_materials(self, prim: Usd.Prim, bound_materials):
        # 목적별로 material binding을 destination prim에 바인딩합니다.
        if not bound_materials:
            print("[ConvertBasisCurvesExtension] no bound materials to apply")
            return

        binding_api = UsdShade.MaterialBindingAPI(prim)

        for purpose, material in bound_materials:
            try:
                binding_api.Bind(material, purpose)
                print(
                    f"[ConvertBasisCurvesExtension] applied bound material "
                    f"purpose={purpose} path={material.GetPath()}"
                )
            except Exception as e:
                print(
                    f"[ConvertBasisCurvesExtension] failed to apply material "
                    f"purpose={purpose}: {e}"
                )


# 아래의 """ ... """ 블록은 과거 실험/레거시로 보이는 코드이며 현재는
# 다중 문자열로 묶여 실행되지 않습니다. (문법적으로는 '주석' 역할)
"""
class ConvertBasisCurvesExtension(omni.ext.IExt):
    def on_startup(self, _ext_id):
        self._usd_context = omni.usd.get_context()
        self._stage_event_sub = self._usd_context.get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event,
            name="basis_curves_repair_on_stage_open",
        )

        self._repair_task = None
        self._repair_done = False
        print("[ConvertBasisCurvesExtension] startup")

    def on_shutdown(self):
        self._repair_done = True

        if self._repair_task and not self._repair_task.done():
            self._repair_task.cancel()
        self._repair_task = None

        self._stage_event_sub = None
        self._usd_context = None
        print("[ConvertBasisCurvesExtension] shutdown")

    def _on_stage_event(self, event):
        if self._repair_done:
            return

        if event.type not in (int(StageEventType.OPENED), int(StageEventType.ASSETS_LOADED),):
            return

        asyncio.ensure_future(self._deferred_repair())

    async def _deferred_repair(self):
        await omni.kit.app.get_app().next_update_async()

        stage = self._usd_context.get_stage()
        if not stage:
            return

        # ?대? ?덉빟??task媛 ?덉쑝硫?以묐났 ?앹꽦 湲덉?
        if self._repair_task and not self._repair_task.done():
            return

        self._repair_task = asyncio.ensure_future(self._deferred_one_shot_repair())

    async def _deferred_one_shot_repair(self):
        try:
            app = omni.kit.app.get_app()

            # import/composition???덉젙???뚭퉴吏 紐??꾨젅???湲?
            for _ in range(10):
                await app.next_update_async()

                if self._repair_done:
                    return

                stage = self._usd_context.get_stage()
                if not stage:
                    continue

                prim = stage.GetPrimAtPath(SOURCE_CURVE_PATH)
                if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
                    continue

                curves = UsdGeom.BasisCurves(prim)
                points = curves.GetPointsAttr().Get()
                counts = curves.GetCurveVertexCountsAttr().Get()

                if not points or not counts:
                    continue

                result = self.repair_basis_curves_prim(prim, default_width=DEFAULT_CURVE_WIDTH)
                if result:
                    print(f"[ConvertBasisCurvesExtension] one-shot repaired {result['path']}")
                    print(
                        f"[ConvertBasisCurvesExtension] "
                        f"widths_authored={result['widths_authored']} "
                        f"extent_authored={result['extent_authored']}"
                    )

                    self._repair_done = True

                    # ?깃났 ?????댁긽 ?대깽??諛쏆? ?딆쓬
                    self._stage_event_sub = None
                    print("[ConvertBasisCurvesExtension] repair complete, unsubscribed stage events")
                    return

            print("[ConvertBasisCurvesExtension] one-shot repair skipped: target curve not ready")
        except asyncio.CancelledError:
            pass
        finally:
            self._repair_task = None

    def _get_max_width(self, widths) -> float:
        if not widths:
            return 0.0
        try:
            return max(float(w) for w in widths)
        except Exception:
            return 0.0

    def _compute_extent_from_points_and_widths(self, points, widths):
        if not points:
            return None

        radius = self._get_max_width(widths) * 0.5

        min_x = min(float(p[0]) for p in points) - radius
        min_y = min(float(p[1]) for p in points) - radius
        min_z = min(float(p[2]) for p in points) - radius

        max_x = max(float(p[0]) for p in points) + radius
        max_y = max(float(p[1]) for p in points) + radius
        max_z = max(float(p[2]) for p in points) + radius

        return Vt.Vec3fArray([
            Gf.Vec3f(min_x, min_y, min_z),
            Gf.Vec3f(max_x, max_y, max_z),
        ])

    def _ensure_widths(self, curves: UsdGeom.BasisCurves, default_width: float = DEFAULT_CURVE_WIDTH):
        widths_attr = curves.GetWidthsAttr()
        widths = widths_attr.Get()

        needs_fix = False

        if widths is None:
            needs_fix = True
        else:
            try:
                needs_fix = len(widths) == 0 or all(float(w) == 0.0 for w in widths)
            except Exception:
                needs_fix = True

        if needs_fix:
            authored_widths = Vt.FloatArray([float(default_width)])
            widths_attr.Set(authored_widths)
            return list(authored_widths), True

        return list(widths), False

    def _ensure_extent(self, curves: UsdGeom.BasisCurves, widths):
        points = curves.GetPointsAttr().Get()
        if not points:
            return False

        normals_attr = curves.GetNormalsAttr()
        if normals_attr and normals_attr.HasAuthoredValue():
            normals_attr.Clear()

        curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)

        extent = self._compute_extent_from_points_and_widths(points, widths)
        if extent is None or len(extent) != 2:
            return False

        curves.GetExtentAttr().Set(extent)
        return True

    def repair_basis_curves_prim(self, prim: Usd.Prim, default_width: float = DEFAULT_CURVE_WIDTH):
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
            return None

        curves = UsdGeom.BasisCurves(prim)

        points = curves.GetPointsAttr().Get()
        counts = curves.GetCurveVertexCountsAttr().Get()

        if not points or not counts:
            return None

        # ?ш린?쒕뒗 "?놁쓣 ?뚮쭔"???꾨땲?? ?꾩삁 媛뺤젣濡?10?쇰줈 怨좎젙?섍퀬 ?띠쑝硫??꾨옒泥섎읆 吏곸젒 Set
        curves.GetWidthsAttr().Set(Vt.FloatArray([float(default_width)]))
        widths = [float(default_width)]
        widths_authored = True

        curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        extent_authored = self._ensure_extent(curves, widths)
        self._force_curve_drawable_state(curves)

        print(f"[ConvertBasisCurvesExtension] final inspect {prim.GetPath()}")
        print("  final widths =", curves.GetWidthsAttr().Get())
        print("  final widthsInterpolation =", curves.GetWidthsInterpolation())
        print("  final extent =", curves.GetExtentAttr().Get())
        print("  final normals =", curves.GetNormalsAttr().Get())
        print("  final type =", curves.GetTypeAttr().Get())
        print("  final basis =", curves.GetBasisAttr().Get())
        print("  final wrap =", curves.GetWrapAttr().Get())

        imageable = UsdGeom.Imageable(curves.GetPrim())
        print("  final visibility =", imageable.GetVisibilityAttr().Get())
        print("  final purpose =", imageable.GetPurposeAttr().Get())

        return {
            "path": str(prim.GetPath()),
            "widths_authored": widths_authored,
            "extent_authored": extent_authored,
        }

    def repair_all_basis_curves(self, stage: Usd.Stage, default_width: float = DEFAULT_CURVE_WIDTH):
        results = []
        target_path = "/World/layer_temp/BasisCurves"

        prim = stage.GetPrimAtPath(target_path)
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
            return results

        result = self.repair_basis_curves_prim(prim, default_width=default_width)
        if result:
            results.append(result)

        return results

    def _force_curve_drawable_state(self, curves: UsdGeom.BasisCurves):
        curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        curves.GetWrapAttr().Set(UsdGeom.Tokens.nonperiodic)

        imageable = UsdGeom.Imageable(curves.GetPrim())
        imageable.MakeVisible()
        imageable.GetPurposeAttr().Set(UsdGeom.Tokens.default_)

    def _compute_points_extent(self, points):
        if not points:
            return None

        min_x = min(float(p[0]) for p in points)
        min_y = min(float(p[1]) for p in points)
        min_z = min(float(p[2]) for p in points)

        max_x = max(float(p[0]) for p in points)
        max_y = max(float(p[1]) for p in points)
        max_z = max(float(p[2]) for p in points)

        return Vt.Vec3fArray([
            Gf.Vec3f(min_x, min_y, min_z),
            Gf.Vec3f(max_x, max_y, max_z),
        ])


    def _offset_points(self, points, offset: Gf.Vec3f):
        out = []
        for p in points:
            out.append(
                Gf.Vec3f(
                    float(p[0]) + float(offset[0]),
                    float(p[1]) + float(offset[1]),
                    float(p[2]) + float(offset[2]),
                )
            )
        return Vt.Vec3fArray(out)

    def create_debug_points_and_curves(self, stage, source_curve_path: str):
        src_prim = stage.GetPrimAtPath(source_curve_path)
        if not src_prim or not src_prim.IsValid():
            print(f"[BasisCurvesDebug] invalid source prim: {source_curve_path}")
            return

        src_curves = UsdGeom.BasisCurves(src_prim)
        points = src_curves.GetPointsAttr().Get()
        counts = src_curves.GetCurveVertexCountsAttr().Get()

        if not points or not counts:
            print(f"[BasisCurvesDebug] source prim missing points/counts: {source_curve_path}")
            return

        root_path = Sdf.Path("/World/DebugBasisCurves")
        if not stage.GetPrimAtPath(root_path):
            UsdGeom.Xform.Define(stage, root_path)

        # 1) ??BasisCurves - ?먮낯怨?嫄곗쓽 ?숈씪?섏?留??놁쑝濡??대룞
        debug_curve_path = root_path.AppendPath("CurveLinear")
        debug_curve = UsdGeom.BasisCurves.Define(stage, debug_curve_path)

        curve_points = self._offset_points(points, Gf.Vec3f(0.0, 20.0, 0.0))
        debug_curve.CreatePointsAttr(curve_points)
        debug_curve.CreateCurveVertexCountsAttr(counts)
        debug_curve.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        debug_curve.GetWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
        debug_curve.GetWidthsAttr().Set(Vt.FloatArray([10.0]))
        debug_curve.SetWidthsInterpolation(UsdGeom.Tokens.constant)

        curve_extent = self._compute_points_extent(curve_points)
        if curve_extent is not None:
            # width 諛섏쁺?댁꽌 議곌툑 ?뺤옣
            r = 5.0
            curve_extent = Vt.Vec3fArray([
                Gf.Vec3f(curve_extent[0][0] - r, curve_extent[0][1] - r, curve_extent[0][2] - r),
                Gf.Vec3f(curve_extent[1][0] + r, curve_extent[1][1] + r, curve_extent[1][2] + r),
            ])
            debug_curve.GetExtentAttr().Set(curve_extent)

        curve_img = UsdGeom.Imageable(debug_curve.GetPrim())
        curve_img.MakeVisible()
        curve_img.GetPurposeAttr().Set(UsdGeom.Tokens.default_)

        curve_gprim = UsdGeom.Gprim(debug_curve.GetPrim())
        curve_gprim.GetDisplayColorAttr().Set(
            Vt.Vec3fArray([Gf.Vec3f(1.0, 0.0, 0.0)])
        )

        # 2) Points - 媛숈? ?꾩튂???議곌툑 ???놁쑝濡??대룞
        debug_points_path = root_path.AppendPath("Points")
        debug_points = UsdGeom.Points.Define(stage, debug_points_path)

        pts_points = self._offset_points(points, Gf.Vec3f(0.0, 40.0, 0.0))
        debug_points.CreatePointsAttr(pts_points)
        debug_points.CreateWidthsAttr(Vt.FloatArray([8.0] * len(pts_points)))

        pts_extent = self._compute_points_extent(pts_points)
        if pts_extent is not None:
            r = 4.0
            pts_extent = Vt.Vec3fArray([
                Gf.Vec3f(pts_extent[0][0] - r, pts_extent[0][1] - r, pts_extent[0][2] - r),
                Gf.Vec3f(pts_extent[1][0] + r, pts_extent[1][1] + r, pts_extent[1][2] + r),
            ])
            debug_points.GetExtentAttr().Set(pts_extent)

        pts_img = UsdGeom.Imageable(debug_points.GetPrim())
        pts_img.MakeVisible()
        pts_img.GetPurposeAttr().Set(UsdGeom.Tokens.default_)

        pts_gprim = UsdGeom.Gprim(debug_points.GetPrim())
        pts_gprim.GetDisplayColorAttr().Set(
            Vt.Vec3fArray([Gf.Vec3f(0.0, 1.0, 0.0)])
        )

        print(f"[BasisCurvesDebug] created debug curve: {debug_curve_path}")
        print(f"[BasisCurvesDebug] created debug points: {debug_points_path}")

        #self._dump_prim_properties(stage.GetPrimAtPath("/World/layer_temp/BasisCurves"))
        #self._dump_prim_properties(stage.GetPrimAtPath("/World/DebugBasisCurves/CurveLinear"))
        #self.clone_curve_from_source(stage, "/World/layer_temp/BasisCurves", "/World/DebugBasisCurves/CurveCloned")

    def _dump_prim_properties(self, prim):
        print(f"[DumpPrim] path = {prim.GetPath()}")
        for prop in prim.GetProperties():
            try:
                name = prop.GetName()
                value = prop.Get()
            except Exception:
                name = prop.GetName()
                value = "<unreadable>"
            print(f"  {name} = {value}")


    def clone_curve_from_source(self, stage, source_path, target_path):
        src_prim = stage.GetPrimAtPath(source_path)
        if not src_prim or not src_prim.IsValid():
            return

        src = UsdGeom.BasisCurves(src_prim)
        points = src.GetPointsAttr().Get()
        counts = src.GetCurveVertexCountsAttr().Get()

        if not points or not counts:
            return

        dst = UsdGeom.BasisCurves.Define(stage, target_path)
        dst.CreatePointsAttr(points)
        dst.CreateCurveVertexCountsAttr(counts)
        dst.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        dst.GetWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
        dst.GetWidthsAttr().Set(Vt.FloatArray([10.0]))
        dst.SetWidthsInterpolation(UsdGeom.Tokens.constant)

        extent = self._compute_extent_from_points_and_widths(points, [10.0])
        if extent:
            dst.GetExtentAttr().Set(extent)

        img = UsdGeom.Imageable(dst.GetPrim())
        img.MakeVisible()
        img.GetPurposeAttr().Set(UsdGeom.Tokens.default_)

        gprim = UsdGeom.Gprim(dst.GetPrim())
        gprim.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(1.0, 1.0, 0.0)]))

    def _sanitize_imported_curve(self, prim):
        curves = UsdGeom.BasisCurves(prim)
        if not curves:
            return

        # 1) material binding ?쒓굅
        UsdShade.MaterialBindingAPI(prim).UnbindAllBindings()

        # 2) visualization???띿꽦 ?쒓굅
        attr = prim.GetAttribute("omni:scene:visualization:drawWireframe")
        if attr and attr.IsValid():
            attr.Clear()

        # 3) displayColor / opacity 紐낆떆
        gprim = UsdGeom.Gprim(prim)
        gprim.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(1.0, 0.0, 0.0)]))
        gprim.GetDisplayOpacityAttr().Set(Vt.FloatArray([1.0]))

        # 4) widths 媛뺤젣
        curves.GetWidthsAttr().Set(Vt.FloatArray([10.0]))
        curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)

        # 5) extent ?ш퀎??
        points = curves.GetPointsAttr().Get()
        if points:
            extent = self._compute_extent_from_points_and_widths(points, [10.0])
            if extent:
                curves.GetExtentAttr().Set(extent)

        # 6) draw state ?щ챸??
        curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        curves.GetWrapAttr().Set(UsdGeom.Tokens.nonperiodic)

        imageable = UsdGeom.Imageable(prim)
        imageable.MakeVisible()
        imageable.GetPurposeAttr().Set(UsdGeom.Tokens.default_)
"""

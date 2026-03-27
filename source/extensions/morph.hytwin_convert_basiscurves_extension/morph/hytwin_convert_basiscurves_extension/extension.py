import asyncio

import omni.ext
import omni.kit.app
import omni.ui as ui
import omni.usd

from pxr import Usd, UsdGeom, Sdf


class ConvertBasisCurvesExtension(omni.ext.IExt):
    def on_startup(self, _ext_id):
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
        self._window = ui.Window("BasisCurves Import Converter", width=560, height=180)
        with self._window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label("USD/USDA/USDC path to import")
                self._asset_path_field = ui.StringField()

                ui.Label("Target prim path")
                self._target_path_field = ui.StringField()
                self._target_path_field.model.set_value("")

                self._status_label = ui.Label("")

                ui.Button(
                    "Import With Purpose Override",
                    height=28,
                    clicked_fn=lambda: asyncio.ensure_future(self._on_click_import()),
                )

    async def _on_click_import(self):
        if self._import_task and not self._import_task.done():
            self._set_status("Already running. Wait for current import.")
            return

        self._import_task = asyncio.ensure_future(self._import_with_pre_authored_override())

    async def _import_with_pre_authored_override(self):
        try:
            asset_path = self._asset_path_field.model.get_value_as_string().strip()
            target_path = self._target_path_field.model.get_value_as_string().strip()

            if not target_path:
                target_path = self._suggest_import_target_path(asset_path)

            if not asset_path or not asset_path.lower().endswith((".usd", ".usda", ".usdc")):
                self._set_status("Invalid import path. Use .usd/.usda/.usdc")
                return

            stage = self._usd_context.get_stage()
            if not stage:
                self._set_status("No stage opened.")
                return

            import_prim_path = self._make_unique_prim_path(stage, target_path)

            # source USD를 별도로 열어서 defaultPrim 기준 BasisCurves 경로를 먼저 수집
            source_info = self._collect_source_basiscurve_info(asset_path)
            if not source_info["ok"]:
                self._set_status(source_info["message"])
                return

            relative_curve_paths = source_info["relative_curve_paths"]
            default_prim_path = source_info["default_prim_path"]

            self._set_status(
                f"Found {len(relative_curve_paths)} BasisCurves in source "
                f"(defaultPrim={default_prim_path})"
            )

            # import 전에 현재 stage에 override prim들을 미리 작성
            self._pre_author_purpose_overrides(
                stage=stage,
                import_root_path=import_prim_path,
                relative_curve_paths=relative_curve_paths,
            )

            # reference container prim 생성
            import_root_prim = UsdGeom.Xform.Define(stage, import_prim_path).GetPrim()

            # 이제 reference 추가
            import_root_prim.GetReferences().AddReference(asset_path)
            self._set_status(f"Imported reference: {asset_path} -> {import_prim_path}")

            # 합성 완료 대기 후 검증
            app = omni.kit.app.get_app()
            for _ in range(20):
                await app.next_update_async()
                if self._is_shutting_down:
                    return

                current_paths = self._collect_basis_curve_paths_under(stage, import_prim_path)
                if current_paths:
                    self._set_status(
                        f"Import done. BasisCurves={len(current_paths)}, "
                        f"purpose override authored before reference."
                    )
                    return

            self._set_status("Import completed, but no BasisCurves were found under target path.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._set_status(f"Import failed: {e}")
        finally:
            self._import_task = None

    def _collect_source_basiscurve_info(self, asset_path: str):
        """
        source USD를 현재 stage와 별도로 열어서:
        - defaultPrim 경로
        - defaultPrim 기준 BasisCurves 상대 경로 목록
        을 반환합니다.

        AddReference(asset_path) 는 보통 source layer의 defaultPrim을
        target prim에 합성하므로, import 전에 override 경로를 정확히 예측하려면
        defaultPrim 기준 상대 경로가 필요합니다.
        """
        try:
            src_stage = Usd.Stage.Open(asset_path)
        except Exception as e:
            return {
                "ok": False,
                "message": f"Failed to open source USD: {e}",
                "default_prim_path": None,
                "relative_curve_paths": [],
            }

        if not src_stage:
            return {
                "ok": False,
                "message": "Failed to open source USD.",
                "default_prim_path": None,
                "relative_curve_paths": [],
            }

        default_prim = src_stage.GetDefaultPrim()
        if not default_prim or not default_prim.IsValid():
            return {
                "ok": False,
                "message": "Source USD has no defaultPrim. Cannot pre-map referenced BasisCurves paths reliably.",
                "default_prim_path": None,
                "relative_curve_paths": [],
            }

        default_prim_path = str(default_prim.GetPath())
        relative_curve_paths = []

        for prim in src_stage.Traverse():
            if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
                continue

            prim_path = str(prim.GetPath())

            # reference target path 매핑:
            # source defaultPrim 자체는 import_root_path 로 합성되고,
            # 그 자식들은 import_root_path/<suffix> 로 들어옵니다.
            if prim_path == default_prim_path:
                relative_curve_paths.append("")
            elif prim_path.startswith(default_prim_path + "/"):
                suffix = prim_path[len(default_prim_path):]
                relative_curve_paths.append(suffix)

        return {
            "ok": True,
            "message": "ok",
            "default_prim_path": default_prim_path,
            "relative_curve_paths": relative_curve_paths,
        }

    def _pre_author_purpose_overrides(self, stage: Usd.Stage, import_root_path: str, relative_curve_paths):
        edit_layer = stage.GetEditTarget().GetLayer()
        if not edit_layer:
            raise RuntimeError("No editable layer found for pre-authoring purpose overrides.")

        for rel_path in relative_curve_paths:
            composed_path = import_root_path if rel_path == "" else f"{import_root_path}{rel_path}"

            prim_spec = Sdf.CreatePrimInLayer(edit_layer, composed_path)
            if prim_spec is None:
                raise RuntimeError(f"Failed to create over prim spec for {composed_path}")

            # over spec 유지
            prim_spec.specifier = Sdf.SpecifierOver

            # purpose: uniform token = "default"
            attr_spec = prim_spec.attributes.get("purpose")
            if attr_spec is None:
                attr_spec = Sdf.AttributeSpec(
                    prim_spec,
                    "purpose",
                    Sdf.ValueTypeNames.Token,
                    variability=Sdf.VariabilityUniform,
                )

            attr_spec.default = "default"

            print(
                "[ConvertBasisCurvesExtension] pre-authored purpose=default "
                f"for future imported prim: {composed_path}"
            )

    def _collect_basis_curve_paths_under(self, stage: Usd.Stage, root_path: str):
        paths = []
        for prim in stage.Traverse():
            if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
                continue

            prim_path = str(prim.GetPath())
            if prim_path == root_path or prim_path.startswith(root_path + "/"):
                paths.append(prim_path)
        return paths

    def _make_unique_prim_path(self, stage: Usd.Stage, base_path: str):
        base = base_path if base_path.startswith("/") else f"/{base_path}"
        candidate = base
        index = 1

        while True:
            prim = stage.GetPrimAtPath(candidate)
            if not prim or not prim.IsValid():
                return candidate
            candidate = f"{base}_{index}"
            index += 1

    def _suggest_import_target_path(self, asset_path: str):
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

    def _set_status(self, text: str):
        if self._status_label:
            self._status_label.text = text
        print(f"[ConvertBasisCurvesExtension] {text}")


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

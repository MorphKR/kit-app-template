"""
BasisCurve가 들어 있는 USD 자산을 레퍼런스로 붙이기 전,
편집 레이어에 purpose 오버라이드를 미리 작성하는 유틸리티.

레퍼런스 추가 전에 Over 스펙과 purpose=default 를 두어,
합성 후에도 의도한 purpose 가 스테이지에 반영되도록 한다.
"""

import omni.kit.app
from pxr import Sdf, Usd, UsdGeom


async def run_pre_authored_reference_import(usd_context, asset_path: str, is_shutting_down=None):
    if not asset_path or not asset_path.lower().endswith((".usd", ".usda", ".usdc")):
        return {"ok": False, "message": "Invalid import path. Use .usd/.usda/.usdc"}

    stage = usd_context.get_stage() if usd_context else None
    if not stage:
        return {"ok": False, "message": "No stage opened."}

    # 레퍼런스가 붙을 루트 후보(소스 default prim 구조에 맞춤); 이미 있으면 _1, _2 … 로 유일 경로 확보
    target_path = suggest_import_target_path(asset_path)
    import_prim_path = make_unique_prim_path(stage, target_path)
    # 레퍼런스 합성 후 BasisCurve 가 놓일 경로와 맞추기 위해, 소스 스테이지에서 상대 경로만 수집
    relative_curve_paths = collect_source_basiscurve_info(asset_path)

    pre_author_purpose_overrides(
        stage=stage,
        import_root_path=import_prim_path,
        relative_curve_paths=relative_curve_paths,
    )

    import_root_prim = UsdGeom.Xform.Define(stage, import_prim_path).GetPrim()
    import_root_prim.GetReferences().AddReference(asset_path)

    # 레퍼런스 로드·합성이 한두 프레임 안에 반영되도록 짧게 폴링
    app = omni.kit.app.get_app()
    for _ in range(20):
        await app.next_update_async()
        if is_shutting_down and is_shutting_down():
            return {"ok": False, "message": "Import cancelled during shutdown."}

        current_paths = collect_basis_curve_paths_under(stage, import_prim_path)
        if current_paths:
            return {
                "ok": True,
                "message": (
                    f"Import done. BasisCurves={len(current_paths)}, "
                    "purpose override authored before reference."
                ),
            }

    return {
        "ok": False,
        "message": "Import completed, but no BasisCurves were found under target path.",
    }


"""
소스 파일을 열어 DefaultPrim 과 그 아래 첫 BasisCurve 의 첫 세그먼트를 참고해,
import 시 사용할 기본 prim 경로 문자열을 제안한다. 열 수 없으면 고정 기본값.
"""
def suggest_import_target_path(asset_path: str):
    try:
        src_stage = Usd.Stage.Open(asset_path)
    except Exception:
        src_stage = None

    if src_stage:
        default_prim = src_stage.GetDefaultPrim()
        if default_prim and default_prim.IsValid():
            default_prim_path = str(default_prim.GetPath())
            first_child = find_path(src_stage, default_prim_path)
            if first_child:
                if default_prim_path == "/":
                    return f"/{first_child}"
                return f"{default_prim_path}/{first_child}"
            return default_prim_path

    return "/World/ImportedUsd"

"""DefaultPrim 아래를 순회하며, 첫 BasisCurve 가 나타나는 경로의 첫 경로 토큰(자식 이름)을 반환."""
def find_path(src_stage: Usd.Stage, default_prim_path: str):
    for prim in src_stage.Traverse():
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
            continue

        prim_path = str(prim.GetPath())
        if prim_path == default_prim_path:
            return ""
        if not prim_path.startswith(default_prim_path + "/"):
            continue

        suffix = prim_path[len(default_prim_path):]
        tokens = [token for token in suffix.split("/") if token]
        if tokens:
            return tokens[0]

    return ""


def make_unique_prim_path(stage: Usd.Stage, base_path: str):
    """base_path 가 이미 유효한 prim 이면 _1, _2 … 접미를 붙여 비어 있는 경로를 찾는다."""
    base = base_path if base_path.startswith("/") else f"/{base_path}"
    candidate = base
    index = 1

    while True:
        prim = stage.GetPrimAtPath(candidate)
        if not prim or not prim.IsValid():
            return candidate
        candidate = f"{base}_{index}"
        index += 1

"""
소스 스테이지의 DefaultPrim 을 기준으로 BasisCurve prim 들의 경로 접미사 목록을 만든다.
DefaultPrim 자체가 BasisCurve 이면 빈 문자열("") 이 하나 들어간다.
"""
def collect_source_basiscurve_info(asset_path: str):

    src_stage = Usd.Stage.Open(asset_path)
    default_prim = src_stage.GetDefaultPrim()
    default_prim_path = str(default_prim.GetPath())
    relative_curve_paths = []

    for prim in src_stage.Traverse():
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
            continue

        prim_path = str(prim.GetPath())
        if prim_path == default_prim_path:
            relative_curve_paths.append("")
        elif prim_path.startswith(default_prim_path + "/"):
            suffix = prim_path[len(default_prim_path):]
            relative_curve_paths.append(suffix)

    return relative_curve_paths


"""
레퍼런스를 AddReference 하기 **전에**, 현재 스테이지의 **편집 타깃 레이어**에만
합성될 BasisCurve prim 경로에 대응하는 스펙을 미리 쓴다.

동작 요약
--------
- ``relative_curve_paths`` 는 소스에서 DefaultPrim 기준 상대 경로(또는 "")이다.
  ``import_root_path`` 와 이어붙여 ``레퍼런스 루트 아래에서의 최종 prim 경로``를 만든다.
- 각 경로에 ``Sdf.CreatePrimInLayer`` 로 prim 스펙을 만들고 ``specifier = Over`` 로 둔다.
    (아직 자식 prim 이 스테이지에 없어도, 레이어에 Over 만으로 합성 슬롯을 확보한다.)
- ``purpose`` 속성(Uniform Token)을 만들고 기본값 ``default`` 를 둔다.
    레퍼런스가 붙은 뒤에도 이 오버라이드가 합성 순서상 적용되어 purpose 가 명시된다.

실패 시
-------
편집 가능한 레이어가 없거나 prim/attribute 스펙 생성에 실패하면 RuntimeError 를 던진다.
"""
def pre_author_purpose_overrides(stage: Usd.Stage, import_root_path: str, relative_curve_paths):
    edit_layer = stage.GetEditTarget().GetLayer()
    if not edit_layer:
        raise RuntimeError("No editable layer found for pre-authoring purpose overrides.")

    for rel_path in relative_curve_paths:
        # 소스에서의 상대 경로를 import 루트 아래 절대 경로로 환산
        composed_path = import_root_path if rel_path == "" else f"{import_root_path}{rel_path}"

        prim_spec = Sdf.CreatePrimInLayer(edit_layer, composed_path)
        if prim_spec is None:
            raise RuntimeError(f"Failed to create over prim spec for {composed_path}")

        # 정의(def)가 아니라 오버(over)만 두어, 이후 레퍼런스 내용과 합성되도록 함
        prim_spec.specifier = Sdf.SpecifierOver

        attr_spec = prim_spec.attributes.get("purpose")
        if attr_spec is None:
            attr_spec = Sdf.AttributeSpec(
                prim_spec,
                "purpose",
                Sdf.ValueTypeNames.Token,
                variability=Sdf.VariabilityUniform,
            )

        attr_spec.default = "default"


"""현재 스테이지에서 root_path 이하에 있는 BasisCurve prim 의 절대 경로 목록."""
def collect_basis_curve_paths_under(stage: Usd.Stage, root_path: str):
    paths = []
    for prim in stage.Traverse():
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
            continue

        prim_path = str(prim.GetPath())
        if prim_path == root_path or prim_path.startswith(root_path + "/"):
            paths.append(prim_path)
    return paths

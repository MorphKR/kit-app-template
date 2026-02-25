# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence, Tuple, Union

import carb
import carb.settings
import numpy as np
import omni.kit.raycast.query
import omni.timeline
from omni.ui import scene as sc
from pxr import Gf, Sdf, Usd, UsdGeom

from .attribute_value_cache import AttributeValueCache


def list_to_gf_matrix4d(data: Sequence[float]) -> Gf.Matrix4d:
    """
    길이 16의 1차원 시퀀스를 `pxr.Gf.Matrix4d`로 변환한다.

    입력 배열은 USD/Viewport API에서 반환하는 행렬(flattened) 포맷을 가정한다.
    길이가 16이 아니면 즉시 예외를 발생시켜 잘못된 변환 사용을 막는다.
    """
    if len(data) != 16:
        raise RuntimeError("Gf.Matrix4d needs 16 nubmers to initialize")
    return Gf.Matrix4d(
        data[0],
        data[1],
        data[2],
        data[3],
        data[4],
        data[5],
        data[6],
        data[7],
        data[8],
        data[9],
        data[10],
        data[11],
        data[12],
        data[13],
        data[14],
        data[15],
    )


class MeasureSnapProvider(ABC):
    """MeasureSnapProvider 클래스 설명입니다."""
    def __init__(self, viewport_api):
        """공통 스냅 제공자 초기화. 각 provider가 공유하는 viewport API를 저장한다."""
        self._viewport_api = viewport_api

    def __del__(self):
        """인스턴스 소멸 시 리소스 정리를 보장한다."""
        self.destroy()

    def destroy(self):
        """하위 클래스에서 캐시/구독을 정리할 수 있도록 기본 정리 훅을 제공한다."""
        self._value_cache = None

    def on_began(self, excluded_paths: List[Union[str, Sdf.Path]], **kwargs):
        """
        스냅 계산 시작 시 호출된다.

        `excluded_paths`는 스냅 대상에서 제외할 prim 경로 목록이며, 현재 provider 인스턴스에 보관한다.
        """
        self._excluded_paths = list(excluded_paths)

    def on_ended(self, **kwargs):
        """스냅 계산 종료 시 호출된다. 시작 시 보관한 제외 목록을 초기화한다."""
        self._excluded_paths = []

    @abstractmethod
    def on_snap(
        self,
        ndc_location: Sequence[float],
        result: omni.kit.raycast.query.RayQueryResult,
        want_orient: bool = False,
        want_keep_spacing: bool = True,
        conform_up_axis: str = "Stage",
    ) -> Tuple[bool, Optional[Dict]]:
        """
        조작기(manipulator)가 스냅 계산을 요청할 때 호출되는 핵심 인터페이스.

        현재 활성화된 provider만 호출되며, 구현체는 스냅 성공 여부와 payload를 반환해야 한다.

        Args:
            ndc_location: 커서의 NDC 좌표.
            result: raycast 결과(hit prim, hit point, normal, primitive id 등).
            want_orient: 방향(회전) 계산이 필요한지 여부.
            want_keep_spacing: 스냅 후 간격 유지 옵션 전달 플래그.
            conform_up_axis: Surface 스냅 등에서 업축 정렬 기준("Stage"/"X"/"Y"/"Z").

        Returns:
            (성공 여부, payload).
            성공 시 payload에는 최소한 position/path/type 등이 들어가며, 필요 시 orient를 포함한다.
        """
        raise NotImplementedError()

    @staticmethod
    @abstractmethod
    def get_name() -> str:
        """
        provider 내부 식별자(ID)를 반환한다.
        스냅 매니저/레지스트리에서 provider를 관리할 때 사용하는 키다.
        """
        raise NotImplementedError()

    @classmethod
    def get_display_name(cls) -> str:
        """
        UI에 표시할 provider 이름을 반환한다.
        오버라이드하지 않으면 내부 식별자(`get_name`)를 그대로 사용한다.
        """
        return cls.get_name()

    @staticmethod
    @abstractmethod
    def can_orient() -> bool:
        """
        해당 provider가 스냅 중 객체 회전(orientation)까지 계산 가능한지 반환한다.
        """
        raise NotImplementedError()

    @staticmethod
    def require_viewport_api() -> bool:
        """
        provider 동작에 viewport API가 필수인지 반환한다.
        """
        return True

    @staticmethod
    def get_order() -> float:
        """
        provider 우선순위를 반환한다.
        동시에 여러 provider가 유효하면 값이 더 작은 provider가 먼저 선택된다.
        """
        return 0.0

    def _generate_picking_ray(self, ndc_location: Sequence[float]) -> Tuple[Gf.Vec3d, Gf.Vec3d, float]:
        """
        NDC 커서 좌표를 월드 좌표계의 picking ray(origin, direction, distance)로 변환한다.
        viewport view/projection 역행렬을 사용해 near/far 점을 역변환한 뒤 ray를 구성한다.
        """
        ndc_near = (ndc_location[0], ndc_location[1], -1)
        ndc_far = (ndc_location[0], ndc_location[1], 1)
        view = self._viewport_api.view
        proj = self._viewport_api.projection
        view_proj_inv = (view * proj).GetInverse()

        origin = view_proj_inv.Transform(ndc_near)
        dir = view_proj_inv.Transform(ndc_far) - origin
        dist = dir.Normalize()

        return (origin, dir, dist)

    def _get_ndc_to_screen_matrix(self, scene_view: Optional[sc.SceneView]) -> Gf.Matrix4d:
        """
        NDC(-1~1) 좌표를 화면 픽셀 좌표로 변환하는 매트릭스를 생성한다.

        `scene_view`가 없으면 viewport 해상도를 fallback으로 사용한다.
        """
        if scene_view:
            width = scene_view.computed_width
            height = scene_view.computed_height
        else:
            # scene_view가 없는 경우 viewport 해상도로 대체한다.
            # 단, viewport_api.resolution과 실제 렌더 타겟 크기가 항상 1:1은 아닐 수 있다.
            width = self._viewport_api.resolution[0]
            height = self._viewport_api.resolution[1]

        ndc_to_screen = Gf.Matrix4d()
        ndc_to_screen.SetScale(Gf.Vec3d(width * 0.5, height * 0.5, 0.5))
        ndc_to_screen.SetTranslateOnly(Gf.Vec3d(width * 0.5, height * 0.5, 0.5))

        return ndc_to_screen


class MeshBasedSnapProvider(MeasureSnapProvider):
    """MeshBasedSnapProvider 클래스 설명입니다."""
    def __init__(self, *args, **kwargs):
        """메시 기반 스냅 공통 초기화. 타임라인/설정 인터페이스를 캐싱한다."""
        super().__init__(*args, **kwargs)
        self._timeline = omni.timeline.get_timeline_interface()
        self._settings = carb.settings.get_settings()

    def destroy(self):
        """부모 클래스 정리 루틴 호출."""
        super().destroy()

    def on_began(self, excluded_paths: List[Union[str, Sdf.Path]], **kwargs):
        """부모 시작 훅 호출(현재는 동작 확장 없음)."""
        super().on_began(excluded_paths, **kwargs)

    def on_ended(self, **kwargs):
        """부모 종료 훅 호출(현재는 동작 확장 없음)."""
        super().on_ended(**kwargs)

    def _get_current_timecode(self) -> Usd.TimeCode:
        """
        현재 타임라인 시간을 USD TimeCode로 변환해 반환한다.
        애니메이션/시뮬레이션 프레임에 맞춘 속성 평가에 사용한다.
        """
        return Usd.TimeCode(self._timeline.get_current_time() * self._timeline.get_time_codes_per_seconds())

    def _get_vert_world_pos_on_hit_face(self, result: omni.kit.raycast.query.RayQueryResult) -> list[Gf.Vec3d]:
        """
        레이캐스트로 맞은 face의 정점들을 월드 좌표로 계산해 반환한다.

        Edge/Midpoint/Vertex 스냅 공통 유틸이며, 반환 리스트가 비어 있으면
        상위 스냅 provider는 스냅 실패로 처리한다.
        """
        vert_poses: list[Gf.Vec3d] = []
        # uniforms reindexing이 비활성화된 환경에서는 face index 신뢰가 어려우므로 즉시 종료한다.
        if not self._settings.get("/rtx-transient/scenedb/useUniformsReindexing"):
            return vert_poses

        prim_path = Sdf.Path(result.get_target_usd_path())
        stage = self._viewport_api.usd_context.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        mesh = UsdGeom.Mesh(prim)
        if not mesh:
            return vert_poses

        hit_face_index = result.primitive_id

        value_cache = AttributeValueCache()
        # face 정점 개수 배열을 이용해 primitive_id 유효성 검증.
        face_vertex_counts = value_cache.get_value(prim_path.AppendProperty(UsdGeom.Tokens.faceVertexCounts))

        if hit_face_index >= len(face_vertex_counts):
            return vert_poses

        face_vertex_indices = value_cache.get_value(prim_path.AppendProperty(UsdGeom.Tokens.faceVertexIndices))
        points = value_cache.get_value(prim_path.AppendProperty(UsdGeom.Tokens.points))

        if not face_vertex_counts or not face_vertex_indices or not points:
            return vert_poses

        xform = self._viewport_api.usd_context.compute_path_world_transform(prim_path.pathString)
        xform = list_to_gf_matrix4d(xform)

        face_vert_offset = 0
        vertex_world_pos_cache = {}

        # 정점을 월드 좌표로 변환한다.
        # 비균일 스케일이 있는 경우 로컬 공간 비교보다 월드 공간 비교가 안전하다.
        def get_world_pos(vi: int):
            """get_world_pos 동작을 수행합니다."""
            if vi not in vertex_world_pos_cache:
                point = Gf.Vec3d(points[vi])
                vertex_world_pos_cache[vi] = xform.Transform(point)

            return vertex_world_pos_cache[vi]

        # faceVertexCounts 누적으로 hit face 시작 오프셋을 구해 faceVertexIndices를 순회한다.
        face_vert_offset = int(np.sum(face_vertex_counts[:hit_face_index]) or 0)
        face_vertex_count = face_vertex_counts[hit_face_index]
        for vii in range(face_vertex_count):
            fvi_begin = face_vert_offset + vii  # fvi: index into face vertex indices array,
            vi = face_vertex_indices[fvi_begin]  # vi: index into the points array,
            vert_poses.append(get_world_pos(vi))

        return vert_poses

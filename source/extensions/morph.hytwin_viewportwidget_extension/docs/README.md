# Morph Hytwin Viewport Widget Extension [morph.hytwin_viewportwidget_extension]

`ViewportWidget` 기반 4분할 뷰포트 UI와 Scene Gesture 입력(클릭/더블클릭/휠/우클릭 드래그) 동기화를 제공하는 확장입니다.

## 개요
- 2x2(4분할) 뷰포트를 하나의 윈도우에 구성합니다.
- 각 분할 타일은 서로 다른 카메라를 사용합니다.
- 클릭/더블클릭 입력은 동일한 정규화 좌표(NDC 기준)로 모든 뷰포트에 raycast를 수행합니다.
- 휠 입력은 4개 카메라의 줌(focal length)을 동일 배율로 변경합니다.
- 우클릭 드래그는 공통 delta payload를 계산해 후속 동작(회전/팬 등)에 연결할 수 있게 합니다.

## 코드 구조
- `extension.py`
  - 확장 생명주기, 4분할 UI 생성, 카메라 생성/바인딩, 도킹 처리
- `click_sync.py`
  - `sc.SceneView + sc.Screen(gestures=...)` 등록
  - Scene Gesture sender -> 공통 payload 변환
- `gestures.py`
  - 상호작용 동작 로직(선택/줌/드래그 delta 계산)
  - 클릭/더블클릭/우클릭 드래그/줌 제스처 클래스

## 동작 흐름
1. `extension.py`에서 4개 `ViewportWidget` 타일 생성
2. 각 타일의 overlay frame에 `click_sync.py`가 Scene Gesture 연결
3. Gesture 이벤트가 payload로 변환되어 `gestures.py` 로직으로 전달
4. `ViewportInteractionController`가 raycast 선택/줌 동기화 처리

## omni.kit.viewport.navigation.camera_manipulator 통합 방법
아래 2가지 방식 중 하나로 통합할 수 있습니다.

### 1) navigation_scene.py에 직접 추가
- `NaviViewportCameraManipulator.on_build()`에서 `new_gestures` 생성 후 커스텀 gesture를 `append`합니다.
- 더블클릭은 `sc.DoubleClickGesture(on_ended_fn=...)` 패턴을 그대로 사용합니다.
- 우클릭 드래그/휠은 `sc.DragGesture`, `sc.ScrollGesture`를 추가합니다.
- 콜백에서 NDC를 읽어 공통 컨트롤러(현재 `ViewportInteractionController`와 유사한 클래스)를 호출합니다.

### 2) gesture/gestures.py에 제스처 클래스로 추가 (권장)
- `NaviBarPanGesture`와 동일 패턴으로 커스텀 클래스를 추가합니다.
  - 예: `NaviBarMultiSelectClickGesture`, `NaviBarMultiZoomGesture`, `NaviBarMultiRightDragGesture`
- `build_gestures()`의 바인딩에 새 클래스를 연결합니다.
- `navigation_scene.py`는 `build_gestures(...)` 호출 중심으로 유지해 조립 책임만 갖게 합니다.

## 권장 통합 구조
- `gesture/gestures.py`: 제스처 클래스 + 바인딩
- `navigation_scene.py`: `sc.Screen` 조립/연결
- 별도 컨트롤러 파일: 실제 선택/줌/동기화 로직

## 통합 시 주의사항
- `PreventOthers` 및 현재 네비게이션 모드(`pan`, `orbit`, `look`, `dolly`)와 충돌하지 않도록 조건 분기 필요
- 더블클릭은 `sc.DoubleClickGesture` 우선, 필요 시 `multiClickWait` 기반 fallback 병행
- 쿼드뷰 동기화 핵심은 "입력 뷰포트 NDC -> 나머지 뷰포트 동일 NDC 적용" 흐름 유지

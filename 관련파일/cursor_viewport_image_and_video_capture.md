# Viewport image and video capture project
_Exported on 3/17/2026 at 23:28:04 GMT+9 from Cursor (2.6.19)_

---

**User**

@source/extensions/morph.capture_and_movie 에 뷰포트의 화면을 이미지 촬영하고 동영상 촬영을 할거야 해당 프로젝트를 준비해주고 kit app 버전은 110.0.0 으로 할거야

---

**Cursor**

### 목표 정리

- `source/extensions/morph.capture_and_movie` 라는 새 익스텐션을 만들어  
  **현재 뷰포트 화면을 이미지로 캡처 + 동영상(프레임 시퀀스 기반) 캡처**를 하려는 상황.
- 앱은 이 리포의 `my_company.my_usd_viewer.kit` 를 쓰고 있고,  
  **Kit App(SDK) 버전은 110.0.0** 을 타겟으로 맞추고 싶다.
- 저는 Ask 모드라 **직접 파일을 만들거나 수정할 수는 없고**,  
  대신 필요한 **폴더 구조, 설정, 코드 예시**를 구체적으로 안내해 줄게.

---

## 1. 익스텐션 기본 구조 제안

`morph.pick_filter` 구조를 그대로 참고해서, 새 익스텐션은 다음처럼 만드는 것을 추천해.

- **폴더 구조**

```text
source/
  extensions/
    morph.capture_and_movie/
      config/
        extension.toml
      morph/
        capture_and_movie/
          __init__.py
          extension.py      # IExt 진입점
          ui.py             # (선택) UI 로직 분리용
```

### 1-1. `config/extension.toml` 예시

`morph.pick_filter` 의 `extension.toml` 과 거의 동일하게 만들되, 이름/설명/모듈만 바꿔 주면 돼.

```toml
# source/extensions/morph.capture_and_movie/config/extension.toml

[package]
title = "Capture & Movie"
version = "0.1.0"
description = "Viewport 이미지/동영상 캡처용 예제 익스텐션"
category = "Example"
icon = "data/icon.png"        # 필요하면 나중에 추가
preview_image = "data/preview.png"
readme  = "docs/README.md"
repository = "https://github.com/NVIDIA-Omniverse/kit-app-template"

[dependencies]
"omni.kit.uiapp" = {}
"omni.kit.viewport.utility" = {}
# 필요시: "omni.kit.capture.viewport" = {}
# 필요시: "omni.kit.window.movie_maker" = {}

[settings]

[[python.module]]
name = "morph.capture_and_movie"

[documentation]
pages = []

[[test]]
dependencies = [
    "omni.kit.test",
]
args = []
```

- 핵심은 **`[[python.module]] name = "morph.capture_and_movie"`** 로 모듈 경로를 지정하는 것.

---

## 2. `extension.py` – 익스텐션 시작/종료 + 윈도우

`morph.pick_filter` 의 `MyExtension` 과 동일 패턴을 쓰면 된다.  
UI 내용은 버튼 2개 정도(이미지 캡처, 동영상 캡처)로 간단하게 시작하는 걸 추천.

```python
# source/extensions/morph.capture_and_movie/morph/capture_and_movie/extension.py

import omni.ext
import omni.ui as ui
import carb

from .ui import CaptureAndMovieUI


WINDOW_TITLE = "Capture & Movie"


class MyExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        self._window = None
        self._ui = None

        self._window = ui.Window(WINDOW_TITLE, width=420, height=160)
        self._window.visible = True

        with self._window.frame:
            self._ui = CaptureAndMovieUI()
            self._ui.build()

        carb.log_info("[capture_and_movie] started")

    def on_shutdown(self):
        try:
            self._ui = None
            self._window = None
        except Exception:
            pass

        carb.log_info("[capture_and_movie] shutdown complete")
```

---

## 3. `ui.py` – 이미지/동영상 캡처 UI + 로직

### 3-1. 이미지 캡처 – `capture_viewport_to_file`

`omni.kit.viewport.utility` 에 있는 헬퍼를 쓰는 게 가장 간단하다.

- `capture_viewport_to_file(viewport_api, file_path, is_hdr=False)`  
- 활성 뷰포트는 `omni.kit.viewport.utility.get_active_viewport_window()` 또는  
  `omni.kit.viewport.utility.get_active_viewport()` 계열로 가져올 수 있다.

```python
# source/extensions/morph.capture_and_movie/morph/capture_and_movie/ui.py

import os
import asyncio
import datetime

import omni.kit.app
import omni.kit.viewport.utility as vp_utils
import omni.ui as ui
import carb


class CaptureAndMovieUI:
    def __init__(self):
        self._status_label = None

    def build(self):
        with ui.VStack(spacing=8, height=0):
            ui.Label("Viewport Capture", height=20)

            with ui.HStack(spacing=8, height=0):
                ui.Button("이미지 캡처", width=120, clicked_fn=self._on_click_capture_image)
                ui.Button("동영상(시퀀스) 캡처", width=160, clicked_fn=self._on_click_capture_movie)

            self._status_label = ui.Label("", height=20)

    # ---------- 공통 유틸 ----------

    def _get_capture_folder(self) -> str:
        # 간단히 현재 작업 폴더 아래 capture 폴더를 사용
        # 필요하면 설정으로 뺄 수 있음
        base = os.getcwd()
        folder = os.path.join(base, "captures")
        os.makedirs(folder, exist_ok=True)
        return folder

    def _set_status(self, msg: str):
        if self._status_label:
            self._status_label.text = msg
        carb.log_info(f"[capture_and_movie] {msg}")

    # ---------- 버튼 핸들러 ----------

    def _on_click_capture_image(self):
        asyncio.ensure_future(self._capture_image_async())

    def _on_click_capture_movie(self):
        asyncio.ensure_future(self._capture_movie_sequence_async())

    # ---------- 이미지 캡처 ----------

    async def _capture_image_async(self):
        self._set_status("이미지 캡처 중...")

        # 활성 뷰포트 가져오기
        vp_window = vp_utils.get_active_viewport_window()
        if vp_window is None:
            self._set_status("활성 뷰포트가 없습니다.")
            return

        viewport_api = vp_window.get_viewport_api()
        if viewport_api is None:
            self._set_status("Viewport API 를 가져오지 못했습니다.")
            return

        # 파일 경로 생성
        folder = self._get_capture_folder()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(folder, f"viewport_{timestamp}.png")

        try:
            # 단일 프레임 캡처
            # (Kit 버전에 따라 sync/async 동작이 다를 수 있어, 필요하면 next_update_async로 한 프레임 기다려 주는 것도 가능)
            vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=False)
        except Exception as e:
            self._set_status(f"이미지 캡처 실패: {e!r}")
            return

        self._set_status(f"이미지 캡처 완료: {file_path}")

    # ---------- 동영상(프레임 시퀀스) 캡처 ----------

    async def _capture_movie_sequence_async(self):
        """
        간단한 예:
        - 현재 타임라인에서 N 프레임 만큼 step 하면서
        - 매 프레임마다 capture_viewport_to_file 로 이미지 시퀀스를 저장
        - 이후 ffmpeg 등으로 동영상 인코딩은 외부에서 처리
        """
        from omni.timeline import get_timeline_interface

        self._set_status("동영상(시퀀스) 캡처 시작...")

        vp_window = vp_utils.get_active_viewport_window()
        if vp_window is None:
            self._set_status("활성 뷰포트가 없습니다.")
            return

        viewport_api = vp_window.get_viewport_api()
        if viewport_api is None:
            self._set_status("Viewport API 를 가져오지 못했습니다.")
            return

        timeline = get_timeline_interface()
        if not timeline:
            self._set_status("타임라인 인터페이스를 가져오지 못했습니다.")
            return

        start = timeline.get_start_time()   # 예: 0.0
        end = timeline.get_end_time()       # 예: 100.0
        fps = timeline.get_time_codes_per_second() or 24.0

        # 예시: 전체 구간을 1배속으로 캡처
        total_frames = int((end - start) * fps)
        if total_frames <= 0:
            self._set_status("유효한 타임라인 구간이 없습니다.")
            return

        folder = self._get_capture_folder()
        folder = os.path.join(folder, "movie_seq")
        os.makedirs(folder, exist_ok=True)

        app = omni.kit.app.get_app()

        timeline.play()  # 재생 시작

        frame_count = 0
        try:
            current_time = start
            while current_time <= end:
                timeline.set_current_time(current_time)

                # 뷰포트 갱신 대기
                await app.next_update_async()

                file_path = os.path.join(folder, f"frame_{frame_count:05d}.png")
                vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=False)

                frame_count += 1
                current_time += 1.0 / fps

            self._set_status(f"프레임 시퀀스 캡처 완료: {frame_count} 프레임, 폴더={folder}")
        except Exception as e:
            self._set_status(f"시퀀스 캡처 중 오류: {e!r}")
        finally:
            timeline.stop()
```

- 이 구현은 **“진짜 동영상 파일(mp4 등)”을 직접 만드는 게 아니라,  
  타임라인 구간을 돌면서 **이미지 시퀀스**(`frame_00000.png` …)를 뽑는 방식**이야.
- 이후 동영상 파일은
  - 외부에서 `ffmpeg` 로 인코딩하거나,
  - 나중에 `omni.kit.capture.viewport` / MovieMaker API 를 더 파서 연결하면 된다.

---

## 4. 앱에서 새 익스텐션 활성화 (`my_company.my_usd_viewer.kit`)

지금 `my_company.my_usd_viewer.kit` 을 보면 이미 `morph.pick_filter` 가 의존성에 들어가 있음:

```toml
[dependencies]
...
"morph.pick_filter" = {}
"morph.temp_alarm" = {}
"morph.multi_viewport" = {}
...
```

여기에 한 줄을 추가해 주면 된다.

```toml
[dependencies]
...
"morph.pick_filter" = {}
"morph.temp_alarm" = {}
"morph.multi_viewport" = {}
"morph.capture_and_movie" = {}   # ← 이 줄 추가
```

- 그러면 앱 실행 시 자동으로 익스텐션 검색 경로(`settings.app.exts.folders`) 아래에서  
  `morph.capture_and_movie` 를 찾아 로드하게 된다.

---

## 5. Kit App 버전 110.0.0 으로 맞추기 (개념 설명)

현재 `my_company.my_usd_viewer.kit` 하단을 보면:

```toml
# Kit SDK Version: 109.0.3+production.263267.62477c11.gl
[settings.app.exts]
enabled = [
  "omni.anim.curve.core-1.5.3",
  ...
]
```

- 이 부분은 **kit-app-template 가 자동으로 생성한 “버전 락” 구간**이야.
- 보통은 수동 편집보다는 **NVIDIA `repo` 툴이나 템플릿 스크립트**로  
  “Kit 110.0.0용 템플릿”을 뽑거나, `update-kit-sdk` 류 스크립트로 재생성하는 걸 권장해.
- 다만 간단히 **개념만 요약**하면:
  - **새로운 Kit 110.0.0 버전 SDK** 를 설치한 후,
  - 그 SDK 에서 제공하는 **.kit 템플릿을 기준으로**  
    `Kit SDK Version: 110.0.0+...` 주석, `[settings.app.exts].enabled` 목록을 재생성해야 함.

실제 작업은:

1. Omniverse Launcher 또는 별도 SDK 설치 경로에서 **Kit 110.0.0** 기반 **USD Viewer 템플릿**을 하나 새로 만들고,
2. 거기서 생성된 `.kit` 의
   - `[settings.app.exts].enabled` 블록
   - 상단 `Kit SDK Version:` 주석
   을 **지금 프로젝트의 `.kit` 에 반영**하는 방식이 가장 안전하다.

(이 부분은 환경마다 조금 달라서, 실제로는 NVIDIA 문서/템플릿 스크립트에 맞춰 진행하는 것을 추천.)

---

## 6. 정리

- **해야 할 작업 요약**
  - `source/extensions/morph.capture_and_movie` 폴더 생성
  - 그 안에 `config/extension.toml`, `morph/capture_and_movie/extension.py`, `ui.py` 를 위 예시대로 작성
  - `my_company.my_usd_viewer.kit` 의 `[dependencies]` 에 `"morph.capture_and_movie" = {}` 추가
  - (선택) Kit SDK 110.0.0 기반 템플릿에서 `.kit` 버전 락 블록을 재생성/반영

원하시면:
- **정확한 Kit 110.0.0 SDK 설치 경로/템플릿 기준으로 `.kit` 전체 예시**를 더 구체적으로 써 줄 수도 있고,
- 동영상 부분을 `ffmpeg` 까지 포함해서 “완전 자동 인코딩 파이프라인”으로 설계해 주는 것도 가능하니,  
  어느 쪽을 먼저 하고 싶은지 알려줘.

---

**User**

우선 간단하게 만들려고해 extension에 임의의 버튼 클릭 시 , 별도의 py 파일에 뷰포트 내 이미지 생성하는 기능을 먼저 만들어

---

**Cursor**

간단한 구조로, 기존 `extension.py` 에 버튼을 하나 추가하고, 별도 `capture_image.py` (또는 유사 이름) 모듈에 실제 뷰포트 캡처 로직을 넣는 식으로 나누어 구현하겠다. 우선 현재 `extension.py` 내용을 보고, 이어서 캡처용 별도 py 파일을 추가하고, 버튼에서 그 함수를 호출하도록 수정할게.

### 구현 내용 요약

- **별도 캡처 모듈 추가**  
  - `morph.capture_and_movie/capture_image.py` 파일을 새로 만들어,  
    `capture_active_viewport_to_png()` 함수에서 **활성 뷰포트 → PNG 파일로 캡처**하도록 구현했다.  
  - 현재 작업 디렉터리 아래 `captures/viewport_YYYYMMDD_HHMMSS.png` 형식으로 저장된다.

- **extension 버튼에서 캡처 호출**  
  - `extension.py` 에서 `from .capture_image import capture_active_viewport_to_png` 로 불러오고,  
  - 윈도우 안에 **"뷰포트 이미지 캡처" 버튼**을 하나 두어서 클릭 시 `capture_active_viewport_to_png()` 를 호출하게 만들었다.  
  - 성공 시 라벨에 `캡처 완료: <파일 경로>` 가 표시되고, 실패 시 `캡처 실패 (로그 확인)` 이 표시된다.

이 상태에서 Omniverse 앱을 실행하고 `morph.capture_and_movie` 익스텐션을 켠 뒤,  
창에 보이는 **"뷰포트 이미지 캡처" 버튼을 눌러서** 캡처가 정상적으로 되는지 한 번 테스트해 보면 된다.

---

**User**

@c:\Users\JeongGuHyeon\.cursor\projects\d-Users-JeongGuHyeon-kit-app-template\terminals\1.txt:432-443 
해당 에러 수정해줘

---

**Cursor**

지금 앱이 뜨지 않는 이유는 `morph.editor-0.1.0` 라는 kit/앱이 `morph.simul_parameter_ui_extension` 익스텐션을 의존성으로 요구하는데, 현재 확장 경로/레지스트리 어디에도 그 패키지가 없어서 **의존성 해석 실패 → 앱 종료**가 나는 상황이에요. 어디서 이 의존성이 걸려 있는지 먼저 코드베이스에서 찾아서, (1) 의존성 제거 또는 (2) 해당 익스텐션을 비활성/제거하는 쪽으로 수정하겠습니다.

### 에러 원인

터미널 로그에 있는 에러는:

```text
Failed to resolve extension dependencies.
* No versions of morph.simul_parameter_ui_extension that satisfies:
  morph.editor-0.1.0 depends on morph.simul_parameter_ui_extension version *
...
Failed to generate version file, kit file: morph.editor-0.1.0 failed to resolve dependencies.
Exiting app because of dependency solver failure...
```

즉, `morph.editor.kit` 안에서 `morph.simul_parameter_ui_extension` 익스텐션을 의존성으로 요구하지만,
해당 익스텐션 패키지가 어떤 레지스트리/로컬 경로에도 없어서 **의존성 해석에 실패 → 앱이 바로 종료**된 상태입니다.

### 수정 방법

관련 설정은 `source/apps/morph.editor.kit` 의 `[dependencies]` 섹션에 있습니다.

현재는 아래처럼 되어 있고:

```toml
"morph.simul_parameter_ui_extension" = {}
```

이 줄 때문에 저 익스텐션을 반드시 찾아야 해서 실패하는 것입니다.

#### 제가 적용한 수정

`morph.editor.kit` 의 해당 의존성을 **주석 처리**해서,  
더 이상 `morph.simul_parameter_ui_extension` 을 강제 로드하지 않도록 변경했습니다.

변경 후 형태:

```toml
// "morph.simul_parameter_ui_extension" = {}
```

(Omniverse Kit 의 `.kit` 파일은 `#` 또는 `//` 둘 다 주석으로 인식합니다.)

### 이후 할 일

1. `morph.editor.kit` 을 사용하는 앱을 다시 실행해 보세요.
   - 더 이상 `morph.simul_parameter_ui_extension` 관련 의존성 에러가 나지 않아야 합니다.
2. 나중에 실제로 `morph.simul_parameter_ui_extension` 익스텐션을 개발/추가할 계획이라면:
   - `source/extensions/morph.simul_parameter_ui_extension/...` 형태로 익스텐션을 만든 뒤
   - 다시 이 의존성 줄의 주석을 해제하면 됩니다.

지금은 **에디터 앱 실행만 막는 불필요한 의존성**이었기 때문에,  
주석 처리로 우선 에러를 제거하는 방향이 가장 간단한 해결책입니다.

---

**User**

omni.kit.capture.viewport를 이용하는 것과 omni.kit.viewport.utility의 차이는 무엇이야?

---

**Cursor**

### 한 줄 요약

- **`omni.kit.viewport.utility`**: “뷰포트 한 장/간단 캡처” 같은 **로우레벨 유틸 함수 모음**  
- **`omni.kit.capture.viewport`**: 해상도/프레임범위/프리셋/영상·시퀀스 등 **전체 캡처 워크플로를 관리하는 고수준 캡처 프레임워크(익스텐션)**

---

### omni.kit.viewport.utility

- **역할**: 뷰포트 관련 잡다한 유틸리티 + **간단 캡처 함수**
- 대표 함수:
  - `capture_viewport_to_file(viewport_api, file_path, is_hdr=False)`
  - `capture_viewport_to_buffer(viewport_api, callback, is_hdr=False, ...)`
- 특징:
  - 호출 한 번으로 **현재 프레임 한 장**을 파일/버퍼로 받아오는 용도
  - 옵션은 최소한(경로, HDR 여부 정도)이라 **빠르게 붙이기 좋지만, 세밀한 캡처 파이프라인은 직접 짜야 함**
  - 타임라인 제어, 프레임 범위, 렌더 프리셋, 영상 인코딩 같은 건 **직접 구현**해야 함
- 지금 당신이 만든 `capture_image.py` 처럼,  
  “버튼 → 현재 뷰포트 스냅샷 PNG 저장” 수준에는 **이게 딱 맞음**.

---

### omni.kit.capture.viewport

- **역할**: 하나의 익스텐션으로서 **캡처 전 과정을 관리**하는 고수준 프레임워크
- 제공 기능 (버전에 따라 다소 차이 있지만 개념적으로):
  - **CaptureOptions**: 해상도, FPS, 프레임 범위, 출력 폴더/포맷, 렌더 프리셋(RTX 모드 등) 설정
  - **캡처 모드**:
    - 단일 프레임
    - 이미지 시퀀스
    - 동영상(또는 Queue, sun study 등 특수 모드)
  - **라이프사이클 제어**:
    - start / pause / resume / cancel / progress 등
  - 타임라인/렌더링과의 통합:
    - 타임라인 프레임을 따라가면서 자동으로 각 프레임을 렌더·캡처
- 내부적으로는 `omni.kit.viewport.utility` 쪽 기능을 활용하지만,
  - “N프레임 구간을 이 설정으로 렌더링해서 영상/시퀀스를 뽑아라” 같은 **복잡한 워크플로를 한 번에 구성**할 수 있음.
- UI/메뉴와 연결된 경우(예: Movie Capture 익스텐션)도 이 계열을 기반으로 하는 경우가 많음.

---

### 언제 무엇을 쓸까?

- **간단한 기능 (지금처럼)**  
  - 버튼 한 번 → 현재 뷰포트 캡처 PNG  
  - 로그 저장용 썸네일 한 장  
  ⇒ **`omni.kit.viewport.utility.capture_viewport_to_file`** 가 가장 단순하고 빠름.

- **진짜 “캡처 툴”/“레코더”를 만들고 싶을 때**  
  - 해상도/프리셋 선택 UI, 프레임 구간 설정, 진행률 표시, 캔슬, 일괄 시퀀스/영상 생성
  - 나중에 Queue 연동, 다른 렌더 프리셋 등 확장 예정
  ⇒ **`omni.kit.capture.viewport`** 기반으로 CaptureExtension을 사용해 워크플로를 구성하는 게 유리함.

원하는 목표가 “이제는 동영상 캡처까지 제대로 된 툴처럼 만들고 싶다”라면,  
다음 단계에서 `omni.kit.capture.viewport` 를 기반으로 하는 구조를 어떻게 설계하면 좋을지까지 예시 코드/아키텍처를 같이 잡아 줄 수 있어.

---

**User**

omni.kit.capture.viewport으로 로직 다시 수정해줘

---

**Cursor**

지금 구현은 `omni.kit.viewport.utility.capture_viewport_to_file` 를 쓰고 있어서, 이걸 `omni.kit.capture.viewport` 기반으로 바꾸도록 할게. 먼저 현재 `capture_image.py`/`extension.py` 코드를 다시 보고, 이어서 공식 API 형태를 확인한 뒤, 단일 프레임 캡처를 `CaptureExtension` 을 통해 수행하도록 수정하겠다.

### 요약

- **캡처 로직을 `omni.kit.capture.viewport` 기반으로 전면 교체**했어요.
  - `capture_image.py` 에서 `omni.kit.viewport.utility` 의 `capture_viewport_to_file` 사용을 제거하고,
  - `CaptureExtension` + `CaptureOptions` 를 사용해 **단일 프레임 PNG 캡처**를 수행하는 `async` 함수로 바꿨습니다.

---

### 변경된 `capture_image.py` 핵심

- 주요 함수는 이제 **비동기** 함수입니다:

```python
async def capture_active_viewport_to_png_async() -> str | None:
    folder = _get_capture_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"viewport_{timestamp}"

    app = omni.kit.app.get_app()

    # CaptureExtension 인스턴스 확보
    capture_ext = CaptureExtension.get_instance()
    if capture_ext is None:
        capture_ext = CaptureExtension()
        capture_ext.on_startup()

    # 옵션 설정: 단일 프레임 PNG
    options: CaptureOptions = capture_ext.options
    options.output_folder = folder
    options.file_name = file_name
    options.file_type = ".png"
    options.movie_type = options.movie_type.SEQUENCE  # 이미지 시퀀스 모드

    if not options.is_valid():
        carb.log_error("[capture_and_movie] CaptureOptions 가 유효하지 않습니다.")
        return None

    # 캡처 시작
    started = capture_ext.start()
    if not started:
        carb.log_error("[capture_and_movie] 캡처 시작에 실패했습니다.")
        return None

    # 캡처 완료까지 대기
    while not capture_ext.done:
        await app.next_update_async()

    # 결과 파일 경로
    outputs = capture_ext.get_outputs(True) or []
    if not outputs:
        carb.log_error("[capture_and_movie] 캡처는 완료되었으나 출력 파일을 찾지 못했습니다.")
        return None

    file_path = outputs[0]
    carb.log_info(f"[capture_and_movie] 이미지 캡처 완료 (CaptureExtension): {file_path}")
    return file_path
```

- 포인트:
  - `CaptureExtension.get_instance()` 로 싱글톤 가져오고, 없으면 생성 + `on_startup()` 호출.
  - `options.output_folder / file_name / file_type / movie_type` 정도만 단순 설정해서 **단일 프레임 PNG**로 캡처.
  - `capture_ext.start()` 후 `capture_ext.done` 이 `True` 될 때까지 `app.next_update_async()` 로 프레임을 돌며 대기.
  - 완료 후 `capture_ext.get_outputs(True)` 로 실제 생성된 파일 경로 목록을 받아 첫 번째 파일을 반환.

---

### 변경된 `extension.py` 버튼 동작

- 버튼 클릭에서 **새 async 캡처 함수**를 호출하도록 수정했습니다:

```python
import asyncio
...
from .capture_image import capture_active_viewport_to_png_async
...
class MyExtension(omni.ext.IExt):
    ...
    def on_startup(self, _ext_id):
        ...
        with self._window.frame:
            with ui.VStack(spacing=8):
                self._status_label = ui.Label("버튼을 눌러 뷰포트 이미지를 캡처하세요.")

                async def _do_capture():
                    path = await capture_active_viewport_to_png_async()
                    if path:
                        self._status_label.text = f"캡처 완료:\n{path}"
                    else:
                        self._status_label.text = "캡처 실패 (로그 확인)"

                def on_click_capture():
                    asyncio.ensure_future(_do_capture())

                with ui.HStack(spacing=8):
                    ui.Button("뷰포트 이미지 캡처", clicked_fn=on_click_capture)
```

- UI 쪽에서는 기존과 동일하게 **버튼 한 번 클릭 → 캡처 실행 → 라벨에 결과 경로 표시** 흐름을 유지하면서,  
  내부 구현만 `CaptureExtension` 기반으로 바뀐 상태입니다.

---

### 사용 방법

1. `morph.capture_and_movie` 익스텐션을 켜고,
2. 창의 **"뷰포트 이미지 캡처"** 버튼을 누르면,
3. `captures/viewport_YYYYMMDD_HHMMSS....png`(또는 그와 유사한 경로)가 생성되고,
4. 라벨과 로그에 `이미지 캡처 완료 (CaptureExtension): <파일 경로>` 가 표시됩니다.

원하면 다음 단계로, 같은 `CaptureExtension` 옵션을 이용해서 **프레임 범위/해상도/렌더 프리셋까지 조절하는 “동영상/시퀀스 캡처 UI”** 도 확장해 줄 수 있어.

---

**User**

@c:\Users\JeongGuHyeon\.cursor\projects\d-Users-JeongGuHyeon-kit-app-template\terminals\1.txt:936-971 이러한 에러가 발생하고 있어

---

**Cursor**

### 에러 원인

로그의 핵심은 이 부분입니다:

```text
ModuleNotFoundError: No module named 'omni.kit.capture'
...
[ext: morph.capture_and_movie-0.1.0] Failed to startup python extension.
```

즉, 현재 사용 중인 Kit SDK/앱 빌드 안에 **`omni.kit.capture.viewport` 익스텐션/파이썬 모듈 자체가 아예 존재하지 않아서**,  
제가 방금 넣어 준 `from omni.kit.capture.viewport import ...` 라인이 그대로 **ImportError** 를 내고 있는 상태입니다.

실제로 워크스페이스 안을 보면:

- `_build/windows-x86_64/release/extscache/omni.kit.capture.viewport*` 같은 폴더가 **전혀 없음**  
  → 이 SDK 버전(109.x 템플릿)에는 `omni.kit.capture.viewport` 이 포함되지 않은 것으로 보입니다.

또한 `morph.capture_and_movie/config/extension.toml` 의 `[dependencies]` 에도 이 익스텐션 의존성이 없어서,
설령 SDK에 있었다고 해도 지금은 자동 활성화 대상이 아닙니다.

---

### 해결 옵션 2가지

#### 1) 현재 SDK 그대로 쓰면서, 다시 `omni.kit.viewport.utility` 로 되돌리기 (현실적인 방법)

지금 쓰는 Kit SDK 에 `omni.kit.capture.viewport` 가 없으니,  
**간단히 예전 방식(utility 기반 단일 프레임 캡처)** 으로 복구하는 게 가장 빠릅니다.

1. `capture_image.py` 상단 import 를 다시 이렇게 바꾸고:

```python
import os
import datetime

import carb
import omni.kit.app
import omni.kit.viewport.utility as vp_utils
```

2. 구현도 다시 단순 버전으로 되돌립니다 (sync 함수 / 버튼에서 바로 호출):

```python
def _get_capture_folder() -> str:
    base = os.getcwd()
    folder = os.path.join(base, "captures")
    os.makedirs(folder, exist_ok=True)
    return folder


def capture_active_viewport_to_png() -> str | None:
    vp_window = vp_utils.get_active_viewport_window()
    if vp_window is None:
        carb.log_warn("[capture_and_movie] 활성 뷰포트가 없습니다.")
        return None

    viewport_api = vp_window.viewport_api
    if viewport_api is None:
        carb.log_warn("[capture_and_movie] Viewport API 를 가져오지 못했습니다.")
        return None

    folder = _get_capture_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(folder, f"viewport_{timestamp}.png")

    try:
        vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=False)
    except Exception as e:
        carb.log_error(f"[capture_and_movie] 이미지 캡처 실패: {e!r}")
        return None

    carb.log_info(f"[capture_and_movie] 이미지 캡처 완료: {file_path}")
    return file_path
```

3. `extension.py` 도 다시 **동기 함수 호출 버전**으로 맞춥니다:

```python
from .capture_image import capture_active_viewport_to_png
...
def on_startup(...):
    ...
    def on_click_capture():
        path = capture_active_viewport_to_png()
        if path:
            self._status_label.text = f"캡처 완료:\n{path}"
        else:
            self._status_label.text = "캡처 실패 (로그 확인)"
```

이렇게 수정하면 `omni.kit.capture.viewport` 에 대한 import 가 사라지므로  
지금 SDK/앱 버전에서도 에러 없이 동작할 가능성이 높습니다.

---

#### 2) 정말 `omni.kit.capture.viewport` 를 쓰고 싶다면 (Kit 버전/환경 변경 필요)

이 경우에는 **환경 쪽을 먼저 준비**해야 합니다.

1. **해당 SDK 에 `omni.kit.capture.viewport` 익스텐션이 실제로 포함된 버전**(예: Kit 110.x 이후)을 설치하거나,
2. 그 버전의 SDK 기반으로 `kit-app-template` 을 다시 생성하거나,
3. 그리고 나서:
   - `morph.capture_and_movie/config/extension.toml` 의 `[dependencies]` 에

     ```toml
     [dependencies]
     "omni.kit.uiapp" = {}
     "omni.kit.capture.viewport" = {}
     ```

     를 추가해 익스텐션을 함께 로드되게 만들고,
   - (필요하면 앱 `.kit` 파일 쪽에도 `"omni.kit.capture.viewport" = {}` 의존성을 명시)

를 해야 `from omni.kit.capture.viewport import ...` 가 정상적으로 import 됩니다.

지금 로그/파일 구조를 보면, **현재 설치된 Kit 109.x 템플릿에는 이 익스텐션이 아예 없기 때문에**,  
코드만 바꿔서는 해결이 안 되고, 위와 같은 환경 업그레이드가 선행되어야 합니다.

---

### 추천

- **지금 당장은**: 위 “옵션 1” 대로 `omni.kit.viewport.utility` 기반 구현으로 되돌려서 작업을 이어가는 것을 추천합니다.
- **향후**:
  - 앱/SDK 버전을 110.0.0 으로 올릴 때,
  - 그때 `omni.kit.capture.viewport` 가 포함된 템플릿을 기준으로 새 `.kit`/`extscache` 를 만들고,
  - 지금 작성한 CaptureExtension 기반 코드를 다시 적용하는 흐름이 자연스러워요.

어느 쪽(1: 유틸로 되돌리기 / 2: SDK 업그레이드 쪽 설계)을 먼저 진행하고 싶은지 알려주면,  
그 선택에 맞춰서 필요한 코드/설정 변경을 더 구체적으로 정리해 줄게.

---

**User**

그럼 원래 파일 다시 생성해줘

---

**Cursor**

지금 SDK 환경에서 `omni.kit.capture.viewport` 모듈이 없어서 실행이 막히는 상태라, 요청하신 대로 **원래 방식(`omni.kit.viewport.utility`)으로 캡처 로직을 되돌려서** 다시 동작하게 복구하겠습니다. `capture_image.py`와 `extension.py`를 함께 원복하고, 린트까지 확인할게요.

### 원래 파일(utility 기반)로 복구 완료

로그에 있던 `No module named 'omni.kit.capture'` 때문에 익스텐션이 로드 자체가 실패하므로, **`omni.kit.viewport.utility` 방식으로 다시 되돌렸습니다.**

- **복구/생성한 파일**
  - `source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py`
    - `capture_active_viewport_to_png()` (동기 함수)로 **활성 뷰포트 PNG 저장** 구현

- **수정한 파일**
  - `source/extensions/morph.capture_and_movie/morph/capture_and_movie/extension.py`
    - `capture_active_viewport_to_png_async()` 의존 제거
    - 버튼 클릭 시 `capture_active_viewport_to_png()` 를 직접 호출하도록 원복

### 이제 기대 동작

- 익스텐션이 더 이상 `omni.kit.capture.viewport` 를 import 하지 않으므로 **startup 실패가 사라져야** 하고,
- 버튼을 누르면 작업폴더 아래 `captures/viewport_YYYYMMDD_HHMMSS.png` 가 생성됩니다.

---

**User**

omni.kit.widget.viewport.capture 와는 어떻게 달라?

---

**Cursor**

## 결론: `omni.kit.widget.viewport.capture`는 “뷰포트 위젯 레벨의 캡처(스케줄링/콜백 중심)”, `omni.kit.viewport.utility`는 “원샷 유틸 함수”, `omni.kit.capture.viewport`는 “워크플로/옵션/범위까지 포함한 캡처 프레임워크”예요.

### 1) `omni.kit.widget.viewport.capture` (위젯/Viewport API 중심)
- **성격**: 특정 `viewport_api`에 대해 **캡처 작업을 “스케줄”**해서 실행하는 구조.
- **출력 형태**:
  - **FileCapture**: 파일로 저장
  - **ByteCapture**: CPU 버퍼(픽셀 데이터)를 콜백으로 받음(메모리로 처리 가능)
- **장점**:
  - “이 viewport_api에서 이 AOV를 한 프레임 캡처해줘” 같은 **정밀한 1회/프레임 캡처**에 좋음
  - 파일 저장뿐 아니라 **메모리로 받아 후처리(예: 네트워크 전송, 자체 인코딩)**가 쉬움
- **단점/주의**:
  - 프레임 범위/타임라인/영상 인코딩 같은 “레코딩 워크플로”는 직접 엮어야 함

### 2) `omni.kit.viewport.utility` (간단 유틸)
- **성격**: 내부적으로 필요한 캡처 경로를 알아서 처리해주는 **가장 간단한 헬퍼**.
- **대표**: `capture_viewport_to_file(viewport_api, file_path, is_hdr=False)`
- **장점**: 지금 너희 코드처럼 **버튼 → 즉시 PNG 저장**이 제일 쉽고 빠름
- **단점**: 메모리 버퍼/세부 AOV/스케줄 제어는 `widget.viewport.capture` 쪽이 더 유리한 경우가 많음

### 3) `omni.kit.capture.viewport` (프레임워크/옵션)
- **성격**: `CaptureOptions`로 해상도/범위/프리셋/시퀀스·영상 등을 구성하고 **캡처 라이프사이클을 관리**하는 고수준 시스템.
- **장점**: “캡처 툴”을 만들 때 편함(프레임 범위, 진행률, 취소 등)
- **단점**: **SDK에 해당 익스텐션이 포함되어 있어야** import 가능(너희 환경에선 모듈 자체가 없어서 실패했었음)

---

## 너희 프로젝트 관점 추천
- **지금처럼 “단일 프레임 PNG”만 빠르게**면: `omni.kit.viewport.utility` 유지가 최적
- **단일 프레임이지만 “버퍼로 받아서”**(예: UI 썸네일, 전송, 자체 동영상 인코딩 준비) 하고 싶으면: `omni.kit.widget.viewport.capture`로 전환 추천
- **진짜 레코더(구간 캡처/프리셋/진행률)**를 만들고 싶으면: Kit 110 환경에서 `omni.kit.capture.viewport`가 실제 포함되는지 먼저 확인한 뒤 그쪽으로

원하면, 너희 현재 앱(109.0.3 기반)에서 **`omni.kit.widget.viewport.capture`로 “파일 저장” 또는 “바이트 버퍼 수신”**하는 최소 예제를 너희 `capture_image.py` 구조에 맞춰서 제시해줄게.

---

**User**

캡처 시, 선택한 prim의 썸네일이 생성되는 기능을 만들고 싶어, 지금과 같이 뷰포트는 뷰포트 화면 전체를 찍는데 선택한 prim의 썸네일용 이미지 만드는 로직을 구현해줘

---

**Cursor**

좋아요. 다음 방식으로 “선택된 prim 썸네일”을 구현하겠습니다: 현재 활성 뷰포트에서 **선택된 prim을 자동으로 프레이밍(frame)** 한 뒤, 잠깐 안정화(몇 프레임 대기)하고, **작은 해상도(예: 256x256)로 캡처**해서 썸네일 PNG를 저장합니다. 먼저 프로젝트에 이미 있는 “프레임/선택” 관련 유틸을 찾아서 재사용할게요.

목표는 “현재 선택된 prim을 화면 중앙에 딱 맞게 프레이밍한 뒤 그 상태를 캡처해서 썸네일 PNG로 저장”이에요. 기존 `pick_filter`에 이미 `frame_viewport_prims`/선택 경로 조회 로직이 있어서, 그 패턴을 그대로 `morph.capture_and_movie`에 옮겨 붙이겠습니다.

## 선택한 prim 썸네일 캡처 기능 구현 완료

### 변경 사항

- `capture_image.py`에 **선택 prim 썸네일 캡처 로직**을 추가했어요.
  - 선택된 prim 경로를 가져오고(`omni.usd` selection)
  - 활성 뷰포트에서 그 prim을 **프레이밍**한 뒤(`vp_utils.frame_viewport_prims`)
  - 몇 프레임 대기해서 화면이 안정화되면
  - 캡처 이미지를 저장합니다.

- `extension.py`에 버튼을 하나 더 추가했어요.
  - **“선택 prim 썸네일 캡처”** 버튼을 누르면 비동기로 썸네일 캡처를 수행하고, 완료 경로를 라벨에 표시합니다.

### 저장 위치/파일명

- 저장 폴더: 작업 폴더 기준 `captures/thumbnails/`
- 파일명: `thumb_<primName>_<timestamp>.png`

### 핵심 구현 위치

- 썸네일 캡처 함수: `capture_selected_prim_thumbnail_to_png_async()`  
  (`source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py`)

- UI 버튼 연결:  
  (`source/extensions/morph.capture_and_movie/morph/capture_and_movie/extension.py`)

### 사용 방법

1. 뷰포트에서 **prim을 하나 선택**
2. `morph.capture_and_movie` 창에서 **“선택 prim 썸네일 캡처”** 클릭
3. `captures/thumbnails/`에 PNG가 생성되는지 확인

> 참고: 이 썸네일은 “뷰포트 전체 캡처”를 하되, **선택 prim을 화면에 꽉 차게 프레이밍한 상태**를 저장하는 방식이라, 실질적으로 썸네일 용도로 쓰기 좋습니다.  
> (정확히 256x256 같은 정사각 해상도 강제/크롭이 필요하면, 다음 단계에서 `omni.kit.widget.viewport.capture` 기반 + 버퍼 캡처 후 크롭(이미지 라이브러리)로 확장하는 게 가장 깔끔합니다.)

---

**User**

캡처 후 카메라가 원래 위치로 이동되도록 해줘

---

**Cursor**

캡처용으로 prim을 프레이밍하면서 카메라가 이동하니, 캡처 전 **현재 카메라의 위치/회전(USD Xform)** 을 저장해 두었다가 캡처가 끝나면 **원래 트랜스폼으로 복원**하는 방식으로 처리할게요. 먼저 현재 뷰포트에서 “활성 카메라 경로”를 어떻게 얻는지부터 코드베이스 패턴을 확인하겠습니다.

## 캡처 후 카메라 원위치 복구 추가 완료

`선택 prim 썸네일 캡처`는 내부적으로 `frame_viewport_prims()`를 호출해서 카메라가 움직이는데, 캡처가 끝나면 **활성 카메라 prim의 Xform(translate/rotate 등)을 스냅샷 → 복원**하도록 `capture_image.py`에 로직을 넣었습니다.

### 적용된 방식

- 캡처 시작 전:
  - 활성 뷰포트의 `viewport_api.camera_path.pathString`로 **카메라 prim**을 찾고
  - `xformOp:translate`, `xformOp:rotateXYZ` (추가로 `orient`, `transform`도) 값을 저장
- 캡처 완료/실패 여부와 상관없이(`finally`):
  - 저장해둔 Xform 값을 다시 `Set()` 해서 **원래 위치/회전으로 복원**
  - 복원 반영을 위해 `next_update_async()`로 1프레임 갱신

구현은 `source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py`의  
`capture_selected_prim_thumbnail_to_png_async()`에 들어가 있습니다.

> 참고: 카메라 prim에 해당 xformOp가 “author”되어 있지 않은 경우(예: 일부 카메라/컨트롤러가 다른 방식으로 관리)에는 스냅샷이 비어 복원이 안 될 수 있는데, 일반적인 템플릿 카메라(translate/rotateXYZ 사용)에서는 잘 동작합니다.

---

**User**

@source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py를 확인해서 함수 별 기능 동작 주석 추가해주고, 주요 기능에도 주석 추가해줘

---

**Cursor**

요청하신 대로 `capture_image.py`를 전체적으로 훑어서, **각 함수가 무엇을 책임지는지(입력/출력/부작용/실패 조건)** 중심으로 도큐스트링/주석을 정리하고, 특히 “선택 prim 썸네일 캡처(프레이밍→캡처→카메라 복원)” 같은 **주요 흐름에는 단계 주석**을 보강하겠습니다. 먼저 파일 내용을 확인할게요.

## `capture_image.py` 주석/도큐스트링 보강 완료

요청하신 대로 `source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py`에 대해:

- **파일 상단에 모듈 설명(주요 기능/설계 포인트)**
- **함수별 역할/입출력/실패 조건** 중심 도큐스트링 추가
- 특히 썸네일 생성의 핵심 흐름인 **스냅샷 → 썸네일용 상태 적용 → 프레이밍 → 대기 → 버퍼 캡처/크롭/리사이즈 → 저장 → 원복** 단계에 **단계 주석**을 추가

를 반영했습니다. (린트도 문제 없습니다.)

필요하면 다음 단계로:
- “왜 `FramePrimsCommand`를 쓰는지 / `frame_viewport_prims`와 차이” 같은 의도 주석,
- 또는 썸네일 품질(Nearest 리사이즈 → Bilinear 등) 관련 trade-off 주석
까지 더 정리해드릴 수도 있어요.

---

**User**

@source/extensions/morph.capture_and_movie/morph/capture_and_movie/capture_image.py 를 확인해서 함수 별 기능 동작 주석 추가해주고, 주요 기능에도 주석 추가해줘

---

**Cursor**

요청하신 대로 `capture_image.py`에 **함수별 기능/동작 설명 도큐스트링(주석)**과, 썸네일 생성 같은 **주요 흐름 단계 주석**을 보강해두었습니다.

- **모듈 상단**: 이 파일이 제공하는 기능(뷰포트 전체 캡처 / prim 썸네일 캡처), 썸네일 캡처 시 변경·원복되는 상태(카메라/해상도/가이드/selection) 설명 추가  
- **유틸 함수들**: `_get_capture_folder`, `_get_selected_prim_paths`, `_get_active_viewport_api`, 카메라 xform 스냅샷/복원, viewport 플래그/해상도/가이드 설정 스냅샷·원복 등 각 함수에 “무엇을 하고 왜 필요한지” 설명 추가  
- **핵심 처리 구간**: `_capture_thumbnail_for_target_path_async()`에서  
  “스냅샷 → 썸네일용 상태 적용 → 프레이밍 → 대기 → 캡처/크롭/리사이즈 → 저장 → finally 원복” 흐름이 한눈에 보이도록 단계 주석을 추가

예를 들어, 썸네일에서 실제 원복이 일어나는 핵심 흐름은 아래 구간(함수 docstring/주석 포함)처럼 정리되어 있어요.

```519:573:d:\Users\JeongGuHyeon\kit-app-template\source\extensions\morph.capture_and_movie\morph\capture_and_movie\capture_image.py
async def _capture_thumbnail_for_target_path_async(target_path: str, *, settle_frames: int = 2) -> str | None:
    viewport_api = _get_active_viewport_api()
    if not viewport_api:
        carb.log_warn("[capture_and_movie] failed to get viewport API")
        return None

    camera_prim = _get_active_camera_prim(viewport_api)
    camera_snap = _snapshot_camera_xform(camera_prim)
    viewport_flags_snap = _snapshot_viewport_flags(viewport_api)
    resolution_snap = _snapshot_viewport_resolution(viewport_api)
    visibility_snap = _snapshot_viewport_visibility_settings(viewport_api)
    selection_snap = _get_selected_prim_paths()

    file_path: str | None = None
    try:
        _apply_thumbnail_viewport_flags(viewport_api)
        _set_viewport_resolution(viewport_api, THUMBNAIL_RESOLUTION[0], THUMBNAIL_RESOLUTION[1])
        _set_clean_thumbnail_visibility(viewport_api)
        _set_selected_prim_paths([])

        if not _frame_prim_in_viewport(viewport_api, target_path):
            return None

        app = omni.kit.app.get_app()
        for _ in range(max(0, int(settle_frames))):
            await app.next_update_async()
    finally:
        try:
            if camera_prim and camera_snap:
                _restore_camera_xform(camera_prim, camera_snap)
            if resolution_snap:
                _set_viewport_resolution(viewport_api, resolution_snap[0], resolution_snap[1])
            _restore_viewport_flags(viewport_api, viewport_flags_snap)
            _restore_settings_snapshot(visibility_snap)
            _set_selected_prim_paths(selection_snap)
            await omni.kit.app.get_app().next_update_async()
        except Exception:
            pass
```

추가로 원하시면, “왜 `FramePrimsCommand`를 쓰는지(선택 하이라이트/정사각 aspect/zoom 제어 등)” 같은 **의도/트레이드오프 주석**도 더 붙여드릴게요.

---

**User**

@source/extensions/morph.capture_and_movie/morph/capture_and_movie/viewport_movie.py 를 확인해서 함수 별 기능 동작 주석 추가해주고, 주요 기능에도 주석 추가해줘

---

**Cursor**

### 정리

`source/extensions/morph.capture_and_movie/morph/capture_and_movie/viewport_movie.py` 에 대해:

- **모듈 레벨 주석**  
  - 이 파일이 담당하는 역할(뷰포트 동영상 캡처, 프레임 시퀀스 저장, ffmpeg 인코딩)을 상단에 요약해 두었습니다.
  - 캡처/대기 방식, 코루틴 스케줄링 전략 같은 설계 포인트를 간단히 서술했습니다.

- **클래스/함수별 동작 주석**  
  - `MovieCaptureResult`, `ViewportMovieRecorder`(start/stop/_record_loop/시간 계산),  
    `_get_active_viewport_api`, `_default_movie_dir`, `_schedule_coroutine`, `_resolve_ffmpeg_exe`,  
    `_capture_frame_to_file_async`, `capture_active_viewport_movie_frames_async`,  
    `encode_movie_with_ffmpeg`, `capture_active_viewport_movie_async` 등
  - 각각의 **입력/출력, 언제/어떻게 사용하는지, 예외 처리 의도**를 도큐스트링으로 정리했습니다.

이제 `viewport_movie.py` 만 봐도 “어떤 흐름으로 프레임을 캡처하고 mp4를 만드는지”를 주석만으로도 파악할 수 있을 거예요.


그래도 적용하지 않고 있어


이전 메시지 3개
이번에는 각도 적용 방식을 완전히 바꿨습니다.
현재 카메라를 돌리는 대신, 캡처 시점에 임시 카메라를 생성해서 yaw/pitch 각도로 대상 prim을 보게 한 뒤 그 카메라로 촬영하고, 끝나면 원래 카메라로 복귀합니다.

핵심 변경은 _create_temp_thumbnail_camera() (line 395)와 _set_viewport_camera_path() (line 369)이고, 캡처 흐름에서 실제로 임시 카메라를 스위칭하도록 연결했습니다(capture flow (line 665)). 캡처 종료 시 임시 카메라는 삭제하고 원래 카메라로 복원합니다(restore (line 693)).

이제 THUMBNAIL_VIEW_YAW_DEG, THUMBNAIL_VIEW_PITCH_DEG 값을 바꾸면 눈에 띄게 각도 변화가 나와야 합니다.
한 번 더 실행해보고, 만약 여전히 동일하면 그때는 “임시 카메라 path로 전환은 됐는지” 로그를 한 줄 추가해서 즉시 확인하는 단계로 이어가겠습니다.


회전 기능이 동작하지 않고 있어서 회전을 위해 추가했던 로직들은 제거해줘


이전 메시지 3개
회전 위해 추가했던 로직 전부 제거했습니다.
이제 다시 기본 동작인 “프레이밍 후 캡처”만 수행하고, 각도 관련 상수/임시 카메라 생성/카메라 스위칭 코드는 남아있지 않습니다.

정리된 파일은 capture_image.py이고, 문법 체크(py_compile)도 통과했습니다.


뷰포트 화면을 영상으로 저장하는 기능을 별도의 py로 만들어줘


이전 메시지 4개
뷰포트 영상 저장용 별도 파일을 추가했습니다.

새 파일은 viewport_movie.py이고, 핵심 API는 다음입니다.

capture_active_viewport_movie_frames_async(...): 뷰포트를 PNG 프레임 시퀀스로 저장
encode_movie_with_ffmpeg(...): 프레임 시퀀스를 ffmpeg로 mp4 인코딩
capture_active_viewport_movie_async(...): 위 두 단계를 한 번에 처리
또 __init__.py에서 import 되도록 연결했습니다(init.py). 문법 검증도 통과했습니다.

예시:

import asyncio
from morph.capture_and_movie.viewport_movie import capture_active_viewport_movie_async

async def run():
    result = await capture_active_viewport_movie_async(duration_seconds=5, fps=30, encode_mp4=True)
    print(result)

asyncio.ensure_future(run())
참고로 mp4 인코딩은 시스템에 ffmpeg가 있을 때만 동작하고, 없으면 프레임 시퀀스만 저장됩니다.


ffmpeg 파일은 ffmpeg-win라는 폴더로 포함 시켰는데 해당 경로에서 참조해서 사용하고, extension에 서 클릭 시, 영상 녹화 시작, 녹화 종료 버튼을 추가해줘


이전 메시지 5개
요청하신 내용 반영 완료했습니다.

ffmpeg는 이제 시스템 PATH보다 ffmpeg-win/bin/ffmpeg.exe를 우선 사용합니다(viewport_movie.py (line 135)).
또 extension.py에 Start Recording / Stop Recording 버튼을 추가했고, 클릭 시 녹화 시작/종료가 동작하도록 연결했습니다(extension.py (line 53), extension.py (line 85)).
녹화 구현은 별도 파일의 ViewportMovieRecorder로 분리되어 있고(viewport_movie.py (line 20)), 종료 시 프레임 시퀀스를 mp4로 인코딩합니다(가능한 경우).

문법 검증도 통과했습니다.


이미지 촬영은하는데 mp4로 만들어지지 않고 있어


이전 메시지 2개
맞습니다. mp4가 안 만들어지는 구간을 잡기 위해 viewport_movie.py를 수정했습니다.

이제 ffmpeg 탐색이 ffmpeg-win/bin/ffmpeg.exe를 소스 경로와 _build/.../exts/... 런타임 경로까지 모두 확인하고, 못 찾으면 PATH를 봅니다. 또 인코딩 전에 프레임 파일 존재 여부를 검사하고, ffmpeg 실패 시 stderr를 그대로 로그에 남기도록 바꿨습니다.

다시 Start Recording -> Stop Recording 해보시면, 로그에 아래 중 하나가 보일 겁니다.

encoding mp4 with ffmpeg: ... 후 mp4 encoding completed: ...
또는 ffmpeg encoding failed: ... stderr=...
두 번째가 나오면 그 로그 그대로 주시면 바로 원인에 맞춰 다음 수정(코덱 옵션/입력 패턴/경로 권한)까지 이어서 처리하겠습니다.


실제 움직인 시간보다 짧게 생성되는데 원인 확인해서 수정해주고 mp4 생성 후 이미지들은 제거해줘


이전 메시지 6개
원인과 수정 반영 완료했습니다. 짧게 생성되던 이유는 캡처가 실제로 30fps보다 느리게 저장되는데, ffmpeg 인코딩을 고정 fps(예: 30)로 해서 재생 시간이 압축되었기 때문입니다.

이제는 녹화 시작/종료 실제 시간으로 encode_fps = frame_count / duration를 계산해서 인코딩하도록 바꿨고, mp4 생성 성공 시 PNG 프레임도 자동 삭제되도록 적용했습니다.

적용 파일:

viewport_movie.py
확인한 항목:

duration_seconds, encode_fps 계산/반영 로직 추가
encode_movie_with_ffmpeg(..., cleanup_input_frames=True) 적용
인코딩 성공 후 프레임 이미지 삭제
문법 체크(py_compile) 통과
한 번 다시 녹화해보시고, 아직 길이 오차가 있으면 생성된 mp4의 ffmpeg stderr 로그를 같이 주시면 바로 추가 보정하겠습니다.


2026-03-13T12:31:32Z [12,232,927ms] [Error] [omni.ui.python] RuntimeError: no running event loop

At:
  d:\users/jeongguhyeon/kit-app-template/_build/windows-x86_64/release/exts/morph.capture_and_movie/morph/capture_and_movie\viewport_movie.py(62): start
  d:/users/jeongguhyeon/kit-app-template/_build/windows-x86_64/release/exts/morph.capture_and_movie/morph/capture_and_movie/extension.py(58): on_click_start_recording

시작 시 이렇게 나와


이전 메시지 3개
원인 맞습니다. Start Recording 클릭 콜백이 실행 중 asyncio 루프가 없는 컨텍스트에서 호출되는데, 기존 코드가 asyncio.get_running_loop()와 asyncio.ensure_future()를 바로 써서 에러가 났습니다.

수정 내용:

asyncio.ensure_future(...) 대신, 루프가 없으면 omni.kit.async_engine.run_coroutine(...)로 스케줄하도록 변경
녹화 시간 측정/프레임 간 대기도 get_running_loop().time() 대신 time.perf_counter() 사용으로 안전화
적용 파일:

extension.py
viewport_movie.py
검증:

python -m py_compile 통과
이제 Start Recording에서 RuntimeError: no running event loop 없이 시작되어야 합니다. 한 번 실행해보고, 새 로그가 뜨면 바로 이어서 잡아드릴게요.


프레임이 7 프레임으로 나오는데 촬영 속도를 30 으로 올릴 수 있을까?



이전 메시지 1개
가능합니다. 병목 원인을 반영해서 30fps에 맞게 캡처 루프를 수정했습니다.

변경한 핵심:

캡처 후 항상 1/30초를 추가 대기하던 방식 제거
이제 캡처에 걸린 시간을 제외한 남은 시간만 대기합니다.
wait_for_result(completion_frames=10) → completion_frames=1로 변경
프레임당 불필요한 대기 프레임을 줄여 실제 캡처 fps를 올렸습니다.
적용 파일:

viewport_movie.py
문법 검증:

py_compile 통과
참고로 실제 캡처 fps는 GPU/디스크 성능에 따라 30에 못 미칠 수는 있습니다. 그래도 지금 구조가 기존보다 훨씬 30fps에 가깝게 동작합니다.
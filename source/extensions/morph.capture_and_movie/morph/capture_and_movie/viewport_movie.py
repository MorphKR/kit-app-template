"""
Viewport 동영상 캡처/인코딩 유틸.

주요 기능
- **프레임 시퀀스 캡처**: 활성 뷰포트를 지정 시간/프레임 수 동안 PNG 시퀀스로 저장
- **실시간 녹화기(Recorder)**: 뷰포트에서 실시간으로 프레임을 계속 캡처해 디렉터리에 쌓음
- **MP4 인코딩**: ffmpeg(동봉된 ffmpeg-win 또는 시스템 ffmpeg)를 사용해 PNG 시퀀스를 mp4로 변환

설계 포인트
- Kit 환경마다 `capture_viewport_to_file()` 의 완료 방식이 다를 수 있어, `wait_for_result()` 유무를 검사해
  가능한 한 정확하게 캡처 완료를 기다린다.
- UI 콜백/비동기 컨텍스트 유무에 상관없이 코루틴을 실행할 수 있도록 `_schedule_coroutine()` 헬퍼를 둔다.
"""

import asyncio
import contextlib
import datetime
import glob
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

import carb
import omni.kit.app
import omni.kit.async_engine
import omni.kit.viewport.utility as vp_utils


@dataclass
class MovieCaptureResult:
    """동영상 캡처 결과 메타데이터."""
    frame_dir: str
    frame_paths: list[str]
    mp4_path: str | None = None
    duration_seconds: float | None = None
    encode_fps: float | None = None


class ViewportMovieRecorder:
    """
    활성 뷰포트의 프레임을 **실시간으로 연속 캡처**하는 Recorder.

    - `start()` 를 호출하면 내부에서 코루틴 루프를 돌면서 지정 fps 에 가깝게 프레임을 PNG로 저장
    - `stop_async()` 를 호출하면 루프를 정지하고, 캡처된 프레임과(선택적으로) mp4 인코딩 결과를 반환
    """
    def __init__(
        self,
        *,
        fps: int = 30,
        output_dir: str | None = None,
        file_prefix: str = "movie",
    ):
        self.fps = max(1, int(fps))
        self.output_dir = output_dir
        self.file_prefix = file_prefix
        self.frame_dir: str | None = None
        self.frame_paths: list[str] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._viewport_api = None
        self._record_start_time: float | None = None
        self._record_stop_time: float | None = None

    @property
    def is_recording(self) -> bool:
        """현재 녹화 진행 중인지 여부."""
        return self._running

    def start(self) -> bool:
        """
        녹화를 시작한다.
        - 활성 viewport 를 찾아서 `_record_loop()` 코루틴을 스케줄하고, 프레임 디렉터리를 준비한다.
        - 이미 녹화 중이면 False.
        """
        if self._running:
            return False

        viewport_api = _get_active_viewport_api()
        if not viewport_api:
            carb.log_warn("[capture_and_movie] failed to get active viewport")
            return False

        output_dir = self.output_dir or _default_movie_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.frame_dir = os.path.join(output_dir, f"{self.file_prefix}_{timestamp}")
        os.makedirs(self.frame_dir, exist_ok=True)
        self.frame_paths = []
        self._viewport_api = viewport_api
        self._record_start_time = time.perf_counter()
        self._record_stop_time = None
        self._running = True
        self._task = _schedule_coroutine(self._record_loop())
        carb.log_info(f"[capture_and_movie] movie recording started: {self.frame_dir}")
        return True

    async def stop_async(self, *, encode_mp4: bool = True) -> MovieCaptureResult | None:
        """
        녹화를 중지하고 결과를 반환한다.

        - 내부 `_record_loop()` 가 끝날 때까지 기다린 후, 전체 녹화 시간을 바탕으로 실제 fps 를 계산
        - `encode_mp4=True` 인 경우 ffmpeg 로 mp4를 인코딩하고, 입력 프레임을 정리할 수 있다.
        """
        if not self._running and not self._task:
            return None

        self._record_stop_time = time.perf_counter()
        self._running = False
        if self._task:
            await self._task
        self._task = None

        if not self.frame_dir:
            return None

        duration_seconds = self._compute_recorded_seconds()
        encode_fps = self._compute_effective_encode_fps(
            frame_count=len(self.frame_paths),
            duration_seconds=duration_seconds,
            fallback_fps=self.fps,
        )

        result = MovieCaptureResult(
            frame_dir=self.frame_dir,
            frame_paths=list(self.frame_paths),
            duration_seconds=duration_seconds,
            encode_fps=encode_fps,
        )
        if encode_mp4:
            result.mp4_path = encode_movie_with_ffmpeg(
                frame_dir=result.frame_dir,
                fps=encode_fps,
                file_prefix=self.file_prefix,
                cleanup_input_frames=True,
            )
        carb.log_info(f"[capture_and_movie] movie recording stopped: {result.frame_dir}")
        return result

    async def _record_loop(self):
        """
        Recorder 내부에서 실행되는 메인 루프.

        - 한 프레임을 캡처하고
        - 목표 fps 에 맞도록 남은 시간 동안 `app.next_update_async()` 를 반복 호출하여 cadence 를 유지한다.
        """
        if not self._viewport_api or not self.frame_dir:
            self._running = False
            return

        app = omni.kit.app.get_app()
        frame_index = 0
        while self._running:
            frame_start = time.perf_counter()
            frame_path = os.path.join(self.frame_dir, f"{self.file_prefix}_{frame_index:05d}.png")
            ok = await _capture_frame_to_file_async(self._viewport_api, frame_path)
            if not ok:
                self._running = False
                break
            self.frame_paths.append(frame_path)
            frame_index += 1

            target_dt = 1.0 / float(self.fps)
            elapsed = time.perf_counter() - frame_start
            end_time = time.perf_counter() + max(0.0, target_dt - elapsed)
            while self._running and time.perf_counter() < end_time:
                await app.next_update_async()

    def _compute_recorded_seconds(self) -> float:
        """녹화 시작/종료 시각을 바탕으로 실제 녹화된 시간(초)을 계산."""
        start = self._record_start_time
        stop = self._record_stop_time or time.perf_counter()
        if start is None:
            return 0.0
        return max(0.0, float(stop - start))

    @staticmethod
    def _compute_effective_encode_fps(*, frame_count: int, duration_seconds: float, fallback_fps: int) -> float:
        """
        실제 녹화된 시간과 프레임 수를 바탕으로 **인코딩에 사용할 fps** 를 계산.
        - 프레임 수/시간이 비정상적이면 fallback_fps 사용
        - 인코더에 지나치게 크거나 작은 fps 가 들어가지 않도록 [1, 240] 범위로 clamp
        """
        if frame_count < 2 or duration_seconds <= 0:
            return float(fallback_fps)
        fps = float(frame_count) / float(duration_seconds)
        # Keep encoder fps in a sane range.
        return max(1.0, min(240.0, fps))


def _get_active_viewport_api():
    """
    활성 viewport API 를 최대한 방어적으로 얻는다.
    - `get_active_viewport()` 또는 `get_active_viewport_window().viewport_api` 를 사용.
    """
    try:
        if hasattr(vp_utils, "get_active_viewport"):
            vp = vp_utils.get_active_viewport()
            if vp:
                return vp
    except Exception:
        pass

    try:
        if hasattr(vp_utils, "get_active_viewport_window"):
            win = vp_utils.get_active_viewport_window()
            if not win:
                return None
            vp = getattr(win, "viewport_api", None)
            if vp is None and hasattr(win, "get_viewport_api"):
                vp = win.get_viewport_api()
            return vp
    except Exception:
        pass

    return None


def _default_movie_dir() -> str:
    """동영상/프레임 기본 출력 디렉터리(`./captures/movies`)를 보장하고 반환."""
    folder = os.path.join(os.getcwd(), "captures", "movies")
    os.makedirs(folder, exist_ok=True)
    return folder


def _schedule_coroutine(coro):
    """
    코루틴을 적절한 러너에 스케줄한다.
    - 이미 asyncio 이벤트 루프가 돌고 있으면 `loop.create_task`
    - 아닌 경우 Kit 의 `omni.kit.async_engine.run_coroutine` 사용
    """
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)
    except RuntimeError:
        # UI callbacks can run without an active asyncio loop; use Kit async engine.
        return omni.kit.async_engine.run_coroutine(coro)


def _resolve_ffmpeg_exe() -> str | None:
    """
    ffmpeg 실행 파일 경로를 탐색한다.

    우선순위
    1. 익스텐션 루트/빌드 아티팩트에 동봉된 `ffmpeg-win/bin/ffmpeg.exe`
    2. 워크스페이스 내 `_build/**/exts/morph.capture_and_movie/ffmpeg-win/...`
    3. 시스템 PATH 상의 `ffmpeg` (`shutil.which`)
    """
    here = os.path.abspath(__file__)
    ext_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))

    candidates = [
        os.path.join(ext_root, "ffmpeg-win", "bin", "ffmpeg.exe"),
        os.path.join(os.getcwd(), "source", "extensions", "morph.capture_and_movie", "ffmpeg-win", "bin", "ffmpeg.exe"),
        os.path.join(
            os.getcwd(),
            "_build",
            "windows-x86_64",
            "release",
            "exts",
            "morph.capture_and_movie",
            "ffmpeg-win",
            "bin",
            "ffmpeg.exe",
        ),
    ]

    # In some layouts, build folder names vary slightly; scan once as fallback.
    candidates.extend(
        glob.glob(
            os.path.join(
                os.getcwd(),
                "_build",
                "*",
                "release",
                "exts",
                "morph.capture_and_movie",
                "ffmpeg-win",
                "bin",
                "ffmpeg.exe",
            )
        )
    )

    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand

    return shutil.which("ffmpeg")


async def _capture_frame_to_file_async(viewport_api, file_path: str) -> bool:
    """
    주어진 viewport 에서 단일 프레임을 파일로 캡처하고, 완료될 때까지 비동기로 대기.
    - Kit 버전에 따라 `wait_for_result()` 가 있을 수도/없을 수도 있어 분기 처리.
    """
    try:
        cap = vp_utils.capture_viewport_to_file(viewport_api, file_path, is_hdr=False)
        if hasattr(cap, "wait_for_result"):
            # Reduce extra wait to improve real capture fps.
            await cap.wait_for_result(completion_frames=1)
        else:
            await omni.kit.app.get_app().next_update_async()
        return True
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] frame capture failed: {e!r}")
        return False


async def capture_active_viewport_movie_frames_async(
    *,
    duration_seconds: float = 3.0,
    fps: int = 30,
    output_dir: str | None = None,
    file_prefix: str = "movie",
) -> MovieCaptureResult | None:
    """
    활성 뷰포트를 지정 시간 동안 프레임 시퀀스로 캡처한다.

    - duration_seconds, fps 로 총 프레임 수를 계산
    - 각 프레임을 PNG로 저장하면서, fps 에 근접하도록 업데이트 루프를 돌린다.
    - mp4 인코딩은 하지 않고, 프레임 디렉터리/경로만 `MovieCaptureResult` 로 반환한다.
    """
    viewport_api = _get_active_viewport_api()
    if not viewport_api:
        carb.log_warn("[capture_and_movie] failed to get active viewport")
        return None

    if fps <= 0 or duration_seconds <= 0:
        carb.log_warn("[capture_and_movie] fps and duration_seconds must be > 0")
        return None

    if output_dir is None:
        output_dir = _default_movie_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    frame_dir = os.path.join(output_dir, f"{file_prefix}_{timestamp}")
    os.makedirs(frame_dir, exist_ok=True)

    frame_count = max(1, int(round(duration_seconds * fps)))
    app = omni.kit.app.get_app()
    frame_paths: list[str] = []

    carb.log_info(f"[capture_and_movie] movie frame capture start: {frame_count} frames @ {fps} fps")

    for i in range(frame_count):
        frame_start = time.perf_counter()
        frame_path = os.path.join(frame_dir, f"{file_prefix}_{i:05d}.png")
        ok = await _capture_frame_to_file_async(viewport_api, frame_path)
        if not ok:
            return None
        frame_paths.append(frame_path)

        # Keep update cadence close to requested fps.
        # Kit is frame-based, so we sleep small dt and let updates progress.
        target_dt = 1.0 / float(fps)
        elapsed = time.perf_counter() - frame_start
        end_time = time.perf_counter() + max(0.0, target_dt - elapsed)
        while time.perf_counter() < end_time:
            await app.next_update_async()

    carb.log_info(f"[capture_and_movie] movie frame capture completed: {frame_dir}")
    return MovieCaptureResult(frame_dir=frame_dir, frame_paths=frame_paths)


def encode_movie_with_ffmpeg(
    *,
    frame_dir: str,
    fps: float = 30.0,
    file_prefix: str = "movie",
    output_mp4_path: str | None = None,
    cleanup_input_frames: bool = False,
) -> str | None:
    """
    PNG 프레임 시퀀스를 ffmpeg 로 mp4 로 인코딩한다.

    - ffmpeg 경로를 `_resolve_ffmpeg_exe()` 로 찾고, 실패 시 None
    - 입력 패턴: `<frame_dir>/<file_prefix>_%05d.png`
    - 성공 시 mp4 경로를 반환하고, `cleanup_input_frames=True` 이면 입력 PNG 를 삭제한다.
    """
    ffmpeg = _resolve_ffmpeg_exe()
    if not ffmpeg:
        carb.log_warn("[capture_and_movie] ffmpeg not found (including ffmpeg-win); skip mp4 encoding")
        return None

    if output_mp4_path is None:
        output_mp4_path = os.path.join(frame_dir, f"{file_prefix}.mp4")

    # Ensure there are frames to encode.
    frames = sorted(glob.glob(os.path.join(frame_dir, f"{file_prefix}_*.png")))
    if not frames:
        carb.log_warn(f"[capture_and_movie] no frames found for encoding in: {frame_dir}")
        return None

    input_pattern = os.path.join(frame_dir, f"{file_prefix}_%05d.png")
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        f"{float(fps):.6f}",
        "-start_number",
        "0",
        "-i",
        input_pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        output_mp4_path,
    ]
    try:
        carb.log_info(f"[capture_and_movie] encoding mp4 with ffmpeg: {ffmpeg}")
        proc = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.stderr:
            carb.log_info(f"[capture_and_movie] ffmpeg stderr:\n{proc.stderr}")
        carb.log_info(f"[capture_and_movie] mp4 encoding completed: {output_mp4_path}")
        if cleanup_input_frames:
            for f in frames:
                with contextlib.suppress(Exception):
                    os.remove(f)
        return output_mp4_path
    except subprocess.CalledProcessError as e:
        carb.log_error(
            "[capture_and_movie] ffmpeg encoding failed: "
            f"returncode={e.returncode}, stderr={getattr(e, 'stderr', '')}"
        )
        return None
    except Exception as e:  # noqa: BLE001
        carb.log_error(f"[capture_and_movie] ffmpeg encoding failed: {e!r}")
        return None


async def capture_active_viewport_movie_async(
    *,
    duration_seconds: float = 3.0,
    fps: int = 30,
    output_dir: str | None = None,
    file_prefix: str = "movie",
    encode_mp4: bool = True,
) -> MovieCaptureResult | None:
    """
    활성 뷰포트를 시퀀스로 캡처한 뒤, 선택적으로 mp4 까지 인코딩하는 헬퍼.

    - 내부적으로 `capture_active_viewport_movie_frames_async` + `encode_movie_with_ffmpeg` 를 조합해 호출.
    """
    result = await capture_active_viewport_movie_frames_async(
        duration_seconds=duration_seconds,
        fps=fps,
        output_dir=output_dir,
        file_prefix=file_prefix,
    )
    if not result:
        return None

    if encode_mp4:
        mp4 = encode_movie_with_ffmpeg(
            frame_dir=result.frame_dir,
            fps=fps,
            file_prefix=file_prefix,
            cleanup_input_frames=True,
        )
        result.mp4_path = mp4

    return result

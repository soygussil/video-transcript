"""Extracción de audio a WAV PCM 16 kHz mono (artefacto controlado y reanudable por bloques)."""

from __future__ import annotations

import os
import subprocess
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from analizador_video.domain.errors import FfmpegMissingError, OperationCancelled
from analizador_video.infrastructure.system import NO_WINDOW, find_ffmpeg

SAMPLE_RATE = 16000


class NoAudioStreamError(Exception):
    """El video no contiene pista de audio."""


def _extract_with_av(video: Path, destination: Path, is_cancelled: Callable[[], bool]) -> Path:
    """Respaldo sin FFmpeg instalado: PyAV incluye sus propias librerías de decodificación."""
    import av

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial.wav")
    try:
        with av.open(str(video)) as container:
            if not container.streams.audio:
                raise NoAudioStreamError()
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            with wave.open(str(temporary), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(SAMPLE_RATE)
                for frame in container.decode(audio=0):
                    if is_cancelled():
                        raise OperationCancelled()
                    for converted in resampler.resample(frame):
                        out.writeframes(converted.to_ndarray().tobytes())
                for converted in resampler.resample(None):
                    out.writeframes(converted.to_ndarray().tobytes())
    except (OperationCancelled, NoAudioStreamError):
        temporary.unlink(missing_ok=True)
        raise
    except (av.error.FFmpegError, OSError, ValueError) as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("No se pudo extraer el audio del video.") from error
    os.replace(temporary, destination)
    return destination


def extract_audio(video: Path, destination: Path, is_cancelled: Callable[[], bool]) -> Path:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        try:
            import av  # noqa: F401
        except ImportError:
            pass
        else:
            return _extract_with_av(video, destination, is_cancelled)
        raise FfmpegMissingError(
            "No se encontró FFmpeg",
            "La transcripción automática necesita este componente para extraer el audio",
            "Instálalo siguiendo la guía de Diagnóstico o continúa usando una transcripción VTT o SRT",
            saved=True,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial.wav")
    command = [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(temporary),
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        while process.poll() is None:
            if is_cancelled():
                process.terminate()
                process.wait(timeout=10)
                raise OperationCancelled()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
        stderr = (process.stderr.read() if process.stderr else b"").decode("utf-8", errors="replace")
    finally:
        if process.stderr:
            process.stderr.close()
        if process.poll() is None:
            process.kill()
    if process.returncode != 0:
        if temporary.exists():
            temporary.unlink()
        lowered = stderr.lower()
        if "does not contain any stream" in lowered or "matches no streams" in lowered:
            raise NoAudioStreamError()
        raise RuntimeError("FFmpeg no pudo extraer el audio del video.")
    os.replace(temporary, destination)
    return destination


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def read_wav_block(path: Path, start_seconds: float, duration_seconds: float) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("El audio extraído no tiene el formato esperado (16 kHz, mono, 16 bits).")
        handle.setpos(min(int(start_seconds * SAMPLE_RATE), handle.getnframes()))
        frames = handle.readframes(int(duration_seconds * SAMPLE_RATE))
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0

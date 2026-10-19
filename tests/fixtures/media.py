"""Medios sintéticos generados en cada prueba (sin datos sensibles ni licencias de terceros)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SCENE_COLORS = ((200, 60, 40), (60, 160, 60), (40, 60, 200), (180, 180, 40))


def make_video(
    path: Path, scenes: int = 3, seconds_per_scene: int = 4, fps: int = 10, size: tuple[int, int] = (320, 240)
) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for scene in range(scenes):
        frame = np.full((size[1], size[0], 3), SCENE_COLORS[scene % len(SCENE_COLORS)], np.uint8)
        cv2.putText(frame, f"Pantalla {scene + 1}", (20, size[1] // 2), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        for _ in range(seconds_per_scene * fps):
            writer.write(frame)
    writer.release()
    return path


def add_silent_audio(video: Path, output: Path) -> Path:
    """Copia el video y le agrega un tono de 440 Hz (PyAV: no requiere FFmpeg instalado)."""
    import av

    rate = 16000
    with av.open(str(video)) as src, av.open(str(output), "w") as dst:
        video_in = src.streams.video[0]
        video_out = dst.add_stream_from_template(video_in)
        audio_out = dst.add_stream("aac", rate=rate, layout="mono")
        seconds = float(video_in.duration * video_in.time_base)
        for packet in src.demux(video_in):
            if packet.dts is None:
                continue
            packet.stream = video_out
            dst.mux(packet)
        samples = np.sin(2 * np.pi * 440 * np.arange(int(seconds * rate)) / rate).astype(np.float32) * 0.3
        for offset in range(0, len(samples) - 1023, 1024):
            frame = av.AudioFrame.from_ndarray(samples[offset : offset + 1024][None, :], format="fltp", layout="mono")
            frame.sample_rate = rate
            frame.pts = offset
            dst.mux(audio_out.encode(frame))
        dst.mux(audio_out.encode(None))
    return output


VTT_TEXT = (
    "WEBVTT\n\n"
    "00:00:00.500 --> 00:00:03.000\n<v Ana López>Bienvenidos a la demostración</v>\n\n"
    "00:00:04.500 --> 00:00:06.000\n<v Luis>Esta es la segunda pantalla</v>\n\n"
    "00:00:09.000 --> 00:00:11.500\n<v Ana López>Cierre de la sesión</v>\n"
)


def write_vtt(path: Path, text: str = VTT_TEXT, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path

"""Fixtures compartidas. Todo se aísla en directorios temporales; no se descargan modelos."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.fixtures.media import make_video, write_vtt


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "app_home"
    monkeypatch.setenv("ANALIZADOR_VIDEO_HOME", str(home))
    return home


@pytest.fixture
def video_factory(tmp_path: Path) -> Callable[..., Path]:
    def factory(name: str = "demo.mp4", **kwargs: object) -> Path:
        return make_video(tmp_path / name, **kwargs)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def sample_video(video_factory: Callable[..., Path]) -> Path:
    return video_factory()


@pytest.fixture
def sample_vtt(tmp_path: Path) -> Path:
    return write_vtt(tmp_path / "demo.vtt")


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    root = tmp_path / "Proyectos"
    root.mkdir()
    return root

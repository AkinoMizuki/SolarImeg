from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Any

import requests
from PIL import Image

DEFAULT_CLOUD_SOURCE_URL = (
    "https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png"
)
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 1024


def _download_image(url: str, timeout: int = 60) -> Image.Image:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater"},
    )
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def _normalize_cloud(image: Image.Image, width: int, height: int) -> Image.Image:
    """Normalize the source to a 2:1 RGBA equirectangular texture."""
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def update_cloud_textures(
    output_dir: Path,
    *,
    source_url: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """
    Update cloud_current.png while preserving the previously published current
    image as cloud_previous.png.

    update_weather.py seeds output_dir with the currently deployed files first,
    so this function can update atomically without requiring repository history.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    source_url = source_url or os.environ.get(
        "CLOUD_SOURCE_URL", DEFAULT_CLOUD_SOURCE_URL
    )

    current_path = output_dir / "cloud_current.png"
    previous_path = output_dir / "cloud_previous.png"

    had_previous_current = current_path.exists()
    if had_previous_current:
        shutil.copy2(current_path, previous_path)

    cloud = _normalize_cloud(_download_image(source_url), width, height)
    tmp_path = output_dir / "cloud_current.tmp.png"
    cloud.save(tmp_path, format="PNG", optimize=True)
    tmp_path.replace(current_path)

    # First deployment: use the same image for both endpoints. On the next run,
    # cloud_previous becomes the formerly published cloud_current automatically.
    if not previous_path.exists():
        shutil.copy2(current_path, previous_path)

    return {
        "cloudSourceUrl": source_url,
        "cloudWidth": width,
        "cloudHeight": height,
        "cloudPreviousFromPublishedCurrent": had_previous_current,
    }

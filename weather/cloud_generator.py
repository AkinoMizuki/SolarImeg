from __future__ import annotations

import hashlib
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

# v2 attempted to re-extract clouds from an image that was already a purpose-built
# transparent cloud texture. v3 intentionally preserves the upstream RGBA data.
CLOUD_PROCESSING_VERSION = 3
CLOUD_EXTRACTION_METHOD = "upstream-clouds-alpha-rgba"


def _download_image(url: str, timeout: int = 60) -> Image.Image:
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater",
        },
    )
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def _normalize_cloud(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    Normalize the upstream transparent cloud map to the texture size used by
    Unity. live-cloud-maps already generates clouds-alpha.png as a dedicated
    cloud texture: cloud intensity is stored in RGB and cloud opacity in A.
    Do not attempt to derive another mask from it here.
    """
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def _pixel_hash(image: Image.Image) -> str:
    """Stable hash of RGBA pixels, independent of PNG metadata/compression."""
    rgba = image.convert("RGBA")
    digest = hashlib.sha256()
    digest.update(f"{rgba.width}x{rgba.height}:RGBA".encode("ascii"))
    digest.update(rgba.tobytes())
    return digest.hexdigest()


def _existing_pixel_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            return _pixel_hash(image)
    except Exception as exc:  # noqa: BLE001
        print(f"Ignoring unreadable existing cloud texture {path}: {exc}")
        return None


def _save_png_atomic(image: Image.Image, path: Path) -> None:
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    image.save(tmp_path, format="PNG", optimize=True)
    tmp_path.replace(path)


def update_cloud_textures(
    output_dir: Path,
    *,
    source_url: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    force_history_reset: bool = False,
) -> dict[str, Any]:
    """
    Update cloud_current.png while keeping a previous observation for shader
    interpolation.

    update_weather.py first seeds output_dir from the currently deployed Pages
    files. If the upstream image has not changed, files and timestamps are left
    untouched. When the source changes, old current becomes previous.

    A processing-version change resets previous/current together so Unity never
    cross-fades between incompatible texture encodings.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    source_url = source_url or os.environ.get(
        "CLOUD_SOURCE_URL", DEFAULT_CLOUD_SOURCE_URL
    )

    current_path = output_dir / "cloud_current.png"
    previous_path = output_dir / "cloud_previous.png"

    had_previous_current = current_path.exists()
    old_hash = _existing_pixel_hash(current_path)

    cloud = _normalize_cloud(_download_image(source_url), width, height)
    new_hash = _pixel_hash(cloud)

    changed = old_hash != new_hash
    history_reset = force_history_reset or not had_previous_current

    if history_reset:
        _save_png_atomic(cloud, current_path)
        shutil.copy2(current_path, previous_path)
    elif changed:
        shutil.copy2(current_path, previous_path)
        _save_png_atomic(cloud, current_path)
    else:
        # Upstream live-cloud-maps normally changes every three hours while this
        # workflow runs hourly. Preserve both endpoints byte-for-byte between
        # actual source updates.
        if not previous_path.exists():
            shutil.copy2(current_path, previous_path)

    return {
        "cloudSourceUrl": source_url,
        "cloudWidth": width,
        "cloudHeight": height,
        "cloudProcessingVersion": CLOUD_PROCESSING_VERSION,
        "cloudExtractionMethod": CLOUD_EXTRACTION_METHOD,
        "cloudImageChanged": changed,
        "cloudHistoryReset": history_reset,
        "cloudImageHash": new_hash,
        "cloudPreviousFromPublishedCurrent": (
            had_previous_current and changed and not history_reset
        ),
        "cloudEncoding": {
            "RGB": "upstream cloud shading/intensity",
            "A": "upstream cloud opacity/transparency",
        },
    }

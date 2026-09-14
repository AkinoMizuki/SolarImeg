from __future__ import annotations

import hashlib
import io
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image, ImageFilter

DEFAULT_CLOUD_SOURCE_URL = (
    "https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png"
)
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 1024
CLOUD_PROCESSING_VERSION = 2
CLOUD_EXTRACTION_METHOD = "local-contrast-alpha"


def _download_image(url: str, timeout: int = 60) -> Image.Image:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater"},
    )
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def _resize_source(image: Image.Image, width: int, height: int) -> Image.Image:
    """Normalize the source to a 2:1 RGBA equirectangular texture."""
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def _extract_cloud_layer(image: Image.Image) -> Image.Image:
    """
    Build a CloudSphere-only RGBA texture.

    The current fallback source contains slowly varying surface/illumination
    structure in addition to clouds. Remove the low-frequency background and
    retain local bright structures as cloud opacity. RGB is intentionally white;
    lighting/colour is applied later by the Unity shader.
    """
    signal_image = image.getchannel("A")

    # Build a low-frequency estimate cheaply at 1/8 resolution. The source is
    # equirectangular, so preserve the 2:1 aspect ratio through the whole pass.
    low_width = max(64, signal_image.width // 8)
    low_height = max(32, signal_image.height // 8)
    background = (
        signal_image.resize((low_width, low_height), Image.Resampling.BILINEAR)
        .filter(ImageFilter.GaussianBlur(radius=3.0))
        .resize(signal_image.size, Image.Resampling.BILINEAR)
    )

    signal = np.asarray(signal_image, dtype=np.float32)
    low_frequency = np.asarray(background, dtype=np.float32)

    # Positive local contrast removes most land/ocean brightness while keeping
    # cloud bands, fronts and convective structures.
    detail = np.clip(signal - low_frequency, 0.0, None)
    detail_alpha = np.clip((detail - 6.0) * 9.0, 0.0, 255.0)

    # Preserve some very broad/thick cloud that local-contrast subtraction can
    # attenuate. Keep this intentionally weak so bright terrain does not become
    # an opaque cloud layer.
    bright_alpha = (
        np.clip((signal - 205.0) * 3.0, 0.0, 255.0) * 0.30
    )

    alpha = np.maximum(detail_alpha, bright_alpha).astype(np.uint8)

    rgba = np.empty((signal_image.height, signal_image.width, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 1] = 255
    rgba[..., 2] = 255
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


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
    Update CloudSphere textures.

    The published cloud_current.png is seeded into output_dir by
    update_weather.py. If the newly processed image is identical, all cloud
    files are left untouched so interpolation timestamps can also remain
    unchanged. When the image changes, old current becomes previous.

    force_history_reset is used when the cloud processing algorithm changes; in
    that case previous/current are both replaced by the new representation so
    Unity never cross-fades between incompatible encodings.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    source_url = source_url or os.environ.get(
        "CLOUD_SOURCE_URL", DEFAULT_CLOUD_SOURCE_URL
    )

    current_path = output_dir / "cloud_current.png"
    previous_path = output_dir / "cloud_previous.png"

    had_previous_current = current_path.exists()
    old_hash = _existing_pixel_hash(current_path)

    source = _resize_source(_download_image(source_url), width, height)
    cloud = _extract_cloud_layer(source)
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
        # Preserve both files byte-for-byte when the source visual has not
        # changed. This is important because the upstream image updates only
        # every few hours while this workflow runs hourly.
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
        "cloudPreviousFromPublishedCurrent": had_previous_current and changed and not history_reset,
    }

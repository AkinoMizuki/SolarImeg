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
    "https://clouds.matteason.co.uk/images/2048x1024/clouds-alpha.png"
)
DEFAULT_SPECULAR_SOURCE_URL = (
    "https://clouds.matteason.co.uk/images/2048x1024/specular.jpg"
)
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 1024

# v4 keeps the upstream transparent cloud texture unchanged and adds a paired
# specular history. Both files advance together so Unity can interpolate cloud
# opacity and cloud-masked ocean reflections with the same blend value.
CLOUD_PROCESSING_VERSION = 4
CLOUD_EXTRACTION_METHOD = "upstream-clouds-alpha-rgba+paired-specular"


def _download_image(url: str, mode: str, timeout: int = 60) -> Image.Image:
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater",
        },
    )
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert(mode)


def _normalize_image(
    image: Image.Image,
    width: int,
    height: int,
    mode: str,
) -> Image.Image:
    image = image.convert(mode)
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def _pixel_hash(image: Image.Image, mode: str) -> str:
    """Stable hash of decoded pixels, independent of PNG/JPEG metadata."""
    normalized = image.convert(mode)
    digest = hashlib.sha256()
    digest.update(
        f"{normalized.width}x{normalized.height}:{mode}".encode("ascii")
    )
    digest.update(normalized.tobytes())
    return digest.hexdigest()


def _existing_pixel_hash(path: Path, mode: str) -> str | None:
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            return _pixel_hash(image, mode)
    except Exception as exc:  # noqa: BLE001
        print(f"Ignoring unreadable weather texture {path}: {exc}")
        return None


def _save_png_atomic(image: Image.Image, path: Path) -> None:
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    image.save(tmp_path, format="PNG", optimize=True)
    tmp_path.replace(path)


def _save_jpeg_atomic(image: Image.Image, path: Path) -> None:
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    image.convert("RGB").save(
        tmp_path,
        format="JPEG",
        quality=90,
        optimize=True,
        subsampling=0,
    )
    tmp_path.replace(path)


def _download_stable_pair(
    cloud_url: str,
    specular_url: str,
    width: int,
    height: int,
    attempts: int = 3,
) -> tuple[Image.Image, Image.Image]:
    """
    Download clouds-alpha and specular as one logical observation.

    live-cloud-maps updates the two files together, but HTTP requests are not
    atomic. Read the cloud image both before and after the specular download. If
    those cloud pixels differ, an upstream update happened during our request;
    retry so the final pair comes from a stable generation.
    """
    for attempt in range(1, attempts + 1):
        cloud_before = _normalize_image(
            _download_image(cloud_url, "RGBA"), width, height, "RGBA"
        )
        specular = _normalize_image(
            _download_image(specular_url, "RGB"), width, height, "RGB"
        )
        cloud_after = _normalize_image(
            _download_image(cloud_url, "RGBA"), width, height, "RGBA"
        )

        before_hash = _pixel_hash(cloud_before, "RGBA")
        after_hash = _pixel_hash(cloud_after, "RGBA")
        if before_hash == after_hash:
            return cloud_after, specular

        print(
            "live-cloud-maps changed while downloading cloud/specular pair; "
            f"retrying ({attempt}/{attempts})"
        )

    raise RuntimeError(
        "Could not obtain a stable clouds-alpha/specular pair after retries"
    )


def update_cloud_textures(
    output_dir: Path,
    *,
    source_url: str | None = None,
    specular_source_url: str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    force_history_reset: bool = False,
) -> dict[str, Any]:
    """
    Update cloud and cloud-masked specular textures as one paired observation.

    update_weather.py first seeds output_dir from the currently deployed Pages
    files. live-cloud-maps generates cloud/specular together, so the lossless
    cloud texture is the generation marker. If it has not changed, all four
    history files and their timestamps remain untouched. When it changes, both
    current files advance together and both old current files become previous.

    A processing-version change resets previous/current together so Unity never
    cross-fades between incompatible output layouts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    source_url = source_url or os.environ.get(
        "CLOUD_SOURCE_URL", DEFAULT_CLOUD_SOURCE_URL
    )
    specular_source_url = specular_source_url or os.environ.get(
        "SPECULAR_SOURCE_URL", DEFAULT_SPECULAR_SOURCE_URL
    )

    cloud_current_path = output_dir / "cloud_current.png"
    cloud_previous_path = output_dir / "cloud_previous.png"
    specular_current_path = output_dir / "specular_current.jpg"
    specular_previous_path = output_dir / "specular_previous.jpg"

    had_complete_current = (
        cloud_current_path.exists() and specular_current_path.exists()
    )
    old_cloud_hash = _existing_pixel_hash(cloud_current_path, "RGBA")

    cloud, specular = _download_stable_pair(
        source_url,
        specular_source_url,
        width,
        height,
    )
    new_cloud_hash = _pixel_hash(cloud, "RGBA")
    new_specular_source_hash = _pixel_hash(specular, "RGB")

    # specular_current.jpg is intentionally JPEG, so decoding our re-encoded
    # published file will not be pixel-identical to the upstream JPEG even when
    # the source has not changed. Use the lossless cloud PNG as the generation
    # marker and advance Cloud/Specular strictly as one pair.
    changed = old_cloud_hash != new_cloud_hash
    history_reset = force_history_reset or not had_complete_current

    if history_reset:
        _save_png_atomic(cloud, cloud_current_path)
        _save_jpeg_atomic(specular, specular_current_path)
        shutil.copy2(cloud_current_path, cloud_previous_path)
        shutil.copy2(specular_current_path, specular_previous_path)
    elif changed:
        shutil.copy2(cloud_current_path, cloud_previous_path)
        shutil.copy2(specular_current_path, specular_previous_path)
        _save_png_atomic(cloud, cloud_current_path)
        _save_jpeg_atomic(specular, specular_current_path)
    else:
        # live-cloud-maps normally changes every three hours while this workflow
        # checks hourly. Preserve both interpolation endpoints byte-for-byte.
        if not cloud_previous_path.exists():
            shutil.copy2(cloud_current_path, cloud_previous_path)
        if not specular_previous_path.exists():
            shutil.copy2(specular_current_path, specular_previous_path)

    return {
        "cloudSourceUrl": source_url,
        "specularSourceUrl": specular_source_url,
        "cloudWidth": width,
        "cloudHeight": height,
        "specularWidth": width,
        "specularHeight": height,
        "cloudProcessingVersion": CLOUD_PROCESSING_VERSION,
        "cloudExtractionMethod": CLOUD_EXTRACTION_METHOD,
        "cloudImageChanged": changed,
        "cloudHistoryReset": history_reset,
        "cloudImageHash": new_cloud_hash,
        "specularSourcePixelHash": new_specular_source_hash,
        "cloudPreviousFromPublishedCurrent": (
            had_complete_current and changed and not history_reset
        ),
        "specularPreviousFromPublishedCurrent": (
            had_complete_current and changed and not history_reset
        ),
        "cloudEncoding": {
            "RGB": "upstream cloud shading/intensity",
            "A": "upstream cloud opacity/transparency",
        },
        "specularEncoding": {
            "RGB": "upstream ocean specular map with cloud occlusion",
            "format": "JPEG",
        },
        "weatherPairing": "cloud and specular previous/current advance together",
    }

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from gmgsi_test_generator import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    _cloud_rgba_from_lw,
    _download_netcdf,
    _find_latest_two_keys,
    _print_alpha_stats,
    _read_gmgsi_plane,
    _specular_from_cloud,
    _to_equirectangular,
)

CLOUD_PROCESSING_VERSION = "gmgsi-lw-local-contrast-20260915-v1"

SPECULAR_BASE_URL = (
    "https://raw.githubusercontent.com/matteason/live-cloud-maps/main/"
    "static_images/monthly/specular-base/{month}.jpg"
)

OUTPUT_NAMES = {
    "previous": ("cloud_previous.png", "specular_previous.jpg"),
    "current": ("cloud_current.png", "specular_current.jpg"),
}


def _utc_string(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _download_monthly_specular_base(slot: datetime, timeout: int = 60) -> tuple[np.ndarray, str]:
    url = SPECULAR_BASE_URL.format(month=slot.month)
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "AkinoMizuki-SolarImeg/EarthWeather"},
    )
    response.raise_for_status()

    image = Image.open(BytesIO(response.content)).convert("L")
    image = image.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.BILINEAR)
    base = np.asarray(image, dtype=np.float32) / 255.0
    return np.clip(base, 0.0, 1.0), url


def _write_generation(
    output_dir: Path,
    prepared: dict[str, tuple[np.ndarray, np.ndarray]],
) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for label in ("previous", "current"):
            rgba, specular = prepared[label]
            cloud_name, spec_name = OUTPUT_NAMES[label]
            cloud_final = output_dir / cloud_name
            spec_final = output_dir / spec_name
            cloud_stage = output_dir / f".{cloud_name}.stage"
            spec_stage = output_dir / f".{spec_name}.stage"

            Image.fromarray(rgba, mode="RGBA").save(
                cloud_stage,
                format="PNG",
                optimize=True,
            )
            Image.fromarray(
                (np.clip(specular, 0.0, 1.0) * 255.0).astype(np.uint8),
                mode="L",
            ).convert("RGB").save(
                spec_stage,
                format="JPEG",
                quality=92,
                optimize=True,
                subsampling=0,
            )
            staged.extend(((cloud_stage, cloud_final), (spec_stage, spec_final)))

        # Commit the complete cloud/specular generation only after all four
        # files were generated successfully.
        for stage, final in staged:
            stage.replace(final)
            print(f"  {final} ({final.stat().st_size} bytes)")
    finally:
        for stage, _ in staged:
            stage.unlink(missing_ok=True)


def update_cloud_textures(
    output_dir: Path,
    force_history_reset: bool = False,
) -> dict[str, object]:
    """Generate production Earth Weather cloud/specular textures from GMGSI."""
    output_dir.mkdir(parents=True, exist_ok=True)

    history_missing = any(
        not (output_dir / name).exists()
        for pair in OUTPUT_NAMES.values()
        for name in pair
    )

    observations = _find_latest_two_keys()
    previous_slot, previous_key = observations[0]
    current_slot, current_key = observations[1]

    # Use live-cloud-maps' static monthly ocean specular base only as the
    # land/ocean reflectivity mask. Cloud occlusion itself comes from GMGSI.
    base_ocean, specular_base_url = _download_monthly_specular_base(current_slot)

    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for label, (slot, key) in zip(("previous", "current"), observations):
        print(
            f"GMGSI production {label}: {slot.isoformat()} "
            f"s3://noaa-gmgsi-pds/{key}"
        )

        nc_path = _download_netcdf(key)
        try:
            raw, raw_valid, bounds = _read_gmgsi_plane(nc_path)
        finally:
            nc_path.unlink(missing_ok=True)

        lw, repaired_mask = _to_equirectangular(raw, raw_valid, bounds)
        rgba, cloud_alpha = _cloud_rgba_from_lw(lw, repaired_mask)
        _print_alpha_stats(label, cloud_alpha)
        specular = _specular_from_cloud(base_ocean, cloud_alpha)
        prepared[label] = (rgba, specular)

    _write_generation(output_dir, prepared)

    return {
        "cloudProcessingVersion": CLOUD_PROCESSING_VERSION,
        "cloudSource": "NOAA/NESDIS GMGSI LW",
        "cloudSourceProduct": "GMGSI_LW",
        "cloudPreviousUtc": _utc_string(previous_slot),
        "cloudCurrentUtc": _utc_string(current_slot),
        "specularPreviousUtc": _utc_string(previous_slot),
        "specularCurrentUtc": _utc_string(current_slot),
        "cloudPreviousSourceKey": previous_key,
        "cloudCurrentSourceKey": current_key,
        "specularBaseSource": specular_base_url,
        "cloudHistoryReset": bool(force_history_reset or history_missing),
        "cloudImageChanged": True,
    }

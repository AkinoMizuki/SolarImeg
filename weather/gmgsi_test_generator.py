from __future__ import annotations

import argparse
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
from netCDF4 import Dataset
from PIL import Image, ImageFilter

S3_BASE_URL = "https://noaa-gmgsi-pds.s3.amazonaws.com"
S3_PRODUCT = "GMGSI_LW"
S3_FILENAME_PREFIX = "GLOBCOMPLIR"

OUTPUT_WIDTH = 2048
OUTPUT_HEIGHT = 1024

DEFAULT_LAT_MAX = 72.7154
DEFAULT_LAT_MIN = -72.7368
DEFAULT_LON_MIN = -179.9284
DEFAULT_LON_MAX = 179.9996

# GMGSI LW values are encoded 0..255 brightness-temperature values.
# The previous pass became too dense after polar mirroring, so this curve
# backs off the saturation while retaining thin/mid-level cloud detail.
CLOUD_ALPHA_START = 68.0
CLOUD_ALPHA_FULL = 225.0
CLOUD_ALPHA_GAMMA = 0.44
CLOUD_ALPHA_GAIN = 1.08
CLOUD_ALPHA_DILATE_SIZE = 3
CLOUD_ALPHA_BLUR_RADIUS = 0.70

# The mirrored caps are kept, but small no-data wedges around the fold seam
# are locally reconstructed from valid neighbours. This is intentionally
# limited to the seam region so ordinary clear/no-data handling elsewhere is
# not changed by the experimental polar treatment.
POLAR_SEAM_FILL_ROWS = 48
POLAR_HOLE_FILL_PASSES = 5
POLAR_HOLE_MIN_NEIGHBORS = 3

PRODUCTION_WEATHER_BASE = "https://akinomizuki.github.io/SolarImeg/weather"
TEST_FILENAMES = (
    "cloud_previous_test.png",
    "cloud_current_test.png",
    "specular_previous_test.jpg",
    "specular_current_test.jpg",
)


def _utc_hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _list_keys(prefix: str, timeout: int = 30) -> list[str]:
    response = requests.get(
        S3_BASE_URL,
        params={"list-type": "2", "prefix": prefix},
        timeout=timeout,
        headers={"User-Agent": "AkinoMizuki-SolarImeg/GMGSI-Test"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    keys: list[str] = []
    for element in root.iter():
        if element.tag.endswith("Key") and element.text:
            keys.append(element.text)
    return keys


def _find_latest_two_keys(lookback_hours: int = 36) -> list[tuple[datetime, str]]:
    now = _utc_hour_floor(datetime.now(timezone.utc))
    found: list[tuple[datetime, str]] = []

    for offset in range(lookback_hours + 1):
        slot = now - timedelta(hours=offset)
        prefix = (
            f"{S3_PRODUCT}/{slot.year:04d}/{slot.month:02d}/{slot.day:02d}/"
            f"{slot.hour:02d}/"
        )
        try:
            keys = _list_keys(prefix)
        except Exception as exc:
            print(f"GMGSI test: list failed for {prefix}: {exc}")
            continue

        candidates = [
            key
            for key in keys
            if key.rsplit("/", 1)[-1].startswith(S3_FILENAME_PREFIX)
            and key.lower().endswith(".nc")
        ]
        if not candidates:
            continue

        found.append((slot, sorted(candidates)[-1]))
        if len(found) >= 2:
            break

    if len(found) < 2:
        raise RuntimeError(
            f"Could not find two GMGSI LW observations in the last {lookback_hours} hours"
        )

    return sorted(found, key=lambda item: item[0])


def _download_netcdf(key: str, timeout: int = 120) -> Path:
    url = f"{S3_BASE_URL}/{quote(key, safe='/')}"
    response = requests.get(
        url,
        timeout=timeout,
        stream=True,
        headers={"User-Agent": "AkinoMizuki-SolarImeg/GMGSI-Test"},
    )
    response.raise_for_status()

    fd, name = tempfile.mkstemp(prefix="gmgsi_lw_", suffix=".nc")
    os.close(fd)
    path = Path(name)
    try:
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _read_gmgsi_plane(path: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    with Dataset(path, "r") as ds:
        raw_data = ds.variables["data"][:]
        if np.ma.isMaskedArray(raw_data):
            raw_data = np.ma.filled(raw_data, np.nan)
        data = np.asarray(raw_data, dtype=np.float32)
        data = np.squeeze(data)
        if data.ndim != 2:
            raise RuntimeError(f"Unexpected GMGSI data shape: {data.shape}")

        if "dqf" in ds.variables:
            dqf = np.asarray(ds.variables["dqf"][:])
            dqf = np.squeeze(dqf)
            if dqf.shape == data.shape:
                data = np.where(dqf == 0, data, np.nan)

        data = np.where(np.isfinite(data), data, 0.0)
        data = np.clip(data, 0.0, 255.0)

        lat_max = float(getattr(ds, "geospatial_lat_max", DEFAULT_LAT_MAX))
        lat_min = float(getattr(ds, "geospatial_lat_min", DEFAULT_LAT_MIN))
        lon_min = float(getattr(ds, "geospatial_lon_min", DEFAULT_LON_MIN))
        lon_max = float(getattr(ds, "geospatial_lon_max", DEFAULT_LON_MAX))

    return data, (lat_max, lat_min, lon_min, lon_max)


def _mercator_y(latitude_deg: np.ndarray | float) -> np.ndarray:
    lat = np.asarray(latitude_deg, dtype=np.float64)
    lat = np.clip(lat, -89.999999, 89.999999)
    return np.arctanh(np.sin(np.deg2rad(lat)))


def _mirror_polar_caps(result: np.ndarray, valid_rows: np.ndarray) -> np.ndarray:
    """Fill unavailable GMGSI polar caps by literal latitude mirroring."""
    filled = np.array(result, copy=True)
    valid_indices = np.flatnonzero(valid_rows)
    if valid_indices.size == 0:
        return filled

    first_valid = int(valid_indices[0])
    last_valid = int(valid_indices[-1])
    height = filled.shape[0]

    north_count = first_valid
    if north_count > 0:
        north_source = np.arange(
            2 * first_valid - 1,
            first_valid - 1,
            -1,
            dtype=np.int32,
        )
        north_source = np.clip(north_source, first_valid, last_valid)
        filled[:first_valid, :] = filled[north_source, :]

    south_start = last_valid + 1
    south_count = height - south_start
    if south_count > 0:
        south_source = np.arange(
            last_valid,
            last_valid - south_count,
            -1,
            dtype=np.int32,
        )
        south_source = np.clip(south_source, first_valid, last_valid)
        filled[south_start:, :] = filled[south_source, :]

    return filled


def _fill_polar_seam_holes(result: np.ndarray, valid_rows: np.ndarray) -> np.ndarray:
    """Fill only small zero-valued holes close to the two polar fold seams.

    GMGSI uses zero as the no-data sentinel after DQF masking. Mirroring can
    turn small edge gaps into visible triangular wedges. Repeated neighbour
    averaging closes those local wedges while leaving the rest of the global
    field untouched. Longitude rolls naturally, which is correct for a 360°
    equirectangular texture.
    """
    filled = np.array(result, copy=True)
    valid_indices = np.flatnonzero(valid_rows)
    if valid_indices.size == 0:
        return filled

    first_valid = int(valid_indices[0])
    last_valid = int(valid_indices[-1])
    height = filled.shape[0]

    seam_mask = np.zeros(filled.shape, dtype=bool)
    north0 = max(0, first_valid - POLAR_SEAM_FILL_ROWS)
    north1 = min(height, first_valid + POLAR_SEAM_FILL_ROWS + 1)
    south0 = max(0, last_valid - POLAR_SEAM_FILL_ROWS)
    south1 = min(height, last_valid + POLAR_SEAM_FILL_ROWS + 1)
    seam_mask[north0:north1, :] = True
    seam_mask[south0:south1, :] = True

    shifts = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),            (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )

    for _ in range(POLAR_HOLE_FILL_PASSES):
        missing = seam_mask & (filled <= 0.0)
        if not np.any(missing):
            break

        neighbour_sum = np.zeros_like(filled, dtype=np.float32)
        neighbour_count = np.zeros_like(filled, dtype=np.uint8)
        for dy, dx in shifts:
            neighbour = np.roll(filled, shift=(dy, dx), axis=(0, 1))
            neighbour_valid = neighbour > 0.0
            neighbour_sum += np.where(neighbour_valid, neighbour, 0.0)
            neighbour_count += neighbour_valid.astype(np.uint8)

        can_fill = missing & (neighbour_count >= POLAR_HOLE_MIN_NEIGHBORS)
        if not np.any(can_fill):
            break

        filled[can_fill] = (
            neighbour_sum[can_fill] / neighbour_count[can_fill].astype(np.float32)
        )

    return filled


def _to_equirectangular(
    source: np.ndarray,
    bounds: tuple[float, float, float, float],
    width: int = OUTPUT_WIDTH,
    height: int = OUTPUT_HEIGHT,
) -> np.ndarray:
    lat_max, lat_min, lon_min, lon_max = bounds
    src_h, _ = source.shape

    src_img = Image.fromarray(np.clip(source, 0, 255).astype(np.uint8), mode="L")
    horizontal = np.asarray(
        src_img.resize((width, src_h), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )

    target_lat = np.linspace(90.0, -90.0, height, dtype=np.float64)
    valid_rows = (target_lat <= lat_max) & (target_lat >= lat_min)

    src_y_top = float(_mercator_y(lat_max))
    src_y_bottom = float(_mercator_y(lat_min))
    target_y = _mercator_y(np.clip(target_lat, lat_min, lat_max))
    row = (src_y_top - target_y) / (src_y_top - src_y_bottom) * (src_h - 1)
    row = np.clip(row, 0.0, src_h - 1.0)

    row0 = np.floor(row).astype(np.int32)
    row1 = np.minimum(row0 + 1, src_h - 1)
    frac = (row - row0).astype(np.float32)[:, None]

    result = horizontal[row0] * (1.0 - frac) + horizontal[row1] * frac
    result = _mirror_polar_caps(result, valid_rows)
    result = _fill_polar_seam_holes(result, valid_rows)

    if lon_min > -179.99 or lon_max < 179.99:
        target_lon = np.linspace(-180.0, 180.0, width, endpoint=False)
        lon_valid = (target_lon >= lon_min) & (target_lon <= lon_max)
        result[:, ~lon_valid] = 0.0

    return result


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _cloud_rgba_from_lw(lw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build the IR-only cloud layer for visual validation."""
    valid = lw > 0.0

    alpha = _smoothstep(CLOUD_ALPHA_START, CLOUD_ALPHA_FULL, lw)
    alpha = np.power(alpha, CLOUD_ALPHA_GAMMA)
    alpha = np.clip(alpha * CLOUD_ALPHA_GAIN, 0.0, 1.0)
    alpha[~valid] = 0.0

    alpha_img = Image.fromarray(
        np.clip(alpha * 255.0, 0, 255).astype(np.uint8), mode="L"
    )
    alpha_img = alpha_img.filter(ImageFilter.MaxFilter(size=CLOUD_ALPHA_DILATE_SIZE))
    alpha_img = alpha_img.filter(
        ImageFilter.GaussianBlur(radius=CLOUD_ALPHA_BLUR_RADIUS)
    )
    alpha = np.asarray(alpha_img, dtype=np.float32) / 255.0
    alpha[~valid] = 0.0

    detail = np.clip(
        (lw - CLOUD_ALPHA_START) / (CLOUD_ALPHA_FULL - CLOUD_ALPHA_START),
        0.0,
        1.0,
    )

    # Keep the clouds bright but step back from the over-white previous pass.
    brightness = (
        168.0
        + 52.0 * np.power(alpha, 0.45)
        + 28.0 * np.sqrt(detail)
    )
    brightness = np.clip(brightness, 0.0, 255.0)
    rgb = np.repeat(brightness[:, :, None], 3, axis=2)
    rgb[~valid] = 255.0

    rgba = np.concatenate(
        [
            rgb.astype(np.uint8),
            np.clip(alpha * 255.0, 0, 255).astype(np.uint8)[:, :, None],
        ],
        axis=2,
    )
    return rgba, alpha


def _print_alpha_stats(label: str, alpha: np.ndarray) -> None:
    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    total = float(alpha_u8.size)

    def pct_over(value: int) -> float:
        return float(np.count_nonzero(alpha_u8 > value)) / total * 100.0

    print(
        f"GMGSI test {label} alpha: "
        f"mean={float(alpha_u8.mean()):.2f}/255, "
        f">0={pct_over(0):.2f}%, "
        f">64={pct_over(64):.2f}%, "
        f">128={pct_over(128):.2f}%, "
        f">192={pct_over(192):.2f}%, "
        f"=255={float(np.count_nonzero(alpha_u8 == 255)) / total * 100.0:.2f}%"
    )


def _load_rgba(path: Path, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(
        Image.open(path).convert("RGBA").resize(size, Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0


def _load_gray(path: Path, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(
        Image.open(path).convert("L").resize(size, Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0


def _estimate_ocean_specular_mask(output_dir: Path) -> np.ndarray:
    """Approximate a static ocean mask from the existing production pair."""
    size = (OUTPUT_WIDTH, OUTPUT_HEIGHT)
    samples: list[tuple[np.ndarray, np.ndarray]] = []
    for suffix in ("previous", "current"):
        cloud_path = output_dir / f"cloud_{suffix}.png"
        spec_path = output_dir / f"specular_{suffix}.jpg"
        if cloud_path.exists() and spec_path.exists():
            cloud = _load_rgba(cloud_path, size)
            spec = _load_gray(spec_path, size)
            samples.append((cloud[:, :, 3], spec))

    if not samples:
        raise RuntimeError(
            "Production cloud/specular textures are required to build test specular maps"
        )

    numerator = np.zeros((OUTPUT_HEIGHT, OUTPUT_WIDTH), dtype=np.float32)
    denominator = np.zeros_like(numerator)
    fallback = np.zeros_like(numerator)

    for cloud_alpha, spec in samples:
        clear_factor = np.clip(1.0 - 0.85 * cloud_alpha, 0.18, 1.0)
        estimate = np.clip(spec / clear_factor, 0.0, 1.0)
        confidence = np.power(1.0 - cloud_alpha, 2.0) + 0.03
        numerator += estimate * confidence
        denominator += confidence
        fallback = np.maximum(fallback, spec)

    base = np.where(denominator > 0.0, numerator / denominator, fallback)
    base = np.maximum(base, fallback)
    base = np.clip(base, 0.0, 1.0)

    base_img = Image.fromarray((base * 255.0).astype(np.uint8), mode="L")
    base_img = base_img.filter(ImageFilter.GaussianBlur(radius=0.6))
    return np.asarray(base_img, dtype=np.float32) / 255.0


def _specular_from_cloud(base_ocean: np.ndarray, cloud_alpha: np.ndarray) -> np.ndarray:
    occlusion = np.clip(1.0 - 0.92 * cloud_alpha, 0.0, 1.0)
    return np.clip(base_ocean * occlusion, 0.0, 1.0)


def _seed_published_test_outputs(output_dir: Path) -> None:
    """Keep the last published _test set if the experimental update fails."""
    stamp = str(int(datetime.now(timezone.utc).timestamp()))
    for name in TEST_FILENAMES:
        path = output_dir / name
        if path.exists():
            continue
        try:
            response = requests.get(
                f"{PRODUCTION_WEATHER_BASE}/{name}",
                params={"t": stamp},
                timeout=20,
                headers={
                    "Cache-Control": "no-cache",
                    "User-Agent": "AkinoMizuki-SolarImeg/GMGSI-Test",
                },
            )
            response.raise_for_status()
            path.write_bytes(response.content)
            print(f"GMGSI test: restored published fallback {name}")
        except Exception:
            pass


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _seed_published_test_outputs(output_dir)

    observations = _find_latest_two_keys()
    labels = ("previous", "current")
    base_ocean = _estimate_ocean_specular_mask(output_dir)

    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for label, (slot, key) in zip(labels, observations):
        print(f"GMGSI test {label}: {slot.isoformat()}  s3://noaa-gmgsi-pds/{key}")
        nc_path = _download_netcdf(key)
        try:
            raw, bounds = _read_gmgsi_plane(nc_path)
        finally:
            nc_path.unlink(missing_ok=True)

        lw = _to_equirectangular(raw, bounds)
        rgba, cloud_alpha = _cloud_rgba_from_lw(lw)
        _print_alpha_stats(label, cloud_alpha)
        specular = _specular_from_cloud(base_ocean, cloud_alpha)
        prepared[label] = (rgba, specular)

    staged: list[tuple[Path, Path]] = []
    try:
        for label in labels:
            rgba, specular = prepared[label]
            cloud_final = output_dir / f"cloud_{label}_test.png"
            spec_final = output_dir / f"specular_{label}_test.jpg"
            cloud_stage = output_dir / f".cloud_{label}_test.stage.png"
            spec_stage = output_dir / f".specular_{label}_test.stage.jpg"

            Image.fromarray(rgba, mode="RGBA").save(
                cloud_stage, format="PNG", optimize=True
            )
            Image.fromarray(
                (specular * 255.0).astype(np.uint8), mode="L"
            ).convert("RGB").save(
                spec_stage,
                format="JPEG",
                quality=92,
                optimize=True,
                subsampling=0,
            )
            staged.append((cloud_stage, cloud_final))
            staged.append((spec_stage, spec_final))

        for stage, final in staged:
            stage.replace(final)
            print(f"  {final} ({final.stat().st_size} bytes)")
    finally:
        for stage, _ in staged:
            stage.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate temporary NOAA GMGSI Earth Weather test textures"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("_site/weather"),
        help="Weather output directory (default: _site/weather)",
    )
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()

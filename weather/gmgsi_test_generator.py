from __future__ import annotations

import argparse
import os
import tempfile
import xml.etree.ElementTree as ET
from collections import deque
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

# IR -> cloud opacity seed curve. The final alpha is histogram-matched to the
# currently published live-cloud-maps cloud texture, so these values preserve
# ranking/detail instead of trying to hand-tune the final density.
CLOUD_ALPHA_START = 45.0
CLOUD_ALPHA_FULL = 245.0
CLOUD_ALPHA_GAMMA = 0.80
CLOUD_ALPHA_DILATE_SIZE = 3
CLOUD_ALPHA_BLUR_RADIUS = 0.60

# A hard safety limit: zero is the GMGSI no-data sentinel after DQF masking.
# Small/medium missing wedges are filled from surrounding valid LW values, but
# a badly corrupted source with a very large missing fraction is left alone.
MISSING_FILL_MAX_FRACTION = 0.20

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


def _read_gmgsi_plane(
    path: Path,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
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
    """Mirror the nearest valid latitude band into both unavailable polar caps."""
    filled = np.array(result, copy=True)
    valid_indices = np.flatnonzero(valid_rows)
    if valid_indices.size == 0:
        return filled

    first_valid = int(valid_indices[0])
    last_valid = int(valid_indices[-1])
    height = filled.shape[0]

    if first_valid > 0:
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


def _fill_missing_lw_regions(result: np.ndarray) -> np.ndarray:
    """Inpaint GMGSI no-data (0) wedges from surrounding valid LW samples.

    The earlier seam-only repair did not touch geometric gaps that occur away
    from the +/-72.7 degree fold. This fill operates on the LW no-data sentinel
    itself, before cloud thresholding, so clear warm land/ocean pixels are not
    mistaken for holes merely because their eventual cloud alpha is low.

    Longitude wraps, while latitude stops at the poles. A multi-source breadth-
    first fill propagates the local mean inward and therefore handles the large
    triangular mosaic gaps as well as one/two-pixel seams.
    """
    filled = np.array(result, copy=True, dtype=np.float32)
    missing = filled <= 0.0
    missing_count = int(np.count_nonzero(missing))
    if missing_count == 0:
        return filled

    fraction = missing_count / float(filled.size)
    if fraction > MISSING_FILL_MAX_FRACTION:
        print(
            "GMGSI test: skip no-data inpaint because missing fraction "
            f"{fraction * 100.0:.2f}% exceeds safety limit"
        )
        return filled

    height, width = filled.shape
    queued = np.zeros_like(missing, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    shifts = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),            (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )

    # Seed the queue only with missing pixels that already touch valid data.
    for y, x in np.argwhere(missing):
        yi = int(y)
        xi = int(x)
        touches_valid = False
        for dy, dx in shifts:
            ny = yi + dy
            if ny < 0 or ny >= height:
                continue
            nx = (xi + dx) % width
            if filled[ny, nx] > 0.0:
                touches_valid = True
                break
        if touches_valid:
            queue.append((yi, xi))
            queued[yi, xi] = True

    filled_count = 0
    while queue:
        y, x = queue.popleft()
        if filled[y, x] > 0.0:
            continue

        values: list[float] = []
        for dy, dx in shifts:
            ny = y + dy
            if ny < 0 or ny >= height:
                continue
            nx = (x + dx) % width
            value = float(filled[ny, nx])
            if value > 0.0:
                values.append(value)

        if not values:
            continue

        filled[y, x] = float(sum(values) / len(values))
        filled_count += 1

        for dy, dx in shifts:
            ny = y + dy
            if ny < 0 or ny >= height:
                continue
            nx = (x + dx) % width
            if filled[ny, nx] <= 0.0 and not queued[ny, nx]:
                queue.append((ny, nx))
                queued[ny, nx] = True

    remaining = int(np.count_nonzero(filled <= 0.0))
    print(
        "GMGSI test no-data inpaint: "
        f"before={missing_count}, filled={filled_count}, remaining={remaining}"
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

    if lon_min > -179.99 or lon_max < 179.99:
        target_lon = np.linspace(-180.0, 180.0, width, endpoint=False)
        lon_valid = (target_lon >= lon_min) & (target_lon <= lon_max)
        result[:, ~lon_valid] = 0.0

    # Fill geometric no-data wedges after reprojection and polar mirroring.
    result = _fill_missing_lw_regions(result)
    return result


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _histogram_match_u8(
    source_u8: np.ndarray,
    reference_u8: np.ndarray,
    source_mask: np.ndarray | None = None,
    reference_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Histogram-match an 8-bit scalar field while preserving spatial ranking."""
    source = np.asarray(source_u8, dtype=np.uint8)
    reference = np.asarray(reference_u8, dtype=np.uint8)

    if source_mask is None:
        source_mask = np.ones(source.shape, dtype=bool)
    if reference_mask is None:
        reference_mask = np.ones(reference.shape, dtype=bool)

    src_values = source[source_mask]
    ref_values = reference[reference_mask]
    if src_values.size == 0 or ref_values.size == 0:
        return source.copy()

    src_unique, src_counts = np.unique(src_values, return_counts=True)
    ref_unique, ref_counts = np.unique(ref_values, return_counts=True)

    src_quantiles = np.cumsum(src_counts).astype(np.float64)
    src_quantiles /= src_quantiles[-1]
    ref_quantiles = np.cumsum(ref_counts).astype(np.float64)
    ref_quantiles /= ref_quantiles[-1]

    matched_values = np.interp(src_quantiles, ref_quantiles, ref_unique)
    lookup = np.arange(256, dtype=np.float32)
    lookup[src_unique] = matched_values.astype(np.float32)

    # Fill unused source bins by interpolation between the bins that occurred.
    if src_unique.size > 1:
        lookup = np.interp(
            np.arange(256, dtype=np.float32),
            src_unique.astype(np.float32),
            matched_values.astype(np.float32),
        ).astype(np.float32)
    elif src_unique.size == 1:
        lookup.fill(float(matched_values[0]))

    result = source.copy()
    result[source_mask] = np.clip(
        np.rint(lookup[source[source_mask]]), 0, 255
    ).astype(np.uint8)
    return result


def _cloud_rgba_from_lw(
    lw: np.ndarray,
    reference_rgba: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Build GMGSI clouds and calibrate density/tone to production cloud texture."""
    valid = lw > 0.0

    # Build a smooth monotonic opacity seed from IR, then let the reference
    # texture define the final global opacity distribution.
    alpha_seed = _smoothstep(CLOUD_ALPHA_START, CLOUD_ALPHA_FULL, lw)
    alpha_seed = np.power(alpha_seed, CLOUD_ALPHA_GAMMA)
    alpha_seed[~valid] = 0.0

    alpha_img = Image.fromarray(
        np.clip(alpha_seed * 255.0, 0, 255).astype(np.uint8), mode="L"
    )
    alpha_img = alpha_img.filter(ImageFilter.MaxFilter(size=CLOUD_ALPHA_DILATE_SIZE))
    alpha_img = alpha_img.filter(
        ImageFilter.GaussianBlur(radius=CLOUD_ALPHA_BLUR_RADIUS)
    )
    alpha_u8 = np.asarray(alpha_img, dtype=np.uint8)

    ref_alpha_u8 = np.clip(reference_rgba[:, :, 3] * 255.0, 0, 255).astype(np.uint8)
    alpha_u8 = _histogram_match_u8(
        alpha_u8,
        ref_alpha_u8,
        source_mask=valid,
        reference_mask=np.ones(ref_alpha_u8.shape, dtype=bool),
    )
    alpha_u8[~valid] = 0
    alpha = alpha_u8.astype(np.float32) / 255.0

    # IR value itself is a useful monotonic cloud-top-detail signal. Histogram
    # matching its luminance to live-cloud-maps restores the broad dark-to-white
    # tonal range that the previous hand-tuned 168..248 curve could not match.
    luma_seed_u8 = np.clip(lw, 0, 255).astype(np.uint8)

    ref_rgb = np.clip(reference_rgba[:, :, :3] * 255.0, 0, 255)
    ref_luma_u8 = np.clip(
        0.2126 * ref_rgb[:, :, 0]
        + 0.7152 * ref_rgb[:, :, 1]
        + 0.0722 * ref_rgb[:, :, 2],
        0,
        255,
    ).astype(np.uint8)

    luma_u8 = _histogram_match_u8(
        luma_seed_u8,
        ref_luma_u8,
        source_mask=valid,
        reference_mask=ref_alpha_u8 > 0,
    )
    luma_u8[~valid] = 255

    rgb = np.repeat(luma_u8[:, :, None], 3, axis=2)
    rgba = np.concatenate([rgb, alpha_u8[:, :, None]], axis=2)
    return rgba.astype(np.uint8), alpha


def _print_alpha_stats(
    label: str,
    alpha: np.ndarray,
    reference_rgba: np.ndarray | None = None,
) -> None:
    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    total = float(alpha_u8.size)

    def pct_over(values: np.ndarray, value: int) -> float:
        return float(np.count_nonzero(values > value)) / float(values.size) * 100.0

    print(
        f"GMGSI test {label} alpha: "
        f"mean={float(alpha_u8.mean()):.2f}/255, "
        f">0={pct_over(alpha_u8, 0):.2f}%, "
        f">64={pct_over(alpha_u8, 64):.2f}%, "
        f">128={pct_over(alpha_u8, 128):.2f}%, "
        f">192={pct_over(alpha_u8, 192):.2f}%, "
        f"=255={float(np.count_nonzero(alpha_u8 == 255)) / total * 100.0:.2f}%"
    )

    if reference_rgba is not None:
        ref = np.clip(reference_rgba[:, :, 3] * 255.0, 0, 255).astype(np.uint8)
        print(
            f"GMGSI reference {label} alpha: "
            f"mean={float(ref.mean()):.2f}/255, "
            f">0={pct_over(ref, 0):.2f}%, "
            f">64={pct_over(ref, 64):.2f}%, "
            f">128={pct_over(ref, 128):.2f}%, "
            f">192={pct_over(ref, 192):.2f}%, "
            f"=255={float(np.count_nonzero(ref == 255)) / float(ref.size) * 100.0:.2f}%"
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
    size = (OUTPUT_WIDTH, OUTPUT_HEIGHT)

    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for label, (slot, key) in zip(labels, observations):
        print(f"GMGSI test {label}: {slot.isoformat()}  s3://noaa-gmgsi-pds/{key}")

        reference_path = output_dir / f"cloud_{label}.png"
        if not reference_path.exists():
            raise RuntimeError(f"Production reference cloud is missing: {reference_path}")
        reference_rgba = _load_rgba(reference_path, size)

        nc_path = _download_netcdf(key)
        try:
            raw, bounds = _read_gmgsi_plane(nc_path)
        finally:
            nc_path.unlink(missing_ok=True)

        lw = _to_equirectangular(raw, bounds)
        rgba, cloud_alpha = _cloud_rgba_from_lw(lw, reference_rgba)
        _print_alpha_stats(label, cloud_alpha, reference_rgba)

        specular = _specular_from_cloud(base_ocean, cloud_alpha)
        prepared[label] = (rgba, specular)

    # Stage all four files and publish only after the full test batch succeeds.
    staged: list[tuple[Path, Path]] = []
    try:
        for label in labels:
            rgba, specular = prepared[label]
            cloud_final = output_dir / f"cloud_{label}_test.png"
            spec_final = output_dir / f"specular_{label}_test.jpg"
            cloud_stage = output_dir / f".cloud_{label}_test.stage.png"
            spec_stage = output_dir / f".specular_{label}_test.stage.jpg"

            Image.fromarray(rgba, mode="RGBA").save(
                cloud_stage,
                format="PNG",
                optimize=True,
            )
            Image.fromarray(
                (specular * 255.0).astype(np.uint8),
                mode="L",
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

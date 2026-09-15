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

# Absolute IR + local-contrast cloud detection.
# The absolute branch captures thick/cold cloud; the local branch recovers
# weaker/warm cloud structures that disappear with a single global threshold.
CLOUD_ABS_START = 60.0
CLOUD_ABS_FULL = 220.0
CLOUD_ABS_GAMMA = 0.68
CLOUD_ABS_GAIN = 0.92

CLOUD_LOCAL_BACKGROUND_RADIUS = 18.0
CLOUD_LOCAL_START = 1.8
CLOUD_LOCAL_FULL = 22.0
CLOUD_LOCAL_GAMMA = 0.78
CLOUD_LOCAL_GAIN = 0.72

CLOUD_ALPHA_BLUR_RADIUS = 0.45
CLOUD_REPAIRED_ALPHA_SCALE = 0.88
CLOUD_REPAIRED_MASK_BLUR = 1.0

# Keep RGB independent from alpha thresholding so weak cloud keeps visible IR
# texture. Values are tuned to stay near the production cloud brightness while
# retaining much more midtone structure than the previous white/black masks.
CLOUD_RGB_BASE = 164.0
CLOUD_RGB_IR_GAIN = 54.0
CLOUD_RGB_ALPHA_GAIN = 30.0
CLOUD_RGB_LOCAL_GAIN = 18.0
CLOUD_RGB_MAX = 247.0

# Conservative no-data repair. Only GMGSI-invalid pixels are filled.
GAP_BUFFER = 3
MAX_ROW_GAP_FRACTION = 0.35
GAUSSIAN_FILL_RADII = (2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
GAUSSIAN_FILL_MIN_WEIGHT = 2

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
    return [
        element.text
        for element in root.iter()
        if element.tag.endswith("Key") and element.text
    ]


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
        if candidates:
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
) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float, float]]:
    with Dataset(path, "r") as ds:
        raw = ds.variables["data"][:]
        if np.ma.isMaskedArray(raw):
            raw = np.ma.filled(raw, np.nan)

        data = np.squeeze(np.asarray(raw, dtype=np.float32))
        if data.ndim != 2:
            raise RuntimeError(f"Unexpected GMGSI data shape: {data.shape}")

        valid = np.isfinite(data)
        if "dqf" in ds.variables:
            dqf = np.squeeze(np.asarray(ds.variables["dqf"][:]))
            if dqf.shape == data.shape:
                valid &= dqf == 0

        valid &= data > 0.0
        data = np.where(valid, np.clip(data, 0.0, 255.0), 0.0)
        bounds = (
            float(getattr(ds, "geospatial_lat_max", DEFAULT_LAT_MAX)),
            float(getattr(ds, "geospatial_lat_min", DEFAULT_LAT_MIN)),
            float(getattr(ds, "geospatial_lon_min", DEFAULT_LON_MIN)),
            float(getattr(ds, "geospatial_lon_max", DEFAULT_LON_MAX)),
        )

    return data, valid.astype(np.float32), bounds


def _mercator_y(latitude_deg: np.ndarray | float) -> np.ndarray:
    lat = np.asarray(latitude_deg, dtype=np.float64)
    lat = np.clip(lat, -89.999999, 89.999999)
    return np.arctanh(np.sin(np.deg2rad(lat)))


def _mirror_polar_caps(field: np.ndarray, valid_rows: np.ndarray) -> np.ndarray:
    filled = np.array(field, copy=True)
    rows = np.flatnonzero(valid_rows)
    if rows.size == 0:
        return filled

    first = int(rows[0])
    last = int(rows[-1])
    height = filled.shape[0]

    if first > 0:
        src = np.arange(2 * first - 1, first - 1, -1, dtype=np.int32)
        filled[:first] = filled[np.clip(src, first, last)]

    south_start = last + 1
    south_count = height - south_start
    if south_count > 0:
        src = np.arange(last, last - south_count, -1, dtype=np.int32)
        filled[south_start:] = filled[np.clip(src, first, last)]

    return filled


def _vertical_resample(
    source: np.ndarray,
    lat_max: float,
    lat_min: float,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    src_h = source.shape[0]
    target_lat = np.linspace(90.0, -90.0, height, dtype=np.float64)
    valid_rows = (target_lat <= lat_max) & (target_lat >= lat_min)

    top = float(_mercator_y(lat_max))
    bottom = float(_mercator_y(lat_min))
    target = _mercator_y(np.clip(target_lat, lat_min, lat_max))
    row = (top - target) / (top - bottom) * (src_h - 1)
    row = np.clip(row, 0.0, src_h - 1.0)

    row0 = np.floor(row).astype(np.int32)
    row1 = np.minimum(row0 + 1, src_h - 1)
    frac = (row - row0).astype(np.float32)[:, None]
    return source[row0] * (1.0 - frac) + source[row1] * frac, valid_rows


def _fill_row_gaps(
    field: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = np.array(field, copy=True)
    work_valid = valid.copy()
    repaired = np.zeros_like(valid, dtype=bool)
    height, width = out.shape
    max_gap = int(width * MAX_ROW_GAP_FRACTION)

    for y in range(height):
        x = 0
        while x < width:
            if work_valid[y, x]:
                x += 1
                continue

            start = x
            while x < width and not work_valid[y, x]:
                x += 1
            end = x
            run = end - start

            if run <= 0 or run > max_gap or start == 0 or end >= width:
                continue

            left = max(0, start - 1 - GAP_BUFFER)
            right = min(width - 1, end + GAP_BUFFER)
            if not work_valid[y, left] or not work_valid[y, right]:
                continue

            xs = np.arange(start, end)
            t = (xs - left) / float(right - left)
            out[y, xs] = (
                out[y, left] * (1.0 - t) + out[y, right] * t
            ).astype(np.float32)
            work_valid[y, xs] = True
            repaired[y, xs] = True

    return out, work_valid, repaired


def _blur_u8(field: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(np.clip(field, 0, 255).astype(np.uint8), mode="L")
    image = image.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(image, dtype=np.float32)


def _fill_remaining_gaps(
    field: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = np.array(field, copy=True)
    work_valid = valid.copy()
    repaired = np.zeros_like(valid, dtype=bool)

    for radius in GAUSSIAN_FILL_RADII:
        missing = ~work_valid
        if not np.any(missing):
            break

        valid_float = work_valid.astype(np.float32)
        numerator = _blur_u8(out * valid_float, radius)
        weight = _blur_u8(valid_float * 255.0, radius)
        can_fill = missing & (weight >= GAUSSIAN_FILL_MIN_WEIGHT)
        if not np.any(can_fill):
            continue

        estimate = numerator * 255.0 / np.maximum(weight, 1.0)
        out[can_fill] = np.clip(estimate[can_fill], 0.0, 255.0)
        work_valid[can_fill] = True
        repaired[can_fill] = True

    return out, work_valid, repaired


def _to_equirectangular(
    source: np.ndarray,
    source_valid: np.ndarray,
    bounds: tuple[float, float, float, float],
    width: int = OUTPUT_WIDTH,
    height: int = OUTPUT_HEIGHT,
) -> tuple[np.ndarray, np.ndarray]:
    lat_max, lat_min, lon_min, lon_max = bounds
    src_h = source.shape[0]

    src_img = Image.fromarray(np.clip(source, 0, 255).astype(np.uint8), mode="L")
    horizontal = np.asarray(
        src_img.resize((width, src_h), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )
    valid_img = Image.fromarray(
        np.clip(source_valid * 255.0, 0, 255).astype(np.uint8), mode="L"
    )
    horizontal_valid = np.asarray(
        valid_img.resize((width, src_h), Image.Resampling.NEAREST),
        dtype=np.float32,
    ) / 255.0

    result, valid_rows = _vertical_resample(horizontal, lat_max, lat_min, height)
    coverage, _ = _vertical_resample(horizontal_valid, lat_max, lat_min, height)
    result = _mirror_polar_caps(result, valid_rows)
    coverage = _mirror_polar_caps(coverage, valid_rows)
    valid = coverage > 0.5

    if lon_min > -179.99 or lon_max < 179.99:
        target_lon = np.linspace(-180.0, 180.0, width, endpoint=False)
        lon_valid = (target_lon >= lon_min) & (target_lon <= lon_max)
        result[:, ~lon_valid] = 0.0
        valid[:, ~lon_valid] = False

    missing_before = int(np.count_nonzero(~valid))
    result, valid, repaired_row = _fill_row_gaps(result, valid)
    result, valid, repaired_gaussian = _fill_remaining_gaps(result, valid)
    repaired = repaired_row | repaired_gaussian
    remaining = int(np.count_nonzero(~valid))

    print(
        "GMGSI test gap repair: "
        f"before={missing_before}, repaired={int(np.count_nonzero(repaired))}, "
        f"remaining={remaining}"
    )
    return result, repaired


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _soft_mask(mask: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    if radius > 0.0:
        image = image.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(image, dtype=np.float32) / 255.0


def _cloud_rgba_from_lw(
    lw: np.ndarray,
    repaired_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    valid = lw > 0.0

    # Absolute-IR branch: thick/cold cloud.
    absolute = _smoothstep(CLOUD_ABS_START, CLOUD_ABS_FULL, lw)
    absolute = np.power(absolute, CLOUD_ABS_GAMMA)
    absolute = np.clip(absolute * CLOUD_ABS_GAIN, 0.0, 1.0)

    # Local-contrast branch: recover weak/warm cloud that is close to the
    # background temperature and therefore lost by a global threshold alone.
    background = _blur_u8(lw, CLOUD_LOCAL_BACKGROUND_RADIUS)
    local_signal = np.maximum(lw - background, 0.0)
    local = _smoothstep(CLOUD_LOCAL_START, CLOUD_LOCAL_FULL, local_signal)
    local = np.power(local, CLOUD_LOCAL_GAMMA)
    local = np.clip(local * CLOUD_LOCAL_GAIN, 0.0, 1.0)

    alpha = np.maximum(absolute, local)
    alpha[~valid] = 0.0

    alpha_img = Image.fromarray(
        np.clip(alpha * 255.0, 0, 255).astype(np.uint8), mode="L"
    )
    alpha_img = alpha_img.filter(
        ImageFilter.GaussianBlur(radius=CLOUD_ALPHA_BLUR_RADIUS)
    )
    alpha = np.asarray(alpha_img, dtype=np.float32) / 255.0
    alpha[~valid] = 0.0

    if np.any(repaired_mask):
        repaired_soft = _soft_mask(repaired_mask, CLOUD_REPAIRED_MASK_BLUR)
        repair_scale = 1.0 - repaired_soft * (1.0 - CLOUD_REPAIRED_ALPHA_SCALE)
        alpha *= repair_scale

    # RGB keeps continuous IR texture independently of the alpha threshold.
    ir_norm = np.clip(lw / 255.0, 0.0, 1.0)
    local_norm = np.clip(local_signal / CLOUD_LOCAL_FULL, 0.0, 1.0)
    brightness = (
        CLOUD_RGB_BASE
        + CLOUD_RGB_IR_GAIN * np.power(ir_norm, 0.90)
        + CLOUD_RGB_ALPHA_GAIN * np.power(alpha, 0.80)
        + CLOUD_RGB_LOCAL_GAIN * np.power(local_norm, 0.75)
    )
    brightness = np.clip(brightness, 0.0, CLOUD_RGB_MAX)
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
    u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    total = float(u8.size)

    def pct_over(value: int) -> float:
        return float(np.count_nonzero(u8 > value)) / total * 100.0

    print(
        f"GMGSI test {label} alpha: mean={float(u8.mean()):.2f}/255, "
        f">0={pct_over(0):.2f}%, >64={pct_over(64):.2f}%, "
        f">128={pct_over(128):.2f}%, >192={pct_over(192):.2f}%"
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
    image = Image.fromarray((base * 255.0).astype(np.uint8), mode="L")
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))
    return np.asarray(image, dtype=np.float32) / 255.0


def _specular_from_cloud(base_ocean: np.ndarray, cloud_alpha: np.ndarray) -> np.ndarray:
    occlusion = np.clip(1.0 - 0.92 * cloud_alpha, 0.0, 1.0)
    return np.clip(base_ocean * occlusion, 0.0, 1.0)


def _seed_published_test_outputs(output_dir: Path) -> None:
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
            raw, raw_valid, bounds = _read_gmgsi_plane(nc_path)
        finally:
            nc_path.unlink(missing_ok=True)

        lw, repaired_mask = _to_equirectangular(raw, raw_valid, bounds)
        rgba, cloud_alpha = _cloud_rgba_from_lw(lw, repaired_mask)
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
            staged.extend(((cloud_stage, cloud_final), (spec_stage, spec_final)))

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

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

# live-cloud-maps uses a soft greyscale cloud field for alpha, then derives the
# RGB shading from a blurred copy. Keep the GMGSI test pipeline equally soft:
# no dilation/max-filter and no hard per-pixel histogram remap.
IR_LOW = 72.0
IR_HIGH = 178.0
IR_GAMMA = 1.46
OUTPUT_GAMMA = 2.0
IR_WEIGHT = 0.77

ALPHA_BLUR_RADIUS = 1.15
RGB_BLUR_RADIUS = 3.0
RGB_BRIGHTNESS = 1.28

# Exactly 1/8 of the equirectangular height is mirrored at each pole, matching
# live-cloud-maps' polar treatment.
POLAR_MIRROR_FRACTION = 1.0 / 8.0
POLAR_SEAM_BLEND_ROWS = 24

# Fill GMGSI geometric gaps row-by-row with a smooth linear gradient, similar
# to live-cloud-maps' antimeridian gap repair. Remaining isolated pixels get a
# conservative vertical pass.
GAP_BUFFER = 3
MAX_ROW_GAP_FRACTION = 0.35
VERTICAL_FILL_PASSES = 8

# Calibrate overall opacity to the production cloud texture using robust
# percentiles rather than a full histogram lookup (which caused banding).
CALIBRATION_PERCENTILES = (5.0, 25.0, 50.0, 75.0, 95.0)

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


def _vertical_resample(
    source: np.ndarray,
    lat_max: float,
    lat_min: float,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    src_h = source.shape[0]
    target_lat = np.linspace(90.0, -90.0, height, dtype=np.float64)
    inside = (target_lat <= lat_max) & (target_lat >= lat_min)

    top = float(_mercator_y(lat_max))
    bottom = float(_mercator_y(lat_min))
    target = _mercator_y(np.clip(target_lat, lat_min, lat_max))
    row = (top - target) / (top - bottom) * (src_h - 1)
    row = np.clip(row, 0.0, src_h - 1.0)

    row0 = np.floor(row).astype(np.int32)
    row1 = np.minimum(row0 + 1, src_h - 1)
    frac = (row - row0).astype(np.float32)[:, None]
    return source[row0] * (1.0 - frac) + source[row1] * frac, inside


def _mirror_poles(field: np.ndarray, inside_rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    out = np.array(field, copy=True)
    mask = np.zeros_like(out, dtype=np.float32)
    valid_rows = np.flatnonzero(inside_rows)
    if valid_rows.size == 0:
        return out, mask

    first = int(valid_rows[0])
    last = int(valid_rows[-1])
    mirror_rows = max(1, int(round(out.shape[0] * POLAR_MIRROR_FRACTION)))

    north_rows = min(first, mirror_rows)
    if north_rows > 0:
        src = np.arange(first + north_rows - 1, first - 1, -1, dtype=np.int32)
        out[first - north_rows:first] = out[src]
        mask[first - north_rows:first] = 1.0

    south_start = last + 1
    south_rows = min(out.shape[0] - south_start, mirror_rows)
    if south_rows > 0:
        src = np.arange(last, last - south_rows, -1, dtype=np.int32)
        out[south_start:south_start + south_rows] = out[src]
        mask[south_start:south_start + south_rows] = 1.0

    if first - north_rows > 0:
        remainder = first - north_rows
        src = np.arange(first + remainder - 1, first - 1, -1, dtype=np.int32)
        src = np.clip(src, first, last)
        out[:remainder] = out[src]
        mask[:remainder] = 1.0

    tail = south_start + south_rows
    if tail < out.shape[0]:
        remainder = out.shape[0] - tail
        src = np.arange(last - south_rows, last - south_rows - remainder, -1, dtype=np.int32)
        src = np.clip(src, first, last)
        out[tail:] = out[src]
        mask[tail:] = 1.0

    return out, mask


def _fill_row_gaps(field: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fill bounded no-data runs with a horizontal gradient.

    This follows live-cloud-maps' visual strategy: interpolate across gaps
    instead of growing local means inward, which produced triangular artifacts.
    """
    out = np.array(field, copy=True)
    repaired = np.zeros_like(valid, dtype=bool)
    height, width = out.shape
    max_gap = int(width * MAX_ROW_GAP_FRACTION)

    for y in range(height):
        row_valid = valid[y]
        if not np.any(row_valid):
            continue

        missing = ~row_valid
        x = 0
        while x < width:
            if not missing[x]:
                x += 1
                continue

            start = x
            while x < width and missing[x]:
                x += 1
            end = x
            run = end - start

            if run > max_gap:
                continue

            left = start - 1
            right = end
            if left < 0 or right >= width:
                continue

            left_safe = max(0, left - GAP_BUFFER)
            right_safe = min(width - 1, right + GAP_BUFFER)
            if not row_valid[left_safe] or not row_valid[right_safe]:
                continue

            span_start = left_safe + 1
            span_end = right_safe
            values = np.linspace(
                float(out[y, left_safe]),
                float(out[y, right_safe]),
                span_end - span_start + 1,
                dtype=np.float32,
            )
            target = np.arange(span_start, span_end + 1)
            replace = ~row_valid[target]
            out[y, target[replace]] = values[replace]
            row_valid[target[replace]] = True
            repaired[y, target[replace]] = True

    return out, repaired


def _fill_remaining_vertical(
    field: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    out = np.array(field, copy=True)
    work_valid = valid.copy()
    repaired = np.zeros_like(valid, dtype=bool)

    for _ in range(VERTICAL_FILL_PASSES):
        missing = ~work_valid
        if not np.any(missing):
            break

        up = np.roll(out, 1, axis=0)
        down = np.roll(out, -1, axis=0)
        up_valid = np.roll(work_valid, 1, axis=0)
        down_valid = np.roll(work_valid, -1, axis=0)
        up_valid[0] = False
        down_valid[-1] = False

        can = missing & up_valid & down_valid
        if not np.any(can):
            break

        out[can] = 0.5 * (up[can] + down[can])
        work_valid[can] = True
        repaired[can] = True

    return out, repaired


def _soft_mask(mask: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    image = image.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(image, dtype=np.float32) / 255.0


def _to_equirectangular(
    source: np.ndarray,
    source_valid: np.ndarray,
    bounds: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lat_max, lat_min, lon_min, lon_max = bounds
    src_h = source.shape[0]

    src_img = Image.fromarray(np.clip(source, 0, 255).astype(np.uint8), mode="L")
    horizontal = np.asarray(
        src_img.resize((OUTPUT_WIDTH, src_h), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )

    valid_img = Image.fromarray((source_valid * 255).astype(np.uint8), mode="L")
    horizontal_valid = np.asarray(
        valid_img.resize((OUTPUT_WIDTH, src_h), Image.Resampling.NEAREST),
        dtype=np.float32,
    ) / 255.0

    field, inside_rows = _vertical_resample(horizontal, lat_max, lat_min, OUTPUT_HEIGHT)
    coverage, _ = _vertical_resample(horizontal_valid, lat_max, lat_min, OUTPUT_HEIGHT)

    field, polar_mask = _mirror_poles(field, inside_rows)
    coverage, _ = _mirror_poles(coverage, inside_rows)
    valid = coverage > 0.5

    if lon_min > -179.99 or lon_max < 179.99:
        target_lon = np.linspace(-180.0, 180.0, OUTPUT_WIDTH, endpoint=False)
        lon_ok = (target_lon >= lon_min) & (target_lon <= lon_max)
        valid[:, ~lon_ok] = False
        field[:, ~lon_ok] = 0.0

    missing_before = int(np.count_nonzero(~valid))

    field, repaired_h = _fill_row_gaps(field, valid)
    valid |= repaired_h
    field, repaired_v = _fill_remaining_vertical(field, valid)
    valid |= repaired_v

    repaired = repaired_h | repaired_v
    remaining = int(np.count_nonzero(~valid))
    print(
        "GMGSI test gap repair: "
        f"before={missing_before}, repaired={int(np.count_nonzero(repaired))}, "
        f"remaining={remaining}"
    )

    fallback = _soft_mask(~valid, 4.0)

    seam = np.zeros_like(valid, dtype=bool)
    rows = np.flatnonzero(inside_rows)
    if rows.size:
        first, last = int(rows[0]), int(rows[-1])
        a = max(0, first - POLAR_SEAM_BLEND_ROWS)
        b = min(OUTPUT_HEIGHT, first + POLAR_SEAM_BLEND_ROWS + 1)
        c = max(0, last - POLAR_SEAM_BLEND_ROWS)
        d = min(OUTPUT_HEIGHT, last + POLAR_SEAM_BLEND_ROWS + 1)
        seam[a:b] = True
        seam[c:d] = True
    seam |= polar_mask > 0.5
    seam_soft = _soft_mask(seam, 6.0) * 0.12

    return field, fallback, seam_soft


def _gamma(gamma_value: float, x: np.ndarray) -> np.ndarray:
    return np.power(np.clip(x, 0.0, 1.0), 1.0 / gamma_value)


def _cloud_seed_from_ir(lw: np.ndarray) -> np.ndarray:
    ir = np.clip((lw - IR_LOW) / (IR_HIGH - IR_LOW), 0.0, 1.0)
    ir = _gamma(IR_GAMMA, ir)
    return _gamma(OUTPUT_GAMMA, ir * IR_WEIGHT)


def _percentile_match(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Softly calibrate density without the edge banding of full histogram match."""
    src = np.clip(source, 0.0, 1.0)
    ref = np.clip(reference, 0.0, 1.0)

    src_q = np.percentile(src, CALIBRATION_PERCENTILES)
    ref_q = np.percentile(ref, CALIBRATION_PERCENTILES)

    src_x = np.concatenate(([0.0], src_q, [1.0]))
    ref_y = np.concatenate(([0.0], ref_q, [1.0]))
    src_x = np.maximum.accumulate(src_x)
    for i in range(1, src_x.size):
        if src_x[i] <= src_x[i - 1]:
            src_x[i] = min(1.0, src_x[i - 1] + 1e-5)

    matched = np.interp(src.ravel(), src_x, ref_y).reshape(src.shape)
    return np.clip(matched, 0.0, 1.0).astype(np.float32)


def _load_rgba(path: Path) -> np.ndarray:
    return np.asarray(
        Image.open(path)
        .convert("RGBA")
        .resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0


def _load_gray(path: Path) -> np.ndarray:
    return np.asarray(
        Image.open(path)
        .convert("L")
        .resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0


def _cloud_rgba(
    lw: np.ndarray,
    reference: np.ndarray,
    fallback_mask: np.ndarray,
    seam_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    alpha = _cloud_seed_from_ir(lw)

    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), mode="L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=ALPHA_BLUR_RADIUS))
    alpha = np.asarray(alpha_img, dtype=np.float32) / 255.0

    ref_alpha = reference[:, :, 3]
    alpha = _percentile_match(alpha, ref_alpha)

    rgb_img = Image.fromarray((alpha * 255).astype(np.uint8), mode="L")
    rgb_img = rgb_img.filter(ImageFilter.GaussianBlur(radius=RGB_BLUR_RADIUS))
    rgb_luma = np.asarray(rgb_img, dtype=np.float32) / 255.0
    rgb_luma = np.clip(rgb_luma * RGB_BRIGHTNESS, 0.0, 1.0)
    rgb = np.repeat(rgb_luma[:, :, None], 3, axis=2)

    if np.any(fallback_mask > 0.0):
        m = fallback_mask[:, :, None]
        rgb = rgb * (1.0 - m) + reference[:, :, :3] * m
        alpha = alpha * (1.0 - fallback_mask) + ref_alpha * fallback_mask

    if np.any(seam_mask > 0.0):
        m = seam_mask[:, :, None]
        rgb = rgb * (1.0 - m) + reference[:, :, :3] * m
        alpha = alpha * (1.0 - seam_mask) + ref_alpha * seam_mask

    alpha_img = Image.fromarray(np.clip(alpha * 255, 0, 255).astype(np.uint8), mode="L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.45))
    alpha = np.asarray(alpha_img, dtype=np.float32) / 255.0

    rgba = np.concatenate(
        [
            np.clip(rgb * 255.0, 0, 255).astype(np.uint8),
            np.clip(alpha * 255.0, 0, 255).astype(np.uint8)[:, :, None],
        ],
        axis=2,
    )
    return rgba, alpha


def _print_alpha_stats(label: str, alpha: np.ndarray, reference: np.ndarray) -> None:
    def stats(a: np.ndarray) -> str:
        u8 = np.clip(a * 255, 0, 255).astype(np.uint8)
        total = float(u8.size)
        return (
            f"mean={float(u8.mean()):.2f}/255, "
            f">64={np.count_nonzero(u8 > 64) / total * 100:.2f}%, "
            f">128={np.count_nonzero(u8 > 128) / total * 100:.2f}%, "
            f">192={np.count_nonzero(u8 > 192) / total * 100:.2f}%"
        )

    print(f"GMGSI test {label} alpha: {stats(alpha)}")
    print(f"GMGSI test {label} reference alpha: {stats(reference[:, :, 3])}")


def _estimate_ocean_specular_mask(output_dir: Path) -> np.ndarray:
    samples: list[tuple[np.ndarray, np.ndarray]] = []
    for suffix in ("previous", "current"):
        cloud_path = output_dir / f"cloud_{suffix}.png"
        spec_path = output_dir / f"specular_{suffix}.jpg"
        if cloud_path.exists() and spec_path.exists():
            cloud = _load_rgba(cloud_path)
            spec = _load_gray(spec_path)
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
    image = Image.fromarray((base * 255).astype(np.uint8), mode="L")
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))
    return np.asarray(image, dtype=np.float32) / 255.0


def _specular_from_cloud(base_ocean: np.ndarray, cloud_alpha: np.ndarray) -> np.ndarray:
    return np.clip(base_ocean * np.clip(1.0 - 0.92 * cloud_alpha, 0.0, 1.0), 0.0, 1.0)


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

        reference = _load_rgba(output_dir / f"cloud_{label}.png")
        lw, fallback_mask, seam_mask = _to_equirectangular(raw, raw_valid, bounds)
        rgba, cloud_alpha = _cloud_rgba(lw, reference, fallback_mask, seam_mask)
        _print_alpha_stats(label, cloud_alpha, reference)
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
                (specular * 255).astype(np.uint8), mode="L"
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

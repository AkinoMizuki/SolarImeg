from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import requests
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)
from PIL import Image

GFS_FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
WIND_SPEED_MAX_MS = 128.0
OUTPUT_WIDTH = 1440
OUTPUT_HEIGHT = 720

_LEVEL_OUTPUTS = {
    "surface": "wind_surface.png",
    "850": "wind_850hpa.png",
    "700": "wind_700hpa.png",
}


def _candidate_runs(now_utc: datetime) -> list[tuple[datetime, int]]:
    """Return likely-available GFS runs and forecast hours, newest first."""
    target = now_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # GFS files normally need several hours after cycle time to become available.
    # Start from the newest cycle at least 5 hours old, then fall back by 6 hours.
    availability_cutoff = target - timedelta(hours=5)
    cycle_hour = (availability_cutoff.hour // 6) * 6
    first_run = availability_cutoff.replace(hour=cycle_hour)

    candidates: list[tuple[datetime, int]] = []
    for step in range(6):
        run = first_run - timedelta(hours=6 * step)
        forecast_hour = int((target - run).total_seconds() // 3600)
        if 0 <= forecast_hour <= 120:
            candidates.append((run, forecast_hour))
    return candidates


def _build_filter_url(run_utc: datetime, forecast_hour: int) -> str:
    cycle = f"{run_utc.hour:02d}"
    params = {
        "file": f"gfs.t{cycle}z.pgrb2.0p25.f{forecast_hour:03d}",
        "lev_10_m_above_ground": "on",
        "lev_850_mb": "on",
        "lev_700_mb": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "subregion": "",
        "leftlon": "0",
        "rightlon": "360",
        "toplat": "90",
        "bottomlat": "-90",
        "dir": f"/gfs.{run_utc:%Y%m%d}/{cycle}/atmos",
    }
    return f"{GFS_FILTER_URL}?{urlencode(params)}"


def _download_latest_grib(target_path: Path, now_utc: datetime) -> tuple[datetime, int, str]:
    last_error: Exception | None = None
    candidates = _candidate_runs(now_utc)

    for index, (run_utc, forecast_hour) in enumerate(candidates):
        url = _build_filter_url(run_utc, forecast_hour)
        try:
            response = requests.get(
                url,
                timeout=120,
                headers={"User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater"},
            )
            response.raise_for_status()
            data = response.content

            # NOMADS may return an HTML error page with HTTP 200 when a file is not
            # ready. A GRIB2 payload always starts with the ASCII magic "GRIB".
            if len(data) < 16 or data[:4] != b"GRIB":
                raise RuntimeError(
                    f"NOMADS did not return GRIB2 data for {run_utc:%Y-%m-%d %HZ} "
                    f"f{forecast_hour:03d}"
                )

            target_path.write_bytes(data)
            return run_utc, forecast_hour, url
        except Exception as exc:  # noqa: BLE001 - fallback across model cycles
            last_error = exc
            if index < len(candidates) - 1:
                # NOMADS asks automated clients to avoid tight request loops.
                time.sleep(10)

    raise RuntimeError(f"Unable to download usable GFS wind data: {last_error}")


def _message_kind(gid: int) -> tuple[str, str] | None:
    short_name = str(codes_get(gid, "shortName")).lower()
    type_of_level = str(codes_get(gid, "typeOfLevel"))
    level = float(codes_get(gid, "level"))

    if short_name in {"u", "10u", "ugrd"}:
        component = "u"
    elif short_name in {"v", "10v", "vgrd"}:
        component = "v"
    else:
        return None

    if type_of_level == "heightAboveGround" and math.isclose(level, 10.0):
        return "surface", component
    if type_of_level in {"isobaricInhPa", "isobaricInPa"}:
        level_hpa = level / 100.0 if type_of_level == "isobaricInPa" else level
        if math.isclose(level_hpa, 850.0):
            return "850", component
        if math.isclose(level_hpa, 700.0):
            return "700", component

    return None


def _read_grib_fields(grib_path: Path) -> dict[str, dict[str, np.ndarray]]:
    fields: dict[str, dict[str, np.ndarray]] = {
        "surface": {},
        "850": {},
        "700": {},
    }

    with grib_path.open("rb") as handle:
        while True:
            gid = codes_grib_new_from_file(handle)
            if gid is None:
                break
            try:
                kind = _message_kind(gid)
                if kind is None:
                    continue

                level_key, component = kind
                ni = int(codes_get(gid, "Ni"))
                nj = int(codes_get(gid, "Nj"))
                values = np.asarray(codes_get_array(gid, "values"), dtype=np.float32)
                values = values.reshape((nj, ni))

                first_lat = float(codes_get(gid, "latitudeOfFirstGridPointInDegrees"))
                last_lat = float(codes_get(gid, "latitudeOfLastGridPointInDegrees"))
                if first_lat < last_lat:
                    values = np.flipud(values)

                # GFS is 0..359.75 E. Roll 180 degrees so texture U=0 starts at
                # 180 W and U=0.5 is Greenwich, matching ordinary equirectangular maps.
                values = np.roll(values, -(ni // 2), axis=1)
                fields[level_key][component] = values
            finally:
                codes_release(gid)

    for level_key in fields:
        missing = {"u", "v"} - fields[level_key].keys()
        if missing:
            raise RuntimeError(
                f"Missing GFS wind component(s) for {level_key}: {sorted(missing)}"
            )

    return fields


def _encode_wind_texture(u: np.ndarray, v: np.ndarray) -> Image.Image:
    if u.shape != v.shape:
        raise ValueError("U/V wind arrays have different shapes")

    valid = np.isfinite(u) & np.isfinite(v)
    safe_u = np.where(valid, u, 0.0)
    safe_v = np.where(valid, v, 0.0)

    speed = np.sqrt(safe_u * safe_u + safe_v * safe_v)
    denom = np.maximum(speed, 1e-6)
    dir_x = safe_u / denom
    dir_y = safe_v / denom

    rgba = np.empty((*u.shape, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(np.rint((dir_x * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)
    rgba[..., 1] = np.clip(np.rint((dir_y * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)
    rgba[..., 2] = np.clip(
        np.rint(np.minimum(speed, WIND_SPEED_MAX_MS) / WIND_SPEED_MAX_MS * 255.0),
        0,
        255,
    ).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)

    image = Image.fromarray(rgba, mode="RGBA")
    if image.size != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
        image = image.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.BILINEAR)
    return image


def update_wind_textures(output_dir: Path, work_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    grib_path = work_dir / "gfs_wind.grib2"
    run_utc, forecast_hour, source_url = _download_latest_grib(grib_path, now_utc)
    fields = _read_grib_fields(grib_path)

    for level_key, output_name in _LEVEL_OUTPUTS.items():
        image = _encode_wind_texture(
            fields[level_key]["u"],
            fields[level_key]["v"],
        )
        tmp_path = output_dir / f"{output_name}.tmp"
        image.save(tmp_path, format="PNG", optimize=True)
        tmp_path.replace(output_dir / output_name)

    valid_utc = run_utc + timedelta(hours=forecast_hour)
    return {
        "gfsRunUtc": run_utc.isoformat().replace("+00:00", "Z"),
        "gfsForecastHour": forecast_hour,
        "gfsValidUtc": valid_utc.isoformat().replace("+00:00", "Z"),
        "gfsSourceUrl": source_url,
        "windSpeedMaxMs": WIND_SPEED_MAX_MS,
        "windTextureWidth": OUTPUT_WIDTH,
        "windTextureHeight": OUTPUT_HEIGHT,
        "windEncoding": {
            "R": "normalized eastward direction X, -1..+1 mapped to 0..255",
            "G": "normalized northward direction Y, -1..+1 mapped to 0..255",
            "B": f"wind speed, 0..{WIND_SPEED_MAX_MS:g} m/s mapped to 0..255",
            "A": "valid data mask, valid=255, missing=0",
        },
    }

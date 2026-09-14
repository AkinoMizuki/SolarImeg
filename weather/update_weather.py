from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from cloud_generator import CLOUD_PROCESSING_VERSION, update_cloud_textures
from wind_generator import update_wind_textures

PUBLISHED_BASE_URL = "https://akinomizuki.github.io/SolarImeg/weather"
OUTPUT_DIR = Path("_site/weather")
WORK_DIR = Path(".weather_work")
PUBLIC_FILES = (
    "cloud_previous.png",
    "cloud_current.png",
    "specular_previous.jpg",
    "specular_current.jpg",
    "wind_surface.png",
    "wind_850hpa.png",
    "wind_700hpa.png",
    "metadata.json",
)


def _utc_now_string() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _seed_from_published_site(output_dir: Path) -> dict[str, bool]:
    """Copy the currently deployed weather files into the new Pages artifact."""
    result: dict[str, bool] = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in PUBLIC_FILES:
        url = f"{PUBLISHED_BASE_URL}/{name}"
        try:
            response = requests.get(
                url,
                timeout=30,
                headers={
                    "Cache-Control": "no-cache",
                    "User-Agent": "AkinoMizuki-SolarImeg/WeatherUpdater",
                },
                params={"t": str(int(datetime.now(timezone.utc).timestamp()))},
            )
            response.raise_for_status()
            (output_dir / name).write_bytes(response.content)
            result[name] = True
        except Exception as exc:  # noqa: BLE001 - first deployment is expected to 404
            print(f"Published fallback unavailable for {name}: {exc}")
            result[name] = False

    return result


def _read_existing_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Ignoring invalid previous metadata.json: {exc}")
        return {}


def main() -> None:
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    seeded = _seed_from_published_site(OUTPUT_DIR)
    previous_metadata = _read_existing_metadata(OUTPUT_DIR / "metadata.json")

    previous_cloud_previous_utc = previous_metadata.get("cloudPreviousUtc")
    previous_cloud_current_utc = previous_metadata.get("cloudCurrentUtc")
    previous_specular_previous_utc = previous_metadata.get(
        "specularPreviousUtc", previous_cloud_previous_utc
    )
    previous_specular_current_utc = previous_metadata.get(
        "specularCurrentUtc", previous_cloud_current_utc
    )
    previous_processing_version = previous_metadata.get("cloudProcessingVersion")
    force_cloud_history_reset = (
        previous_processing_version != CLOUD_PROCESSING_VERSION
    )

    metadata: dict[str, Any] = dict(previous_metadata)
    metadata["generatedUtc"] = _utc_now_string()
    metadata["schemaVersion"] = 3
    metadata["publishedFallbackSeeded"] = seeded

    cloud_error: Exception | None = None
    wind_error: Exception | None = None

    try:
        cloud_result = update_cloud_textures(
            OUTPUT_DIR,
            force_history_reset=force_cloud_history_reset,
        )
        metadata.update(cloud_result)

        if cloud_result["cloudHistoryReset"]:
            # First deployment or output-layout change: cloud/specular previous
            # and current intentionally begin as the same paired observation.
            current_utc = _utc_now_string()
            metadata["cloudPreviousUtc"] = current_utc
            metadata["cloudCurrentUtc"] = current_utc
            metadata["specularPreviousUtc"] = current_utc
            metadata["specularCurrentUtc"] = current_utc
        elif cloud_result["cloudImageChanged"]:
            # Normal transition: old cloud/specular current become previous and
            # both new current files share the same observation timestamp.
            current_utc = _utc_now_string()
            previous_utc = previous_cloud_current_utc or current_utc
            metadata["cloudPreviousUtc"] = previous_utc
            metadata["cloudCurrentUtc"] = current_utc
            metadata["specularPreviousUtc"] = (
                previous_specular_current_utc or previous_utc
            )
            metadata["specularCurrentUtc"] = current_utc
        else:
            # Upstream pair did not change. Keep both interpolation endpoints
            # and timestamps stable instead of inventing a new observation.
            if previous_cloud_previous_utc is not None:
                metadata["cloudPreviousUtc"] = previous_cloud_previous_utc
            if previous_cloud_current_utc is not None:
                metadata["cloudCurrentUtc"] = previous_cloud_current_utc
            if previous_specular_previous_utc is not None:
                metadata["specularPreviousUtc"] = previous_specular_previous_utc
            if previous_specular_current_utc is not None:
                metadata["specularCurrentUtc"] = previous_specular_current_utc
    except Exception as exc:  # noqa: BLE001 - retain prior published texture when possible
        cloud_error = exc
        print(
            "Cloud/specular update failed; keeping published fallback if available: "
            f"{exc}"
        )

    try:
        metadata.update(update_wind_textures(OUTPUT_DIR, WORK_DIR))
        metadata["windUpdatedUtc"] = _utc_now_string()
    except Exception as exc:  # noqa: BLE001 - retain prior published texture when possible
        wind_error = exc
        print(f"Wind update failed; keeping published fallback if available: {exc}")

    metadata["cloudStatus"] = "updated" if cloud_error is None else "fallback"
    metadata["specularStatus"] = metadata["cloudStatus"]
    metadata["windStatus"] = "updated" if wind_error is None else "fallback"
    metadata["cloudError"] = None if cloud_error is None else str(cloud_error)
    metadata["specularError"] = metadata["cloudError"]
    metadata["windError"] = None if wind_error is None else str(wind_error)

    required_images = PUBLIC_FILES[:-1]
    missing = [name for name in required_images if not (OUTPUT_DIR / name).exists()]
    if missing:
        raise RuntimeError(
            "Weather generation failed and no published fallback exists for: "
            + ", ".join(missing)
        )

    (OUTPUT_DIR / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Weather files ready:")
    for name in PUBLIC_FILES:
        path = OUTPUT_DIR / name
        print(f"  {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

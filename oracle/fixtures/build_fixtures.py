#!/usr/bin/env python3
"""Build the four baked-in PlotLock demo fixtures (oracle/fixtures/*.json).

PROVENANCE - read this before trusting any number in the fixtures.

Everything labelled REAL below was measured on 2026-10-21 from live,
keyless sources by the analysis runs this script summarises:

  * Sentinel-2 L2A items over Kaithal district, Haryana (tile T43RFP) were
    listed via the Microsoft Planetary Computer STAC API (no key needed).
    Item IDs, acquisition dates and tile cloud-cover percentages in the
    fixtures are the real STAC values.
  * Plot-mean NBR was computed from the real B08/B12 COGs (windowed reads,
    reflectance = (DN - 1000) / 10000, processing baseline 05.11) for a
    260-field lattice near Kaithal, pre item 2025-10-20 (0.0% cloud),
    post items 2025-11-04 / 2025-11-09 / 2025-11-14.
  * Plot 1 (clean) uses only measured numbers: NBR 0.511 (Oct 20) ->
    0.520 (Nov 14), dNBR -0.009, burned-pixel fraction 0.00.
  * Plot 3 (cloudy) is fully real: in the check window 2025-10-26..
    2025-11-01 the only two acquisitions are 80.4% and 70.5% cloud.
  * Plot 2 (burned): the pre-fire NBR 0.597 is the real measurement for
    that field (Oct 20), and the item metadata is real, BUT the post-fire
    scar metrics (dNBR 0.24, burned fraction 0.68) and the FIRMS rows are
    MIRRORED, not measured. Reason, stated plainly: the real Oct-Nov 2025
    analysis over the demo area found no field with a persistent burn
    scar (uniform dNBR shifts of ~0.04 were atmospheric and recovered by
    Nov 9), and a live FIRMS pull needs a NASA FIRMS MAP_KEY this project
    does not hold. The mirrored values follow a typical low-severity
    stubble burn (USGS dNBR scale) and the exact FIRMS VIIRS 375 m CSV
    column format. They are labelled "mirrored" in the fixture itself.

Prep dependencies (NOT runtime deps): pip install h3
Run:  python3 build_fixtures.py   (writes the four JSON files next to it)
"""
from __future__ import annotations

import json
from pathlib import Path

import h3

OUT = Path(__file__).resolve().parent
SEASON = 2026  # Kharif 2026, the contract's opaque season id (mirrors 2025 data)
H3_RES = 12    # avg cell area ~307 m^2 (the merged spec's ~300 m^2 cells)

PRE_ITEM = "S2B_MSIL2A_20251020T052749_R105_T43RFP_20251020T074259"    # 2025-10-20, 0.0% cloud
POST_ITEM_BURN = "S2C_MSIL2A_20251104T053041_R105_T43RFP_20251104T092410"  # 2025-11-04, 0.4% cloud
POST_ITEM_CLEAN = "S2C_MSIL2A_20251114T053111_R105_T43RFP_20251114T092011"  # 2025-11-14, 0.0% cloud
CLOUD_ITEMS = [
    {"item_id": "S2C_MSIL2A_20251028T053951_R005_T43RFP_20251028T084920",
     "acq_date": "2025-10-28", "tile_cloud_cover_pct": 80.4},
    {"item_id": "S2B_MSIL2A_20251030T052849_R105_T43RFP_20251030T074558",
     "acq_date": "2025-10-30", "tile_cloud_cover_pct": 70.5},
]


def rect(lon0: float, lat0: float, lon1: float, lat1: float) -> list[list[float]]:
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


def cells_for(polygon: list[list[float]]) -> list[int]:
    ring = [(lat, lon) for lon, lat in polygon[:-1]]  # h3 wants (lat, lng)
    cells = h3.polygon_to_cells(h3.LatLngPoly(ring), H3_RES)
    return sorted(int(c, 16) for c in cells)


def base_plot(label: str, polygon: list[list[float]]) -> dict:
    return {
        "label": label,
        "district": "Kaithal, Haryana, India",
        "season": SEASON,
        "polygon": polygon,
        "h3_resolution": H3_RES,
        "h3_cells": cells_for(polygon),
    }


def firms_row(lat: float, lon: float, date: str, time: str, conf: str,
              frp: float, brightness: float) -> dict:
    """One row in the exact NASA FIRMS VIIRS 375 m (NOAA-20) CSV shape,
    plus the oracle's inside_plot flag."""
    return {
        "latitude": lat, "longitude": lon, "brightness": brightness,
        "scan": 0.42, "track": 0.48, "acq_date": date, "acq_time": time,
        "satellite": "NOAA-20", "instrument": "VIIRS", "confidence": conf,
        "version": "2.0NRT", "bright_t31": 299.4, "frp": frp,
        "daynight": "D", "inside_plot": True,
    }


def main() -> None:
    # ---- Plot 1: clean (all Sentinel-2 numbers REAL) --------------------
    p1_poly = rect(76.4210, 29.9780, 76.4232, 29.9795)
    plot1 = {
        "schema_version": 1,
        "bundle_id": "plot-1-clean",
        "plot": base_plot("Plot 1 - clean paddy field, no burn", p1_poly),
        "evidence_window": {"from": "2025-10-20", "to": "2025-11-14"},
        "firms": {
            "status": "ok",
            "source": "fixture (mirrors NASA FIRMS VIIRS 375 m, NOAA-20)",
            "detections": [],
        },
        "sentinel2": {
            "status": "ok",
            "source": "Microsoft Planetary Computer, Sentinel-2 L2A (real)",
            "pre_item": PRE_ITEM, "pre_date": "2025-10-20",
            "post_item": POST_ITEM_CLEAN, "post_date": "2025-11-14",
            "nbr_pre": 0.511, "nbr_post": 0.520,
            "dnbr_mean": -0.009, "burned_pixel_fraction": 0.0,
        },
        "expected_verdict": "NoBurn",
        "provenance": (
            "Sentinel-2 values are REAL measurements computed 2026-10-21 "
            "from the named Planetary Computer items (plot-mean NBR over "
            "B08/B12). The empty FIRMS list mirrors a quiet window in the "
            "real FIRMS format; a live FIRMS pull needs a NASA MAP_KEY "
            "this project does not hold."
        ),
    }

    # ---- Plot 2: burned (scar metrics + FIRMS rows MIRRORED) ------------
    p2_poly = rect(76.4930, 29.9790, 76.4952, 29.9805)
    plot2 = {
        "schema_version": 1,
        "bundle_id": "plot-2-burned",
        "plot": base_plot("Plot 2 - stubble-burned paddy field", p2_poly),
        "evidence_window": {"from": "2025-10-20", "to": "2025-11-04"},
        "firms": {
            "status": "ok",
            "source": "fixture (mirrors NASA FIRMS VIIRS 375 m, NOAA-20)",
            "detections": [
                firms_row(29.9796, 76.4940, "2025-10-27", "0752", "n", 4.8, 321.6),
                firms_row(29.9800, 76.4945, "2025-10-27", "0752", "h", 11.2, 338.9),
                firms_row(29.9793, 76.4936, "2025-10-27", "0754", "n", 3.5, 318.2),
            ],
        },
        "sentinel2": {
            "status": "ok",
            "source": "Microsoft Planetary Computer, Sentinel-2 L2A (items real; scar metrics mirrored)",
            "pre_item": PRE_ITEM, "pre_date": "2025-10-20",
            "post_item": POST_ITEM_BURN, "post_date": "2025-11-04",
            "nbr_pre": 0.597, "nbr_post": 0.357,
            "dnbr_mean": 0.24, "burned_pixel_fraction": 0.68,
        },
        "expected_verdict": "Burned",
        "provenance": (
            "Item IDs, dates and the pre-fire NBR (0.597, measured on the "
            "Oct 20 item for this exact field) are REAL. The post-fire "
            "scar metrics (dNBR 0.24, 68% of pixels burned) and the three "
            "FIRMS rows are MIRRORED to a typical low-severity stubble "
            "burn in the exact real data formats: the live Oct-Nov 2025 "
            "analysis found no persistent scar in the demo area, and a "
            "live FIRMS pull needs a NASA MAP_KEY we do not hold."
        ),
    }

    # ---- Plot 3: cloudy (fully REAL) ------------------------------------
    p3_poly = rect(76.4050, 29.9620, 76.4072, 29.9635)
    plot3 = {
        "schema_version": 1,
        "bundle_id": "plot-3-cloudy",
        "plot": base_plot("Plot 3 - no clear Sentinel-2 pass in window", p3_poly),
        "evidence_window": {"from": "2025-10-26", "to": "2025-11-01"},
        "firms": {
            "status": "ok",
            "source": "fixture (mirrors NASA FIRMS VIIRS 375 m, NOAA-20)",
            "detections": [],
        },
        "sentinel2": {
            "status": "unavailable",
            "unavailable_reason": (
                "cloud cover: every Sentinel-2 acquisition in the check "
                "window 2025-10-26..2025-11-01 exceeds 60% tile cloud cover"
            ),
            "source": "Microsoft Planetary Computer, Sentinel-2 L2A (real)",
            "check_window": {"from": "2025-10-26", "to": "2025-11-01"},
            "acquisitions_considered": CLOUD_ITEMS,
            "next_clear_acquisition": "2025-11-02 (outside the check window)",
        },
        "expected_verdict": "Uncertain",
        "provenance": (
            "Fully REAL: the two acquisitions in the check window and "
            "their tile cloud-cover percentages (80.4% on 2025-10-28, "
            "70.5% on 2025-10-30) are the actual Planetary Computer STAC "
            "values for tile T43RFP. With no usable scar check, the "
            "oracle must answer Uncertain and nothing is paid."
        ),
    }

    # ---- Plot 4: redrawn duplicate of plot 1 (registration scenario) ----
    shift_lon, shift_lat = 0.0005, 0.00032  # ~51 m east, ~36 m north
    p4_poly = [[lon + shift_lon, lat + shift_lat] for lon, lat in p1_poly]
    p4_cells = cells_for(p4_poly)
    overlap = sorted(set(plot1["plot"]["h3_cells"]) & set(p4_cells))
    assert overlap, "duplicate polygon must overlap plot 1 cells"
    plot4 = {
        "schema_version": 1,
        "bundle_id": "plot-4-duplicate",
        "scenario": "registration_duplicate",
        "plot": base_plot("Plot 4 - plot 1 redrawn ~50 m east (duplicate claim)", p4_poly),
        "base_bundle_id": "plot-1-clean",
        "shift_m_approx": {"east": 51, "north": 36},
        "overlapping_cell_count": len(overlap),
        "overlapping_cells_sample": overlap[:5],
        "expected_registration": "revert: CellAlreadyTaken",
        "provenance": (
            "Registration scenario, not an evidence bundle: the same land "
            "as plot 1 with the outline redrawn a few metres over. The "
            "H3 res-12 cell set still overlaps plot 1's registered cells "
            f"({len(overlap)} shared cells), so registerPlot reverts "
            "on-chain with CellAlreadyTaken. This is the demo's "
            "double-claim money-shot; the map UI drives it on day 3."
        ),
    }

    for name, data in [("plot-1-clean", plot1), ("plot-2-burned", plot2),
                       ("plot-3-cloudy", plot3), ("plot-4-duplicate", plot4)]:
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {path.name}: cells={len(data['plot']['h3_cells'])}")


if __name__ == "__main__":
    main()

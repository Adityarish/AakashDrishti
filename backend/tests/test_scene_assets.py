"""Unity scene refinement: which footprints stay buildings, where trees go, how detections become shapes."""

from __future__ import annotations

import math

import numpy as np

from app.export.scene_assets import build_objects, build_trees, classify_buildings
from app.landcover.classify import TREE

SIZE = 256


def _scene():
    rgb = np.full((SIZE, SIZE, 3), 120, dtype=np.uint8)
    rgb[20:70, 20:90] = (225, 225, 220)      # white flat roof
    rgb[20:70, 150:230] = (70, 78, 92)       # dark blue-grey roof: low saturation signal must NOT read as vegetation
    rgb[150:230, 40:130] = (118, 84, 60)     # bare brown tree canopy
    return rgb


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_roofs_stay_buildings_and_vegetation_becomes_trees():
    rgb = _scene()
    buildings = [
        {"id": 1, "footprint": _rect(20, 20, 90, 70), "height_m": 9.0},
        {"id": 2, "footprint": _rect(150, 20, 230, 70), "height_m": 7.0},
        # irregular (non-rectangular) brown blob
        {"id": 3, "footprint": [[40, 150], [130, 160], [120, 200], [95, 230], [60, 215]], "height_m": 6.0},
    ]
    kept, tree_masks, stats = classify_buildings(buildings, rgb, None, [])

    assert [b["id"] for b in kept] == [1, 2]
    assert stats["dropped_vegetation"] == 1 and len(tree_masks) == 1


def test_parked_car_cluster_is_not_a_building():
    rgb = _scene()
    cars = [{"label": "small vehicle", "polygon": _rect(150 + 10 * i, 20, 158 + 10 * i, 70)} for i in range(8)]
    kept, _, stats = classify_buildings([{"id": 2, "footprint": _rect(150, 20, 230, 70), "height_m": 7.0}], rgb, None, cars)
    assert kept == [] and stats["dropped_vehicle_cluster"] == 1


def test_trees_stay_inside_mask_and_clear_of_roofs():
    rgb = _scene()
    labels = np.zeros((SIZE, SIZE), dtype=np.uint8)
    labels[150:230, 40:130] = TREE
    labels[20:70, 20:90] = TREE  # land cover wrongly paints a roof as tree
    ndsm = np.full((SIZE, SIZE), 6.0, dtype=np.float32)
    roof = [_rect(20, 20, 90, 70)]

    trees = build_trees(rgb, ndsm, None, labels, [], 0.5, True, lambda c, r: [c * 0.5, (SIZE - r) * 0.5], building_footprints=roof)

    assert trees
    for t in trees:
        col, row = t["position"][0] / 0.5, SIZE - t["position"][1] / 0.5
        assert 40 <= col <= 130 and 150 <= row <= 230       # only inside the real canopy mask
        assert 3.0 <= t["height_m"] <= 22.0 and t["crown_radius_m"] > 0


def test_vehicle_becomes_sized_oriented_shape():
    rgb = np.full((SIZE, SIZE, 3), 90, dtype=np.uint8)
    rgb[100:104, 60:70] = (200, 30, 30)  # a red car, 10 px long x 4 px wide, long axis east-west
    poly = _rect(60, 100, 70, 104)
    detections = [{"id": 5, "label": "small vehicle", "confidence": 0.9, "polygon": poly, "center_px": [65, 102]}]

    # 0.5 m per pixel -> the box is 5 m x 2 m
    out = build_objects(detections, rgb, None, (SIZE, SIZE), (SIZE * 0.5, SIZE * 0.5), lambda c, r: [c * 0.5, (SIZE - r) * 0.5])

    assert len(out) == 1
    car = out[0]
    assert car["kind"] == "vehicle"
    assert math.isclose(car["size_m"]["length"], 5.0, abs_tol=0.01) and math.isclose(car["size_m"]["width"], 2.0, abs_tol=0.01)
    assert abs(((car["yaw_deg"] + 90) % 180) - 90) < 1.0   # along the east axis (0 or 180 degrees)
    assert car["color_rgb"][0] > 150 and car["color_rgb"][1] < 80   # the photo colour, not a default


def test_implausible_vehicle_box_is_clamped():
    rgb = np.full((SIZE, SIZE, 3), 90, dtype=np.uint8)
    huge = _rect(10, 10, 110, 40)  # 50 m x 15 m at 0.5 m/px: not a car
    out = build_objects([{"id": 1, "label": "small vehicle", "polygon": huge, "center_px": [60, 25]}], rgb, None,
                        (SIZE, SIZE), (SIZE * 0.5, SIZE * 0.5), lambda c, r: [c * 0.5, r * 0.5])
    assert out[0]["size_m"]["length"] <= 6.0 and out[0]["size_m"]["width"] <= 2.3

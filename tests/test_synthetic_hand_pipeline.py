from __future__ import annotations

import csv
import gzip
from pathlib import Path

import numpy as np
import pytest

from ml.synthetic_hand_pipeline import (
    CONTROL_CHANNELS,
    MARKER_NAMES,
    _rotation_matrix,
    estimate_six_controls,
    generate_local_markers,
    load_labeled_frames,
    run_pipeline,
)


def test_layout_contains_exactly_24_unique_markers() -> None:
    assert list(MARKER_NAMES) == list(range(1, 25))
    assert len(set(MARKER_NAMES.values())) == 24


def test_control_estimate_is_invariant_to_global_pose() -> None:
    truth = {
        "thumb_flexion": 0.37,
        "thumb_opposition": 0.62,
        "index_flexion": 0.18,
        "middle_flexion": 0.44,
        "ring_flexion": 0.71,
        "little_flexion": 0.89,
    }
    local = generate_local_markers(truth)
    rotation = _rotation_matrix(roll_deg=17.0, pitch_deg=-23.0, yaw_deg=41.0)
    translation = np.array([320.0, -150.0, 870.0])
    transformed = {
        marker_id: rotation @ point + translation for marker_id, point in local.items()
    }

    estimated, _angles = estimate_six_controls(transformed)

    for channel in CONTROL_CHANNELS:
        assert estimated[channel] == pytest.approx(truth[channel], abs=1e-9)


def test_pipeline_writes_nokov_shaped_raw_data_and_six_outputs(tmp_path: Path) -> None:
    result = run_pipeline(
        frames=8,
        fps=90.0,
        noise_mm=0.0,
        seed=7,
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
    )

    with gzip.open(result.raw_session / "frames.csv.gz", "rt", encoding="utf-8-sig") as stream:
        frame_rows = list(csv.DictReader(stream))
    with gzip.open(result.raw_session / "points.csv.gz", "rt", encoding="utf-8-sig") as stream:
        point_rows = list(csv.DictReader(stream))
    with (result.processed_session / "controls_6d.csv").open(
        encoding="utf-8-sig"
    ) as stream:
        control_rows = list(csv.DictReader(stream))

    assert len(frame_rows) == 8
    assert len(point_rows) == 8 * 24  # hand mode saves labeled_marker rows only
    assert len(control_rows) == 8
    assert {row["labeled_markers"] for row in frame_rows} == {"24"}
    assert result.overall_mae < 1e-9
    assert result.overall_max_error < 1e-8


def test_load_labeled_frames_normalizes_right_hand_marker_ids(tmp_path: Path) -> None:
    points_csv = tmp_path / "points.csv"
    with points_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "sample_index",
                "frame_no",
                "timestamp_ms",
                "elapsed_s",
                "category",
                "group_name",
                "point_id_or_index",
                "x_mm",
                "y_mm",
                "z_mm",
                "valid",
                "size_mm",
            ],
        )
        writer.writeheader()
        for marker_id in range(25, 49):
            writer.writerow(
                {
                    "sample_index": 1,
                    "frame_no": 100,
                    "timestamp_ms": 1000,
                    "elapsed_s": 0.0,
                    "category": "labeled_marker",
                    "group_name": "",
                    "point_id_or_index": marker_id,
                    "x_mm": marker_id,
                    "y_mm": 0.0,
                    "z_mm": 0.0,
                    "valid": 1,
                    "size_mm": 7.5,
                }
            )

    frames = load_labeled_frames(points_csv)

    assert len(frames) == 1
    assert frames[0].marker_id_offset == 24
    assert sorted(frames[0].markers) == list(range(1, 25))

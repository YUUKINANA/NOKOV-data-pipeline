from __future__ import annotations

import csv
import json
from pathlib import Path

from ml.process_hand_sessions import process_skeleton_session


def test_process_skeleton_session_writes_summary_and_relative_angles(
    tmp_path: Path,
) -> None:
    session = tmp_path / "raw" / "mocap_test"
    processed = tmp_path / "processed" / "mocap_test"
    session.mkdir(parents=True)
    processed.mkdir(parents=True)

    (session / "skeleton_descriptions.json").write_text(
        json.dumps(
            {
                "skeletons": [
                    {
                        "name": "hand",
                        "id": 1,
                        "segment_count": 2,
                        "segments": [
                            {"id": 10, "name": "palm", "parent_id": 0},
                            {"id": 11, "name": "index", "parent_id": 10},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with (session / "skeleton_segments.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "sample_index",
                "frame_no",
                "timestamp_ms",
                "elapsed_s",
                "skeleton_id",
                "segment_index",
                "segment_id",
                "x_mm",
                "y_mm",
                "z_mm",
                "qx",
                "qy",
                "qz",
                "qw",
                "marker_count",
                "mean_error",
                "params",
                "marker_ids",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_index": 1,
                "frame_no": 100,
                "timestamp_ms": 1_000,
                "elapsed_s": 0.0,
                "skeleton_id": 1,
                "segment_index": 0,
                "segment_id": 10,
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "qx": 0,
                "qy": 0,
                "qz": 0,
                "qw": 1,
                "marker_count": 0,
                "mean_error": 0,
                "params": 0,
                "marker_ids": "",
            }
        )
        writer.writerow(
            {
                "sample_index": 1,
                "frame_no": 100,
                "timestamp_ms": 1_000,
                "elapsed_s": 0.0,
                "skeleton_id": 1,
                "segment_index": 1,
                "segment_id": 11,
                "x_mm": 1,
                "y_mm": 0,
                "z_mm": 0,
                "qx": 0,
                "qy": 0,
                "qz": 0,
                "qw": 1,
                "marker_count": 0,
                "mean_error": 0,
                "params": 0,
                "marker_ids": "",
            }
        )
        for segment_id in (10, 11):
            writer.writerow(
                {
                    "sample_index": 1,
                    "frame_no": 100,
                    "timestamp_ms": 1_000,
                    "elapsed_s": 0.0,
                    "skeleton_id": 0,
                    "segment_index": segment_id - 10,
                    "segment_id": segment_id,
                    "x_mm": 9_999_999,
                    "y_mm": 9_999_999,
                    "z_mm": 9_999_999,
                    "qx": 9_999_999,
                    "qy": 9_999_999,
                    "qz": 9_999_999,
                    "qw": 1,
                    "marker_count": 3,
                    "mean_error": 0,
                    "params": 0,
                    "marker_ids": "1;2;3",
                }
            )

    summary = process_skeleton_session(session, processed)

    assert summary["skeleton_available"] is True
    assert summary["skeleton_segments"] == 2
    assert summary["invalid_skeleton_rows_skipped"] == 2

    with (processed / "skeleton_segment_summary.csv").open(
        encoding="utf-8-sig"
    ) as stream:
        summary_rows = list(csv.DictReader(stream))
    with (processed / "skeleton_segment_angles.csv").open(
        encoding="utf-8-sig"
    ) as stream:
        angle_rows = list(csv.DictReader(stream))

    assert summary_rows[1]["segment_name"] == "index"
    assert len(summary_rows) == 2
    assert len(angle_rows) == 1
    assert angle_rows[0]["segment_id"] == "11"
    assert float(angle_rows[0]["relative_orientation_angle_deg"]) == 0.0

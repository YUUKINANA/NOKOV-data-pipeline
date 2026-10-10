from __future__ import annotations

import gzip
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "mocap"))

from inspect_mocap import SessionRecorder  # noqa: E402


def test_late_frame_after_close_is_ignored(tmp_path: Path) -> None:
    recorder = SessionRecorder(tmp_path, compress_on_finish=False)
    snapshot = {
        "frame": 1,
        "timestamp_ms": 1_000,
        "latency": 1.0,
        "counts": {
            "marker_sets": 0,
            "labeled_markers": 0,
            "unidentified_markers": 0,
            "rigid_bodies": 0,
            "skeletons": 0,
            "analog_channels": 0,
        },
        "marker_sets": [],
        "labeled_markers": [],
        "unidentified_markers": [],
        "rigid_bodies": [],
        "skeletons": [],
    }

    recorder.write(snapshot, sample_index=1)
    recorder.close()
    recorder.write(snapshot, sample_index=2)

    rows = recorder.paths["frames"].read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 2  # header plus the one frame accepted before close


def test_hand_mode_can_compress_saved_csv_files(tmp_path: Path) -> None:
    recorder = SessionRecorder(tmp_path, save_mode="hand", compress_on_finish=True)
    snapshot = {
        "frame": 1,
        "timestamp_ms": 1_000,
        "latency": 1.0,
        "counts": {
            "marker_sets": 1,
            "labeled_markers": 1,
            "unidentified_markers": 1,
            "rigid_bodies": 1,
            "skeletons": 0,
            "analog_channels": 0,
        },
        "marker_sets": [
            {
                "name": "hand",
                "marker_count": 1,
                "visible_count": 1,
                "markers": [
                    {"index": 0, "xyz_mm": [1.0, 2.0, 3.0], "valid": True}
                ],
            }
        ],
        "labeled_markers": [
            {"id": 1, "xyz_mm": [1.0, 2.0, 3.0], "size": 9.0, "valid": True}
        ],
        "unidentified_markers": [
            {"index": 0, "xyz_mm": [1.0, 2.0, 3.0], "valid": True}
        ],
        "rigid_bodies": [
            {
                "id": 1,
                "position_mm": [1.0, 2.0, 3.0],
                "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "marker_count": 1,
                "mean_error": 0.0,
                "params": 0,
            }
        ],
        "skeletons": [
            {
                "id": 1,
                "segment_count": 1,
                "segments": [
                    {
                        "index": 0,
                        "id": 101,
                        "position_mm": [1.0, 2.0, 3.0],
                        "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "marker_count": 1,
                        "marker_ids": [1],
                        "marker_points_mm": [[1.0, 2.0, 3.0]],
                        "mean_error": 0.0,
                        "params": 0,
                    }
                ],
            }
        ],
    }

    recorder.write(snapshot, sample_index=1)
    recorder.close()

    assert not (recorder.session_dir / "frames.csv").exists()
    assert not (recorder.session_dir / "points.csv").exists()
    assert (recorder.session_dir / "frames.csv.gz").exists()
    assert (recorder.session_dir / "points.csv.gz").exists()
    assert (recorder.session_dir / "skeleton_segments.csv.gz").exists()
    assert "raw" not in recorder.paths
    assert (recorder.session_dir / "rigid_bodies.csv.gz").exists()

    with gzip.open(recorder.session_dir / "points.csv.gz", "rt", encoding="utf-8-sig") as stream:
        rows = stream.read().splitlines()
    assert len(rows) == 2
    assert "labeled_marker" in rows[1]

    with gzip.open(
        recorder.session_dir / "skeleton_segments.csv.gz", "rt", encoding="utf-8-sig"
    ) as stream:
        skeleton_rows = stream.read().splitlines()
    assert len(skeleton_rows) == 2
    assert "101" in skeleton_rows[1]

"""Generate a synthetic 24-marker hand session and recover six control values.

This module is an engineering fixture, not an anatomical hand model. It uses a
documented provisional marker topology so the project can exercise the same
``frames.csv``/``points.csv`` capture path before the real glove arrives.
The six outputs are normalized values in [0, 1]; they are not yet REVO2 motor
commands.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(PROJECT_ROOT))

CONTROL_CHANNELS = (
    "thumb_flexion",
    "thumb_opposition",
    "index_flexion",
    "middle_flexion",
    "ring_flexion",
    "little_flexion",
)

MARKER_NAMES = {
    1: "WristM",
    2: "WristIn",
    3: "WristOut",
    4: "HandOffset",
    5: "FingerThumb1",
    6: "FingerThumb2",
    7: "FingerThumb3",
    8: "FingerThumb4",
    9: "FingerIndex1",
    10: "FingerIndex2",
    11: "FingerIndex3",
    12: "FingerIndex4",
    13: "FingerMiddle1",
    14: "FingerMiddle2",
    15: "FingerMiddle3",
    16: "FingerMiddle4",
    17: "FingerRing1",
    18: "FingerRing2",
    19: "FingerRing3",
    20: "FingerRing4",
    21: "FingerPinky1",
    22: "FingerPinky2",
    23: "FingerPinky3",
    24: "FingerPinky4",
}

FINGER_MARKER_IDS = {
    "thumb": (5, 6, 7, 8),
    "index": (9, 10, 11, 12),
    "middle": (13, 14, 15, 16),
    "ring": (17, 18, 19, 20),
    "little": (21, 22, 23, 24),
}

FINGER_BASES_MM = {
    "index": np.array([-24.0, 72.0, 0.0]),
    "middle": np.array([-8.0, 76.0, 0.0]),
    "ring": np.array([9.0, 74.0, 0.0]),
    "little": np.array([25.0, 68.0, 0.0]),
}

FINGER_LENGTHS_MM = {
    "index": (45.0, 28.0, 20.0),
    "middle": (50.0, 31.0, 22.0),
    "ring": (46.0, 29.0, 21.0),
    "little": (38.0, 23.0, 18.0),
}

FINGER_MAX_FLEX_DEG = (70.0, 90.0, 65.0)
THUMB_MAX_FLEX_DEG = (45.0, 55.0, 35.0)
THUMB_BASE_YAW_DEG = 145.0
THUMB_MAX_OPPOSITION_DEG = 60.0


@dataclass(frozen=True)
class PipelineResult:
    raw_session: Path
    processed_session: Path
    overall_mae: float
    overall_max_error: float


@dataclass(frozen=True)
class LabeledFrame:
    sample_index: int
    frame_no: int
    timestamp_ms: int
    elapsed_s: float
    markers: dict[int, np.ndarray]
    marker_id_offset: int = 0


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        raise ValueError("Cannot normalize a zero-length vector")
    return vector / norm


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _angle_deg(first: np.ndarray, second: np.ndarray) -> float:
    cosine = float(np.dot(_unit(first), _unit(second)))
    return math.degrees(math.acos(min(max(cosine, -1.0), 1.0)))


def _direction(horizontal: np.ndarray, pitch_deg: float) -> np.ndarray:
    pitch_rad = math.radians(pitch_deg)
    horizontal = _unit(np.array([horizontal[0], horizontal[1], 0.0]))
    return np.array(
        [
            math.cos(pitch_rad) * horizontal[0],
            math.cos(pitch_rad) * horizontal[1],
            -math.sin(pitch_rad),
        ]
    )


def _finger_chain(
    base: np.ndarray,
    horizontal: np.ndarray,
    joint_angles_deg: Iterable[float],
    lengths_mm: Iterable[float],
) -> list[np.ndarray]:
    points = [np.asarray(base, dtype=float)]
    cumulative_angle = 0.0
    for joint_angle, length in zip(joint_angles_deg, lengths_mm, strict=True):
        cumulative_angle += float(joint_angle)
        points.append(points[-1] + _direction(horizontal, cumulative_angle) * length)
    return points


def synthetic_controls(elapsed_s: float) -> dict[str, float]:
    """Return six independently varying normalized control signals."""
    frequencies = (0.17, 0.11, 0.13, 0.19, 0.23, 0.29)
    phases = (0.0, 0.7, 1.1, 1.8, 2.4, 3.0)
    return {
        channel: _clamp01(
            0.5 + 0.45 * math.sin(2.0 * math.pi * frequency * elapsed_s + phase)
        )
        for channel, frequency, phase in zip(
            CONTROL_CHANNELS, frequencies, phases, strict=True
        )
    }


def generate_local_markers(controls: dict[str, float]) -> dict[int, np.ndarray]:
    """Forward-kinematics fixture producing 24 marker coordinates in mm."""
    markers: dict[int, np.ndarray] = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([-36.0, 0.0, 0.0]),
        3: np.array([36.0, 0.0, 0.0]),
        4: np.array([0.0, 68.0, 0.0]),
    }

    thumb_flexion = _clamp01(controls["thumb_flexion"])
    thumb_opposition = _clamp01(controls["thumb_opposition"])
    thumb_yaw = THUMB_BASE_YAW_DEG - THUMB_MAX_OPPOSITION_DEG * thumb_opposition
    thumb_horizontal = np.array(
        [math.cos(math.radians(thumb_yaw)), math.sin(math.radians(thumb_yaw)), 0.0]
    )
    thumb_angles = [value * thumb_flexion for value in THUMB_MAX_FLEX_DEG]
    thumb_points = _finger_chain(
        np.array([-40.0, 48.0, 0.0]),
        thumb_horizontal,
        thumb_angles,
        (36.0, 25.0, 20.0),
    )
    for marker_id, point in zip(
        FINGER_MARKER_IDS["thumb"], thumb_points, strict=True
    ):
        markers[marker_id] = point

    for finger in ("index", "middle", "ring", "little"):
        flexion = _clamp01(controls[f"{finger}_flexion"])
        joint_angles = [value * flexion for value in FINGER_MAX_FLEX_DEG]
        points = _finger_chain(
            FINGER_BASES_MM[finger],
            np.array([0.0, 1.0, 0.0]),
            joint_angles,
            FINGER_LENGTHS_MM[finger],
        )
        for marker_id, point in zip(
            FINGER_MARKER_IDS[finger], points, strict=True
        ):
            markers[marker_id] = point

    if set(markers) != set(MARKER_NAMES):
        raise AssertionError("Synthetic layout must contain exactly marker IDs 1..24")
    return markers


def _rotation_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    roll, pitch, yaw = map(math.radians, (roll_deg, pitch_deg, yaw_deg))
    rx = np.array(
        [[1.0, 0.0, 0.0], [0.0, math.cos(roll), -math.sin(roll)], [0.0, math.sin(roll), math.cos(roll)]]
    )
    ry = np.array(
        [[math.cos(pitch), 0.0, math.sin(pitch)], [0.0, 1.0, 0.0], [-math.sin(pitch), 0.0, math.cos(pitch)]]
    )
    rz = np.array(
        [[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]]
    )
    return rz @ ry @ rx


def apply_global_pose(
    markers: dict[int, np.ndarray], elapsed_s: float
) -> dict[int, np.ndarray]:
    """Move the entire hand so estimation cannot rely on world coordinates."""
    rotation = _rotation_matrix(
        roll_deg=8.0 * math.sin(0.7 * elapsed_s),
        pitch_deg=12.0 * math.sin(0.5 * elapsed_s + 0.3),
        yaw_deg=30.0 * math.sin(0.4 * elapsed_s + 0.8),
    )
    translation = np.array(
        [
            250.0 + 80.0 * math.sin(0.35 * elapsed_s),
            400.0 + 60.0 * math.sin(0.28 * elapsed_s + 0.6),
            700.0 + 90.0 * math.sin(0.31 * elapsed_s + 1.2),
        ]
    )
    return {marker_id: rotation @ point + translation for marker_id, point in markers.items()}


def _to_palm_coordinates(markers: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
    wrist_midpoint = markers[1]
    x_axis = _unit(markers[3] - markers[2])
    y_hint = markers[4] - wrist_midpoint
    y_axis = _unit(y_hint - np.dot(y_hint, x_axis) * x_axis)
    z_axis = _unit(np.cross(x_axis, y_axis))
    basis = np.column_stack((x_axis, y_axis, z_axis))
    return {
        marker_id: basis.T @ (point - wrist_midpoint)
        for marker_id, point in markers.items()
    }


def estimate_six_controls(
    markers: dict[int, np.ndarray]
) -> tuple[dict[str, float], dict[str, float]]:
    """Estimate provisional 6-D controls and diagnostic joint angles."""
    missing = sorted(set(MARKER_NAMES) - set(markers))
    if missing:
        raise ValueError(f"Missing required marker IDs: {missing}")

    local = _to_palm_coordinates(markers)
    controls: dict[str, float] = {}
    angles: dict[str, float] = {}

    thumb_ids = FINGER_MARKER_IDS["thumb"]
    thumb_segments = [
        local[thumb_ids[index + 1]] - local[thumb_ids[index]] for index in range(3)
    ]
    first_thumb = thumb_segments[0]
    thumb_mcp = math.degrees(
        math.atan2(-first_thumb[2], math.hypot(first_thumb[0], first_thumb[1]))
    )
    thumb_pip = _angle_deg(thumb_segments[0], thumb_segments[1])
    thumb_dip = _angle_deg(thumb_segments[1], thumb_segments[2])
    thumb_yaw = math.degrees(math.atan2(first_thumb[1], first_thumb[0]))
    thumb_opposition = THUMB_BASE_YAW_DEG - thumb_yaw

    angles.update(
        {
            "thumb_mcp_flex_deg": thumb_mcp,
            "thumb_pip_flex_deg": thumb_pip,
            "thumb_dip_flex_deg": thumb_dip,
            "thumb_opposition_deg": thumb_opposition,
        }
    )
    controls["thumb_flexion"] = _clamp01(
        np.mean(
            [
                thumb_mcp / THUMB_MAX_FLEX_DEG[0],
                thumb_pip / THUMB_MAX_FLEX_DEG[1],
                thumb_dip / THUMB_MAX_FLEX_DEG[2],
            ]
        )
    )
    controls["thumb_opposition"] = _clamp01(
        thumb_opposition / THUMB_MAX_OPPOSITION_DEG
    )

    for finger in ("index", "middle", "ring", "little"):
        ids = FINGER_MARKER_IDS[finger]
        segments = [local[ids[index + 1]] - local[ids[index]] for index in range(3)]
        first = segments[0]
        mcp = math.degrees(math.atan2(-first[2], math.hypot(first[0], first[1])))
        pip = _angle_deg(segments[0], segments[1])
        dip = _angle_deg(segments[1], segments[2])
        angles.update(
            {
                f"{finger}_mcp_flex_deg": mcp,
                f"{finger}_pip_flex_deg": pip,
                f"{finger}_dip_flex_deg": dip,
            }
        )
        controls[f"{finger}_flexion"] = _clamp01(
            np.mean(
                [
                    mcp / FINGER_MAX_FLEX_DEG[0],
                    pip / FINGER_MAX_FLEX_DEG[1],
                    dip / FINGER_MAX_FLEX_DEG[2],
                ]
            )
        )

    return controls, angles


def _snapshot(
    markers: dict[int, np.ndarray], frame_no: int, timestamp_ms: int
) -> dict[str, object]:
    marker_rows = [
        {
            "index": marker_id - 1,
            "xyz_mm": markers[marker_id].tolist(),
            "valid": True,
        }
        for marker_id in sorted(markers)
    ]
    labeled_rows = [
        {
            "id": marker_id,
            "xyz_mm": markers[marker_id].tolist(),
            "size": 7.5,
            "valid": True,
        }
        for marker_id in sorted(markers)
    ]
    return {
        "frame": frame_no,
        "timestamp_ms": timestamp_ms,
        "latency": 4.0,
        "counts": {
            "marker_sets": 1,
            "labeled_markers": 24,
            "unidentified_markers": 0,
            "rigid_bodies": 0,
            "skeletons": 0,
            "analog_channels": 0,
        },
        "marker_sets": [
            {
                "name": "synthetic_hand_24",
                "marker_count": 24,
                "visible_count": 24,
                "markers": marker_rows,
            }
        ],
        "labeled_markers": labeled_rows,
        "unidentified_markers": [],
        "rigid_bodies": [],
    }


def _write_dict_rows(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def existing_text_path(path: Path) -> Path:
    if path.exists():
        return path
    compressed = path.with_name(path.name + ".gz")
    if compressed.exists():
        return compressed
    raise FileNotFoundError(path)


def open_text_auto(path: Path):
    resolved = existing_text_path(path)
    if resolved.name.endswith(".gz"):
        return gzip.open(resolved, "rt", encoding="utf-8-sig", newline="")
    return resolved.open(encoding="utf-8-sig", newline="")


def estimate_points_csv(
    points_csv: Path,
    truth_by_sample: dict[int, dict[str, object]] | None = None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, list[float]],
]:
    """Read NOKOV long-form points CSV and produce 6-D rows.

    Only ``labeled_marker`` rows are used because Marker Set rows duplicate the
    same physical points in the current recorder format. Frames missing any of
    the required 24 IDs are retained with ``valid=0`` and blank outputs.
    """
    frames = load_labeled_frames(points_csv)
    control_rows: list[dict[str, object]] = []
    angle_rows: list[dict[str, object]] = []
    errors = {channel: [] for channel in CONTROL_CHANNELS}
    truth_by_sample = truth_by_sample or {}

    for frame in frames:
        common = {
            "sample_index": frame.sample_index,
            "frame_no": frame.frame_no,
            "timestamp_ms": frame.timestamp_ms,
            "elapsed_s": frame.elapsed_s,
        }
        markers = frame.markers
        truth = truth_by_sample.get(frame.sample_index, {})
        missing = sorted(set(MARKER_NAMES) - set(markers))
        missing_text = ";".join(str(marker_id) for marker_id in missing)
        control_row: dict[str, object] = {
            **common,
            "valid": int(not missing),
            "missing_marker_ids": missing_text,
        }
        angle_row: dict[str, object] = {
            **common,
            "valid": int(not missing),
            "missing_marker_ids": missing_text,
        }

        if missing:
            for channel in CONTROL_CHANNELS:
                control_row[f"truth_{channel}_0_1"] = truth.get(channel, "")
                control_row[f"command_{channel}_0_1"] = ""
                control_row[f"abs_error_{channel}"] = ""
        else:
            estimated, angles = estimate_six_controls(markers)
            angle_row.update(angles)
            for channel in CONTROL_CHANNELS:
                truth_value = truth.get(channel, "")
                control_row[f"truth_{channel}_0_1"] = truth_value
                control_row[f"command_{channel}_0_1"] = estimated[channel]
                if truth_value == "":
                    control_row[f"abs_error_{channel}"] = ""
                else:
                    error = abs(estimated[channel] - float(truth_value))
                    errors[channel].append(error)
                    control_row[f"abs_error_{channel}"] = error

        control_rows.append(control_row)
        angle_rows.append(angle_row)

    return control_rows, angle_rows, errors


def load_labeled_frames(points_csv: Path) -> list[LabeledFrame]:
    """Load valid labeled-marker rows from a NOKOV long-form points CSV.

    XINGYING can assign different SDK marker ID ranges to different hand
    templates. The project algorithms use the vendor's 1..24 hand table as the
    semantic marker IDs, so a right-hand recording whose SDK IDs are 25..48 is
    normalized back to 1..24 while loading.
    """
    frames: dict[int, dict[str, object]] = {}
    raw_marker_ids: set[int] = set()
    with open_text_auto(points_csv) as stream:
        for row in csv.DictReader(stream):
            if row["category"] != "labeled_marker":
                continue
            sample_index = int(row["sample_index"])
            frame = frames.setdefault(
                sample_index,
                {
                    "common": {
                        "sample_index": sample_index,
                        "frame_no": int(row["frame_no"]),
                        "timestamp_ms": int(row["timestamp_ms"]),
                        "elapsed_s": float(row["elapsed_s"]),
                    },
                    "markers": {},
                },
            )
            if int(row["valid"]) == 1:
                marker_id = int(row["point_id_or_index"])
                raw_marker_ids.add(marker_id)
                frame["markers"][marker_id] = np.array(
                    [float(row["x_mm"]), float(row["y_mm"]), float(row["z_mm"])]
                )
    marker_id_offset = infer_marker_id_offset(raw_marker_ids)
    loaded: list[LabeledFrame] = []
    for sample_index in sorted(frames):
        common = frames[sample_index]["common"]
        raw_markers = frames[sample_index]["markers"]
        normalized_markers = {
            marker_id - marker_id_offset: point
            for marker_id, point in raw_markers.items()
            if marker_id - marker_id_offset in MARKER_NAMES
        }
        loaded.append(
            LabeledFrame(
                sample_index=sample_index,
                frame_no=int(common["frame_no"]),
                timestamp_ms=int(common["timestamp_ms"]),
                elapsed_s=float(common["elapsed_s"]),
                markers=normalized_markers,
                marker_id_offset=marker_id_offset,
            )
        )
    return loaded


def infer_marker_id_offset(marker_ids: set[int]) -> int:
    """Infer how SDK marker IDs map onto the 1..24 XINGYING hand table."""
    expected = set(MARKER_NAMES)
    candidates = (0, 24, 48, 72)
    scores = {
        offset: sum(1 for marker_id in marker_ids if marker_id - offset in expected)
        for offset in candidates
    }
    best_offset, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score == 0:
        return 0
    return best_offset


def run_pipeline(
    *,
    frames: int = 540,
    fps: float = 90.0,
    noise_mm: float = 0.15,
    seed: int = 42,
    raw_root: Path | None = None,
    processed_root: Path | None = None,
) -> PipelineResult:
    if frames <= 1:
        raise ValueError("frames must be greater than one")
    if fps <= 0:
        raise ValueError("fps must be greater than zero")
    if noise_mm < 0:
        raise ValueError("noise_mm cannot be negative")

    # Importing here keeps the geometry functions usable without loading the
    # vendor SDK. The actual write path is shared with live NOKOV recording.
    from mocap.inspect_mocap import SessionRecorder

    raw_root = raw_root or PROJECT_ROOT / "data" / "raw" / "synthetic"
    processed_root = processed_root or PROJECT_ROOT / "data" / "processed" / "synthetic"
    recorder = SessionRecorder(raw_root)
    processed_session = processed_root / recorder.session_name
    processed_session.mkdir(parents=True, exist_ok=False)

    rng = np.random.default_rng(seed)
    base_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    truth_rows: list[dict[str, object]] = []

    try:
        for zero_index in range(frames):
            sample_index = zero_index + 1
            elapsed_s = zero_index / fps
            timestamp_ms = base_timestamp_ms + round(zero_index * 1000.0 / fps)
            frame_no = 100_000 + zero_index
            truth = synthetic_controls(elapsed_s)
            local_markers = generate_local_markers(truth)
            markers = apply_global_pose(local_markers, elapsed_s)
            if noise_mm:
                markers = {
                    marker_id: point + rng.normal(0.0, noise_mm, size=3)
                    for marker_id, point in markers.items()
                }

            recorder.write(_snapshot(markers, frame_no, timestamp_ms), sample_index)
            common = {
                "sample_index": sample_index,
                "frame_no": frame_no,
                "timestamp_ms": timestamp_ms,
                "elapsed_s": elapsed_s,
            }
            truth_rows.append({**common, **truth})
    finally:
        recorder.close()

    truth_by_sample = {
        int(row["sample_index"]): row for row in truth_rows
    }
    control_rows, angle_rows, errors = estimate_points_csv(
        recorder.paths["points"], truth_by_sample
    )

    truth_fields = ["sample_index", "frame_no", "timestamp_ms", "elapsed_s", *CONTROL_CHANNELS]
    control_fields = [
        "sample_index",
        "frame_no",
        "timestamp_ms",
        "elapsed_s",
        "valid",
        "missing_marker_ids",
    ]
    for channel in CONTROL_CHANNELS:
        control_fields.extend(
            [
                f"truth_{channel}_0_1",
                f"command_{channel}_0_1",
                f"abs_error_{channel}",
            ]
        )
    # Preserve a deterministic, human-readable angle-column order.
    angle_fields = [
        "sample_index",
        "frame_no",
        "timestamp_ms",
        "elapsed_s",
        "valid",
        "missing_marker_ids",
        "thumb_mcp_flex_deg",
        "thumb_pip_flex_deg",
        "thumb_dip_flex_deg",
        "thumb_opposition_deg",
        *[
            f"{finger}_{joint}_flex_deg"
            for finger in ("index", "middle", "ring", "little")
            for joint in ("mcp", "pip", "dip")
        ],
    ]

    _write_dict_rows(processed_session / "truth_6d.csv", truth_fields, truth_rows)
    _write_dict_rows(processed_session / "controls_6d.csv", control_fields, control_rows)
    _write_dict_rows(processed_session / "joint_angles.csv", angle_fields, angle_rows)
    _write_dict_rows(
        processed_session / "marker_layout.csv",
        ["labeled_marker_id", "markerset_index", "semantic_name", "unit"],
        [
            {
                "labeled_marker_id": marker_id,
                "markerset_index": marker_id - 1,
                "semantic_name": name,
                "unit": "mm",
            }
            for marker_id, name in MARKER_NAMES.items()
        ],
    )

    flattened_errors = np.concatenate(
        [np.asarray(errors[channel], dtype=float) for channel in CONTROL_CHANNELS]
    )
    metrics = {
        "purpose": "synthetic engineering validation only; not anatomical ground truth",
        "frames": frames,
        "fps": fps,
        "noise_mm_standard_deviation": noise_mm,
        "seed": seed,
        "raw_session": str(recorder.session_dir),
        "processed_session": str(processed_session),
        "input_points_csv": str(recorder.paths["points"]),
        "valid_frames": sum(int(row["valid"]) for row in control_rows),
        "invalid_frames": sum(not int(row["valid"]) for row in control_rows),
        "overall_mae": float(np.mean(flattened_errors)),
        "overall_max_error": float(np.max(flattened_errors)),
        "per_channel": {
            channel: {
                "mae": float(np.mean(errors[channel])),
                "max_error": float(np.max(errors[channel])),
            }
            for channel in CONTROL_CHANNELS
        },
    }
    (processed_session / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return PipelineResult(
        raw_session=recorder.session_dir,
        processed_session=processed_session,
        overall_mae=metrics["overall_mae"],
        overall_max_error=metrics["overall_max_error"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic 24-marker data and estimate provisional 6-D controls."
    )
    parser.add_argument("--frames", type=int, default=540)
    parser.add_argument("--fps", type=float, default=90.0)
    parser.add_argument("--noise-mm", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_pipeline(
        frames=args.frames,
        fps=args.fps,
        noise_mm=args.noise_mm,
        seed=args.seed,
    )
    print(f"Synthetic raw session: {result.raw_session}")
    print(f"Processed 6-D output: {result.processed_session}")
    print(f"Overall MAE: {result.overall_mae:.6f}")
    print(f"Maximum absolute error: {result.overall_max_error:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

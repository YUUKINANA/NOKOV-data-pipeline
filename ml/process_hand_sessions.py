"""Convert real 24-marker NOKOV sessions into provisional 6-D hand controls."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.synthetic_hand_pipeline import (  # noqa: E402
    CONTROL_CHANNELS,
    MARKER_NAMES,
    existing_text_path,
    estimate_points_csv,
    load_labeled_frames,
    open_text_auto,
)
from ml.hand_control_filter import StableHandControlFilter  # noqa: E402


RAW_ROOT = PROJECT_ROOT / "data" / "raw"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"

ANGLE_FIELDS = [
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

CONTROL_FIELDS = [
    "sample_index",
    "frame_no",
    "timestamp_ms",
    "elapsed_s",
    "valid",
    "missing_marker_ids",
    *[f"command_{channel}_0_1" for channel in CONTROL_CHANNELS],
]

STABLE_CONTROL_FIELDS = [
    "sample_index",
    "frame_no",
    "timestamp_ms",
    "elapsed_s",
    "raw_valid",
    "model_valid",
    "held_from_previous",
    "confidence",
    "missing_marker_ids",
    "imputed_marker_ids",
    *[f"command_{channel}_0_1" for channel in CONTROL_CHANNELS],
]


def _write_dict_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def latest_raw_sessions(limit: int) -> list[Path]:
    sessions = sorted(
        (path for path in RAW_ROOT.glob("mocap_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
    )
    if not sessions:
        raise FileNotFoundError(f"No raw mocap session folders found under {RAW_ROOT}")
    return sessions[-limit:]


def processed_session_dir(session: Path, output_root: Path = PROCESSED_ROOT) -> Path:
    session = session.resolve()
    try:
        relative = session.relative_to(RAW_ROOT.resolve())
    except ValueError:
        relative = Path(session.name)
    return output_root / relative


def _missing_counts(control_rows: list[dict[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in control_rows:
        missing = str(row.get("missing_marker_ids", ""))
        if not missing:
            continue
        for marker_id in missing.split(";"):
            if marker_id:
                counts[marker_id] += 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _channel_stats(control_rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for channel in CONTROL_CHANNELS:
        key = f"command_{channel}_0_1"
        values = [
            float(row[key])
            for row in control_rows
            if int(row["valid"]) and row.get(key) != ""
        ]
        if values:
            stats[channel] = {
                "min": float(np.min(values)),
                "mean": float(np.mean(values)),
                "max": float(np.max(values)),
            }
    return stats


def _read_json_auto(path: Path) -> dict[str, object]:
    with open_text_auto(path) as stream:
        return json.load(stream)


def _quat_xyzw(row: dict[str, str]) -> np.ndarray:
    quat = np.array(
        [float(row["qx"]), float(row["qy"]), float(row["qz"]), float(row["qw"])],
        dtype=float,
    )
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=float)
    return quat / norm


def _quaternion_angle_deg(first: np.ndarray, second: np.ndarray) -> float:
    dot = abs(float(np.dot(first, second)))
    dot = min(max(dot, -1.0), 1.0)
    return math.degrees(2.0 * math.acos(dot))


def _skeleton_segment_metadata(session: Path) -> dict[tuple[int, int], dict[str, object]]:
    try:
        descriptions_path = existing_text_path(session / "skeleton_descriptions.json")
    except FileNotFoundError:
        return {}

    descriptions = _read_json_auto(descriptions_path)
    metadata: dict[tuple[int, int], dict[str, object]] = {}
    for skeleton in descriptions.get("skeletons", []):
        skeleton_id = int(skeleton["id"])
        for segment in skeleton.get("segments", []):
            segment_id = int(segment["id"])
            metadata[(skeleton_id, segment_id)] = {
                "skeleton_name": skeleton.get("name", ""),
                "segment_name": segment.get("name", ""),
                "parent_id": int(segment.get("parent_id", 0)),
            }
    return metadata


def process_skeleton_session(session: Path, processed_dir: Path) -> dict[str, object]:
    try:
        skeleton_csv = existing_text_path(session / "skeleton_segments.csv")
    except FileNotFoundError:
        return {
            "skeleton_available": False,
            "reason": "raw session does not contain skeleton_segments.csv",
        }

    metadata = _skeleton_segment_metadata(session)
    rows: list[dict[str, str]] = []
    with open_text_auto(skeleton_csv) as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return {
            "skeleton_available": True,
            "skeleton_rows": 0,
            "reason": "skeleton_segments.csv is empty",
        }

    by_frame: dict[tuple[int, int], dict[int, dict[str, str]]] = {}
    segment_counts: Counter[tuple[int, int]] = Counter()
    for row in rows:
        skeleton_id = int(row["skeleton_id"])
        segment_id = int(row["segment_id"])
        sample_index = int(row["sample_index"])
        by_frame.setdefault((sample_index, skeleton_id), {})[segment_id] = row
        segment_counts[(skeleton_id, segment_id)] += 1

    summary_rows = []
    for (skeleton_id, segment_id), count in sorted(segment_counts.items()):
        info = metadata.get((skeleton_id, segment_id), {})
        summary_rows.append(
            {
                "skeleton_id": skeleton_id,
                "skeleton_name": info.get("skeleton_name", ""),
                "segment_id": segment_id,
                "segment_name": info.get("segment_name", ""),
                "parent_id": info.get("parent_id", ""),
                "frames_seen": count,
            }
        )
    _write_dict_rows(
        processed_dir / "skeleton_segment_summary.csv",
        [
            "skeleton_id",
            "skeleton_name",
            "segment_id",
            "segment_name",
            "parent_id",
            "frames_seen",
        ],
        summary_rows,
    )

    angle_rows = []
    for (sample_index, skeleton_id), segments in sorted(by_frame.items()):
        frame_anchor = next(iter(segments.values()))
        for segment_id, row in sorted(segments.items()):
            info = metadata.get((skeleton_id, segment_id), {})
            parent_id = int(info.get("parent_id", 0) or 0)
            parent_row = segments.get(parent_id)
            if parent_id == 0 or parent_row is None:
                continue
            angle_rows.append(
                {
                    "sample_index": sample_index,
                    "frame_no": frame_anchor["frame_no"],
                    "timestamp_ms": frame_anchor["timestamp_ms"],
                    "elapsed_s": frame_anchor["elapsed_s"],
                    "skeleton_id": skeleton_id,
                    "segment_id": segment_id,
                    "segment_name": info.get("segment_name", ""),
                    "parent_id": parent_id,
                    "parent_name": metadata.get((skeleton_id, parent_id), {}).get(
                        "segment_name", ""
                    ),
                    "relative_orientation_angle_deg": _quaternion_angle_deg(
                        _quat_xyzw(parent_row), _quat_xyzw(row)
                    ),
                }
            )
    _write_dict_rows(
        processed_dir / "skeleton_segment_angles.csv",
        [
            "sample_index",
            "frame_no",
            "timestamp_ms",
            "elapsed_s",
            "skeleton_id",
            "segment_id",
            "segment_name",
            "parent_id",
            "parent_name",
            "relative_orientation_angle_deg",
        ],
        angle_rows,
    )

    return {
        "skeleton_available": True,
        "skeleton_rows": len(rows),
        "skeleton_frames": len(by_frame),
        "skeleton_segments": len(segment_counts),
        "has_descriptions": bool(metadata),
        "relative_angle_rows": len(angle_rows),
    }


def stable_control_rows(
    points_csv: Path,
    *,
    hold_s: float,
    smooth_alpha: float,
    max_rate_per_s: float,
) -> list[dict[str, object]]:
    frames = load_labeled_frames(points_csv)
    control_filter = StableHandControlFilter(
        hold_s=hold_s,
        smooth_alpha=smooth_alpha,
        max_rate_per_s=max_rate_per_s,
    )
    rows: list[dict[str, object]] = []
    for frame in frames:
        result = control_filter.update(frame.markers, frame.elapsed_s)
        rows.append(
            {
                "sample_index": frame.sample_index,
                "frame_no": frame.frame_no,
                "timestamp_ms": frame.timestamp_ms,
                "elapsed_s": frame.elapsed_s,
                "raw_valid": int(result.raw_valid),
                "model_valid": int(result.model_valid),
                "held_from_previous": int(result.held_from_previous),
                "confidence": result.confidence,
                "missing_marker_ids": ";".join(
                    str(marker_id) for marker_id in result.missing_marker_ids
                ),
                "imputed_marker_ids": ";".join(
                    str(marker_id) for marker_id in result.imputed_marker_ids
                ),
                **{
                    f"command_{channel}_0_1": result.commands[channel]
                    for channel in CONTROL_CHANNELS
                },
            }
        )
    return rows


def process_session(
    session: Path,
    output_root: Path = PROCESSED_ROOT,
    *,
    hold_s: float = 0.25,
    smooth_alpha: float = 0.35,
    max_rate_per_s: float = 3.0,
) -> Path:
    session = session.resolve()
    try:
        points_csv = existing_text_path(session / "points.csv")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing points.csv in {session}") from exc

    processed_dir = processed_session_dir(session, output_root)
    processed_dir.mkdir(parents=True, exist_ok=True)

    input_frames = load_labeled_frames(points_csv)
    marker_id_offset = input_frames[0].marker_id_offset if input_frames else 0
    estimated_rows, angle_rows, _errors = estimate_points_csv(points_csv)
    stable_rows = stable_control_rows(
        points_csv,
        hold_s=hold_s,
        smooth_alpha=smooth_alpha,
        max_rate_per_s=max_rate_per_s,
    )
    control_rows = [
        {
            field: row.get(field, "")
            for field in CONTROL_FIELDS
        }
        for row in estimated_rows
    ]

    _write_dict_rows(processed_dir / "controls_6d.csv", CONTROL_FIELDS, control_rows)
    _write_dict_rows(
        processed_dir / "controls_6d_stable.csv",
        STABLE_CONTROL_FIELDS,
        stable_rows,
    )
    _write_dict_rows(processed_dir / "joint_angles.csv", ANGLE_FIELDS, angle_rows)
    _write_dict_rows(
        processed_dir / "marker_layout.csv",
        ["labeled_marker_id", "semantic_name", "unit"],
        (
            {
                "labeled_marker_id": marker_id,
                "semantic_name": name,
                "unit": "mm",
            }
            for marker_id, name in MARKER_NAMES.items()
        ),
    )
    skeleton_summary = process_skeleton_session(session, processed_dir)

    elapsed = [float(row["elapsed_s"]) for row in control_rows]
    duration_s = (max(elapsed) - min(elapsed)) if elapsed else 0.0
    nominal_fps = (
        (len(elapsed) - 1) / duration_s
        if len(elapsed) > 1 and duration_s > 0
        else 0.0
    )
    frame_steps = [
        second - first
        for first, second in zip(elapsed[:-1], elapsed[1:], strict=True)
    ]
    summary = {
        "purpose": "real hand recording converted to provisional normalized 6-D controls; not final REVO2 motor commands",
        "raw_session": str(session),
        "processed_session": str(processed_dir),
        "input_points_csv": str(points_csv),
        "input_marker_id_offset": marker_id_offset,
        "frames": len(control_rows),
        "duration_s": duration_s,
        "nominal_fps": nominal_fps,
        "median_frame_interval_s": statistics.median(frame_steps) if frame_steps else 0.0,
        "valid_frames": sum(int(row["valid"]) for row in control_rows),
        "invalid_frames": sum(1 - int(row["valid"]) for row in control_rows),
        "stable_model_valid_frames": sum(int(row["model_valid"]) for row in stable_rows),
        "stable_held_frames": sum(int(row["held_from_previous"]) for row in stable_rows),
        "stable_imputed_frames": sum(bool(row["imputed_marker_ids"]) for row in stable_rows),
        "stable_filter": {
            "hold_s": hold_s,
            "smooth_alpha": smooth_alpha,
            "max_rate_per_s": max_rate_per_s,
        },
        "skeleton": skeleton_summary,
        "missing_marker_frame_counts": _missing_counts(control_rows),
        "channels": list(CONTROL_CHANNELS),
        "channel_stats": _channel_stats(control_rows),
        "stable_channel_stats": _channel_stats(
            [
                {
                    "valid": row["model_valid"],
                    **{
                        f"command_{channel}_0_1": row[f"command_{channel}_0_1"]
                        for channel in CONTROL_CHANNELS
                    },
                }
                for row in stable_rows
            ]
        ),
    }
    (processed_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return processed_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert real NOKOV 24-marker sessions into provisional 6-D controls."
    )
    parser.add_argument(
        "sessions",
        nargs="*",
        type=Path,
        help="Raw session folders. Defaults to the newest direct data/raw session.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=1,
        help="Process the newest N direct data/raw/mocap_* folders when no sessions are given.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROCESSED_ROOT,
        help="Root folder for processed outputs.",
    )
    parser.add_argument(
        "--hold-s",
        type=float,
        default=0.25,
        help="Seconds to impute a temporarily missing marker from its last position.",
    )
    parser.add_argument(
        "--smooth-alpha",
        type=float,
        default=0.35,
        help="Low-pass smoothing alpha for stable controls.",
    )
    parser.add_argument(
        "--max-rate",
        type=float,
        default=3.0,
        help="Maximum change per second for each normalized 0-1 channel.",
    )
    args = parser.parse_args()
    if args.latest < 1:
        parser.error("--latest must be at least 1")
    if args.hold_s < 0:
        parser.error("--hold-s must be greater than or equal to 0")
    if not 0 < args.smooth_alpha <= 1:
        parser.error("--smooth-alpha must be in (0, 1]")
    if args.max_rate <= 0:
        parser.error("--max-rate must be greater than 0")
    return args


def main() -> int:
    args = parse_args()
    sessions = [path.resolve() for path in args.sessions] if args.sessions else latest_raw_sessions(args.latest)
    print("Processing sessions:")
    for session in sessions:
        print(f"  {session}")
    for session in sessions:
        processed_dir = process_session(
            session,
            args.output_root.resolve(),
            hold_s=args.hold_s,
            smooth_alpha=args.smooth_alpha,
            max_rate_per_s=args.max_rate,
        )
        print(f"Saved provisional 6-D controls to: {processed_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

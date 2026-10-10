"""Replay a recorded 24-marker session and visualize live 6-D estimation."""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.synthetic_hand_pipeline import (
    CONTROL_CHANNELS,
    FINGER_MARKER_IDS,
    MARKER_NAMES,
    estimate_six_controls,
    existing_text_path,
    load_labeled_frames,
    open_text_auto,
)
from ml.hand_control_filter import StableHandControlFilter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYNTHETIC_ROOT = PROJECT_ROOT / "data" / "raw" / "synthetic"
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"

CHANNEL_LABELS = {
    "thumb_flexion": "Thumb flexion",
    "thumb_opposition": "Thumb opposition",
    "index_flexion": "Index flexion",
    "middle_flexion": "Middle flexion",
    "ring_flexion": "Ring flexion",
    "little_flexion": "Little flexion",
}

PALM_CONNECTIONS = (
    (2, 1),
    (1, 3),
    (1, 4),
    (2, 4),
    (3, 4),
    (4, 5),
    (4, 9),
    (4, 13),
    (4, 17),
    (4, 21),
    (5, 9),
    (9, 13),
    (13, 17),
    (17, 21),
)
FINGER_CONNECTIONS = tuple(
    tuple(zip(ids[:-1], ids[1:], strict=True))
    for ids in FINGER_MARKER_IDS.values()
)


def latest_session(root: Path = DEFAULT_SYNTHETIC_ROOT) -> Path:
    sessions = sorted(path for path in root.glob("mocap_*") if path.is_dir())
    if not sessions:
        raise FileNotFoundError(
            f"No synthetic session found under {root}. Run "
            "python -m ml.synthetic_hand_pipeline first."
        )
    return sessions[-1]


def choose_session_folder() -> Path | None:
    """Open a folder picker for PyCharm's green-run-button workflow."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError as exc:
        raise RuntimeError(
            "tkinter is not available; pass --session PATH on the command line instead."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askdirectory(
        title="Select a NOKOV raw session folder",
        initialdir=str(RAW_ROOT),
    )
    root.attributes("-topmost", False)
    if not selected:
        root.destroy()
        return None

    session = Path(selected).resolve()
    missing = [
        file_name
        for file_name in ("points.csv", "frames.csv")
        if not (session / file_name).exists()
        and not (session / f"{file_name}.gz").exists()
    ]
    if missing:
        messagebox.showerror(
            "Invalid session folder",
            "Please select a raw mocap session folder containing:\n"
            + "\n".join(missing),
        )
        root.destroy()
        return None

    root.destroy()
    return session


def processed_session_dir(session: Path) -> Path:
    session = session.resolve()
    try:
        relative = session.relative_to(RAW_ROOT.resolve())
    except ValueError:
        relative = Path(session.name)
    return PROCESSED_ROOT / relative


def _sdk_latency_by_sample(frames_csv: Path) -> dict[int, float]:
    with open_text_auto(frames_csv) as stream:
        return {
            int(row["sample_index"]): float(row["latency_ms"])
            for row in csv.DictReader(stream)
        }


def _set_equal_hand_view(axis: object, markers: dict[int, np.ndarray]) -> None:
    if not markers:
        return
    points = np.vstack(list(markers.values()))
    center = points.mean(axis=0)
    radius = max(float(np.ptp(points, axis=0).max()) * 0.65, 90.0)
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(center[2] - radius, center[2] + radius)
    axis.set_box_aspect((1.0, 1.0, 1.0))


def _draw_hand(axis: object, markers: dict[int, np.ndarray]) -> None:
    axis.cla()
    visible_marker_ids = sorted(set(MARKER_NAMES) & set(markers))
    if visible_marker_ids:
        points = np.vstack([markers[marker_id] for marker_id in visible_marker_ids])
        axis.scatter(points[:, 0], points[:, 1], points[:, 2], s=28, c="#1496bb")
        for marker_id in visible_marker_ids:
            point = markers[marker_id]
            axis.text(point[0], point[1], point[2], str(marker_id), fontsize=8)

    for start_id, end_id in PALM_CONNECTIONS:
        if start_id not in markers or end_id not in markers:
            continue
        segment = np.vstack((markers[start_id], markers[end_id]))
        axis.plot(segment[:, 0], segment[:, 1], segment[:, 2], c="#4f5965", lw=2)
    for finger_connections in FINGER_CONNECTIONS:
        for start_id, end_id in finger_connections:
            if start_id not in markers or end_id not in markers:
                continue
            segment = np.vstack((markers[start_id], markers[end_id]))
            axis.plot(segment[:, 0], segment[:, 1], segment[:, 2], c="#ef8354", lw=3)

    axis.set_title("24-marker replay")
    axis.set_xlabel("X (mm)")
    axis.set_ylabel("Y (mm)")
    axis.set_zlabel("Z (mm)")
    _set_equal_hand_view(axis, markers)


def replay(
    session: Path,
    *,
    speed: float = 1.0,
    ui_fps: float = 15.0,
    print_every: int = 90,
    keep_open: bool = True,
    visual: bool = True,
    hold_s: float = 0.25,
    smooth_alpha: float = 0.35,
    max_rate_per_s: float = 3.0,
) -> Path:
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    if ui_fps <= 0:
        raise ValueError("ui_fps must be greater than zero")

    load_started = time.perf_counter()
    points_csv = existing_text_path(session / "points.csv")
    frames_csv = existing_text_path(session / "frames.csv")
    frames = load_labeled_frames(points_csv)
    sdk_latency = _sdk_latency_by_sample(frames_csv)
    file_load_ms = (time.perf_counter() - load_started) * 1000.0
    if not frames:
        raise ValueError(f"No labeled marker frames found in {session / 'points.csv'}")

    processed_session = processed_session_dir(session)
    processed_session.mkdir(parents=True, exist_ok=True)
    latency_path = processed_session / "replay_latency.csv"

    figure = None
    hand_axis = None
    bars = None
    status_text = None
    if visual:
        plt.ion()
        figure = plt.figure(figsize=(12, 6.5), layout="constrained")
        hand_axis = figure.add_subplot(1, 2, 1, projection="3d")
        control_axis = figure.add_subplot(1, 2, 2)
        y_positions = np.arange(len(CONTROL_CHANNELS))
        bars = control_axis.barh(
            y_positions, np.zeros(len(CONTROL_CHANNELS)), color="#1496bb"
        )
        control_axis.set_yticks(
            y_positions, [CHANNEL_LABELS[channel] for channel in CONTROL_CHANNELS]
        )
        control_axis.set_xlim(0.0, 1.0)
        control_axis.set_xlabel("Normalized command (0–1)")
        control_axis.set_title("Provisional 6-D output")
        control_axis.invert_yaxis()
        status_text = control_axis.text(
            0.0,
            -0.16,
            "",
            transform=control_axis.transAxes,
            family="monospace",
            va="top",
        )
        figure.canvas.manager.set_window_title("NOKOV hand replay")
        plt.show(block=False)

    nominal_fps = 1.0 / statistics.median(
        second.elapsed_s - first.elapsed_s
        for first, second in zip(frames[:-1], frames[1:], strict=True)
    )
    ui_stride = max(round(nominal_fps / ui_fps), 1)
    base_elapsed = frames[0].elapsed_s
    replay_started = time.perf_counter()
    latency_rows: list[dict[str, object]] = []
    stable_filter = StableHandControlFilter(
        hold_s=hold_s,
        smooth_alpha=smooth_alpha,
        max_rate_per_s=max_rate_per_s,
    )

    for index, frame in enumerate(frames):
        target_time = replay_started + (frame.elapsed_s - base_elapsed) / speed
        remaining = target_time - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

        compute_started = time.perf_counter()
        missing = sorted(set(MARKER_NAMES) - set(frame.markers))
        stable = stable_filter.update(frame.markers, frame.elapsed_s)
        commands = stable.commands
        compute_ms = (time.perf_counter() - compute_started) * 1000.0
        schedule_lag_ms = max((compute_started - target_time) * 1000.0, 0.0)

        latency_rows.append(
            {
                "sample_index": frame.sample_index,
                "frame_no": frame.frame_no,
                "elapsed_s": frame.elapsed_s,
                "raw_valid": int(stable.raw_valid),
                "model_valid": int(stable.model_valid),
                "held_from_previous": int(stable.held_from_previous),
                "confidence": stable.confidence,
                "missing_marker_ids": ";".join(str(value) for value in missing),
                "imputed_marker_ids": ";".join(
                    str(value) for value in stable.imputed_marker_ids
                ),
                "sdk_latency_ms": sdk_latency.get(frame.sample_index, ""),
                "compute_ms": compute_ms,
                "schedule_lag_ms": schedule_lag_ms,
                **{f"command_{channel}_0_1": commands[channel] for channel in CONTROL_CHANNELS},
            }
        )

        if print_every > 0 and (index == 0 or (index + 1) % print_every == 0):
            if stable.model_valid or stable.held_from_previous:
                vector = ", ".join(f"{commands[channel]:.3f}" for channel in CONTROL_CHANNELS)
            else:
                vector = "invalid; missing=" + ",".join(str(value) for value in missing)
            print(
                f"frame={frame.frame_no} elapsed={frame.elapsed_s:.3f}s "
                f"compute={compute_ms:.3f}ms commands=[{vector}]"
            )

        if visual and (index % ui_stride == 0 or index == len(frames) - 1):
            assert figure is not None
            assert hand_axis is not None
            assert bars is not None
            assert status_text is not None
            if not plt.fignum_exists(figure.number):
                break
            _draw_hand(hand_axis, frame.markers)
            for bar, channel in zip(bars, CONTROL_CHANNELS, strict=True):
                value = commands[channel]
                bar.set_width(0.0 if np.isnan(value) else value)
            missing_text = (
                "none" if not missing else ", ".join(str(marker_id) for marker_id in missing)
            )
            imputed_text = (
                "none"
                if not stable.imputed_marker_ids
                else ", ".join(str(marker_id) for marker_id in stable.imputed_marker_ids)
            )
            status_text.set_text(
                f"frame: {frame.frame_no}\n"
                f"recorded time: {frame.elapsed_s:.3f} s\n"
                f"raw complete: {int(stable.raw_valid)}\n"
                f"model valid: {int(stable.model_valid)}\n"
                f"held output: {int(stable.held_from_previous)}\n"
                f"confidence: {stable.confidence:.2f}\n"
                f"missing markers: {missing_text}\n"
                f"imputed markers: {imputed_text}\n"
                f"geometry compute: {compute_ms:.3f} ms\n"
                f"playback lag: {schedule_lag_ms:.3f} ms\n"
                f"file preload: {file_load_ms:.1f} ms"
            )
            figure.canvas.draw_idle()
            figure.canvas.flush_events()
            plt.pause(0.001)

    fieldnames = [
        "sample_index",
        "frame_no",
        "elapsed_s",
        "raw_valid",
        "model_valid",
        "held_from_previous",
        "confidence",
        "missing_marker_ids",
        "imputed_marker_ids",
        "sdk_latency_ms",
        "compute_ms",
        "schedule_lag_ms",
        *[f"command_{channel}_0_1" for channel in CONTROL_CHANNELS],
    ]
    with latency_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(latency_rows)

    valid_compute = [
        float(row["compute_ms"])
        for row in latency_rows
        if row["model_valid"] or row["held_from_previous"]
    ]
    lags = [float(row["schedule_lag_ms"]) for row in latency_rows]
    print(f"Loaded {len(frames)} frames in {file_load_ms:.1f} ms")
    print(
        f"Geometry compute: mean={statistics.mean(valid_compute):.3f} ms, "
        f"max={max(valid_compute):.3f} ms"
    )
    print(
        f"Playback scheduling lag: mean={statistics.mean(lags):.3f} ms, "
        f"max={max(lags):.3f} ms"
    )
    print(f"Replay diagnostics saved to: {latency_path}")

    if visual:
        assert figure is not None
        if keep_open and plt.fignum_exists(figure.number):
            print("Replay finished. Close the plot window to exit.")
            plt.ioff()
            plt.show()
        else:
            plt.close(figure)
    return latency_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay 24-marker data, calculate six controls, and show latency."
    )
    parser.add_argument(
        "--session",
        type=Path,
        help="Raw session folder. If omitted, a folder picker opens.",
    )
    parser.add_argument(
        "--latest-synthetic",
        action="store_true",
        help="Replay the newest synthetic session instead of opening the folder picker.",
    )
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--ui-fps", type=float, default=15.0)
    parser.add_argument("--print-every", type=int, default=90)
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
    parser.add_argument(
        "--close-on-finish",
        action="store_true",
        help="Close the plot automatically when replay ends.",
    )
    parser.add_argument(
        "--no-visual",
        action="store_true",
        help="Run the timing path without Matplotlib rendering overhead.",
    )
    args = parser.parse_args()
    if args.hold_s < 0:
        parser.error("--hold-s must be greater than or equal to 0")
    if not 0 < args.smooth_alpha <= 1:
        parser.error("--smooth-alpha must be in (0, 1]")
    if args.max_rate <= 0:
        parser.error("--max-rate must be greater than 0")
    return args


def main() -> int:
    args = parse_args()
    if args.session:
        session = args.session.resolve()
    elif args.latest_synthetic:
        session = latest_session()
    else:
        session = choose_session_folder()
        if session is None:
            print("No session selected; replay cancelled.")
            return 0
    print(f"Replaying session: {session}")
    replay(
        session,
        speed=args.speed,
        ui_fps=args.ui_fps,
        print_every=args.print_every,
        keep_open=not args.close_on_finish,
        visual=not args.no_visual,
        hold_s=args.hold_s,
        smooth_alpha=args.smooth_alpha,
        max_rate_per_s=args.max_rate,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Inspect and record live XINGYING/Nokov motion-capture frames.

The terminal shows a rate-limited JSON preview. Every received source frame is
saved under ``data`` as JSONL plus analysis-friendly CSV files. Vendor examples
remain untouched.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import gc
import gzip
import json
import math
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from nokov.nokovsdk import DataDescriptions, DataDescriptors, PySDKClient


LOST_MARKER_VALUE = 9_999_999.0
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START_DELAY_S = 5.0
DEFAULT_DURATION_S = 5.0
DEFAULT_SAVE_MODE = "hand"
DEFAULT_COMPRESS_ON_FINISH = True


def decode_name(value: bytes) -> str:
    """Decode a fixed-size C string without failing on unexpected bytes."""
    return value.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def point_xyz(point: Any) -> list[float]:
    return [float(point[0]), float(point[1]), float(point[2])]


def point_is_valid(point: list[float]) -> bool:
    return all(
        math.isfinite(value) and abs(value) < LOST_MARKER_VALUE
        for value in point
    )


def unique_session_name(output_dir: Path) -> str:
    """Return a timestamp folder name, adding a suffix when necessary."""
    base = datetime.now().strftime("mocap_%Y%m%d_%H%M%S")
    candidate = base
    suffix = 2
    while (output_dir / candidate).exists():
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def sleep_with_countdown(seconds: float, label: str) -> None:
    """Wait before recording while showing a small console countdown."""
    if seconds <= 0:
        return

    deadline = time.monotonic() + seconds
    last_displayed: int | None = None
    print(f"{label} in {seconds:g} seconds. Press Ctrl+C to cancel.")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        displayed = int(math.ceil(remaining))
        if displayed != last_displayed:
            print(f"  {displayed}...")
            last_displayed = displayed
        time.sleep(min(0.2, remaining))


def gzip_replace(path: Path) -> Path:
    """Compress one finished text file and remove the uncompressed copy."""
    compressed = path.with_name(path.name + ".gz")
    temporary = compressed.with_name(compressed.name + ".tmp")
    with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
    temporary.replace(compressed)
    path.unlink()
    return compressed


class SessionRecorder:
    """Write one synchronized set of raw and tabular files per run."""

    FRAME_FIELDS = [
        "sample_index", "frame_no", "timestamp_ms", "elapsed_s", "latency_ms",
        "marker_sets", "labeled_markers", "unidentified_markers",
        "rigid_bodies", "skeletons", "analog_channels",
    ]
    POINT_FIELDS = [
        "sample_index", "frame_no", "timestamp_ms", "elapsed_s", "category",
        "group_name", "point_id_or_index", "x_mm", "y_mm", "z_mm", "valid",
        "size_mm",
    ]
    RIGID_FIELDS = [
        "sample_index", "frame_no", "timestamp_ms", "elapsed_s", "rigid_id",
        "x_mm", "y_mm", "z_mm", "qx", "qy", "qz", "qw", "marker_count",
        "mean_error", "params",
    ]
    SKELETON_FIELDS = [
        "sample_index", "frame_no", "timestamp_ms", "elapsed_s", "skeleton_id",
        "segment_index", "segment_id", "x_mm", "y_mm", "z_mm", "qx", "qy",
        "qz", "qw", "marker_count", "mean_error", "params", "marker_ids",
    ]

    def __init__(
        self,
        output_dir: Path,
        *,
        save_mode: str = DEFAULT_SAVE_MODE,
        compress_on_finish: bool = DEFAULT_COMPRESS_ON_FINISH,
        data_descriptions: dict[str, Any] | None = None,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.save_mode = save_mode
        self.compress_on_finish = compress_on_finish
        self.session_name = unique_session_name(output_dir)
        self.session_dir = output_dir / self.session_name
        self.session_dir.mkdir()
        self.paths = {
            "frames": self.session_dir / "frames.csv",
            "points": self.session_dir / "points.csv",
            "skeleton_segments": self.session_dir / "skeleton_segments.csv",
            "rigid_bodies": self.session_dir / "rigid_bodies.csv",
        }
        if data_descriptions is not None:
            self.paths["skeleton_descriptions"] = (
                self.session_dir / "skeleton_descriptions.json"
            )
        if self.save_mode == "full":
            self.paths["raw"] = self.session_dir / "raw.jsonl"
        self._raw: TextIO | None = None
        if "raw" in self.paths:
            self._raw = self.paths["raw"].open("w", encoding="utf-8")
        self._frames_file: TextIO = self.paths["frames"].open(
            "w", encoding="utf-8-sig", newline=""
        )
        self._points_file: TextIO = self.paths["points"].open(
            "w", encoding="utf-8-sig", newline=""
        )
        self._rigids_file: TextIO | None = None
        if "rigid_bodies" in self.paths:
            self._rigids_file = self.paths["rigid_bodies"].open(
                "w", encoding="utf-8-sig", newline=""
            )
        self._skeletons_file: TextIO = self.paths["skeleton_segments"].open(
            "w", encoding="utf-8-sig", newline=""
        )
        self._frames = csv.DictWriter(self._frames_file, fieldnames=self.FRAME_FIELDS)
        self._points = csv.DictWriter(self._points_file, fieldnames=self.POINT_FIELDS)
        self._skeletons = csv.DictWriter(
            self._skeletons_file, fieldnames=self.SKELETON_FIELDS
        )
        self._rigids = (
            csv.DictWriter(self._rigids_file, fieldnames=self.RIGID_FIELDS)
            if self._rigids_file is not None
            else None
        )
        self._frames.writeheader()
        self._points.writeheader()
        self._skeletons.writeheader()
        if self._rigids is not None:
            self._rigids.writeheader()
        if data_descriptions is not None:
            self.paths["skeleton_descriptions"].write_text(
                json.dumps(data_descriptions, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        self._first_timestamp_ms: int | None = None
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()
        self._closed = False

    def write(self, snapshot: dict[str, Any], sample_index: int) -> None:
        with self._lock:
            # A native SDK callback can already be in flight while shutdown is
            # starting. Silently ignore that late frame once files are closed.
            if self._closed:
                return
            timestamp_ms = int(snapshot["timestamp_ms"])
            if self._first_timestamp_ms is None:
                self._first_timestamp_ms = timestamp_ms
            elapsed_s = (timestamp_ms - self._first_timestamp_ms) / 1000.0
            common = {
                "sample_index": sample_index,
                "frame_no": snapshot["frame"],
                "timestamp_ms": timestamp_ms,
                "elapsed_s": elapsed_s,
            }

            if self._raw is not None:
                raw_record = {
                    "sample_index": sample_index,
                    "elapsed_s": elapsed_s,
                    **snapshot,
                }
                self._raw.write(json.dumps(raw_record, ensure_ascii=False) + "\n")

            self._frames.writerow(
                {
                    **common,
                    "latency_ms": snapshot["latency"],
                    **snapshot["counts"],
                }
            )

            if self.save_mode == "full":
                for marker_set in snapshot["marker_sets"]:
                    for marker in marker_set["markers"]:
                        self._write_point(
                            common,
                            category="markerset",
                            group_name=marker_set["name"],
                            point_id=marker["index"],
                            xyz=marker["xyz_mm"],
                            valid=marker["valid"],
                            size_mm="",
                        )

            for marker in snapshot["labeled_markers"]:
                self._write_point(
                    common,
                    category="labeled_marker",
                    group_name="",
                    point_id=marker["id"],
                    xyz=marker["xyz_mm"],
                    valid=marker["valid"],
                    size_mm=marker["size"],
                )

            if self.save_mode == "full":
                for marker in snapshot["unidentified_markers"]:
                    self._write_point(
                        common,
                        category="unidentified_marker",
                        group_name="",
                        point_id=marker["index"],
                        xyz=marker["xyz_mm"],
                        valid=marker["valid"],
                        size_mm="",
                    )

            if self._rigids is not None:
                for body in snapshot["rigid_bodies"]:
                    x, y, z = body["position_mm"]
                    qx, qy, qz, qw = body["orientation_xyzw"]
                    self._rigids.writerow(
                        {
                            **common,
                            "rigid_id": body["id"],
                            "x_mm": x,
                            "y_mm": y,
                            "z_mm": z,
                            "qx": qx,
                            "qy": qy,
                            "qz": qz,
                            "qw": qw,
                            "marker_count": body["marker_count"],
                            "mean_error": body["mean_error"],
                            "params": body["params"],
                        }
                    )

            for skeleton in snapshot.get("skeletons", []):
                for segment in skeleton["segments"]:
                    x, y, z = segment["position_mm"]
                    qx, qy, qz, qw = segment["orientation_xyzw"]
                    # XINGYING can stream an absent template's segments with
                    # 9999999 coordinates on every frame. Keep the template
                    # description and frame clock, but omit these empty rows.
                    if not point_is_valid([x, y, z]) or not point_is_valid(
                        [qx, qy, qz, qw]
                    ):
                        continue
                    self._skeletons.writerow(
                        {
                            **common,
                            "skeleton_id": skeleton["id"],
                            "segment_index": segment["index"],
                            "segment_id": segment["id"],
                            "x_mm": x,
                            "y_mm": y,
                            "z_mm": z,
                            "qx": qx,
                            "qy": qy,
                            "qz": qz,
                            "qw": qw,
                            "marker_count": segment["marker_count"],
                            "mean_error": segment["mean_error"],
                            "params": segment["params"],
                            "marker_ids": ";".join(
                                str(marker_id) for marker_id in segment["marker_ids"]
                            ),
                        }
                    )

            if time.monotonic() - self._last_flush >= 1.0:
                self.flush()

    def _write_point(
        self,
        common: dict[str, Any],
        *,
        category: str,
        group_name: str,
        point_id: int,
        xyz: list[float],
        valid: bool,
        size_mm: float | str,
    ) -> None:
        self._points.writerow(
            {
                **common,
                "category": category,
                "group_name": group_name,
                "point_id_or_index": point_id,
                "x_mm": xyz[0],
                "y_mm": xyz[1],
                "z_mm": xyz[2],
                "valid": int(valid),
                "size_mm": size_mm,
            }
        )

    def flush(self) -> None:
        for stream in self._open_streams():
            if stream is not None:
                stream.flush()
        self._last_flush = time.monotonic()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.flush()
            for stream in self._open_streams():
                if stream is not None:
                    stream.close()
            self._closed = True
            if self.compress_on_finish:
                self.compress_files()

    def _open_streams(self) -> tuple[TextIO | None, ...]:
        return (
            self._raw,
            self._frames_file,
            self._points_file,
            self._skeletons_file,
            self._rigids_file,
        )

    def compress_files(self) -> None:
        compressed_paths: dict[str, Path] = {}
        for key, path in self.paths.items():
            if path.exists():
                compressed_paths[key] = gzip_replace(path)
        self.paths.update(compressed_paths)


class FrameInspector:
    def __init__(
        self,
        print_every: int,
        max_points: int,
        recorder: SessionRecorder | None,
    ) -> None:
        self.print_every = print_every
        self.max_points = max_points
        self.recorder = recorder
        self.last_frame: int | None = None
        self.frames_received = 0
        self.callback_errors = 0
        self._accepting_frames = True

    def stop(self) -> None:
        """Prevent new native callbacks from touching the recorder."""
        self._accepting_frames = False

    def __call__(self, frame_pointer: Any, _user_data: Any) -> None:
        if not frame_pointer or not self._accepting_frames:
            return

        try:
            frame = frame_pointer.contents
            frame_number = int(frame.iFrame)
            if frame_number == self.last_frame:
                return

            self.last_frame = frame_number
            self.frames_received += 1
            snapshot = self.frame_snapshot(frame)
            if self.recorder is not None:
                self.recorder.write(snapshot, self.frames_received)

            if self.frames_received == 1 or not self.frames_received % self.print_every:
                print(
                    json.dumps(
                        self.preview_snapshot(snapshot),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        except Exception as exc:  # ctypes callbacks must not leak exceptions
            self.callback_errors += 1
            print(f"[callback error] {type(exc).__name__}: {exc}", file=sys.stderr)

    def preview_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Limit console output without truncating the recorded files."""
        preview = dict(snapshot)
        preview["marker_sets"] = [
            {**marker_set, "markers": marker_set["markers"][: self.max_points]}
            for marker_set in snapshot["marker_sets"][: self.max_points]
        ]
        preview["labeled_markers"] = snapshot["labeled_markers"][: self.max_points]
        preview["unidentified_markers"] = snapshot["unidentified_markers"][: self.max_points]
        preview["rigid_bodies"] = snapshot["rigid_bodies"][: self.max_points]
        preview["skeletons"] = [
            {**skeleton, "segments": skeleton["segments"][: self.max_points]}
            for skeleton in snapshot["skeletons"][: self.max_points]
        ]
        return preview

    @staticmethod
    def frame_snapshot(frame: Any) -> dict[str, Any]:
        marker_sets = []
        for set_index in range(int(frame.nMarkerSets)):
            marker_set = frame.MocapData[set_index]
            markers = []
            visible_count = 0
            for marker_index in range(int(marker_set.nMarkers)):
                xyz = point_xyz(marker_set.Markers[marker_index])
                valid = point_is_valid(xyz)
                visible_count += int(valid)
                markers.append(
                    {"index": marker_index, "xyz_mm": xyz, "valid": valid}
                )
            marker_sets.append(
                {
                    "name": decode_name(marker_set.szName),
                    "marker_count": int(marker_set.nMarkers),
                    "visible_count": visible_count,
                    "markers": markers,
                }
            )

        unidentified = []
        for marker_index in range(int(frame.nOtherMarkers)):
            xyz = point_xyz(frame.OtherMarkers[marker_index])
            unidentified.append(
                {"index": marker_index, "xyz_mm": xyz, "valid": point_is_valid(xyz)}
            )

        labeled = []
        for marker_index in range(int(frame.nLabeledMarkers)):
            marker = frame.LabeledMarkers[marker_index]
            xyz = [float(marker.x), float(marker.y), float(marker.z)]
            labeled.append(
                {
                    "id": int(marker.ID),
                    "xyz_mm": xyz,
                    "size": float(marker.size),
                    "valid": point_is_valid(xyz),
                }
            )

        rigid_bodies = []
        for body_index in range(int(frame.nRigidBodies)):
            body = frame.RigidBodies[body_index]
            rigid_bodies.append(
                {
                    "id": int(body.ID),
                    "position_mm": [float(body.x), float(body.y), float(body.z)],
                    "orientation_xyzw": [
                        float(body.qx), float(body.qy), float(body.qz), float(body.qw)
                    ],
                    "marker_count": int(body.nMarkers),
                    "mean_error": float(body.MeanError),
                    "params": int(body.params),
                }
            )

        skeletons = []
        for skeleton_index in range(int(frame.nSkeletons)):
            skeleton = frame.Skeletons[skeleton_index]
            segments = []
            for segment_index in range(int(skeleton.nRigidBodies)):
                body = skeleton.RigidBodyData[segment_index]
                marker_ids = []
                marker_points = []
                for marker_index in range(int(body.nMarkers)):
                    marker_ids.append(int(body.MarkerIDs[marker_index]))
                    marker_points.append(point_xyz(body.Markers[marker_index]))
                segments.append(
                    {
                        "index": segment_index,
                        "id": int(body.ID),
                        "position_mm": [float(body.x), float(body.y), float(body.z)],
                        "orientation_xyzw": [
                            float(body.qx),
                            float(body.qy),
                            float(body.qz),
                            float(body.qw),
                        ],
                        "marker_count": int(body.nMarkers),
                        "marker_ids": marker_ids,
                        "marker_points_mm": marker_points,
                        "mean_error": float(body.MeanError),
                        "params": int(body.params),
                    }
                )
            skeletons.append(
                {
                    "id": int(skeleton.skeletonID),
                    "segment_count": int(skeleton.nRigidBodies),
                    "segments": segments,
                }
            )

        return {
            "frame": int(frame.iFrame),
            "timestamp_ms": int(frame.iTimeStamp),
            "latency": float(frame.fLatency),
            "counts": {
                "marker_sets": int(frame.nMarkerSets),
                "labeled_markers": int(frame.nLabeledMarkers),
                "unidentified_markers": int(frame.nOtherMarkers),
                "rigid_bodies": int(frame.nRigidBodies),
                "skeletons": int(frame.nSkeletons),
                "analog_channels": int(frame.nAnalogdatas),
            },
            "marker_sets": marker_sets,
            "labeled_markers": labeled,
            "unidentified_markers": unidentified,
            "rigid_bodies": rigid_bodies,
            "skeletons": skeletons,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect and record live marker/rigid-body data from XINGYING."
    )
    parser.add_argument(
        "--server",
        default="10.1.1.198",
        help="XINGYING SDK server/NIC IPv4 address (default: %(default)s)",
    )
    parser.add_argument(
        "--print-every",
        type=int,
        default=30,
        help="Print one JSON preview every N received frames (default: %(default)s)",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=20,
        help="Maximum items shown per category in terminal only (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
        help="Parent folder for timestamped session folders (default: project data/raw folder)",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=DEFAULT_START_DELAY_S,
        help=(
            "Seconds to wait after connecting before recording starts "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_S,
        help=(
            "Seconds to record after the delay; 0 records until Ctrl+C "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--save-mode",
        choices=("full", "hand"),
        default=DEFAULT_SAVE_MODE,
        help=(
            "full saves JSON, marker sets, labeled markers, unidentified markers, "
            "rigid bodies, and skeleton data; hand saves frames, labeled markers, "
            "rigid bodies, and skeleton data "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--compress-on-finish",
        action="store_true",
        default=DEFAULT_COMPRESS_ON_FINISH,
        help="Gzip each saved text file after recording finishes. Enabled by default.",
    )
    parser.add_argument(
        "--no-compress-on-finish",
        dest="compress_on_finish",
        action="store_false",
        help="Keep newly recorded text files uncompressed for manual inspection.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Show terminal previews without saving files",
    )
    args = parser.parse_args()
    if args.print_every < 1:
        parser.error("--print-every must be at least 1")
    if args.max_points < 1:
        parser.error("--max-points must be at least 1")
    if args.start_delay < 0:
        parser.error("--start-delay must be greater than or equal to 0")
    if args.duration < 0:
        parser.error("--duration must be greater than or equal to 0")
    return args


def message_callback(level: int, message_pointer: Any) -> None:
    raw = ctypes.cast(message_pointer, ctypes.c_char_p).value
    message = raw.decode("utf-8", errors="replace") if raw else ""
    if level <= 2:
        print(f"[SDK level={level}] {message}", file=sys.stderr)


def read_data_descriptions(client: PySDKClient) -> dict[str, Any]:
    """Read XINGYING data descriptions, especially skeleton segment hierarchy."""
    pointer = ctypes.POINTER(DataDescriptions)()
    result = client.PyGetDataDescriptions(pointer)
    descriptions: dict[str, Any] = {
        "return_code": int(result) if result is not None else 0,
        "skeletons": [],
        "marker_sets": [],
        "rigid_bodies": [],
    }
    if not pointer:
        return descriptions

    data_defs = pointer.contents
    for index in range(int(data_defs.nDataDescriptions)):
        data_def = data_defs.arrDataDescriptions[index]
        if data_def.type == DataDescriptors.Descriptor_Skeleton.value:
            skeleton_def = data_def.Data.SkeletonDescription.contents
            segments = []
            for body_index in range(int(skeleton_def.nRigidBodies)):
                body_def = skeleton_def.RigidBodies[body_index]
                segments.append(
                    {
                        "index": body_index,
                        "id": int(body_def.ID),
                        "name": decode_name(body_def.szName),
                        "parent_id": int(body_def.parentID),
                        "offset_mm": [
                            float(body_def.offsetx),
                            float(body_def.offsety),
                            float(body_def.offsetz),
                        ],
                        "orientation_xyzw": [
                            float(body_def.qx),
                            float(body_def.qy),
                            float(body_def.qz),
                            float(body_def.qw),
                        ],
                    }
                )
            descriptions["skeletons"].append(
                {
                    "name": decode_name(skeleton_def.szName),
                    "id": int(skeleton_def.skeletonID),
                    "segment_count": int(skeleton_def.nRigidBodies),
                    "segments": segments,
                }
            )
        elif data_def.type == DataDescriptors.Descriptor_MarkerSet.value:
            marker_set_def = data_def.Data.MarkerSetDescription.contents
            descriptions["marker_sets"].append(
                {
                    "name": decode_name(marker_set_def.szName),
                    "marker_count": int(marker_set_def.nMarkers),
                    "markers": [
                        decode_name(marker_set_def.szMarkerNames[marker_index])
                        for marker_index in range(int(marker_set_def.nMarkers))
                    ],
                }
            )
        elif data_def.type == DataDescriptors.Descriptor_RigidBody.value:
            rigid_body_def = data_def.Data.RigidBodyDescription.contents
            descriptions["rigid_bodies"].append(
                {
                    "id": int(rigid_body_def.ID),
                    "name": decode_name(rigid_body_def.szName),
                    "parent_id": int(rigid_body_def.parentID),
                }
            )
    return descriptions


def main() -> int:
    args = parse_args()
    client = PySDKClient()
    version = tuple(int(value) for value in client.PyNokovVersion())

    print(f"Python: {sys.executable}")
    print("Nokov SDK version: " + ".".join(map(str, version)))
    print(f"Connecting to XINGYING SDK server: {args.server}")

    client.PySetVerbosityLevel(0)
    client.PySetMessageCallback(message_callback)
    result = client.Initialize(args.server.encode("utf-8"))
    if result != 0:
        print(f"Connection failed, SDK return code: {result}", file=sys.stderr)
        print(
            "Check the wired NIC address, XINGYING SDK Enabled setting, "
            "and whether Live Mode is running.",
            file=sys.stderr,
        )
        return int(result) or 1

    data_descriptions = read_data_descriptions(client)
    if data_descriptions["skeletons"]:
        print(
            "Skeleton templates: "
            + ", ".join(
                f"{item['name']}({item['segment_count']} segments)"
                for item in data_descriptions["skeletons"]
            )
        )
    else:
        print("Skeleton templates: none reported by SDK")

    try:
        sleep_with_countdown(args.start_delay, "Recording starts")
    except KeyboardInterrupt:
        print("\nCancelled before recording started.")
        del client
        gc.collect()
        return 130

    recorder = (
        None
        if args.no_save
        else SessionRecorder(
            args.output_dir.resolve(),
            save_mode=args.save_mode,
            compress_on_finish=args.compress_on_finish,
            data_descriptions=data_descriptions,
        )
    )
    inspector = FrameInspector(args.print_every, args.max_points, recorder)
    if recorder is not None:
        print(f"Recording every received frame to session folder:\n  {recorder.session_dir}")
        print(f"Save mode: {recorder.save_mode}")
        if recorder.compress_on_finish:
            print("Compression: enabled after recording finishes")
        print("Files:")
        for path in recorder.paths.values():
            print(f"  {path.name}")

    callback_result = client.PySetDataCallback(inspector, None)
    if callback_result != 0:
        if recorder is not None:
            recorder.close()
        print(
            f"Registering the data callback failed: {callback_result}",
            file=sys.stderr,
        )
        return int(callback_result) or 1

    if args.duration > 0:
        print(f"Connected. Recording for {args.duration:g} seconds; press Ctrl+C to stop early.")
    else:
        print("Connected. Waiting for frames; press Ctrl+C to stop safely.")
    try:
        started_at = time.monotonic()
        while True:
            if args.duration > 0:
                remaining = args.duration - (time.monotonic() - started_at)
                if remaining <= 0:
                    print("\nRequested duration reached; stopping safely...")
                    break
                time.sleep(min(0.2, remaining))
            else:
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping safely; waiting for the SDK callback to finish...")
    finally:
        # Stop accepting frames before the SDK client uninitializes. Destroying
        # the client first lets the native SDK finish any in-flight callback;
        # only then is it safe to close the output streams.
        inspector.stop()
        del client
        gc.collect()
        if recorder is not None:
            recorder.close()
            print(f"Saved session folder: {recorder.session_dir}")
            if recorder.compress_on_finish:
                print("Compressed files:")
                for path in recorder.paths.values():
                    print(f"  {path.name}")
        print(
            f"Stopped. Unique frames received: {inspector.frames_received}; "
            f"callback errors: {inspector.callback_errors}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

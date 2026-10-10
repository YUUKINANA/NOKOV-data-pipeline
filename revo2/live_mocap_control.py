"""Live NOKOV/XINGYING 24-marker control loop for the REVO2 hand.

Pipeline:
  XINGYING SDK live frames -> 24 labeled hand markers -> stable 6-D controls
  -> bounded 0..1000 REVO2 position commands.

The script is safe by default: it only prints computed commands. Add
``--enable-hand`` to actually open the REVO2 serial port and send commands.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np

from ml.hand_control_filter import StableHandControlFilter
from ml.synthetic_hand_pipeline import (
    CONTROL_CHANNELS,
    MARKER_NAMES,
    infer_marker_id_offset,
)
from revo2.replay_positions import (
    CHANNEL_COLUMNS,
    DEFAULT_FALLBACK_POSITIONS,
    _clip,
)
from revo2.send_positions import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_SLAVE_ID,
    _baudrate_from_int,
    _close_client,
    _format_positions,
    _normalized_positions,
    _normalized_speed,
    stark,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER = "10.1.1.198"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_RATE_HZ = 15.0
DEFAULT_SPEED = 250
DEFAULT_MAX_POSITION = 500
DEFAULT_MAX_STEP = 35
DEFAULT_START_POSITIONS = DEFAULT_FALLBACK_POSITIONS
DEFAULT_OUTPUT_DEADBAND = 10
DEFAULT_OUTPUT_QUANTUM = 5
DEFAULT_OUTPUT_ALPHA = 0.6
DEFAULT_MIN_CONFIDENCE = 0.15

MarkerOffsetMode = Literal["auto", "0", "24", "48", "72"]


@dataclass(frozen=True)
class LiveMocapFrame:
    sample_index: int
    frame_no: int
    timestamp_ms: int
    elapsed_s: float
    latency_ms: float
    markers: dict[int, np.ndarray]
    raw_marker_count: int
    marker_id_offset: int


@dataclass(frozen=True)
class CommandFrame:
    positions: list[int]
    normalized_controls: dict[str, float]
    confidence: float
    raw_valid: bool
    model_valid: bool
    held_from_previous: bool
    missing_marker_ids: list[int]
    imputed_marker_ids: list[int]


@dataclass(frozen=True)
class MechanicalSafetyResult:
    positions: list[int]
    should_send: bool
    reason: str


class LatestFrameBuffer:
    """Thread-safe one-slot buffer.

    The SDK may deliver frames at about 90 Hz while the hand should receive a
    much lower-rate command stream. Keeping only the newest frame avoids a
    growing delay backlog.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: LiveMocapFrame | None = None
        self.received = 0
        self.overwritten = 0

    def push(self, frame: LiveMocapFrame) -> None:
        with self._lock:
            if self._frame is not None:
                self.overwritten += 1
            self._frame = frame
            self.received += 1

    def pop_latest(self) -> LiveMocapFrame | None:
        with self._lock:
            frame = self._frame
            self._frame = None
            return frame


class MechanicalSafetyOutputLayer:
    """Final guard before sending commands to real REVO2 hardware.

    The upstream hand model intentionally tracks small motion. Real servos do
    not need every tiny numerical wiggle, so this layer freezes low-confidence
    frames, quantizes positions, smooths the final 0..1000 signal, and suppresses
    sends whose change is smaller than a mechanical deadband.
    """

    def __init__(
        self,
        initial_positions: Sequence[int],
        *,
        deadband: int = DEFAULT_OUTPUT_DEADBAND,
        quantum: int = DEFAULT_OUTPUT_QUANTUM,
        alpha: float = DEFAULT_OUTPUT_ALPHA,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        keepalive_s: float = 0.0,
    ) -> None:
        if deadband < 0:
            raise ValueError("deadband cannot be negative")
        if quantum <= 0:
            raise ValueError("quantum must be positive")
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be in [0, 1]")
        if keepalive_s < 0:
            raise ValueError("keepalive_s cannot be negative")

        self.deadband = int(deadband)
        self.quantum = int(quantum)
        self.alpha = float(alpha)
        self.min_confidence = float(min_confidence)
        self.keepalive_s = float(keepalive_s)
        self._last_output = _normalized_positions(initial_positions)
        self._last_send_elapsed_s: float | None = None

    @property
    def last_output(self) -> list[int]:
        return self._last_output.copy()

    def apply(
        self,
        target_positions: Sequence[int],
        *,
        confidence: float,
        elapsed_s: float,
    ) -> MechanicalSafetyResult:
        target = _normalized_positions(target_positions)

        if confidence < self.min_confidence:
            return MechanicalSafetyResult(
                positions=self.last_output,
                should_send=False,
                reason="low_confidence",
            )

        quantized = self._quantize(target)
        smoothed = [
            _clip(
                round(previous + self.alpha * (next_value - previous)),
                0,
                1000,
            )
            for previous, next_value in zip(self._last_output, quantized, strict=True)
        ]
        deltas = [
            abs(next_value - previous)
            for previous, next_value in zip(self._last_output, smoothed, strict=True)
        ]

        if self._last_send_elapsed_s is None:
            self._last_output = smoothed
            self._last_send_elapsed_s = elapsed_s
            return MechanicalSafetyResult(
                positions=self.last_output,
                should_send=True,
                reason="first_output",
            )

        keepalive_due = (
            self.keepalive_s > 0
            and elapsed_s - self._last_send_elapsed_s >= self.keepalive_s
        )
        if max(deltas, default=0) < self.deadband and not keepalive_due:
            return MechanicalSafetyResult(
                positions=self.last_output,
                should_send=False,
                reason="deadband",
            )

        self._last_output = smoothed
        self._last_send_elapsed_s = elapsed_s
        return MechanicalSafetyResult(
            positions=self.last_output,
            should_send=True,
            reason="changed" if not keepalive_due else "keepalive",
        )

    def _quantize(self, positions: Sequence[int]) -> list[int]:
        if self.quantum <= 1:
            return _normalized_positions(positions)
        return [
            _clip(round(round(position / self.quantum) * self.quantum), 0, 1000)
            for position in positions
        ]


class LiveFrameCallback:
    """SDK callback that extracts one latest hand-marker frame."""

    def __init__(
        self,
        *,
        buffer: LatestFrameBuffer,
        frame_snapshot,
        marker_id_offset: MarkerOffsetMode,
        recorder: Any | None = None,
    ) -> None:
        self.buffer = buffer
        self.frame_snapshot = frame_snapshot
        self.marker_id_offset = marker_id_offset
        self.recorder = recorder
        self.frames_received = 0
        self.callback_errors = 0
        self.last_frame_no: int | None = None
        self._accepting_frames = True
        self._first_received_at: float | None = None

    def stop(self) -> None:
        self._accepting_frames = False

    def __call__(self, frame_pointer: Any, _user_data: Any) -> None:
        if not frame_pointer or not self._accepting_frames:
            return

        try:
            frame = frame_pointer.contents
            frame_no = int(frame.iFrame)
            if frame_no == self.last_frame_no:
                return
            self.last_frame_no = frame_no
            self.frames_received += 1

            received_at = time.perf_counter()
            if self._first_received_at is None:
                self._first_received_at = received_at
            elapsed_s = received_at - self._first_received_at

            snapshot = self.frame_snapshot(frame)
            if self.recorder is not None:
                self.recorder.write(snapshot, self.frames_received)

            markers, offset = normalize_labeled_markers(
                snapshot["labeled_markers"], self.marker_id_offset
            )
            self.buffer.push(
                LiveMocapFrame(
                    sample_index=self.frames_received,
                    frame_no=frame_no,
                    timestamp_ms=int(snapshot["timestamp_ms"]),
                    elapsed_s=elapsed_s,
                    latency_ms=float(snapshot["latency"]),
                    markers=markers,
                    raw_marker_count=len(snapshot["labeled_markers"]),
                    marker_id_offset=offset,
                )
            )
        except Exception as exc:  # ctypes callbacks must not leak exceptions
            self.callback_errors += 1
            print(f"[callback error] {type(exc).__name__}: {exc}", file=sys.stderr)


def normalize_labeled_markers(
    labeled_markers: Sequence[dict[str, Any]],
    marker_id_offset: MarkerOffsetMode = "auto",
) -> tuple[dict[int, np.ndarray], int]:
    """Normalize XINGYING hand marker IDs to the semantic 1..24 table."""

    raw: dict[int, np.ndarray] = {}
    for marker in labeled_markers:
        if not marker.get("valid", False):
            continue
        marker_id = int(marker["id"])
        xyz = marker["xyz_mm"]
        raw[marker_id] = np.array(
            [float(xyz[0]), float(xyz[1]), float(xyz[2])], dtype=float
        )

    if marker_id_offset == "auto":
        offset = infer_marker_id_offset(set(raw))
    else:
        offset = int(marker_id_offset)

    normalized = {
        marker_id - offset: point
        for marker_id, point in raw.items()
        if marker_id - offset in MARKER_NAMES
    }
    return normalized, offset


def controls_to_revo2_positions(
    normalized_controls: dict[str, float],
    previous_positions: Sequence[int],
    *,
    max_position: int,
    max_step: int,
    hold_thumb: bool = False,
) -> list[int]:
    """Convert 0..1 control channels into bounded REVO2 0..1000 positions."""

    previous = _normalized_positions(previous_positions)
    max_position = _clip(int(max_position), 0, 1000)
    max_step = max(1, int(max_step))
    positions = previous.copy()

    for finger_index, column in CHANNEL_COLUMNS.items():
        if hold_thumb and finger_index in (0, 1):
            continue

        channel = column.removeprefix("command_").removesuffix("_0_1")
        normalized = float(normalized_controls.get(channel, math.nan))
        if math.isfinite(normalized):
            target = _clip(round(normalized * 1000), 0, max_position)
        else:
            target = previous[finger_index]

        delta = _clip(target - previous[finger_index], -max_step, max_step)
        positions[finger_index] = previous[finger_index] + delta

    return positions


def build_command_frame(
    result,
    previous_positions: Sequence[int],
    *,
    max_position: int,
    max_step: int,
    hold_thumb: bool,
) -> CommandFrame:
    positions = controls_to_revo2_positions(
        result.commands,
        previous_positions,
        max_position=max_position,
        max_step=max_step,
        hold_thumb=hold_thumb,
    )
    return CommandFrame(
        positions=positions,
        normalized_controls=dict(result.commands),
        confidence=float(result.confidence),
        raw_valid=bool(result.raw_valid),
        model_valid=bool(result.model_valid),
        held_from_previous=bool(result.held_from_previous),
        missing_marker_ids=list(result.missing_marker_ids),
        imputed_marker_ids=list(result.imputed_marker_ids),
    )


async def _read_current_positions_or_fallback(
    client: Any,
    slave_id: int,
    fallback_positions: Sequence[int],
) -> list[int]:
    try:
        current = await client.get_finger_positions(slave_id)
        return _normalized_positions([int(value) for value in list(current)])
    except Exception as exc:
        fallback = _normalized_positions(fallback_positions)
        print(
            "[warn] failed to read current REVO2 positions; "
            f"using fallback: {_format_positions(fallback)} ({exc})"
        )
        return fallback


async def _send_positions_best_effort(
    client: Any,
    *,
    slave_id: int,
    positions: Sequence[int],
    speeds: Sequence[int],
) -> bool:
    try:
        await client.set_finger_positions_and_speeds(
            slave_id, list(positions), list(speeds)
        )
        return True
    except Exception as exc:
        print(f"[warn] REVO2 send failed: {exc}")
        return False


def _format_controls(commands: dict[str, float]) -> str:
    return ", ".join(
        f"{channel}={commands[channel]:.3f}"
        for channel in CONTROL_CHANNELS
        if channel in commands and math.isfinite(float(commands[channel]))
    )


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _alpha_float(value: str) -> float:
    parsed = _positive_float(value)
    if parsed > 1:
        raise argparse.ArgumentTypeError("value must be <= 1")
    return parsed


def _unit_interval_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("value must be in [0, 1]")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime XINGYING/NOKOV 24-marker capture -> 6-D controls -> "
            "optional REVO2 hand output."
        )
    )

    mocap = parser.add_argument_group("XINGYING/NOKOV live input")
    mocap.add_argument("--server", default=DEFAULT_SERVER)
    mocap.add_argument(
        "--marker-id-offset",
        choices=("auto", "0", "24", "48", "72"),
        default="auto",
        help=(
            "How to map SDK marker IDs onto the 1..24 XINGYING hand table. "
            "Use auto unless the SDK template ID range is known."
        ),
    )
    mocap.add_argument(
        "--start-delay",
        type=_non_negative_float,
        default=0.0,
        help="Seconds to wait after connecting before control starts.",
    )
    mocap.add_argument(
        "--duration",
        type=_non_negative_float,
        default=0.0,
        help="Seconds to run. 0 means run until Ctrl+C.",
    )
    mocap.add_argument(
        "--record",
        action="store_true",
        help="Also save the raw live mocap session under data/raw/mocap_...",
    )
    mocap.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Parent folder used by --record.",
    )
    mocap.add_argument(
        "--no-compress-on-finish",
        action="store_true",
        help="Keep recorded CSV/JSON files uncompressed when --record is used.",
    )

    control = parser.add_argument_group("6-D control calculation")
    control.add_argument("--rate-hz", type=_positive_float, default=DEFAULT_RATE_HZ)
    control.add_argument("--hold-s", type=_non_negative_float, default=0.25)
    control.add_argument("--smooth-alpha", type=_alpha_float, default=0.35)
    control.add_argument("--max-rate-per-s", type=_positive_float, default=3.0)
    control.add_argument(
        "--max-position",
        type=int,
        default=DEFAULT_MAX_POSITION,
        help="Clamp every generated REVO2 position to this 0..1000 ceiling.",
    )
    control.add_argument(
        "--max-step",
        type=_positive_int,
        default=DEFAULT_MAX_STEP,
        help="Maximum 0..1000 command change allowed per send tick.",
    )
    control.add_argument(
        "--hold-thumb",
        action="store_true",
        help="Keep the two thumb channels fixed and only drive index/middle/ring/pinky.",
    )
    control.add_argument(
        "--print-every",
        type=_positive_int,
        default=15,
        help="Print one status line every N send ticks.",
    )
    control.add_argument(
        "--output-deadband",
        type=_non_negative_int,
        default=DEFAULT_OUTPUT_DEADBAND,
        help=(
            "Suppress REVO2 output if all 0..1000 channel changes are smaller "
            "than this value. 0 disables the deadband."
        ),
    )
    control.add_argument(
        "--output-quantum",
        type=_positive_int,
        default=DEFAULT_OUTPUT_QUANTUM,
        help=(
            "Round final REVO2 positions to this step size before sending. "
            "1 disables quantization."
        ),
    )
    control.add_argument(
        "--output-alpha",
        type=_alpha_float,
        default=DEFAULT_OUTPUT_ALPHA,
        help=(
            "Final 0..1000 output smoothing factor. Smaller is steadier; "
            "1 disables this extra smoothing."
        ),
    )
    control.add_argument(
        "--min-confidence",
        type=_unit_interval_float,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Freeze final output while marker confidence is below this value.",
    )
    control.add_argument(
        "--keepalive-s",
        type=_non_negative_float,
        default=0.0,
        help=(
            "Optionally resend the last safe command after this many seconds "
            "even when inside the deadband. 0 disables keepalive."
        ),
    )

    hand = parser.add_argument_group("REVO2 output")
    hand.add_argument(
        "--enable-hand",
        action="store_true",
        help="Actually open the serial port and send commands to REVO2.",
    )
    hand.add_argument("--port", default=DEFAULT_PORT)
    hand.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    hand.add_argument("--slave-id", type=int, default=DEFAULT_SLAVE_ID)
    hand.add_argument("--speed", type=_normalized_speed, default=DEFAULT_SPEED)
    hand.add_argument(
        "--start-positions",
        nargs=6,
        type=int,
        default=DEFAULT_START_POSITIONS,
        metavar="POS",
        help="Fallback 6-D start positions if REVO2 readback fails.",
    )
    hand.add_argument(
        "--max-send-errors",
        type=_positive_int,
        default=5,
        help="Stop after this many consecutive REVO2 send failures.",
    )
    hand.add_argument(
        "--open-on-exit",
        action="store_true",
        help="When --enable-hand is used, send [0,0,0,0,0,0] before exiting.",
    )

    return parser


async def run_live_control(args: argparse.Namespace) -> None:
    from mocap.inspect_mocap import (  # Imported lazily for dry import/tests.
        FrameInspector,
        SessionRecorder,
        message_callback,
        read_data_descriptions,
        sleep_with_countdown,
    )
    from nokov.nokovsdk import PySDKClient

    max_position = _clip(int(args.max_position), 0, 1000)
    speeds = [_normalized_speed(args.speed)] * 6
    fallback_positions = _normalized_positions(args.start_positions)
    frame_buffer = LatestFrameBuffer()
    hand_filter = StableHandControlFilter(
        hold_s=args.hold_s,
        smooth_alpha=args.smooth_alpha,
        max_rate_per_s=args.max_rate_per_s,
    )

    print(f"Connecting to XINGYING SDK server: {args.server}")
    mocap_client = PySDKClient()
    version = tuple(int(value) for value in mocap_client.PyNokovVersion())
    print("Nokov SDK version: " + ".".join(map(str, version)))
    mocap_client.PySetVerbosityLevel(0)
    mocap_client.PySetMessageCallback(message_callback)
    result = mocap_client.Initialize(args.server.encode("utf-8"))
    if result != 0:
        raise RuntimeError(
            f"XINGYING SDK connection failed with return code {result}. "
            "Check Live Mode, SDK/NIC settings, and the wired network."
        )

    data_descriptions = read_data_descriptions(mocap_client)
    recorder = None
    revo_client = None
    callback = None
    previous_positions = fallback_positions
    safety_layer: MechanicalSafetyOutputLayer | None = None
    stats = {
        "ticks": 0,
        "commands": 0,
        "outputs": 0,
        "suppressed": 0,
        "frozen_low_confidence": 0,
        "skipped_no_frame": 0,
        "skipped_invalid": 0,
        "send_errors": 0,
        "consecutive_send_errors": 0,
    }

    try:
        if args.record:
            recorder = SessionRecorder(
                args.output_dir.resolve(),
                save_mode="hand",
                compress_on_finish=not args.no_compress_on_finish,
                data_descriptions=data_descriptions,
            )
            print(f"Recording raw mocap frames to:\n  {recorder.session_dir}")

        callback = LiveFrameCallback(
            buffer=frame_buffer,
            frame_snapshot=FrameInspector.frame_snapshot,
            marker_id_offset=args.marker_id_offset,
            recorder=recorder,
        )
        callback_result = mocap_client.PySetDataCallback(callback, None)
        if callback_result != 0:
            raise RuntimeError(
                f"Registering the XINGYING data callback failed: {callback_result}"
            )

        if args.start_delay > 0:
            sleep_with_countdown(args.start_delay, "Realtime control starts")

        if args.enable_hand:
            print(
                f"Opening REVO2: port={args.port}, baudrate={args.baudrate}, "
                f"slave_id={args.slave_id}"
            )
            revo_client = await stark.modbus_open(
                args.port, _baudrate_from_int(args.baudrate)
            )
            await revo_client.set_finger_unit_mode(
                args.slave_id, stark.FingerUnitMode.Normalized
            )
            previous_positions = await _read_current_positions_or_fallback(
                revo_client, args.slave_id, fallback_positions
            )
        else:
            print("Dry-run mode: REVO2 serial port is not opened.")

        safety_layer = MechanicalSafetyOutputLayer(
            previous_positions,
            deadband=args.output_deadband,
            quantum=args.output_quantum,
            alpha=args.output_alpha,
            min_confidence=args.min_confidence,
            keepalive_s=args.keepalive_s,
        )

        print(
            f"Control loop: {args.rate_hz:g} Hz, speed={args.speed}, "
            f"max_position={max_position}, max_step={args.max_step}, "
            f"mode={'hold thumb' if args.hold_thumb else 'all six channels'}"
        )
        print(
            "Mechanical safety output: "
            f"deadband={args.output_deadband}, quantum={args.output_quantum}, "
            f"alpha={args.output_alpha:g}, min_confidence={args.min_confidence:g}, "
            f"keepalive_s={args.keepalive_s:g}"
        )
        if args.duration > 0:
            print(f"Running for {args.duration:g} seconds. Press Ctrl+C to stop early.")
        else:
            print("Running until Ctrl+C.")

        started_at = time.perf_counter()
        next_tick = started_at
        tick_interval = 1.0 / args.rate_hz

        while True:
            now = time.perf_counter()
            if args.duration > 0 and now - started_at >= args.duration:
                print("Requested duration reached; stopping.")
                break

            if now < next_tick:
                await asyncio.sleep(min(next_tick - now, 0.02))
                continue
            next_tick += tick_interval
            stats["ticks"] += 1

            frame = frame_buffer.pop_latest()
            if frame is None:
                stats["skipped_no_frame"] += 1
                if stats["ticks"] == 1 or not stats["ticks"] % args.print_every:
                    print("[wait] no mocap frame available yet")
                continue

            stable = hand_filter.update(frame.markers, frame.elapsed_s)
            command = build_command_frame(
                stable,
                safety_layer.last_output,
                max_position=max_position,
                max_step=args.max_step,
                hold_thumb=args.hold_thumb,
            )

            if not all(math.isfinite(value) for value in command.normalized_controls.values()):
                stats["skipped_invalid"] += 1
                if stats["ticks"] == 1 or not stats["ticks"] % args.print_every:
                    print(
                        "[wait] not enough markers to initialize hand model; "
                        f"visible={len(frame.markers)}/24, missing={command.missing_marker_ids}"
                    )
                continue

            safe_output = safety_layer.apply(
                command.positions,
                confidence=command.confidence,
                elapsed_s=frame.elapsed_s,
            )
            stats["commands"] += 1

            if not safe_output.should_send:
                stats["suppressed"] += 1
                if safe_output.reason == "low_confidence":
                    stats["frozen_low_confidence"] += 1

            if safe_output.should_send and args.enable_hand and revo_client is not None:
                sent = await _send_positions_best_effort(
                    revo_client,
                    slave_id=args.slave_id,
                    positions=safe_output.positions,
                    speeds=speeds,
                )
                if sent:
                    stats["consecutive_send_errors"] = 0
                else:
                    stats["send_errors"] += 1
                    stats["consecutive_send_errors"] += 1
                    if stats["consecutive_send_errors"] >= args.max_send_errors:
                        raise RuntimeError(
                            "Too many consecutive REVO2 send failures; stopping for safety."
                        )

            if safe_output.should_send:
                stats["outputs"] += 1
            previous_positions = safe_output.positions

            if stats["commands"] == 1 or not stats["commands"] % args.print_every:
                print(
                    f"frame={frame.frame_no} visible={len(frame.markers)}/24 "
                    f"offset={frame.marker_id_offset} conf={command.confidence:.2f} "
                    f"target=[{_format_positions(command.positions)}] "
                    f"output=[{_format_positions(safe_output.positions)}] "
                    f"action={safe_output.reason} "
                    f"controls=[{_format_controls(command.normalized_controls)}]"
                )
                if command.imputed_marker_ids or command.held_from_previous:
                    print(
                        "  tolerance: "
                        f"imputed={command.imputed_marker_ids} "
                        f"held={command.held_from_previous}"
                    )
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        if callback is not None:
            callback.stop()
        if revo_client is not None:
            if args.open_on_exit:
                try:
                    await _send_positions_best_effort(
                        revo_client,
                        slave_id=args.slave_id,
                        positions=[0, 0, 0, 0, 0, 0],
                        speeds=speeds,
                    )
                    print("Sent open command on exit.")
                except Exception as exc:
                    print(f"[warn] open-on-exit failed: {exc}")
            await _close_client(revo_client)
        del mocap_client
        gc.collect()
        if recorder is not None:
            recorder.close()
            print(f"Saved live raw session: {recorder.session_dir}")
        if callback is not None:
            print(
                "Stopped. "
                f"SDK frames={callback.frames_received}; "
                f"buffer overwrites={frame_buffer.overwritten}; "
                f"computed commands={stats['commands']}; "
                f"outputs={stats['outputs']}; "
                f"suppressed={stats['suppressed']}; "
                f"low-confidence freezes={stats['frozen_low_confidence']}; "
                f"no-frame ticks={stats['skipped_no_frame']}; "
                f"invalid ticks={stats['skipped_invalid']}; "
                f"send errors={stats['send_errors']}; "
                f"callback errors={callback.callback_errors}"
            )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run_live_control(args))
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 130
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

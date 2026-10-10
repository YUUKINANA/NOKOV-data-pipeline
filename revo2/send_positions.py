"""Minimal REVO2 position sender using the official BrainCo Python SDK.

This module only handles the low-level hand link:
COM port -> Modbus/RS485 -> six normalized finger positions.

Finger order used by REVO2:
  0 thumb flex
  1 thumb auxiliary motion
  2 index
  3 middle
  4 ring
  5 pinky
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
from collections.abc import Sequence

from bc_stark_sdk import main_mod as stark


DEFAULT_PORT = "COM3"
DEFAULT_SLAVE_ID = 127
DEFAULT_BAUDRATE = 460800
DEFAULT_SPEED = 200

FINGER_NAMES = (
    "thumb_flex",
    "thumb_aux",
    "index",
    "middle",
    "ring",
    "pinky",
)


def _baudrate_from_int(value: int):
    mapping = {
        115200: stark.Baudrate.Baud115200,
        57600: stark.Baudrate.Baud57600,
        19200: stark.Baudrate.Baud19200,
        460800: stark.Baudrate.Baud460800,
        1000000: stark.Baudrate.Baud1Mbps,
        2000000: stark.Baudrate.Baud2Mbps,
        3000000: stark.Baudrate.Baud3Mbps,
        4000000: stark.Baudrate.Baud4Mbps,
        5000000: stark.Baudrate.Baud5Mbps,
        6000000: stark.Baudrate.Baud6Mbps,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        known = ", ".join(str(item) for item in sorted(mapping))
        raise argparse.ArgumentTypeError(
            f"Unsupported baudrate {value}. Known values: {known}"
        ) from exc


def _normalized_positions(values: Sequence[int]) -> list[int]:
    if len(values) != 6:
        raise argparse.ArgumentTypeError("Exactly 6 position values are required.")
    positions = [int(value) for value in values]
    bad_values = [value for value in positions if value < 0 or value > 1000]
    if bad_values:
        raise argparse.ArgumentTypeError(
            f"Positions must be in 0..1000, got {bad_values}"
        )
    return positions


def _normalized_speed(value: int) -> int:
    speed = int(value)
    if speed < 0 or speed > 1000:
        raise argparse.ArgumentTypeError("Speed must be in 0..1000.")
    return speed


def _format_positions(values: Sequence[int]) -> str:
    return ", ".join(
        f"{name}={value}" for name, value in zip(FINGER_NAMES, values, strict=True)
    )


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _open_client(port: str, baudrate: int):
    return await stark.modbus_open(port, _baudrate_from_int(baudrate))


async def _close_client(client) -> None:
    await _maybe_await(stark.modbus_close(client))


async def _status_call(
    label: str,
    port: str,
    baudrate: int,
    slave_id: int,
    method_name: str,
) -> bool:
    print(f"[check] {label} ...")
    client = await _open_client(port, baudrate)
    try:
        method = getattr(client, method_name)
        value = await method(slave_id)
        if method_name == "get_finger_positions":
            value = _format_positions(list(value))
        elif hasattr(value, "description"):
            value = value.description
        print(f"[ ok ] {label}: {value}")
        return True
    except Exception as exc:
        print(f"[fail] {label}: {exc}")
        return False
    finally:
        try:
            await _close_client(client)
        except Exception as exc:
            print(f"[warn] close after {label}: {exc}")


async def read_status(port: str, baudrate: int, slave_id: int) -> None:
    print(f"Port: {port}, baudrate: {baudrate}, slave_id: {slave_id}")
    checks = (
        ("open/read device info", "get_device_info"),
        ("read finger unit mode", "get_finger_unit_mode"),
        ("read finger positions", "get_finger_positions"),
        ("read motor status", "get_motor_status"),
    )
    results = [
        await _status_call(label, port, baudrate, slave_id, method_name)
        for label, method_name in checks
    ]
    if not any(results):
        raise RuntimeError(
            "Connected to the serial port, but the REVO2 did not respond to any "
            "status query. Close the official desktop app, replug the USB-RS485 "
            "adapter, and verify port/baudrate/slave-id."
        )


async def send_positions(
    port: str,
    baudrate: int,
    slave_id: int,
    positions: Sequence[int],
    speeds: Sequence[int] | None = None,
    speed: int | None = DEFAULT_SPEED,
    verify_info: bool = False,
    readback: bool = False,
) -> None:
    positions = _normalized_positions(positions)
    if speeds is not None:
        speeds = _normalized_positions(speeds)
    elif speed is not None:
        speeds = [_normalized_speed(speed)] * 6

    client = await _open_client(port, baudrate)
    try:
        if verify_info:
            info = await client.get_device_info(slave_id)
            print(f"Device info: {info}")

        await client.set_finger_unit_mode(slave_id, stark.FingerUnitMode.Normalized)
        print("Finger unit mode set to Normalized.")

        if speeds is None:
            await client.set_finger_positions(slave_id, positions)
        else:
            await client.set_finger_positions_and_speeds(slave_id, positions, speeds)

        print(f"Sent positions: {_format_positions(positions)}")
        if speeds is not None:
            print(f"Sent speeds: {_format_positions(speeds)}")
        if readback:
            try:
                current = await client.get_finger_positions(slave_id)
                print(f"Current positions: {_format_positions(list(current))}")
            except Exception as exc:
                print(f"[warn] readback failed after send: {exc}")
    finally:
        await _close_client(client)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send six normalized 0..1000 position commands to a REVO2 hand."
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serial port, e.g. COM3.")
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help="Serial baudrate. Default: 460800.",
    )
    parser.add_argument(
        "--slave-id",
        type=int,
        default=DEFAULT_SLAVE_ID,
        help="Modbus device id. Default: 127.",
    )
    parser.add_argument(
        "--verify-info",
        action="store_true",
        help="Also read device info before sending. Disabled by default.",
    )
    parser.add_argument(
        "--readback",
        action="store_true",
        help="Read finger positions after sending.",
    )
    parser.add_argument(
        "--speed",
        type=_normalized_speed,
        default=DEFAULT_SPEED,
        help="Use one speed value for all fingers when sending. Default: 200.",
    )
    parser.add_argument(
        "--no-speed",
        action="store_true",
        help="Send positions without an explicit speed value.",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Connect and print device status only.")
    open_parser = subparsers.add_parser("open", help="Send [0, 0, 0, 0, 0, 0].")
    open_parser.add_argument(
        "--speed",
        type=_normalized_speed,
        default=argparse.SUPPRESS,
        help="Use one speed value for all fingers when sending. Default: 200.",
    )
    open_parser.add_argument(
        "--no-speed",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Send positions without an explicit speed value.",
    )

    send_parser = subparsers.add_parser("send", help="Send six explicit positions.")
    send_parser.add_argument(
        "positions",
        nargs=6,
        type=int,
        metavar="POS",
        help="Six values in 0..1000.",
    )
    send_parser.add_argument(
        "--speeds",
        nargs=6,
        type=int,
        metavar="SPD",
        help="Optional six speed values in 0..1000.",
    )
    send_parser.add_argument(
        "--speed",
        type=_normalized_speed,
        default=argparse.SUPPRESS,
        help="Use one speed value for all fingers when sending. Default: 200.",
    )
    send_parser.add_argument(
        "--no-speed",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Send positions without an explicit speed value.",
    )

    return parser


async def main_async(args: argparse.Namespace) -> None:
    command = args.command or "status"
    if command == "status":
        await read_status(args.port, args.baudrate, args.slave_id)
    elif command == "open":
        await send_positions(
            args.port,
            args.baudrate,
            args.slave_id,
            [0] * 6,
            speed=None if args.no_speed else args.speed,
            verify_info=args.verify_info,
            readback=args.readback,
        )
    elif command == "send":
        await send_positions(
            args.port,
            args.baudrate,
            args.slave_id,
            args.positions,
            args.speeds,
            None if args.no_speed else args.speed,
            args.verify_info,
            args.readback,
        )
    else:
        raise ValueError(f"Unknown command: {command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Process one real hand session and replay the stable six-channel output."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.process_hand_sessions import process_session  # noqa: E402
from ml.replay_hand_motion import choose_session_folder, replay  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one NOKOV hand session and replay stable 6-D controls."
    )
    parser.add_argument(
        "--session",
        type=Path,
        help="Raw session folder. If omitted, a folder picker opens.",
    )
    parser.add_argument("--speed", type=float, default=0.5)
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
        "--no-visual",
        action="store_true",
        help="Generate processed files without opening the replay window.",
    )
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be greater than 0")
    if args.ui_fps <= 0:
        parser.error("--ui-fps must be greater than 0")
    if args.hold_s < 0:
        parser.error("--hold-s must be greater than or equal to 0")
    if not 0 < args.smooth_alpha <= 1:
        parser.error("--smooth-alpha must be in (0, 1]")
    if args.max_rate <= 0:
        parser.error("--max-rate must be greater than 0")
    return args


def main() -> int:
    args = parse_args()
    session = args.session.resolve() if args.session else choose_session_folder()
    if session is None:
        print("No session selected; demo cancelled.")
        return 0

    processed_dir = process_session(
        session,
        hold_s=args.hold_s,
        smooth_alpha=args.smooth_alpha,
        max_rate_per_s=args.max_rate,
    )
    print(f"Processed stable 6-D controls: {processed_dir / 'controls_6d_stable.csv'}")
    replay(
        session,
        speed=args.speed,
        ui_fps=args.ui_fps,
        print_every=args.print_every,
        visual=not args.no_visual,
        hold_s=args.hold_s,
        smooth_alpha=args.smooth_alpha,
        max_rate_per_s=args.max_rate,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

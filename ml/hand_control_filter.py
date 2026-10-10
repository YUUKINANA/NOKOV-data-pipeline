"""Robust provisional 24-marker to 6-D hand-control filtering."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ml.synthetic_hand_pipeline import (
    CONTROL_CHANNELS,
    MARKER_NAMES,
    estimate_six_controls,
)


@dataclass(frozen=True)
class StableControlResult:
    raw_valid: bool
    model_valid: bool
    held_from_previous: bool
    confidence: float
    missing_marker_ids: list[int]
    imputed_marker_ids: list[int]
    commands: dict[str, float]
    angles: dict[str, float]


class StableHandControlFilter:
    """Keep six hand-control channels continuous through short marker dropouts."""

    def __init__(
        self,
        *,
        hold_s: float = 0.25,
        smooth_alpha: float = 0.35,
        max_rate_per_s: float = 3.0,
    ) -> None:
        if hold_s < 0:
            raise ValueError("hold_s cannot be negative")
        if not 0 < smooth_alpha <= 1:
            raise ValueError("smooth_alpha must be in (0, 1]")
        if max_rate_per_s <= 0:
            raise ValueError("max_rate_per_s must be greater than zero")

        self.hold_s = hold_s
        self.smooth_alpha = smooth_alpha
        self.max_rate_per_s = max_rate_per_s
        self._last_seen_markers: dict[int, np.ndarray] = {}
        self._last_seen_elapsed_s: dict[int, float] = {}
        self._last_commands: dict[str, float] | None = None
        self._last_elapsed_s: float | None = None

    def update(
        self, markers: dict[int, np.ndarray], elapsed_s: float
    ) -> StableControlResult:
        raw_missing = sorted(set(MARKER_NAMES) - set(markers))
        filled_markers: dict[int, np.ndarray] = {}
        imputed: list[int] = []
        unavailable: list[int] = []

        for marker_id in MARKER_NAMES:
            if marker_id in markers:
                point = markers[marker_id]
                filled_markers[marker_id] = point
                self._last_seen_markers[marker_id] = point
                self._last_seen_elapsed_s[marker_id] = elapsed_s
                continue

            last_point = self._last_seen_markers.get(marker_id)
            last_elapsed = self._last_seen_elapsed_s.get(marker_id)
            if (
                last_point is not None
                and last_elapsed is not None
                and elapsed_s - last_elapsed <= self.hold_s
            ):
                filled_markers[marker_id] = last_point
                imputed.append(marker_id)
            else:
                unavailable.append(marker_id)

        dt = self._frame_dt(elapsed_s)
        raw_valid = not raw_missing
        model_valid = not unavailable
        held = False
        angles: dict[str, float] = {}

        if model_valid:
            target_commands, angles = estimate_six_controls(filled_markers)
            commands = self._smooth_and_limit(target_commands, dt)
            confidence = self._confidence(imputed, elapsed_s)
            self._last_commands = commands
        elif self._last_commands is not None:
            commands = dict(self._last_commands)
            confidence = 0.0
            held = True
        else:
            commands = {channel: math.nan for channel in CONTROL_CHANNELS}
            confidence = 0.0
            held = True

        self._last_elapsed_s = elapsed_s
        return StableControlResult(
            raw_valid=raw_valid,
            model_valid=model_valid,
            held_from_previous=held,
            confidence=confidence,
            missing_marker_ids=raw_missing,
            imputed_marker_ids=imputed,
            commands=commands,
            angles=angles,
        )

    def _frame_dt(self, elapsed_s: float) -> float:
        if self._last_elapsed_s is None:
            return 1.0 / 90.0
        dt = elapsed_s - self._last_elapsed_s
        if dt <= 0:
            return 1.0 / 90.0
        return dt

    def _smooth_and_limit(
        self, target_commands: dict[str, float], dt: float
    ) -> dict[str, float]:
        if self._last_commands is None:
            return dict(target_commands)

        max_delta = self.max_rate_per_s * dt
        commands: dict[str, float] = {}
        for channel in CONTROL_CHANNELS:
            previous = self._last_commands[channel]
            target = target_commands[channel]
            smoothed = previous + self.smooth_alpha * (target - previous)
            delta = float(np.clip(smoothed - previous, -max_delta, max_delta))
            commands[channel] = float(np.clip(previous + delta, 0.0, 1.0))
        return commands

    def _confidence(self, imputed_marker_ids: list[int], elapsed_s: float) -> float:
        if not imputed_marker_ids:
            return 1.0
        if self.hold_s <= 0:
            return 0.0
        max_age = max(
            elapsed_s - self._last_seen_elapsed_s[marker_id]
            for marker_id in imputed_marker_ids
        )
        age_score = max(0.0, 1.0 - max_age / self.hold_s)
        count_score = max(0.0, 1.0 - 0.04 * len(imputed_marker_ids))
        return float(age_score * count_score)

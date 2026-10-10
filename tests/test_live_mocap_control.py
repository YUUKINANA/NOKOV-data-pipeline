from __future__ import annotations

import math

import numpy as np

from revo2.live_mocap_control import (
    LatestFrameBuffer,
    LiveMocapFrame,
    MechanicalSafetyOutputLayer,
    controls_to_revo2_positions,
    normalize_labeled_markers,
)


def test_normalize_labeled_markers_infers_right_hand_offset() -> None:
    labeled = [
        {"id": marker_id, "xyz_mm": [marker_id, 1.0, 2.0], "valid": True}
        for marker_id in range(25, 49)
    ]

    markers, offset = normalize_labeled_markers(labeled, "auto")

    assert offset == 24
    assert sorted(markers) == list(range(1, 25))
    assert np.allclose(markers[1], [25.0, 1.0, 2.0])


def test_controls_to_revo2_positions_limits_step_and_position() -> None:
    controls = {
        "thumb_flexion": 0.9,
        "thumb_opposition": 0.8,
        "index_flexion": 0.6,
        "middle_flexion": 0.4,
        "ring_flexion": 0.2,
        "little_flexion": 0.1,
    }

    positions = controls_to_revo2_positions(
        controls,
        [400, 399, 50, 50, 50, 49],
        max_position=500,
        max_step=35,
    )

    assert positions == [435, 434, 85, 85, 85, 84]


def test_controls_to_revo2_positions_can_hold_thumb_and_ignore_nan() -> None:
    controls = {
        "thumb_flexion": 1.0,
        "thumb_opposition": 1.0,
        "index_flexion": math.nan,
        "middle_flexion": 0.2,
        "ring_flexion": 0.2,
        "little_flexion": 0.2,
    }

    positions = controls_to_revo2_positions(
        controls,
        [400, 399, 50, 50, 50, 49],
        max_position=500,
        max_step=35,
        hold_thumb=True,
    )

    assert positions == [400, 399, 50, 85, 85, 84]


def test_latest_frame_buffer_keeps_only_newest_frame() -> None:
    buffer = LatestFrameBuffer()
    first = LiveMocapFrame(
        sample_index=1,
        frame_no=101,
        timestamp_ms=1000,
        elapsed_s=0.0,
        latency_ms=0.1,
        markers={},
        raw_marker_count=0,
        marker_id_offset=0,
    )
    second = LiveMocapFrame(
        sample_index=2,
        frame_no=102,
        timestamp_ms=1011,
        elapsed_s=0.011,
        latency_ms=0.1,
        markers={},
        raw_marker_count=0,
        marker_id_offset=0,
    )

    buffer.push(first)
    buffer.push(second)

    assert buffer.received == 2
    assert buffer.overwritten == 1
    assert buffer.pop_latest() == second
    assert buffer.pop_latest() is None


def test_mechanical_safety_output_suppresses_small_deadband_changes() -> None:
    layer = MechanicalSafetyOutputLayer(
        [100, 100, 100, 100, 100, 100],
        deadband=10,
        quantum=1,
        alpha=1.0,
        min_confidence=0.0,
    )

    first = layer.apply(
        [100, 100, 100, 100, 100, 100],
        confidence=1.0,
        elapsed_s=0.0,
    )
    small = layer.apply(
        [105, 105, 105, 105, 105, 105],
        confidence=1.0,
        elapsed_s=0.1,
    )
    large = layer.apply(
        [115, 115, 115, 115, 115, 115],
        confidence=1.0,
        elapsed_s=0.2,
    )

    assert first.should_send is True
    assert first.reason == "first_output"
    assert small.should_send is False
    assert small.reason == "deadband"
    assert small.positions == [100, 100, 100, 100, 100, 100]
    assert large.should_send is True
    assert large.positions == [115, 115, 115, 115, 115, 115]


def test_mechanical_safety_output_quantizes_and_smooths() -> None:
    layer = MechanicalSafetyOutputLayer(
        [0, 0, 0, 0, 0, 0],
        deadband=0,
        quantum=10,
        alpha=0.5,
        min_confidence=0.0,
    )

    output = layer.apply(
        [23, 27, 44, 46, 51, 55],
        confidence=1.0,
        elapsed_s=0.0,
    )

    assert output.should_send is True
    assert output.positions == [10, 15, 20, 25, 25, 30]


def test_mechanical_safety_output_freezes_low_confidence() -> None:
    layer = MechanicalSafetyOutputLayer(
        [200, 200, 200, 200, 200, 200],
        deadband=0,
        quantum=1,
        alpha=1.0,
        min_confidence=0.5,
    )

    output = layer.apply(
        [400, 400, 400, 400, 400, 400],
        confidence=0.2,
        elapsed_s=0.0,
    )

    assert output.should_send is False
    assert output.reason == "low_confidence"
    assert output.positions == [200, 200, 200, 200, 200, 200]

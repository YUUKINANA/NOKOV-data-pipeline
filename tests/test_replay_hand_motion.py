from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from ml.replay_hand_motion import _draw_hand  # noqa: E402
from ml.synthetic_hand_pipeline import generate_local_markers  # noqa: E402


def test_draw_hand_skips_missing_markers_without_crashing() -> None:
    markers = generate_local_markers(
        {
            "thumb_flexion": 0.2,
            "thumb_opposition": 0.3,
            "index_flexion": 0.4,
            "middle_flexion": 0.5,
            "ring_flexion": 0.6,
            "little_flexion": 0.7,
        }
    )
    del markers[22]

    figure = plt.figure()
    try:
        axis = figure.add_subplot(1, 1, 1, projection="3d")
        _draw_hand(axis, markers)
    finally:
        plt.close(figure)

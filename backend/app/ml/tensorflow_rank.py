"""Optional TensorFlow softmax ranking over match scores (falls back to NumPy)."""
from __future__ import annotations

from typing import List


def rank_indices(scores: List[float]) -> List[int]:
    if not scores:
        return []
    try:
        import tensorflow as tf

        t = tf.constant(scores, dtype=tf.float32)
        # Higher score = better match
        order = tf.argsort(t, direction="DESCENDING")
        return [int(x) for x in order.numpy().tolist()]
    except Exception:
        return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

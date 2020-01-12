from typing import Tuple, List, cast

from .types import Array2d, Array
from .util import get_array_module, to_categorical


def categorical_crossentropy(scores: Array2d, labels: Array) -> Array2d:
    xp = get_array_module(scores)
    if labels.ndim != scores.ndim:
        target = to_categorical(labels, n_classes=scores.shape[-1])
    else:
        target = cast(Array2d, labels)
    if scores.shape != target.shape:
        raise ValueError(f"Cannot calculate loss: mismatched shapes. {scores.shape} vs {target.shape}")
    difference = scores - target
    loss = (difference**2).sum()
    return difference / scores.shape[0]


def sequence_categorical_crossentropy(scores: List[Array2d], labels: List[Array]) -> List[Array2d]:
    if not scores:
        return []
    if len(scores) != len(labels):
        raise ValueError("Scores and labels must be same length.")
    d_scores = []
    for yh, y in zip(scores, labels):
        d_scores.append(categorical_crossentropy(yh, y))
    return d_scores


def L1_distance(
    vec1: Array2d, vec2: Array2d, labels: Array2d, margin: float = 0.2
) -> Tuple[float, Tuple[Array2d, Array2d]]:
    xp = get_array_module(vec1)
    dist = xp.abs(vec1 - vec2).sum(axis=1)
    loss = (dist > margin) - labels
    return (vec1 - vec2) * loss, (vec2 - vec1) * loss


def cosine_distance(
    yh: Array2d, y: Array2d, ignore_zeros: bool = False
) -> Array2d:
    xp = get_array_module(yh)
    # Find the zero vectors
    if ignore_zeros:
        zero_indices = xp.abs(y).sum(axis=1) == 0
    # Add a small constant to avoid 0 vectors
    yh = yh + 1e-8
    y = y + 1e-8
    # https://math.stackexchange.com/questions/1923613/partial-derivative-of-cosinesimilarity
    norm_yh = xp.linalg.norm(yh, axis=1, keepdims=True)
    norm_y = xp.linalg.norm(y, axis=1, keepdims=True)
    mul_norms = norm_yh * norm_y
    cosine = (yh * y).sum(axis=1, keepdims=True) / mul_norms
    d_yh = (y / mul_norms) - (cosine * (yh / norm_yh ** 2))
    losses = xp.abs(cosine - 1)
    if ignore_zeros:
        # If the target was a zero vector, don't count it in the loss.
        d_yh[zero_indices] = 0
        losses[zero_indices] = 0
    return -d_yh


__all__ = ["categorical_crossentropy", "L1_distance", "cosine_distance"]

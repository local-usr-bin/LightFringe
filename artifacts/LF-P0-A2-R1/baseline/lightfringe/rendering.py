"""Rendering geometry only; never changes or feeds back into intensity data."""
import numpy as np


def curve_vertex_indices(x, y, max_vertical_error):
    """Select original vertices; linear interpolation deviates by <= tolerance.

    Coordinates and tolerance are in Qt logical pixels. This avoids sending
    thousands of nearly collinear vertices through Qt's software stroker.
    The check is against every original oversampled point, including extrema.
    """
    keep = {0, len(x) - 1}
    pending = [(0, len(x) - 1)]
    while pending:
        left, right = pending.pop()
        if right - left <= 1:
            continue
        local_x = x[left+1:right]
        expected = y[left] + (y[right]-y[left]) * (local_x-x[left]) / (x[right]-x[left])
        errors = np.abs(y[left+1:right] - expected)
        j = int(np.argmax(errors))
        if errors[j] > max_vertical_error:
            middle = left + 1 + j
            keep.add(middle)
            pending.extend(((left, middle), (middle, right)))
    return np.array(sorted(keep), dtype=int)

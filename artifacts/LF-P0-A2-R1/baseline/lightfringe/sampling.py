"""Display sampling policy, kept separate from physics and Qt.

The largest spatial frequency of the intensity is D/(lambda*z), where D is
the full extent of the aperture. Require at least 12 *physical display pixels*
per shortest period; if unavailable, hide both views instead of aliasing.
"""
from dataclasses import dataclass
import numpy as np

from .model import Parameters, ModelError, half_span, intensity, validate

MIN_PIXELS_PER_PERIOD = 12
SUBPIXELS = 16


@dataclass(frozen=True)
class DisplayData:
    x: np.ndarray
    intensity: np.ndarray
    envelope: np.ndarray
    pixel_mean: np.ndarray
    pixels_per_period: float
    span: float


def prepare_display(p: Parameters, pixel_width: int) -> DisplayData:
    validate(p)
    if not isinstance(pixel_width, int) or not 1 <= pixel_width <= 32768:
        raise ModelError("显示宽度无效")
    span = half_span(p)
    dx = 2 * span / pixel_width
    period = p.wavelength * p.distance / p.aperture_extent
    pixels_per_period = period / dx
    if pixels_per_period < MIN_PIXELS_PER_PERIOD:
        raise ModelError(
            f"显示采样不足：最短周期仅 {pixels_per_period:.1f} 像素，"
            f"要求 ≥ {MIN_PIXELS_PER_PERIOD}。请放大窗口；条纹及曲线已隐藏。"
        )
    # Sixteen midpoint samples per physical screen pixel: mean *intensity* first.
    sub_x = -span + (np.arange(pixel_width * SUBPIXELS) + 0.5) * dx / SUBPIXELS
    mean = intensity(sub_x, p).reshape(pixel_width, SUBPIXELS).mean(axis=1)
    # Four vertices per physical pixel; include the exact origin and endpoints.
    x = np.linspace(-span, span, pixel_width * 4 + 1)
    curve = intensity(x, p)
    envelope = np.sinc(p.slit_width * x / (p.wavelength * p.distance)) ** 2
    return DisplayData(x, curve, envelope, mean, pixels_per_period, span)

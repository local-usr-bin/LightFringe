"""Pure SI-unit science model. No Qt or display transforms are used here.

Paraxial Fraunhofer prediction for coherent, uniformly illuminated long slits.
Relative intensity is normalized separately to each configuration's on-axis value.
"""
from dataclasses import dataclass
from enum import Enum
import math

import numpy as np


class Mode(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"


class ModelError(ValueError):
    """Invalid inputs or configuration outside this prototype's valid domain."""


@dataclass(frozen=True)
class Parameters:
    mode: Mode = Mode.DOUBLE
    wavelength: float = 550e-9
    slit_width: float = 30e-6
    separation: float = 150e-6
    distance: float = 1.0

    @property
    def aperture_extent(self) -> float:
        return self.slit_width if self.mode == Mode.SINGLE else self.separation + self.slit_width

    @property
    def fresnel_number(self) -> float:
        """Half full-aperture extent squared / (lambda z), explicitly defined."""
        return (self.aperture_extent / 2) ** 2 / (self.wavelength * self.distance)


MAX_FRESNEL = 0.05
MAX_ANGLE_RATIO = 0.05


def validate(p: Parameters) -> None:
    if p.mode not in (Mode.SINGLE, Mode.DOUBLE):
        raise ModelError("未知实验模式")
    for name, value, low, high in (
        ("波长", p.wavelength, 380e-9, 750e-9),
        ("缝宽", p.slit_width, 10e-6, 80e-6),
        ("中心间距", p.separation, 40e-6, 250e-6),
        ("屏距", p.distance, 0.5, 3.0),
    ):
        if not math.isfinite(value) or not low <= value <= high:
            raise ModelError(f"{name}超出允许范围")
    if p.mode == Mode.DOUBLE and p.separation <= p.slit_width:
        raise ModelError("双缝中心间距必须大于缝宽，孔径不得接触或重叠")
    if p.fresnel_number > MAX_FRESNEL:
        raise ModelError(
            f"超出本原型远场准则：F={p.fresnel_number:.4f} > 0.05。"
            "请增大屏距，或减小孔径尺寸。已停止显示预测。"
        )


def intensity(x, p: Parameters) -> np.ndarray:
    """I(x)/I(0), linear, unmodified. np.sinc(t) = sin(pi*t)/(pi*t)."""
    validate(p)
    x = np.asarray(x, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        raise ModelError("横向坐标必须有限")
    if np.any(np.abs(x) > MAX_ANGLE_RATIO * p.distance * (1 + 1e-12)):
        raise ModelError("横向位置超出傍轴范围 |x|/z ≤ 0.05")
    spatial_frequency = x / (p.wavelength * p.distance)
    envelope = np.sinc(p.slit_width * spatial_frequency) ** 2
    if p.mode == Mode.SINGLE:
        return envelope
    return envelope * np.cos(np.pi * p.separation * spatial_frequency) ** 2


def half_span(p: Parameters) -> float:
    """Keep ±40 mm unless the paraxial field limit requires a smaller window."""
    return min(0.040, MAX_ANGLE_RATIO * p.distance)


def characteristic_lengths(p: Parameters) -> tuple[float, float | None]:
    validate(p)
    first_zero = p.wavelength * p.distance / p.slit_width
    fringe = p.wavelength * p.distance / p.separation if p.mode == Mode.DOUBLE else None
    return first_zero, fringe

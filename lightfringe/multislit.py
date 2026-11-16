"""Finite, equally spaced, in-phase slit array. Legacy N=1/2 are dispatched intact.

Only N=3..8 uses the new formula. All SI units, gates and display constants
are inherited from the audited modules, which this module does not modify.
"""
from dataclasses import dataclass
from enum import Enum
import numpy as np

from .model import (Mode, Parameters, ModelError, MAX_FRESNEL, MAX_ANGLE_RATIO,
                    validate as legacy_validate, half_span,
                    characteristic_lengths as legacy_lengths)
from .sampling import (DisplayData, MIN_PIXELS_PER_PERIOD, SUBPIXELS,
                       prepare_display as legacy_prepare_display)


class MultiMode(str, Enum):
    MULTI = "multi"


@dataclass(frozen=True)
class MultiParameters:
    slit_count: int = 8
    wavelength: float = 550e-9
    slit_width: float = 20e-6
    separation: float = 60e-6
    distance: float = 2.0
    mode: MultiMode = MultiMode.MULTI

    @property
    def aperture_extent(self):
        return (self.slit_count - 1) * self.separation + self.slit_width

    @property
    def fresnel_number(self):
        return (self.aperture_extent / 2) ** 2 / (self.wavelength * self.distance)


def is_multi(p):
    return isinstance(p, MultiParameters)


def validate(p):
    if not is_multi(p):
        return legacy_validate(p)
    if type(p.slit_count) is not int or not 3 <= p.slit_count <= 8 or p.mode != MultiMode.MULTI:
        raise ModelError("多缝缝数 N 必须为 3—8 的整数")
    # Reuse every audited outer bound and finite-value test. Single-slit F is
    # only a preliminary necessary gate; the full-array gate follows below.
    legacy_validate(Parameters(Mode.SINGLE, p.wavelength, p.slit_width,
                               p.separation, p.distance))
    if p.separation <= p.slit_width:
        raise ModelError("多缝中心间距必须大于缝宽，狭缝不得接触或重叠")
    if p.fresnel_number > MAX_FRESNEL:
        raise ModelError(f"超出远场准则：N={p.slit_count}，完整孔径 W={p.aperture_extent*1e6:.0f} μm，"
                         f"F={p.fresnel_number:.4f} > 0.05。请减小孔径或增大屏距；预测已暂停。")


def intensity(x, p: MultiParameters):
    """I/Imax; Imax=I(0). No clipping, smoothing or per-sample renormalization."""
    validate(p)
    if not is_multi(p):
        raise ModelError("多缝求解器仅处理 N=3—8；单/双缝使用原求解器")
    x = np.asarray(x, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        raise ModelError("横向坐标必须有限")
    if np.any(np.abs(x) > MAX_ANGLE_RATIO*p.distance*(1+1e-12)):
        raise ModelError("横向位置超出傍轴范围 |x|/L ≤ 0.05")
    u = x / (p.wavelength*p.distance)
    t = p.separation*u
    r = t - np.rint(t)
    # Intensity is periodic in t. |r|<=1/2 keeps sinc(r)>=2/pi, and r=0
    # evaluates its limit exactly, without a threshold plateau at each pole.
    with np.errstate(under='ignore'):
        result = np.sinc(p.slit_width*u)**2 * (np.sinc(p.slit_count*r)/np.sinc(r))**2
    if not np.all(np.isfinite(result)) or np.any((result < 0) | (result > 1)):
        raise ModelError("多缝归一化计算结果无效，已停止预测")
    return result


def characteristic_lengths(p):
    if not is_multi(p):
        return legacy_lengths(p)
    validate(p)
    return p.wavelength*p.distance/p.slit_width, p.wavelength*p.distance/p.separation


def prepare_display(p, pixel_width):
    """Same display policy; shortest period is lambda*L / full aperture W."""
    if not is_multi(p):
        return legacy_prepare_display(p, pixel_width)
    validate(p)
    if not isinstance(pixel_width, int) or not 1 <= pixel_width <= 32768:
        raise ModelError("显示宽度无效")
    span = half_span(p)
    dx = 2*span/pixel_width
    pixels_per_period = (p.wavelength*p.distance/p.aperture_extent)/dx
    if pixels_per_period < MIN_PIXELS_PER_PERIOD:
        raise ModelError(f"显示采样不足：完整孔径最短周期仅 {pixels_per_period:.1f} 像素，"
                         f"要求 ≥ {MIN_PIXELS_PER_PERIOD}。请放大窗口；光纹与曲线已隐藏。")
    sub_x = -span + (np.arange(pixel_width*SUBPIXELS)+.5)*dx/SUBPIXELS
    pixels = intensity(sub_x, p).reshape(pixel_width, SUBPIXELS).mean(axis=1)
    x = np.linspace(-span, span, pixel_width*4+1)
    curve = intensity(x, p)
    envelope = np.sinc(p.slit_width*x/(p.wavelength*p.distance))**2
    return DisplayData(x, curve, envelope, pixels, pixels_per_period, span)

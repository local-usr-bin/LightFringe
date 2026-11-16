"""Ideal circular-aperture scalar paraxial Fraunhofer model, in SI units.

No Qt, PDF, display transfer, absolute power, or legacy solver imports.
The frozen A4-0 contract defines F=(D/2)^2/(wavelength*distance)<=0.05
and hypot(x,y)/distance<=0.05. These are applicability gates, not an
asserted percentage error relative to an electromagnetic solution.
"""
from dataclasses import dataclass
from enum import Enum
from numbers import Real
import math

import numpy as np
from scipy.special import j1

MAX_FRESNEL = 0.05
MAX_RADIAL_RATIO = 0.05
MAX_HALF_SPAN_M = 0.040
J1_FIRST_ZERO = 3.8317059702075123156144358863081607665645452742878
SMALL_U = 1e-3


class CircularModelError(ValueError):
    """No reliable physical evaluation for the requested inputs."""


class ModelStatus(str, Enum):
    VALID = "MODEL_VALID"
    INVALID = "MODEL_INVALID"


class RingVisibility(str, Enum):
    FULL = "FIRST_RING_FULL"
    PARTIAL = "FIRST_RING_PARTIAL"
    OUTSIDE = "FIRST_RING_OUTSIDE_VIEW"


@dataclass(frozen=True)
class CircularParameters:
    wavelength: float = 550 / 1e9
    diameter: float = 100 / 1e6
    distance: float = 1.0

    @classmethod
    def from_display_units(cls, wavelength_nm, diameter_um, distance_m):
        """Explicit nm/um/m -> m/m/m conversion, without rounding inputs."""
        for v in (wavelength_nm, diameter_um, distance_m):
            if not _finite_real(v):
                raise CircularModelError("Unit conversion requires finite real numbers")
        return cls(float(wavelength_nm) / 1e9, float(diameter_um) / 1e6,
                   float(distance_m))


@dataclass(frozen=True)
class ModelAssessment:
    status: ModelStatus
    reason: str
    fresnel_number: float | None


def _finite_real(v):
    return isinstance(v, Real) and not isinstance(v, (bool, np.bool_)) and math.isfinite(v)


def assess_model(p: CircularParameters) -> ModelAssessment:
    if not isinstance(p, CircularParameters):
        return ModelAssessment(ModelStatus.INVALID, "Expected CircularParameters", None)
    fields = ((p.wavelength, 380 / 1e9, 750 / 1e9, "wavelength (m)"),
              (p.diameter, 20 / 1e6, 500 / 1e6, "diameter (m)"),
              (p.distance, 0.5, 3.0, "distance (m)"))
    for value, low, high, name in fields:
        if not _finite_real(value):
            return ModelAssessment(ModelStatus.INVALID, name + " must be finite and real", None)
        if not low <= value <= high:
            return ModelAssessment(ModelStatus.INVALID, f"{name} outside [{low}, {high}]", None)
    f = (float(p.diameter) / 2) ** 2 / (float(p.wavelength) * float(p.distance))
    if f > MAX_FRESNEL:
        return ModelAssessment(ModelStatus.INVALID, f"Far-field limit: F={f:.12g} > 0.05", f)
    return ModelAssessment(ModelStatus.VALID, "Parameters pass the stated model gates", f)


def validate(p: CircularParameters) -> None:
    result = assess_model(p)
    if result.status != ModelStatus.VALID:
        raise CircularModelError(result.reason)


def fresnel_number(p: CircularParameters) -> float:
    """Diagnostic F, including a finite F that fails the far-field gate."""
    result = assess_model(p)
    if result.fresnel_number is None:
        raise CircularModelError(result.reason)
    return result.fresnel_number


def observation_half_span(p: CircularParameters) -> float:
    validate(p)
    limit = MAX_RADIAL_RATIO * float(p.distance)
    s = min(MAX_HALF_SPAN_M, limit / math.sqrt(2))
    # Round a constructed boundary inward if binary rounding puts the corner
    # one ULP outside the unchanged radial gate. No gate tolerance is added.
    while math.hypot(s, s) > limit or float(np.hypot(s, s)) > limit:
        s = math.nextafter(s, 0.0)
    return s


def first_dark_radius(p: CircularParameters) -> float:
    validate(p)
    return (J1_FIRST_ZERO / math.pi) * float(p.wavelength) * float(p.distance) / float(p.diameter)


def first_ring_visibility(p: CircularParameters) -> RingVisibility:
    radius = first_dark_radius(p)
    s = observation_half_span(p)
    if radius <= s:
        return RingVisibility.FULL
    if radius <= math.hypot(s, s):
        return RingVisibility.PARTIAL
    return RingVisibility.OUTSIDE


def _real_array(values, name):
    try:
        a = np.asarray(values)
        if a.dtype.kind not in "iuf":
            raise CircularModelError(name + " must contain real numeric values")
        a = np.asarray(a, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as ex:
        raise CircularModelError(name + " must contain real numeric values") from ex
    if not np.all(np.isfinite(a)):
        raise CircularModelError(name + " must be finite")
    return a


def _scalar_or_array(values):
    return float(values) if values.ndim == 0 else values


def normalized_amplitude(u):
    """Dimensionless mathematical A(u), not a physical-validity declaration."""
    u = _real_array(u, "u")
    result = np.empty_like(u)
    small = np.abs(u) < SMALL_U
    with np.errstate(under="ignore"):
        t = u[small] * u[small]
        result[small] = 1 - t / 8 + t * t / 192 - t**3 / 9216 + t**4 / 737280
        large = u[~small]
        result[~small] = 2 * j1(large) / large
    if not np.all(np.isfinite(result)):
        raise CircularModelError("Non-finite normalized amplitude")
    return _scalar_or_array(result)


def normalized_intensity(u):
    """A(u)^2; no clipping, zero snapping or sample-maximum normalization."""
    a = np.asarray(normalized_amplitude(u))
    with np.errstate(under="ignore"):
        result = a * a
    if not np.all(np.isfinite(result)) or np.any((result < 0) | (result > 1)):
        raise CircularModelError("Non-finite or out-of-range relative intensity")
    return _scalar_or_array(result)


def _coordinate_radius(p, x, y):
    validate(p)
    x = _real_array(x, "x (m)")
    y = _real_array(y, "y (m)")
    try:
        x, y = np.broadcast_arrays(x, y)
    except ValueError as ex:
        raise CircularModelError("x and y cannot be broadcast together") from ex
    with np.errstate(over="ignore", under="ignore"):
        rho = np.hypot(x, y)
    if not np.all(np.isfinite(rho)) or np.any(rho > MAX_RADIAL_RATIO * float(p.distance)):
        raise CircularModelError("Observation outside hypot(x,y)/distance <= 0.05")
    return x, y, rho


def intensity(p: CircularParameters, x, y=0.0):
    """Continuous relative point intensity I(x,y)/I(0), x/y in metres."""
    _, _, rho = _coordinate_radius(p, x, y)
    with np.errstate(under="ignore"):
        u = (math.pi * float(p.diameter) /
             (float(p.wavelength) * float(p.distance))) * rho
    return normalized_intensity(u)

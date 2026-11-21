"""Scalar paraxial Fraunhofer field of two to four identical circular openings.

Illumination is a normally incident, monochromatic, coherent, uniform plane
wave with the same phase at every hole. All lengths are in metres.
Both planes have x right and y up, with positive
angles counterclockwise about the centroid. For time dependence exp(-i*w*t)
the pupil translation contributes exp(-2*pi*i*(x*cx+y*cy)/(lambda*z)).
The common propagation factor is removed. Each disk supplies 2*J1(u)/u,
u=pi*diameter*hypot(x,y)/(lambda*z). Its analytic origin limit and small-u
series come from the single-disk helper. The axial field is exactly one.
"""
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import math
from numbers import Real

import numpy as np

from .circular_model import normalized_amplitude


WAVELENGTH_RANGE_M = (380e-9, 750e-9)
DIAMETER_RANGE_M = (20e-6, 500e-6)
DISTANCE_RANGE_M = (0.5, 3.0)
_FRESNEL_LIMIT = Fraction(1, 20)
_RADIAL_RATIO_LIMIT = Fraction(1, 20)
MAX_ARRAY_FRESNEL = float(_FRESNEL_LIMIT)
MAX_RADIAL_RATIO = float(_RADIAL_RATIO_LIMIT)
DEFAULT_HALF_SPAN_CAP_M = 0.040


class MultiApertureError(ValueError):
    """Invalid geometry, observation domain or numerical input."""


class Layout(str, Enum):
    PAIR = "pair"
    TRIANGLE = "triangle"
    SQUARE = "square"
    RECTANGLE = "rectangle"


@dataclass(frozen=True)
class MultiApertureParameters:
    """Centre spacings before rotation. Only a rectangle takes a second spacing.

    The equilateral triangle has a horizontal base and its apex points up.
    Pairs and four-hole presets allow rigid rotation from their axial layout.
    """
    layout: Layout = Layout.PAIR
    wavelength_m: float = 550e-9
    diameter_m: float = 80e-6
    distance_m: float = 1.0
    spacing_m: float = 150e-6
    spacing_y_m: float | None = None
    angle_deg: float = 0.0


@dataclass(frozen=True)
class Field:
    """Positive half-widths of a centred rectangle. The 40 mm cap is for the default square."""
    half_x_m: float
    half_y_m: float


@dataclass(frozen=True)
class Geometry:
    centers_m: tuple[tuple[float, float], ...]
    minimum_spacing_m: float
    radius_m: float


@dataclass(frozen=True)
class ModelAssessment:
    geometry: Geometry | None = None
    fresnel_number: float | None = None
    field: Field | None = None
    reason: str = ""

    @property
    def valid(self):
        return self.field is not None

    @property
    def status(self):
        return "MODEL_VALID" if self.valid else "MODEL_INVALID"

    def require_valid(self):
        if not self.valid:
            raise MultiApertureError(self.reason)


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise MultiApertureError(f"{name} must be a finite real number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise MultiApertureError(f"{name} exceeds the numeric range") from exc
    if not math.isfinite(number):
        raise MultiApertureError(f"{name} must be finite")
    return number


def direction(angle_deg):
    """Unit direction for a finite angle in degrees, exact on cardinal axes."""
    angle = math.remainder(_number(angle_deg, "angle_deg"), 360.0)
    if angle % 90.0 == 0.0:
        axes = ((1., 0.), (0., 1.), (-1., 0.), (0., -1.))
        return axes[int(angle / 90) % 4]
    rad = math.radians(angle)
    return math.cos(rad), math.sin(rad)


def _geometry(p):
    try:
        layout = Layout(p.layout)
    except (TypeError, ValueError) as exc:
        raise MultiApertureError("Unknown multi-aperture layout") from exc
    dx = _number(p.spacing_m, "spacing_m")
    dy = dx
    if layout == Layout.RECTANGLE:
        dy = _number(p.spacing_y_m, "rectangle spacing_y_m")
    elif p.spacing_y_m is not None:
        raise MultiApertureError("Only a rectangle accepts spacing_y_m")

    # For these rigid presets the shortest pair is a defining edge. Compare
    # the input lengths before rotation, so a tangent edge needs no tolerance.
    minimum = min(dx, dy)
    if minimum < p.diameter_m:
        raise MultiApertureError("Holes overlap: each centre spacing must be >= diameter")
    c, s = direction(p.angle_deg)
    hx, hy = dx / 2, dy / 2
    if layout == Layout.PAIR:
        centers = ((-hx, 0.), (hx, 0.))
        outer_center = hx
    elif layout == Layout.TRIANGLE:
        if (c, s) != (1., 0.):
            raise MultiApertureError("The triangle preset has a fixed upward apex")
        outer_center = dx / math.sqrt(3)
        centers = ((-hx, -outer_center / 2), (hx, -outer_center / 2), (0., outer_center))
    else:
        centers = ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy))
        outer_center = math.hypot(hx, hy)
    rotated = tuple((c*x - s*y, s*x + c*y) for x, y in centers)
    return Geometry(rotated, minimum, outer_center + float(p.diameter_m) / 2)


def _far_field_valid(p):
    """Compare (a + sqrt(h2))² to lambda*z/20 using only rational operations."""
    a = Fraction(float(p.diameter_m)) / 2
    dx = Fraction(float(p.spacing_m))
    if p.layout == Layout.PAIR:
        h2 = (dx / 2)**2
    elif p.layout == Layout.TRIANGLE:
        h2 = dx**2 / 3
    else:
        dy = dx if p.layout == Layout.SQUARE else Fraction(float(p.spacing_y_m))
        h2 = (dx**2 + dy**2) / 4
    scale = Fraction(float(p.wavelength_m)) * Fraction(float(p.distance_m))
    remaining = _FRESNEL_LIMIT * scale - a*a - h2
    return remaining >= 0 and remaining**2 >= 4*a*a*h2


def _disk_limit_squared(distance):
    return (Fraction(float(distance)) * _RADIAL_RATIO_LIMIT)**2


def _inside_disk(x, y, limit_squared):
    return Fraction(float(x))**2 + Fraction(float(y))**2 <= limit_squared


def _observation_field(field, distance):
    limit_squared = _disk_limit_squared(distance)
    if field is None:
        half = min(DEFAULT_HALF_SPAN_CAP_M, float(distance) / 20 / math.sqrt(2))
        while not _inside_disk(half, half, limit_squared):
            half = math.nextafter(half, 0.0)
        # The estimate can round either way. Return the largest legal binary64
        # half-width up to the existing default cap.
        larger = math.nextafter(half, math.inf)
        while larger <= DEFAULT_HALF_SPAN_CAP_M and _inside_disk(larger, larger, limit_squared):
            half = larger
            larger = math.nextafter(half, math.inf)
        return Field(half, half)
    if not isinstance(field, Field):
        raise MultiApertureError("Expected a rectangular Field in metres")
    x = _number(field.half_x_m, "half_x_m")
    y = _number(field.half_y_m, "half_y_m")
    if min(x, y) <= 0 or not _inside_disk(x, y, limit_squared):
        raise MultiApertureError("Field half-widths must be positive and the corner within 0.05*z")
    return Field(x, y)


def assess_model(p: MultiApertureParameters, field: Field | None = None) -> ModelAssessment:
    """Require R²/(lambda*z) <= 0.05 and the full field inside r <= 0.05*z.

    R is half the diameter plus the farthest centre's distance from the centroid.
    """
    if not isinstance(p, MultiApertureParameters):
        return ModelAssessment(reason="Expected MultiApertureParameters")
    try:
        for name, bounds in (("wavelength_m", WAVELENGTH_RANGE_M),
                             ("diameter_m", DIAMETER_RANGE_M), ("distance_m", DISTANCE_RANGE_M)):
            value = _number(getattr(p, name), name)
            if not bounds[0] <= value <= bounds[1]:
                raise MultiApertureError(f"{name} outside {bounds}")
        geometry = _geometry(p)
    except MultiApertureError as exc:
        return ModelAssessment(reason=str(exc))
    scale = float(p.wavelength_m) * float(p.distance_m)
    fresnel = geometry.radius_m * geometry.radius_m / scale
    if not _far_field_valid(p):
        return ModelAssessment(geometry, fresnel, reason="Whole-array R² exceeds wavelength*distance/20"
                               f" (approximate F={fresnel:.17g})")
    try:
        field = _observation_field(field, p.distance_m)
    except MultiApertureError as exc:
        return ModelAssessment(geometry, fresnel, reason=str(exc))
    return ModelAssessment(geometry, fresnel, field)


def _coordinate(values):
    try:
        array = np.asarray(values)
        if array.dtype.kind in "iuf":
            array = np.asarray(array, dtype=np.float64)
            if np.all(np.isfinite(array)):
                return array
    except (TypeError, ValueError, OverflowError) as exc:
        raise MultiApertureError("Invalid screen coordinates") from exc
    raise MultiApertureError("Screen coordinates must be finite and real")


def _coherent_field(p, centers_m, x, y, radius):
    """Normalized disk transform times the coherent mean over the open disks."""
    scale = float(p.wavelength_m) * float(p.distance_m)
    envelope = normalized_amplitude((math.pi * float(p.diameter_m) / scale) * radius)
    phase = -2j * math.pi / scale
    total = np.zeros(np.shape(radius), dtype=np.complex128)
    for cx, cy in centers_m:
        # On a rectangular grid the x and y phase vectors stay one-dimensional.
        total += np.exp((phase * cx) * x) * np.exp((phase * cy) * y)
    return (total / len(centers_m)) * envelope


def amplitude(p: MultiApertureParameters, x_m, y_m=0.0):
    """Complex E/E(0) at broadcastable point coordinates in the paraxial disk."""
    model = assess_model(p)
    model.require_valid()
    x, y = _coordinate(x_m), _coordinate(y_m)
    try:
        with np.errstate(over="ignore", under="ignore"):
            radius = np.hypot(x, y)
    except ValueError as exc:
        raise MultiApertureError("Screen coordinates must broadcast together") from exc
    limit_squared = _disk_limit_squared(p.distance_m)
    xmax = np.max(np.abs(x), initial=0.)
    ymax = np.max(np.abs(y), initial=0.)
    if not _inside_disk(xmax, ymax, limit_squared):
        # A rectangular screen entirely inside the disk needs just one corner
        # certificate. For other point sets, filter with outward-rounded squares.
        # Only ambiguous or exterior coordinate pairs require exact arithmetic.
        with np.errstate(over="ignore", under="ignore"):
            xx = np.nextafter(x*x, np.inf)
            yy = np.nextafter(y*y, np.inf)
            upper = np.nextafter(xx + yy, np.inf)
        boundary = upper >= math.nextafter(float(limit_squared), 0.)
        bx, by = np.broadcast_arrays(x, y)
        if any(not _inside_disk(cx, cy, limit_squared) for cx, cy in zip(bx[boundary], by[boundary])):
            raise MultiApertureError("Point outside the paraxial observation disk")
    with np.errstate(under="ignore"):
        return _coherent_field(p, model.geometry.centers_m, x, y, radius)


def intensity(p: MultiApertureParameters, x_m, y_m=0.0):
    """Linear point intensity I/I(0), retaining cancellation residuals."""
    with np.errstate(under="ignore"):
        return np.square(np.abs(amplitude(p, x_m, y_m)))

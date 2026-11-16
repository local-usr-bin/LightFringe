"""Pure numerical screen-cell means and a separately checked point profile.

Screen: N cells, N+1 edges, N centers, N-1 neighboring center intervals.
The full field extends between EDGES, so its cell pitch is 2*s/N.
Profile: M points INCLUDE both endpoints, so its pitch is 2*s/(M-1).
All intensities are linear I/I(0); no gray/RGB image is produced here.
"""
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import math
import numpy as np

from .circular_model import (
    CircularParameters, ModelAssessment, ModelStatus, RingVisibility,
    assess_model, validate, observation_half_span, first_ring_visibility,
    intensity, _coordinate_radius, _scalar_or_array, _real_array, MAX_RADIAL_RATIO,
)

MAX_SCREEN_SIDE = 383
MIN_PIXELS_PER_PERIOD = 12
# A memory bound on a requested 1D array, not a physical parameter range.
MAX_PROFILE_POINTS = 131073


class SamplingRequestError(ValueError):
    pass


class DisplayStatus(str, Enum):
    VALID = "DISPLAY_VALID"
    UNDERSAMPLED = "DISPLAY_UNDERSAMPLED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class SamplingAssessment:
    status: DisplayStatus
    reason: str
    layout: str
    provided_count: int
    intervals_across_full_field: int
    neighboring_center_intervals: int
    required_count: int | None
    required_odd_count: int | None
    pitch_m: float | None
    pixels_per_period: float | None


@dataclass(frozen=True)
class ScreenData:
    params: CircularParameters
    half_span_m: float
    x_edges: np.ndarray
    y_edges: np.ndarray
    x_centers: np.ndarray
    y_centers: np.ndarray
    pixel_mean: np.ndarray
    center_index: int | None
    value_kind: str = "PIXEL_AREA_MEAN_2X2_GAUSS"
    row_order: str = "row i corresponds to y_centers[i], increasing physical y"


@dataclass(frozen=True)
class ProfileData:
    params: CircularParameters
    half_span_m: float
    x: np.ndarray
    intensity: np.ndarray
    center_index: int | None
    value_kind: str = "CONTINUOUS_POINT_INTENSITY"


@dataclass(frozen=True)
class ScreenResult:
    model: ModelAssessment
    sampling: SamplingAssessment
    visibility: RingVisibility | None
    data: ScreenData | None


@dataclass(frozen=True)
class ProfileResult:
    model: ModelAssessment
    sampling: SamplingAssessment
    visibility: RingVisibility | None
    data: ProfileData | None


def _count(n, minimum):
    if not isinstance(n, (int, np.integer)) or isinstance(n, (bool, np.bool_)) or n < minimum:
        raise SamplingRequestError(f"Count must be an integer >= {minimum}")
    return int(n)


def _freeze(a):
    a = np.asarray(a, dtype=np.float64)
    return np.frombuffer(a.tobytes(), dtype=np.float64).reshape(a.shape)


def _required_intervals(s, period):
    required = max(1, math.ceil(2 * s / period * MIN_PIXELS_PER_PERIOD))
    # Keep the integer recommendation consistent with the actual float gate,
    # without rounding a near-12 result up or relaxing the threshold.
    while period / (2 * s / required) < MIN_PIXELS_PER_PERIOD:
        required += 1
    while required > 1 and period / (2 * s / (required - 1)) >= MIN_PIXELS_PER_PERIOD:
        required -= 1
    return required


def assess_sampling(p: CircularParameters, count: int, *, endpoint_points=False):
    count = _count(count, 2 if endpoint_points else 1)
    intervals = count - 1 if endpoint_points else count
    layout = "ENDPOINT_POINTS" if endpoint_points else "PIXEL_CELLS"
    model = assess_model(p)
    if model.status != ModelStatus.VALID:
        return SamplingAssessment(DisplayStatus.NOT_EVALUATED, model.reason, layout,
                                  count, intervals, count - 1, None, None, None, None)
    s = observation_half_span(p)
    period = float(p.wavelength) * float(p.distance) / float(p.diameter)
    pitch = 2 * s / intervals
    ppp = period / pitch
    required = _required_intervals(s, period) + int(endpoint_points)
    required_odd = required if required % 2 else required + 1
    cap = MAX_PROFILE_POINTS if endpoint_points else MAX_SCREEN_SIDE
    if count > cap:
        return SamplingAssessment(DisplayStatus.UNDERSAMPLED,
            f"Requested count {count} exceeds calculation budget {cap}; no data allocated",
            layout, count, intervals, count - 1, required, required_odd, pitch, ppp)
    good = ppp >= MIN_PIXELS_PER_PERIOD
    return SamplingAssessment(DisplayStatus.VALID if good else DisplayStatus.UNDERSAMPLED,
        "Declared physical sampling passes" if good else
        f"{ppp:.12g} per shortest period < 12; need count >= {required} ({required_odd} odd)",
        layout, count, intervals, count - 1, required, required_odd, pitch, ppp)


def pixel_area_mean(p: CircularParameters, x, y, pitch_m):
    """2x2 Gauss-Legendre mean for square cells centered at x/y (metres).

    All cell corners must be in the paraxial domain and the cell pitch must
    provide >=12 samples per shortest cycle. This is an area mean, not I(x,y).
    """
    validate(p)
    if (not isinstance(pitch_m, (int, float, np.integer, np.floating)) or
            isinstance(pitch_m, (bool, np.bool_)) or
            not math.isfinite(pitch_m) or pitch_m <= 0):
        raise SamplingRequestError("Pixel pitch must be finite and positive")
    period = float(p.wavelength) * float(p.distance) / float(p.diameter)
    if period / pitch_m < MIN_PIXELS_PER_PERIOD:
        raise SamplingRequestError("Pixel area averaging cannot rescue undersampling")
    # Keep the original broadcastable axes: x[1,N] and y[N,1] shifts stay
    # one-dimensional. Corner checks still cover every entire physical cell.
    x = _real_array(x, "x (m)")
    y = _real_array(y, "y (m)")
    _coordinate_radius(p, np.abs(x) + pitch_m / 2, np.abs(y) + pitch_m / 2)
    offset = pitch_m / (2 * math.sqrt(3))
    total = np.zeros(np.broadcast_shapes(x.shape, y.shape), dtype=np.float64)
    for dx in (-offset, offset):
        for dy in (-offset, offset):
            total += np.asarray(intensity(p, x + dx, y + dy)) * 0.25
    if not np.all(np.isfinite(total)) or np.any((total < 0) | (total > 1)):
        raise SamplingRequestError("Invalid pixel-area intensity")
    return _scalar_or_array(total)


def _screen_centers(p, side, half_span_m, pitch_m):
    """Represent the nominal grid with inward-rounded outer centers only.

    Edges, span, pitch, parameters and public domain predicates are unchanged.
    Exact rational checks prevent center+half-pitch reconstruction from crossing
    the approved square/circle. The 4-ULP cap is a fail-closed representation
    budget, never a tolerance added to a public validity or sampling gate.
    """
    centers = (2 * np.arange(side, dtype=np.float64) + 1 - side) * (half_span_m / side)
    outer = original = float(centers[-1])
    half = pitch_m / 2
    limit = MAX_RADIAL_RATIO * float(p.distance)
    span_exact = Fraction(half_span_m)
    limit_squared = Fraction(limit) ** 2
    while True:
        corner_exact = Fraction(outer) + Fraction(half)
        corner = outer + half
        if (corner_exact <= span_exact and
                2 * corner_exact ** 2 <= limit_squared and
                float(np.hypot(corner, corner)) <= limit):
            break
        inward = math.nextafter(outer, 0.0)
        if inward == outer or original - inward > 4 * math.ulp(half_span_m):
            raise SamplingRequestError("Grid representation exceeds the inward rounding budget")
        outer = inward
    centers[0], centers[-1] = -outer, outer
    return centers


def prepare_screen(p: CircularParameters, side=MAX_SCREEN_SIDE) -> ScreenResult:
    sampling = assess_sampling(p, side)
    model = assess_model(p)
    if model.status != ModelStatus.VALID:
        return ScreenResult(model, sampling, None, None)
    visibility = first_ring_visibility(p)
    if sampling.status != DisplayStatus.VALID:
        return ScreenResult(model, sampling, visibility, None)
    side = int(side)
    s = observation_half_span(p)
    # Integer antisymmetric coordinates give an EXACT central 0 for odd N.
    centers = _screen_centers(p, side, s, sampling.pitch_m)
    edges = (2 * np.arange(side + 1, dtype=np.float64) - side) * (s / side)
    edges[0], edges[-1] = -s, s
    values = pixel_area_mean(p, centers[None, :], centers[:, None], sampling.pitch_m)
    centers, edges = _freeze(centers), _freeze(edges)
    data = ScreenData(p, s, edges, edges, centers, centers, _freeze(values),
                      side // 2 if side % 2 else None)
    return ScreenResult(model, sampling, visibility, data)


def prepare_profile(p: CircularParameters, point_count=383) -> ProfileResult:
    """Endpoint-inclusive 1D point grid; GUI plotted pixel width is NOT known.

    A future GUI must ALSO check its true physical plotting width; increasing
    curve vertices must never be reported as increasing display pixels.
    """
    sampling = assess_sampling(p, point_count, endpoint_points=True)
    model = assess_model(p)
    if model.status != ModelStatus.VALID:
        return ProfileResult(model, sampling, None, None)
    visibility = first_ring_visibility(p)
    if sampling.status != DisplayStatus.VALID:
        return ProfileResult(model, sampling, visibility, None)
    point_count = int(point_count)
    s = observation_half_span(p)
    x = (2 * np.arange(point_count, dtype=np.float64) - (point_count - 1)) * (s / (point_count - 1))
    x[0], x[-1] = -s, s
    values = intensity(p, x, 0.0)
    data = ProfileData(p, s, _freeze(x), _freeze(values),
                       point_count // 2 if point_count % 2 else None)
    return ProfileResult(model, sampling, visibility, data)

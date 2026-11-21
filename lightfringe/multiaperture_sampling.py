"""Numerical sampling of multi-aperture intensities, independent of Qt and PDF.

The pupil autocorrelation bounds cycles/metre along n by the projected pupil
width (diameter + centre projection range) divided by wavelength*distance.
Twelve intervals per shortest period is a candidate sampling criterion for the
linear intensity. It does not bound physical model error or quadrature error.
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
from numbers import Integral
import sys

import numpy as np

from .multiaperture_model import Field, Layout, ModelAssessment, _number, assess_model, intensity


MIN_INTERVALS_PER_PERIOD = 12
PDF_GRID_SIDES = (383, 511, 767)
PDF_PROFILE_POINTS = 1025


class SamplingError(ValueError):
    """Malformed sampling request or insufficient resolution to generate data."""


@dataclass(frozen=True)
class GridSampling:
    counts_xy: tuple[int, int]
    required_xy: tuple[int, int]
    bandwidth_xy_per_m: tuple[float, float]
    pitch_xy_m: tuple[float, float]

    @property
    def valid(self):
        return all(n >= needed for n, needed in zip(self.counts_xy, self.required_xy))


@dataclass(frozen=True)
class _ProfileAxis:
    """Exact binary64 coordinate lattice for one signed half-chord component."""
    units: int
    quantum: float

    @classmethod
    def from_endpoint(cls, value):
        if value == 0:
            return cls(0, 0.)
        quantum = math.copysign(math.ulp(value), value)
        return cls(int(value / quantum), quantum)

    def step_bounds(self, n):
        whole, remainder = divmod(2*self.units, n)
        q = Fraction(self.quantum)
        return (whole*q, (whole + bool(remainder))*q)

    def coordinates(self, radii, n):
        # Round the positive half to nearest units, then reflect about zero.
        # The gap differs from 2L/n by at most one unit. If 2L/n is integral
        # every ideal coordinate -L + i*2L/n is already an exact lattice point.
        whole, remainder = divmod(self.units, n)
        if n*remainder + n//2 <= np.iinfo(np.int64).max:
            extra = (radii*remainder + n//2) // n
        else:
            extra = np.fromiter(((i*remainder + n//2)//n for i in range(n%2, n+1, 2)),
                                dtype=np.int64, count=len(radii))
        ray = (radii*whole + extra) * self.quantum
        mirrored = ray[::-1] if n%2 else ray[:0:-1]
        return np.concatenate((-mirrored, ray))


@dataclass(frozen=True)
class ProfileSampling:
    """Admission of the ideal chord and the binary64 coordinates to be evaluated."""
    points: int
    required_points: int  # minimum certified for the full mathematical request
    direction_xy: tuple[float, float] | None
    half_length_m: float | None
    bandwidth_per_m: float | None
    pitch_m: float | None  # mean length per interval of the endpoint chord
    _axes: tuple[_ProfileAxis, _ProfileAxis] | None

    @property
    def valid(self):
        return self.points >= self.required_points and self._axes is not None

    @property
    def endpoint_xy_m(self):
        if self._axes is not None:
            return tuple(a.units*a.quantum for a in self._axes)
        return None

    def coordinates(self):
        if self.points < self.required_points:
            raise SamplingError(f"Undersampled profile: need at least {self.required_points} points")
        if self._axes is None:
            raise SamplingError("Cannot certify the emitted profile at binary64 resolution")
        n = self.points-1
        radii = np.arange(n%2, self.points, 2, dtype=np.int64)
        return tuple(a.coordinates(radii, n) for a in self._axes)

    @property
    def required_odd_points(self):
        return self.required_points + int(self.required_points % 2 == 0)


@dataclass(frozen=True)
class SamplingDecision:
    channel: str
    model: ModelAssessment
    grid: GridSampling | None = None
    profile: ProfileSampling | None = None

    @property
    def status(self):
        if not self.model.valid:
            return "NOT_EVALUATED"
        if self.grid.valid and self.profile.valid:
            return self.channel + "_SAMPLE_VALID"
        return self.channel + "_SAMPLE_INVALID"

    @property
    def selected_pdf_side(self):
        """The qualified 2D side only. Consult status for the full PDF decision."""
        if self.channel == "PDF" and self.grid is not None and self.grid.valid:
            return self.grid.counts_xy[0]
        return None


def _count(value, minimum):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral)
            or not minimum <= value <= sys.maxsize):
        raise SamplingError(f"Expected a representable integer count >= {minimum}")
    return int(value)


def _bandwidth(p, geometry, nx, ny):
    projected = [cx*nx + cy*ny for cx, cy in geometry.centers_m]
    width = float(p.diameter_m) + (max(projected) - min(projected))
    return width / (float(p.wavelength_m) * float(p.distance_m))


def _acute(angle):
    """Return an exact degree angle in [0, 90] with cosine equal to |cos(angle)|."""
    return abs((angle + 90) % 180 - 90)


@lru_cache(maxsize=256)
def _cos_bounds(angle, bits):
    """Enclose cos(angle) by monotone bisection in degrees, without libm or pi.

    Endpoints and half-step cosines are outward-rounded fixed-point intervals.
    cos(mid) = (cos(left) + cos(right)) / (2*cos(half_step)). The initial
    90-degree step has cosine zero. Integer square roots enclose each half-step.
    """
    scale = 1 << (bits + 32)
    left, right = (scale, scale), (0, 0)
    step_lo = step_hi = 0
    part, whole = angle.as_integer_ratio()
    whole *= 90
    for _ in range(bits):
        step_lo = math.isqrt((scale + step_lo) * (scale // 2))
        step_hi = min(scale, math.isqrt((scale + step_hi) * (scale // 2)) + 1)
        lo = (left[0] + right[0]) * scale // (2 * step_hi)
        divisor = 2 * step_lo
        hi = min(scale, ((left[1] + right[1]) * scale + divisor - 1) // divisor)
        part *= 2
        if part == whole:
            return Fraction(lo, scale), Fraction(hi, scale)
        if part < whole:
            right = (lo, hi)
        else:
            left = (lo, hi)
            part -= whole
    return Fraction(right[0], scale), Fraction(left[1], scale)


def _width_terms(p, theta):
    """Projected pupil width as length coefficients times absolute cosines."""
    relative = theta - Fraction(float(p.angle_deg))
    spacing = Fraction(float(p.spacing_m))
    if p.layout == Layout.TRIANGLE:
        # The longest projection is from the nearest of the three edge axes.
        relative = (relative + 30) % 60 - 30
    terms = [(0, Fraction(float(p.diameter_m))), (_acute(relative), spacing)]
    if p.layout in (Layout.SQUARE, Layout.RECTANGLE):
        dy = spacing if p.layout == Layout.SQUARE else Fraction(float(p.spacing_y_m))
        terms.append((_acute(relative - 90), dy))
    return terms


def _exact_cosine_zero(constant, coefficients):
    """Resolve exact ties between different cosines of binary64 degree angles.

    Twice the sum is a rational Laurent polynomial P at a primitive N-th root,
    N = 360 * common dyadic denominator. Its primitive conjugates vanish together.
    Sum |P|² over those roots by excluding multiples of 2, 3 and 5. Over all
    m-th roots, orthogonality gives m * sum of squared residue-class sums.
    """
    denominator = max(a.denominator for a in coefficients)
    period = 360 * denominator
    terms = [(0, 2*constant)]
    for angle, weight in coefficients.items():
        exponent = angle.numerator * (denominator // angle.denominator)
        terms.extend(((exponent, weight), (-exponent, weight)))
    norm = 0
    for divisor, sign in ((1, 1), (2, -1), (3, -1), (5, -1),
                          (6, 1), (10, 1), (15, 1), (30, -1)):
        order = period // divisor
        residues = {}
        for exponent, weight in terms:
            r = exponent % order
            residues[r] = residues.get(r, 0) + weight
        norm += sign * order * sum(w*w for w in residues.values())
    return norm == 0


def _nonpositive_cosine_sum(terms):
    """Prove a linear inequality, combining equal directions before bounding."""
    constant = Fraction(0)
    coefficients = {}
    for angle, weight in terms:
        if angle == 0:
            constant += weight
        elif angle == 60:
            constant += weight / 2
        elif angle != 90:
            coefficients[angle] = coefficients.get(angle, 0) + weight
    coefficients = {angle: w for angle, w in coefficients.items() if w}
    if len(coefficients) == 1:
        angle, weight = next(iter(coefficients.items()))
        if angle in (30, 45):
            # Compare constant + weight*sqrt(q) <= 0 exactly, preserving signs.
            q = Fraction(3, 4) if angle == 30 else Fraction(1, 2)
            squared = weight**2 * q
            if weight > 0:
                return constant <= 0 and squared <= constant**2
            return constant <= 0 or constant**2 <= squared
    for bits in (128, 384):
        lower = upper = constant
        for angle, weight in coefficients.items():
            lo, hi = _cos_bounds(angle, bits)
            lower += weight * (lo if weight > 0 else hi)
            upper += weight * (hi if weight > 0 else lo)
        if upper <= 0:
            return True
        if lower > 0:
            return False
        if bits == 128 and _exact_cosine_zero(constant, coefficients):
            return True
    # Still straddles zero after refinement and is provably not an equality.
    # Only this unproved budget is refused.
    return False


def _minimum_intervals(p, field, angle_deg, estimated_intervals):
    """Certify n for the full physical chord, independently of its output coordinates.

    T=min(Sx/|cos(theta)|, Sy/|sin(theta)|). Thus n suffices if either wall
    proves 24*S*width <= n*lambda*z*|direction_component|. All coefficients
    start at the original binary64 inputs. Axial chords give the two grid tests.
    The result is the smallest certified integer budget.
    """
    theta = Fraction(float(angle_deg))
    width = _width_terms(p, theta)
    scale = Fraction(float(p.wavelength_m)) * Fraction(float(p.distance_m))
    walls = []
    for span, axis in ((field.half_x_m, 0), (field.half_y_m, 90)):
        component = _acute(theta - axis)
        if component != 90:
            length = 2 * MIN_INTERVALS_PER_PERIOD * Fraction(span)
            walls.append(([(a, length*w) for a, w in width], component))

    def fits(n):
        return any(_nonpositive_cosine_sum(lhs + [(component, -n*scale)])
                   for lhs, component in walls)

    n = max(1, math.ceil(estimated_intervals))
    if fits(n):
        if n == 1 or not fits(n-1):
            return n
        lo, hi = 0, n-1
    else:
        if fits(n+1):
            return n+1
        # One direction component exceeds 1/2, and all absolute cosines are
        # at most one. This strict upper bracket also bounds tiny-angle searches.
        hi = 1 + math.ceil(48*max(Fraction(field.half_x_m), Fraction(field.half_y_m))
                           * sum(w for _, w in width) / scale)
        lo = n+1
        if hi <= lo or not fits(hi):
            raise SamplingError("Cannot certify a full-chord interval budget")
    while hi-lo > 1:
        middle = (lo+hi)//2
        if fits(middle):
            hi = middle
        else:
            lo = middle
    return hi


def _pitch(half_length, intervals):
    pitch = 2 * half_length / intervals
    if pitch == 0:
        raise SamplingError("Sampling pitch is below float64 resolution")
    return pitch


def _grid(p, model, width, height):
    counts = (_count(width, 1), _count(height, 1))
    spans = (model.field.half_x_m, model.field.half_y_m)
    bands = (_bandwidth(p, model.geometry, 1., 0.), _bandwidth(p, model.geometry, 0., 1.))
    minimum = tuple(_minimum_intervals(p, model.field, angle, 2*MIN_INTERVALS_PER_PERIOD*s*k)
                    for angle, s, k in zip((0, 90), spans, bands))
    pitches = tuple(_pitch(s, n) for s, n in zip(spans, counts))
    return GridSampling(counts, minimum, bands, pitches)


def _signed_cos_bounds(angle, bits):
    acute = _acute(angle)
    exact = {0: 1, 60: Fraction(1, 2), 90: 0}
    if acute in exact:
        lo = hi = Fraction(exact[acute])
    else:
        lo, hi = _cos_bounds(acute, bits)
    return (-hi, -lo) if 90 < angle % 360 < 270 else (lo, hi)


def _inward(value):
    """Largest binary64 not exceeding a nonnegative rational length."""
    f = float(value)
    return math.nextafter(f, 0.) if f > value else f


def _chord_endpoint(field, theta):
    """Intersect the requested ray with its rectangle using enclosed ratios.

    Each magnitude is min(S_i, S_j*|u_i/u_j|). The candidate lies inward
    and is within two endpoint ulps of the exact intersection in *both* axes.
    """
    spans = (Fraction(field.half_x_m), Fraction(field.half_y_m))
    for bits in (128, 384):
        components = [_signed_cos_bounds(theta-axis, bits) for axis in (0, 90)]
        magnitudes = [sorted((abs(lo), abs(hi))) for lo, hi in components]
        end = []
        for i, (lo, hi) in enumerate(magnitudes):
            j = 1-i
            other_lo, other_hi = magnitudes[j]
            if hi == 0:
                end.append(0.)
                continue
            if lo == 0:
                break
            lower = upper = spans[i]
            if other_hi:
                lower = min(lower, spans[j]*lo/other_hi)
            if other_lo:
                upper = min(upper, spans[j]*hi/other_lo)
            if _acute(theta) == 45:
                lower = upper = min(spans)
            f = _inward(lower)
            if f == 0 or (f < sys.float_info.min and upper != f):
                break
            if upper - Fraction(f) > 2*Fraction(math.ulp(f)):
                break
            end.append(-f if components[i][1] < 0 else f)
        if len(end) == 2:
            return tuple(end)
    return None


def _projected_step(dx, dy, axis):
    """Upper bound for the magnitude of a physical step along a pupil edge."""
    lower = upper = Fraction(0)
    for delta, (lo, hi) in zip((dx, dy), axis):
        a, b = delta*lo, delta*hi
        lower += min(a, b)
        upper += max(a, b)
    return max(-lower, upper)


def _certify_steps(p, geometry, axes, n):
    # Exact integer interpolation emits one of at most four gap vectors.
    steps = [tuple(set(a.step_bounds(n))) for a in axes]
    if all(0 in choices for choices in steps):
        return False  # cannot certify distinct consecutive coordinates
    angle = Fraction(float(p.angle_deg))
    edges = [angle]
    if p.layout == Layout.TRIANGLE:
        edges += [angle-60, angle+60]
    elif p.layout in (Layout.SQUARE, Layout.RECTANGLE):
        edges.append(angle+90)
    orientations = [(_signed_cos_bounds(e, 128), _signed_cos_bounds(e-90, 128)) for e in edges]
    spacing = Fraction(float(p.spacing_m))
    spacing_y = Fraction(float(p.spacing_y_m)) if p.layout == Layout.RECTANGLE else spacing
    disk_squared = Fraction(float(p.diameter_m))**2
    budget = Fraction(float(p.wavelength_m))*Fraction(float(p.distance_m))/MIN_INTERVALS_PER_PERIOD
    coordinates = [(Fraction(x), Fraction(y)) for x, y in geometry.centers_m]
    for dx in steps[0]:
        for dy in steps[1]:
            projections = [_projected_step(dx, dy, axis) for axis in orientations]
            if p.layout in (Layout.SQUARE, Layout.RECTANGLE):
                centres = spacing*projections[0] + spacing_y*projections[1]
            else:
                centres = spacing*max(projections)
            # Cover the stored binary64 centres used by intensity as well as
            # the mathematical pupil, especially for a rotated preset at a tie.
            stored = [x*dx + y*dy for x, y in coordinates]
            rest = budget - max(centres, max(stored)-min(stored))
            if rest < 0 or rest**2 < disk_squared*(dx**2+dy**2):
                return False
    return True


def _qualified_axes(p, geometry, endpoint, n):
    axes = tuple(_ProfileAxis.from_endpoint(v) for v in endpoint)
    if _certify_steps(p, geometry, axes, n):
        return axes

    # When a lattice gap rounds up at a tight budget, move BOTH components
    # inward by the same scale. In component i the maximum displacement error
    # is q_i (integer interpolation) + 2*(2+1)*q_i/n (initial endpoint and
    # final inward rounding). D + sum of edge lengths bounds the change in
    # pupil support per metre of displacement, also for oblique pupils.
    width = sum(w for _, w in _width_terms(p, Fraction(0)))
    quantum = sum(abs(Fraction(a.quantum)) for a in axes)
    budget = Fraction(float(p.wavelength_m))*Fraction(float(p.distance_m))/MIN_INTERVALS_PER_PERIOD
    contraction = width*quantum*(1+Fraction(6, n))/budget
    if contraction >= 1:
        return None
    smaller = tuple(math.copysign(_inward(abs(Fraction(v))*(1-contraction)), v) for v in endpoint)
    if any(v != s and abs(s) < sys.float_info.min for v, s in zip(endpoint, smaller)):
        return None
    axes = tuple(_ProfileAxis.from_endpoint(v) for v in smaller)
    return axes if _certify_steps(p, geometry, axes, n) else None


def _profile(p, model, points, angle_deg):
    points = _count(points, 2)
    theta = Fraction(_number(angle_deg, "profile_angle_deg"))
    endpoint = _chord_endpoint(model.field, theta)
    if endpoint is None:
        minimum = _minimum_intervals(p, model.field, theta, 1)
        return ProfileSampling(points, minimum+1, None, None, None, None, None)

    half = math.hypot(*endpoint)
    unit = tuple(v/half for v in endpoint)
    band = _bandwidth(p, model.geometry, *unit)
    minimum = _minimum_intervals(p, model.field, theta, 2*MIN_INTERVALS_PER_PERIOD*half*band)
    n = points-1
    axes = _qualified_axes(p, model.geometry, endpoint, n) if n >= minimum else None
    if axes is not None:
        endpoint = tuple(a.units*a.quantum for a in axes)
        half = math.hypot(*endpoint)
        unit = tuple(v/half for v in endpoint)
        band = _bandwidth(p, model.geometry, *unit)
    return ProfileSampling(points, minimum+1, unit, half, band, 2*half/n, axes)


def assess_gui(p, width_px, height_px, profile_pixels, *, profile_points=None,
               field: Field | None = None, profile_angle_deg=0.0) -> SamplingDecision:
    """Use actual physical image cells and plot positions, after device scaling.

    If the plotted curve has fewer computed points, it has that smaller budget.
    Both the grid and endpoint-inclusive profile must qualify.
    """
    model = assess_model(p, field)
    if not model.valid:
        return SamplingDecision("GUI", model)
    available = _count(profile_pixels, 2)
    if profile_points is not None:
        available = min(available, _count(profile_points, 2))
    return SamplingDecision("GUI", model, _grid(p, model, width_px, height_px),
                            _profile(p, model, available, profile_angle_deg))


def assess_pdf(p, *, field: Field | None = None, profile_angle_deg=0.0) -> SamplingDecision:
    """Pick the smallest qualified candidate square and check 1025 line points.

    When all grids fail, grid describes the largest rejected attempt.
    This calculation takes no GUI state and performs no rendering.
    """
    model = assess_model(p, field)
    if not model.valid:
        return SamplingDecision("PDF", model)
    for side in PDF_GRID_SIDES:
        grid = _grid(p, model, side, side)
        if grid.valid:
            break
    return SamplingDecision("PDF", model, grid, _profile(p, model, PDF_PROFILE_POINTS,
                                                         profile_angle_deg))


@dataclass(frozen=True)
class ScreenData:
    x_centers_m: np.ndarray
    y_centers_m: np.ndarray
    pixel_mean: np.ndarray  # (y, x), rows increasing in physical y, linear I/I(0)
    sampling: GridSampling


@dataclass(frozen=True)
class ProfileData:
    position_m: np.ndarray
    point_intensity: np.ndarray
    sampling: ProfileSampling


def prepare_screen(p, width, height, *, field: Field | None = None) -> ScreenData:
    """2x2 Gauss-Legendre cell means on an independently qualified rectangle."""
    model = assess_model(p, field)
    model.require_valid()
    grid = _grid(p, model, width, height)
    if not grid.valid:
        raise SamplingError(f"Undersampled grid: need at least {grid.required_xy} cells")
    nx, ny = grid.counts_xy
    dx, dy = grid.pitch_xy_m
    x = (np.arange(nx, dtype=np.float64) - (nx - 1) / 2) * dx
    y = (np.arange(ny, dtype=np.float64) - (ny - 1) / 2) * dy
    ox, oy = dx / (2 * math.sqrt(3)), dy / (2 * math.sqrt(3))
    if min(ox, oy) == 0:
        raise SamplingError("Quadrature offset is below float64 resolution")
    mean = np.zeros((ny, nx), dtype=np.float64)
    for y_node in (y - oy, y + oy):
        for x_node in (x - ox, x + ox):
            mean += intensity(p, x_node[None, :], y_node[:, None])
    mean *= 0.25
    return ScreenData(x, y, mean, grid)


def prepare_profile(p, points, *, field: Field | None = None, profile_angle_deg=0.0) -> ProfileData:
    """Signed, endpoint-inclusive point profile with its own direction and gate."""
    model = assess_model(p, field)
    model.require_valid()
    line = _profile(p, model, points, profile_angle_deg)
    x, y = line.coordinates()
    position = np.hypot(x, y)
    position[:line.points//2] *= -1
    return ProfileData(position, intensity(p, x, y), line)

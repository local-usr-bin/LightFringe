"""Admission boundaries and raw numerical data of the multi-aperture sampler."""
from dataclasses import replace
from fractions import Fraction
import math
import unittest
from unittest.mock import patch

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.special import jv

from lightfringe import multiaperture_model as model
from lightfringe.multiaperture_model import Field, Layout, MultiApertureParameters, intensity
from lightfringe.multiaperture_sampling import (
    MIN_INTERVALS_PER_PERIOD, PDF_GRID_SIDES, PDF_PROFILE_POINTS, SamplingError,
    assess_gui, assess_pdf, prepare_profile, prepare_screen,
)


PAIR = MultiApertureParameters()
DENSE = replace(PAIR, layout=Layout.RECTANGLE, wavelength_m=405e-9, diameter_m=65e-6,
                spacing_m=170e-6, spacing_y_m=125e-6, angle_deg=35.)
AREA_ATOL = 2e-5


def reference_cell_means(p, x, y, pitches, order):
    """Tensor quadrature of a separate cosine-product and Jv formula for pair/rectangle."""
    nodes, weights = leggauss(order)
    scale = np.pi / (p.wavelength_m * p.distance_m)
    angle = np.deg2rad(p.angle_deg)
    mean = np.zeros((len(y), len(x)))
    for ty, wy in zip(nodes, weights):
        yy = y[:, None] + ty*pitches[1]/2
        for tx, wx in zip(nodes, weights):
            xx = x[None, :] + tx*pitches[0]/2
            u = scale * p.diameter_m * np.hypot(xx, yy)
            disk = np.ones_like(u)
            np.divide(2*jv(1, u), u, out=disk, where=u != 0)
            local_x = xx*np.cos(angle) + yy*np.sin(angle)
            amp = disk * np.cos(scale*p.spacing_m*local_x)
            if p.layout == Layout.RECTANGLE:
                local_y = -xx*np.sin(angle) + yy*np.cos(angle)
                amp *= np.cos(scale*p.spacing_y_m*local_y)
            mean += wx*wy*np.square(amp)/4
    return mean


def cell_comparison(p):
    shape = assess_pdf(p).grid.required_xy
    data = prepare_screen(p, *shape)
    nx, ny = shape
    ix = [0, nx//4, nx//2-9, nx//2, nx//2+8, 3*nx//4, nx-1]
    iy = [0, ny//4, ny//2-6, ny//2, ny//2+11, 3*ny//4, ny-1]
    xy = data.x_centers_m[ix], data.y_centers_m[iy]
    ref8 = reference_cell_means(p, *xy, data.sampling.pitch_xy_m, 8)
    ref12 = reference_cell_means(p, *xy, data.sampling.pitch_xy_m, 12)
    return data.pixel_mean[np.ix_(iy, ix)], ref8, ref12


class MultiApertureSamplingTests(unittest.TestCase):
    def check_axis_pair_emission(self, p, field, angle, points, side):
        """Intercept the public data call and check each binary64 displacement."""
        gui = assess_gui(p, side, side, points, field=field, profile_angle_deg=angle)
        self.assertEqual(gui.status, "GUI_SAMPLE_VALID")
        with patch("lightfringe.multiaperture_sampling.intensity", wraps=intensity) as evaluate:
            data = prepare_profile(p, points, field=field, profile_angle_deg=angle)
            evaluate.assert_called_once()
            _, x, y = evaluate.call_args.args
        self.assertEqual(gui.profile, data.sampling)
        self.assertEqual(data.sampling.endpoint_xy_m, (x[-1], y[-1]))
        self.assertEqual((x[0], y[0]), (-x[-1], -y[-1]))
        np.testing.assert_array_equal(data.point_intensity, intensity(p, x, y))
        np.testing.assert_array_equal(abs(data.position_m), np.hypot(x, y))
        self.assertEqual(data.position_m.size, points)
        self.assertTrue(np.all(np.diff(data.position_m) > 0))

        # Independently reduce near a cardinal in degrees before converting the
        # small residual to radians. This retains the sign and size just past 90°.
        quarter = round(angle/90)
        r = math.radians(angle-90*quarter)
        c, s = math.cos(r), math.sin(r)
        unit = ((c, s), (-s, c), (-c, -s), (s, -c))[quarter % 4]
        spans = (field.half_x_m, field.half_y_m)
        half = min(span/abs(u) for span, u in zip(spans, unit) if u)
        for samples, span, u in zip((x, y), spans, unit):
            np.testing.assert_array_equal(samples, -samples[::-1])
            self.assertLessEqual(max(abs(samples)), span)
            self.assertAlmostEqual(samples[-1], half*u, delta=3e-13*abs(half*u))
            self.assertAlmostEqual(samples[-1]/data.sampling.half_length_m, u, delta=2e-15*abs(u))
            # Interior points lie within half an endpoint ulp of the straight
            # segment interpolating the observed endpoints (even budgets too).
            end = Fraction(samples[-1])
            n = points-1
            error = max(abs(n*Fraction(v)-(2*i-n)*end) for i, v in enumerate(samples))
            self.assertLessEqual(2*error, n*Fraction(math.ulp(samples[-1])))

        axis = 1 if p.angle_deg == 90 else 0
        self.assertIn(p.angle_deg, (0, 90))
        scale = Fraction(p.wavelength_m)*Fraction(p.distance_m)
        d, spacing = Fraction(p.diameter_m), Fraction(p.spacing_m)
        def fits(dx, dy, intervals):
            rest = intervals*scale - 12*spacing*abs((dx, dy)[axis])
            return rest >= 0 and rest**2 >= (12*d)**2*(dx**2+dy**2)

        xx, yy = list(map(Fraction, x)), list(map(Fraction, y))
        self.assertTrue(fits(xx[-1]-xx[0], yy[-1]-yy[0], points-1))
        self.assertTrue(all(fits(b-a, v-u, 1) for a,b,u,v in zip(xx, xx[1:], yy, yy[1:])))
        return data

    def check_rejection_before_intensity(self, p, field, angle, points):
        with patch("lightfringe.multiaperture_sampling.intensity") as evaluate:
            with self.assertRaises(SamplingError):
                prepare_profile(p, points, field=field, profile_angle_deg=angle)
            evaluate.assert_not_called()

    def test_reaudit_one_ulp_past_vertical_narrow_x(self):
        p = replace(PAIR, angle_deg=90.)
        f = Field(2.**-58, .035)
        theta = math.nextafter(90., math.inf)
        line = self.check_axis_pair_emission(p, f, theta, 142, 383)
        self.assertAlmostEqual(line.sampling.half_length_m, .013988227420186112, delta=1e-16)
        self.check_rejection_before_intensity(p, f, theta, 141)

    def test_reaudit_91_degree_rectangle(self):
        p = replace(PAIR, angle_deg=90.)
        f = Field(.00044520705294485123, .0375)
        self.check_axis_pair_emission(p, f, 91., 257, 383)
        self.check_rejection_before_intensity(p, f, 91., 256)

    def test_reaudit_120_degree_pdf_and_60_degree_mirror(self):
        d, sx = 31/131072, 9/128
        p = replace(PAIR, diameter_m=d, spacing_m=d, distance_m=3., wavelength_m=2*sx*(1.5*d)/128)
        for theta in (60., 120.):
            for half in (math.nextafter(sx, 0.), sx, math.nextafter(sx, math.inf)):
                with self.subTest(theta=theta, half=half):
                    f = Field(half, 1/8)
                    pdf = assess_pdf(p, field=f, profile_angle_deg=theta)
                    self.assertEqual(pdf.selected_pdf_side, 767)
                    if half <= sx:
                        line = self.check_axis_pair_emission(p, f, theta, 1025, 767)
                        self.assertEqual(pdf.profile, line.sampling)
                        self.assertEqual(pdf.status, "PDF_SAMPLE_VALID")
                    else:
                        self.assertEqual(pdf.status, "PDF_SAMPLE_INVALID")
                        self.check_rejection_before_intensity(p, f, theta, 1025)

    def test_emitted_directions_and_extents_on_rectangles(self):
        for i, angle in enumerate((0., 45., 60., 90., 91., 108., 120., -37., -90., -120.)):
            with self.subTest(angle=angle):
                field = Field(.016, .006) if i%2 else Field(.009, .014)
                self.check_axis_pair_emission(PAIR, field, angle, 255+i%2, 383)

    def test_unrepresentable_geometry_rejects_before_intensity(self):
        # The ideal interval budget alone cannot authorize unresolved direction
        # or more distinct positions than the coordinate format can represent.
        cases = ((Field(.03, 5.770611636116085e-132), 2.**-420, 383, 1025),
                 (Field(16*math.ulp(0.), .001), 0., 1, 129))
        for f, theta, width, points in cases:
            with self.subTest(angle=theta):
                gui = assess_gui(PAIR, width, 383, points, field=f, profile_angle_deg=theta)
                self.assertTrue(gui.model.valid and gui.grid.valid)
                self.assertGreaterEqual(points, gui.profile.required_points)
                self.assertEqual(gui.status, "GUI_SAMPLE_INVALID")
                self.check_rejection_before_intensity(PAIR, f, theta, points)

    def test_x_and_y_can_fail_independently(self):
        for angle, required in ((0., (355, 124)), (90., (124, 355)), (45., (288, 288))):
            p = replace(PAIR, angle_deg=angle)
            nx, ny = required
            with self.subTest(angle=angle):
                good = assess_gui(p, nx, ny, 1025)
                self.assertEqual(good.grid.required_xy, required)
                self.assertEqual(good.status, "GUI_SAMPLE_VALID")
                self.assertFalse(assess_gui(p, nx-1, ny, 1025).grid.valid)
                self.assertFalse(assess_gui(p, nx, ny-1, 1025).grid.valid)
        # Along y the pair-centre contribution vanishes, but the disk bandwidth remains.
        self.assertAlmostEqual(assess_pdf(PAIR).grid.bandwidth_xy_per_m[1],
                               PAIR.diameter_m / (PAIR.wavelength_m*PAIR.distance_m))

    def test_twelve_exact_intervals_and_next_representable_field(self):
        # Kx=256, Ky=128 cycles/m, field width=1/32 m. The screen has N cells;
        # the endpoint-inclusive line uses M-1 intervals.
        p = replace(PAIR, wavelength_m=2.**-21, diameter_m=2.**-14, spacing_m=2.**-14)
        field = Field(1/64, 1/64)
        exact = assess_gui(p, 96, 48, 97, field=field)
        self.assertEqual(exact.grid.required_xy, (96, 48))
        self.assertEqual(exact.profile.required_points, 97)
        self.assertEqual(exact.status, "GUI_SAMPLE_VALID")
        larger = assess_gui(p, 96, 48, 97, field=Field(math.nextafter(1/64, 1), 1/64))
        self.assertEqual(larger.grid.required_xy, (97, 48))
        self.assertEqual(larger.profile.required_points, 98)
        self.assertEqual(larger.profile.required_odd_points, 99)
        self.assertEqual(larger.status, "GUI_SAMPLE_INVALID")

    def test_audit_pdf_tier_boundaries_and_data_entry_points(self):
        base = replace(PAIR, wavelength_m=3*2.**-22, distance_m=2., diameter_m=2.**-13,
                       spacing_m=3*2.**-13)
        scale = Fraction(base.wavelength_m) * Fraction(base.distance_m)
        for side, next_side in ((383, 511), (511, 767), (767, None)):
            field = Field(side/8192, 1/256)
            for d in (math.nextafter(base.diameter_m, 0.), base.diameter_m, math.nextafter(base.diameter_m, 1.)):
                with self.subTest(side=side, diameter=d.hex()):
                    p = replace(base, diameter_m=d)
                    raw = 24*Fraction(field.half_x_m)*(Fraction(d) + Fraction(p.spacing_m))/scale
                    self.assertEqual(raw == side, d == base.diameter_m)
                    pdf = assess_pdf(p, field=field)
                    self.assertEqual(pdf.grid.required_xy, (math.ceil(raw), math.ceil(24*Fraction(field.half_y_m)*Fraction(d)/scale)))
                    self.assertEqual(pdf.profile.required_points, math.ceil(raw)+1)
                    selected = side if raw <= side else next_side
                    self.assertEqual(pdf.selected_pdf_side, selected)
                    self.assertEqual(pdf.status, "PDF_SAMPLE_VALID" if selected else "PDF_SAMPLE_INVALID")
                    gui = assess_gui(p, side, 20, side+1, field=field)
                    if raw <= side:
                        self.assertEqual(gui.status, "GUI_SAMPLE_VALID")
                        self.assertEqual(prepare_screen(p, side, 20, field=field).pixel_mean.shape, (20, side))
                    else:
                        self.assertEqual(gui.status, "GUI_SAMPLE_INVALID")
                        with patch("lightfringe.multiaperture_sampling.intensity") as evaluate:
                            with self.assertRaises(SamplingError):
                                prepare_screen(p, side, side, field=field)
                            with self.assertRaises(SamplingError):
                                prepare_profile(p, side+1, field=field)
                            evaluate.assert_not_called()

    def test_audit_45_degree_chord_needs_1026_despite_qualified_767_grid(self):
        p = replace(PAIR, wavelength_m=2.**-21, distance_m=3., diameter_m=2.**-13,
                    spacing_m=3*2.**-13, angle_deg=45.)
        cutoff = .08838834764831845
        for sx in (math.nextafter(cutoff, 0.), cutoff, math.nextafter(cutoff, 1.)):
            with self.subTest(sx=sx.hex()):
                # Squaring eliminates sqrt(2) from the true T = sqrt(2)*S.
                left = 2*(24*Fraction(sx)*(Fraction(p.diameter_m)+Fraction(p.spacing_m)))**2
                right = (1024*Fraction(p.wavelength_m)*Fraction(p.distance_m))**2
                allowed = left <= right
                self.assertEqual(allowed, sx < cutoff)
                field = Field(sx, sx)
                pdf = assess_pdf(p, field=field, profile_angle_deg=45)
                self.assertEqual(pdf.grid.required_xy, (566, 566))
                self.assertEqual(pdf.selected_pdf_side, 767)
                self.assertEqual(pdf.profile.required_points, 1025 if allowed else 1026)
                self.assertEqual(pdf.status, "PDF_SAMPLE_VALID" if allowed else "PDF_SAMPLE_INVALID")
                if allowed:
                    self.assertEqual(prepare_profile(p, 1025, field=field, profile_angle_deg=45).position_m.size, 1025)
                else:
                    with patch("lightfringe.multiaperture_sampling.intensity") as evaluate:
                        with self.assertRaises(SamplingError):
                            prepare_profile(p, 1025, field=field, profile_angle_deg=45)
                        evaluate.assert_not_called()
                    self.assertEqual(prepare_profile(p, 1026, field=field, profile_angle_deg=45).position_m.size, 1026)

    def test_oblique_exactly_1024_intervals_and_neighbouring_views(self):
        # A horizontal tangent pair seen along 60 degrees has width 3D/2.
        # Set T=2*Sx so that the limiting half-width is exactly representable.
        d = 31 / 131072
        half = 9 / 128
        p = replace(PAIR, diameter_m=d, spacing_m=d, distance_m=3., wavelength_m=(2*half)*(1.5*d)/128)
        for sx in (math.nextafter(half, 0.), half, math.nextafter(half, 1.)):
            raw = 24*(2*Fraction(sx))*(3*Fraction(d)/2)/(Fraction(p.wavelength_m)*Fraction(p.distance_m))
            self.assertEqual(raw == 1024, sx == half)
            field = Field(sx, 1/8)
            pdf = assess_pdf(p, field=field, profile_angle_deg=60)
            self.assertTrue(pdf.grid.valid)
            self.assertEqual(pdf.profile.required_points, 1+math.ceil(raw))
            self.assertEqual(pdf.status, "PDF_SAMPLE_VALID" if raw <= 1024 else "PDF_SAMPLE_INVALID")
            if raw <= 1024:
                self.assertEqual(prepare_profile(p, 1025, field=field, profile_angle_deg=60).position_m.size, 1025)

    def test_general_rotation_enclosure_against_golden_ratio_projection(self):
        # cos(36 degrees)=(1+sqrt(5))/4. Use this independent radical to certify
        # neighbours of a cutoff handled by the general angle branch in production.
        p = replace(PAIR, angle_deg=36.)
        d, spacing = Fraction(p.diameter_m), Fraction(p.spacing_m)
        budget = 383*Fraction(p.wavelength_m)*Fraction(p.distance_m)
        rough = float(budget)/(24*(p.diameter_m + p.spacing_m*(1+math.sqrt(5))/4))
        requirements = set()
        for sx in (math.nextafter(rough, 0., steps=2), math.nextafter(rough, 0.), rough,
                   math.nextafter(rough, 1.), math.nextafter(rough, 1., steps=2)):
            rest = budget - 24*Fraction(sx)*(d+spacing/4)
            fits = rest >= 0 and rest**2 >= 5*(24*Fraction(sx)*spacing/4)**2
            pdf = assess_pdf(p, field=Field(sx, .003))
            self.assertEqual(pdf.grid.required_xy[0], 383 if fits else 384)
            requirements.add(pdf.grid.required_xy[0])
        self.assertEqual(requirements, {383, 384})

    def test_exact_oblique_tie_between_distinct_irrational_projections(self):
        # cos(36°) - cos(72°) = 1/2. With D=d/2 and a limiting X wall,
        # 24*T*(D+d*cos(72°))/(lambda*z) reduces exactly to 24*Sx*d/(lambda*z).
        p = replace(PAIR, wavelength_m=3*2.**-22, distance_m=2., diameter_m=2.**-13,
                    spacing_m=2.**-12, angle_deg=108.)
        for sx in (math.nextafter(1/16, 0.), 1/16, math.nextafter(1/16, 1.)):
            raw = 24*Fraction(sx)*Fraction(p.spacing_m)/(Fraction(p.wavelength_m)*Fraction(p.distance_m))
            self.assertEqual(raw == 256, sx == 1/16)
            field = Field(sx, .05)
            gui = assess_gui(p, 767, 767, 257, field=field, profile_angle_deg=36)
            self.assertEqual(gui.profile.required_points, 1+math.ceil(raw))
            self.assertEqual(gui.status, "GUI_SAMPLE_VALID" if raw <= 256 else "GUI_SAMPLE_INVALID")
            if raw <= 256:
                self.assertEqual(prepare_profile(p, 257, field=field, profile_angle_deg=36).position_m.size, 257)
            else:
                with self.assertRaises(SamplingError):
                    prepare_profile(p, 257, field=field, profile_angle_deg=36)

    def test_gui_physical_resolution_and_pdf_are_independent(self):
        gui = assess_gui(PAIR, 300, 300, 401)
        self.assertEqual(gui.model.status, "MODEL_VALID")
        self.assertEqual(gui.status, "GUI_SAMPLE_INVALID")
        self.assertFalse(gui.grid.valid)
        self.assertTrue(gui.profile.valid)
        self.assertIsNone(gui.selected_pdf_side)
        for physical, computed in ((300, 4097), (4097, 300)):
            short = assess_gui(PAIR, 383, 383, physical, profile_points=computed)
            self.assertTrue(short.grid.valid)
            self.assertFalse(short.profile.valid)
            self.assertEqual(short.profile.points, 300)
        self.assertEqual(assess_pdf(PAIR).status, "PDF_SAMPLE_VALID")
        self.assertEqual(assess_pdf(PAIR).selected_pdf_side, 383)

    def test_smallest_qualified_pdf_grid_in_each_of_the_three_tiers(self):
        self.assertEqual(PDF_GRID_SIDES, (383, 511, 767))
        self.assertEqual(PDF_PROFILE_POINTS, 1025)
        for p, field, side, required in ((PAIR, None, 383, (355, 124)),
                                         (DENSE, Field(.03, .03), 511, (491, 471)),
                                         (DENSE, None, 767, (579, 556))):
            with self.subTest(side=side):
                pdf = assess_pdf(p, field=field, profile_angle_deg=45)
                self.assertEqual(pdf.status, "PDF_SAMPLE_VALID")
                self.assertEqual(pdf.grid.required_xy, required)
                self.assertEqual(pdf.selected_pdf_side, side)
                self.assertEqual(pdf.profile.points, 1025)

    def test_diagonal_profile_has_its_own_threshold_and_physical_endpoints(self):
        short = assess_gui(DENSE, 767, 767, 401, profile_angle_deg=45)
        self.assertTrue(short.grid.valid)
        self.assertFalse(short.profile.valid)
        self.assertEqual(short.profile.required_points, 754)
        self.assertEqual(short.profile.required_odd_points, 755)
        with self.assertRaises(SamplingError):
            prepare_profile(DENSE, 753, profile_angle_deg=45)
        for count in (754, 755):
            data = prepare_profile(DENSE, count, profile_angle_deg=45)
            t = data.position_m
            self.assertEqual(t[-1], -t[0])
            self.assertAlmostEqual(t[-1], .05, delta=2e-17)
            np.testing.assert_allclose(data.point_intensity, intensity(DENSE, t/np.sqrt(2), t/np.sqrt(2)),
                                       atol=2e-13, rtol=0)
            if count % 2:
                self.assertEqual(t[count//2], 0.)
                self.assertEqual(data.point_intensity[count//2], 1.)
        asymmetric = Field(.005, .02)
        for angle, half in ((0., .005), (90., .02), (180., .005), (270., .02)):
            line = prepare_profile(PAIR, 401, field=asymmetric, profile_angle_deg=angle)
            self.assertEqual(line.sampling.half_length_m, half)

    def test_pdf_grid_passes_but_1025_diagonal_points_fail(self):
        p = replace(PAIR, wavelength_m=380e-9, distance_m=3., diameter_m=100e-6,
                    spacing_m=370e-6, angle_deg=45.)
        field = Field(.09, .09)
        pdf = assess_pdf(p, field=field, profile_angle_deg=45)
        self.assertEqual(pdf.model.status, "MODEL_VALID")
        self.assertEqual(pdf.grid.required_xy, (686, 686))
        self.assertEqual(pdf.selected_pdf_side, 767)
        self.assertTrue(pdf.grid.valid)
        self.assertEqual(pdf.profile.required_points, 1261)
        self.assertEqual(pdf.status, "PDF_SAMPLE_INVALID")
        with self.assertRaises(SamplingError):
            prepare_profile(p, 1025, field=field, profile_angle_deg=45)

    def test_real_paraxial_rectangle_exceeds_highest_candidate(self):
        p = replace(PAIR, wavelength_m=380e-9, spacing_m=166e-6, distance_m=.8)
        field = Field(.0399, .001)
        pdf = assess_pdf(p, field=field, profile_angle_deg=90)
        self.assertEqual(pdf.model.status, "MODEL_VALID")
        self.assertEqual(pdf.grid.required_xy, (775, 7))
        self.assertEqual(pdf.grid.counts_xy, (767, 767))
        self.assertTrue(pdf.profile.valid)
        self.assertEqual(pdf.status, "PDF_SAMPLE_INVALID")
        self.assertIsNone(pdf.selected_pdf_side)
        # An area average must never be computed as a fallback for missing pixels.
        with patch("lightfringe.multiaperture_sampling.intensity") as evaluate:
            with self.assertRaises(SamplingError):
                prepare_screen(p, 767, 767, field=field)
            evaluate.assert_not_called()

    def test_conditional_default_field_bound_and_near_saturation(self):
        self.assertEqual((model.WAVELENGTH_RANGE_M[0], model.MAX_ARRAY_FRESNEL, model.MAX_RADIAL_RATIO,
                          model.DEFAULT_HALF_SPAN_CAP_M, MIN_INTERVALS_PER_PERIOD),
                         (380e-9, .05, .05, .04, 12))
        # Across z, S/sqrt(z) peaks where 0.05*z/sqrt(2) crosses 0.040 m.
        z_star = .04*math.sqrt(2)/.05
        radius = math.sqrt(.05*380e-9*z_star)
        max_intervals = 24*.04*(2*radius)/(380e-9*z_star)
        self.assertEqual(math.ceil(max_intervals), 655)
        self.assertEqual(1 + math.ceil(math.sqrt(2)*max_intervals), 927)
        p = replace(PAIR, wavelength_m=380e-9, distance_m=z_star,
                    spacing_m=math.nextafter(2*radius-PAIR.diameter_m, 0))
        self.assertEqual(assess_pdf(p).grid.required_xy[0], 655)
        diagonal = assess_pdf(replace(p, angle_deg=45), profile_angle_deg=45)
        self.assertEqual(diagonal.profile.required_points, 927)
        self.assertEqual(diagonal.status, "PDF_SAMPLE_VALID")

    def test_model_rejection_stays_separate_from_sampling(self):
        for p, field in ((replace(PAIR, spacing_m=500e-6), None), (PAIR, Field(.04, .04))):
            for decision in (assess_gui(p, 1000, 1000, 2001, field=field), assess_pdf(p, field=field)):
                self.assertEqual(decision.model.status, "MODEL_INVALID")
                self.assertEqual(decision.status, "NOT_EVALUATED")
                self.assertIsNone(decision.grid)
                self.assertIsNone(decision.profile)
                self.assertIsNone(decision.selected_pdf_side)
            with self.assertRaises(model.MultiApertureError):
                prepare_screen(p, 1000, 1000, field=field)

    def test_area_means_against_refined_independent_quadrature(self):
        for p in (PAIR, DENSE):
            with self.subTest(layout=p.layout):
                actual, ref8, ref12 = cell_comparison(p)
                np.testing.assert_allclose(ref8, ref12, atol=2e-12, rtol=0)
                np.testing.assert_allclose(actual, ref12, atol=AREA_ATOL, rtol=0)

    def test_rectangular_screen_axes_cell_centres_and_unscaled_values(self):
        field = Field(.006, .004)
        data = prepare_screen(PAIR, 65, 47, field=field)
        self.assertEqual(data.pixel_mean.shape, (47, 65))
        self.assertEqual(data.x_centers_m[32], 0.)
        self.assertEqual(data.y_centers_m[23], 0.)
        dx, dy = data.sampling.pitch_xy_m
        np.testing.assert_allclose(np.diff(data.x_centers_m), dx, rtol=0, atol=2e-18)
        np.testing.assert_allclose(np.diff(data.y_centers_m), dy, rtol=0, atol=2e-18)
        self.assertAlmostEqual(data.x_centers_m[-1] + dx/2, field.half_x_m, delta=2e-18)
        self.assertTrue(np.all(np.isfinite(data.pixel_mean)))
        self.assertGreaterEqual(data.pixel_mean.min(), 0.)
        self.assertLess(data.pixel_mean.max(), 1.)  # axial cell mean differs from axial point
        self.assertEqual(prepare_profile(PAIR, 129, field=field).point_intensity[64], 1.)

    def test_malformed_counts_and_profile_angles(self):
        for counts in ((True, 383, 401), (0, 383, 401), (383, 3.5, 401), (383, 383, 1)):
            with self.subTest(counts=counts), self.assertRaises(SamplingError):
                assess_gui(PAIR, *counts)
        with self.assertRaises(model.MultiApertureError):
            assess_pdf(PAIR, profile_angle_deg=np.nan)

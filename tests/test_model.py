"""Independent expectations: tabulated constants and direct aperture quadrature.

The quadrature below never calls sinc/cos or production envelope code.
"""
from dataclasses import replace
import unittest
import numpy as np

from lightfringe.model import (
    Parameters, Mode, ModelError, intensity, validate, characteristic_lengths,
)
from lightfringe.sampling import prepare_display
from lightfringe.rendering import curve_vertex_indices


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.p = Parameters()
        self.single = replace(self.p, mode=Mode.SINGLE)

    def test_single_tabulated_intensities(self):
        # At x = lambda*z/(2a): (2/pi)^2, independent decimal reference.
        x = np.array([0, 0.009166666666666667, 0.018333333333333333])
        np.testing.assert_allclose(intensity(x, self.single),
                                   [1, 0.4052847345693511, 0], atol=2e-15)

    def test_double_tabulated_intensities(self):
        # At d*x/(lambda*z) = 1: [sin(pi/5)/(pi/5)]^2.
        x = [0, 0.0018333333333333333, 0.0036666666666666666]
        np.testing.assert_allclose(intensity(x, self.p),
                                   [1, 0, 0.8751402000833809], atol=2e-15)

    def test_direct_complex_aperture_integral(self):
        # Midpoint quadrature over actual transmitting intervals, 16000/slit.
        # Integrate exp(-i*2*pi*x*xi/(lambda*z)) and normalize by open width.
        for p in (self.single, self.p,
                  Parameters(wavelength=630e-9, slit_width=45e-6,
                             separation=130e-6, distance=1.7)):
            x = np.array([-0.031, -0.0137, -0.0023, 0, 0.0023, 0.0137, 0.031])
            centers = [0] if p.mode == Mode.SINGLE else [-p.separation/2, p.separation/2]
            amplitude = np.zeros(x.size, dtype=complex)
            xi_local = ((np.arange(16000) + .5) / 16000 - .5) * p.slit_width
            for center in centers:
                xi = xi_local + center
                amplitude += np.exp(-2j * np.pi * x[:, None] * xi / (p.wavelength*p.distance)).mean(axis=1)
            reference = np.abs(amplitude / len(centers)) ** 2
            np.testing.assert_allclose(intensity(x, p), reference, atol=8e-9, rtol=0)

    def test_wavelength_increases_fringe_spacing(self):
        p = replace(self.p, wavelength=660e-9)
        _, delta = characteristic_lengths(p)
        self.assertAlmostEqual(delta, .0044, places=14)
        self.assertGreater(delta, characteristic_lengths(self.p)[1])
        self.assertLess(float(intensity(delta / 2, p)), 1e-28)

    def test_separation_decreases_fringe_spacing(self):
        p = replace(self.p, separation=200e-6)
        delta = characteristic_lengths(p)[1]
        self.assertAlmostEqual(delta, .00275, places=14)
        self.assertLess(delta, characteristic_lengths(self.p)[1])
        self.assertLess(float(intensity(delta / 2, p)), 1e-28)

    def test_narrower_single_slit_widens_envelope(self):
        p = replace(self.single, slit_width=15e-6)
        zero, _ = characteristic_lengths(p)
        self.assertAlmostEqual(zero, .03666666666666667, places=14)
        self.assertGreater(float(intensity(.018333333333333333, p)), .40528)
        self.assertLess(float(intensity(zero, p)), 1e-28)

    def test_default_missing_orders(self):
        # m = +/-5 coincides with the first envelope zero at +/-18.333 mm.
        # +/-10 coincides with the second zero. Neighbouring orders survive.
        delta = .0036666666666666666
        values = intensity(np.array([-10, -5, 5, 10]) * delta, self.p)
        self.assertTrue(np.all(values < 1e-28))
        neighbours = intensity(np.array([-6, -4, 4, 6]) * delta, self.p)
        self.assertTrue(np.all(neighbours > .02))

    def test_center_stable(self):
        for p in (self.single, self.p):
            x = np.array([-1e-300, 0, 1e-300])
            with np.errstate(all='raise', under='ignore'):
                np.testing.assert_array_equal(intensity(x, p), [1, 1, 1])

    def test_symmetry_bounds_finiteness(self):
        for p in (self.single, self.p):
            values = intensity(np.linspace(-.04, .04, 10001), p)
            np.testing.assert_allclose(values, values[::-1], atol=5e-15)
            self.assertTrue(np.all(np.isfinite(values)))
            self.assertTrue(np.all((values >= 0) & (values <= 1)))

    def test_invalid_aperture_geometry(self):
        for d in (40e-6, 50e-6):
            with self.assertRaises(ModelError):
                validate(replace(self.p, slit_width=50e-6, separation=d))

    def test_invalid_numbers_and_ranges(self):
        for field in ('wavelength', 'slit_width', 'separation', 'distance'):
            for value in (float('nan'), float('inf'), -1, 0):
                with self.subTest(field=field, value=value), self.assertRaises(ModelError):
                    validate(replace(self.p, **{field: value}))
        for x in ([np.nan], [np.inf], [.051]):
            with self.assertRaises(ModelError):
                intensity(x, self.p)
        with self.assertRaises(ModelError):
            validate(replace(self.p, mode='unsupported'))

    def test_far_field_gate_uses_full_double_aperture(self):
        self.assertAlmostEqual(self.p.fresnel_number, .014727272727272727)
        invalid = replace(self.p, wavelength=380e-9, slit_width=80e-6,
                          separation=250e-6, distance=.5)
        self.assertAlmostEqual(invalid.fresnel_number, .14328947368421052)
        with self.assertRaises(ModelError):
            intensity([0], invalid)
        # Same narrow slit alone passes: the double slit extent matters.
        validate(replace(invalid, mode=Mode.SINGLE))

    def test_range_edges_and_fresnel_boundary(self):
        for lam in (380e-9, 750e-9):
            for a in (10e-6, 80e-6):
                validate(Parameters(Mode.SINGLE, lam, a, 40e-6, .5))
        boundary = replace(self.p, distance=(90e-6)**2 / (550e-9 * .05))
        # Boundary distance is below allowed 0.5 m; use wider aperture.
        boundary = replace(boundary, separation=250e-6, slit_width=50e-6,
                           distance=(150e-6)**2 / (550e-9 * .05))
        validate(replace(boundary, distance=boundary.distance * (1+1e-10)))
        with self.assertRaises(ModelError):
            validate(replace(boundary, distance=boundary.distance * (1-1e-10)))


class SamplingTests(unittest.TestCase):
    def test_rendered_polyline_has_subpixel_error_bound(self):
        data = prepare_display(Parameters(), 1000)
        x = (data.x + .04) / .08 * 1000
        for values in (data.intensity, data.envelope):
            y = 400 * values
            indices = curve_vertex_indices(x, y, .15)
            error = np.abs(np.interp(x, x[indices], y[indices]) - y)
            self.assertLessEqual(float(error.max()), .150000001)
            self.assertLess(len(indices), len(x) // 2)

    def test_insufficient_display_sampling_is_blocked(self):
        with self.assertRaisesRegex(ModelError, '采样不足'):
            prepare_display(Parameters(), 50)

    def test_adequate_sampling_matches_independent_pixel_integral(self):
        p = Parameters()
        data = prepare_display(p, 1000)
        self.assertAlmostEqual(data.pixels_per_period, 38.19444444444444)
        self.assertEqual(data.intensity[len(data.x)//2], 1)
        # Independent midpoint aperture formula using elementary sine,
        # evaluated at 20000 positions within selected screen pixels.
        for j in (499, 515, 730):
            x = -.04 + (j + (np.arange(20000)+.5)/20000) * .00008
            beta = np.pi * 30e-6 * x / 550e-9
            alpha = np.pi * 150e-6 * x / 550e-9
            reference = ((np.sin(beta)/beta)**2 * np.cos(alpha)**2).mean()
            self.assertAlmostEqual(data.pixel_mean[j], reference, delta=3e-6)

    def test_paraxial_view_limit_and_budget(self):
        p = replace(Parameters(), distance=.5)
        data = prepare_display(p, 1200)
        self.assertEqual(data.span, .025)
        for width in (0, -3, 32769):
            with self.assertRaises(ModelError):
                prepare_display(p, width)

    def test_display_sampling_symmetry(self):
        data = prepare_display(Parameters(), 1000)
        np.testing.assert_allclose(data.pixel_mean, data.pixel_mean[::-1], atol=2e-15)

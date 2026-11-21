"""Multi-disk point fields, with a separate pupil integral as the reference."""
from dataclasses import replace
from fractions import Fraction
import math
import unittest

import numpy as np
from numpy.polynomial.legendre import leggauss

from lightfringe import circular_model as single
from lightfringe import multiaperture_model as model
from lightfringe.multiaperture_model import (
    Field, Layout, MultiApertureError, MultiApertureParameters, amplitude, assess_model, intensity,
)


PAIR = MultiApertureParameters()
TRIANGLE = replace(PAIR, layout=Layout.TRIANGLE)
RECTANGLE = replace(PAIR, layout=Layout.RECTANGLE, spacing_y_m=130e-6)
DENSE = replace(RECTANGLE, wavelength_m=405e-9, diameter_m=65e-6, spacing_m=170e-6,
                spacing_y_m=125e-6, angle_deg=35.)
OBSERVATIONS = 1e-3 * np.array([(0., 0.), (1.2, -.8), (-3.4, 2.1), (4.5, -.9),
                                 (5.8, 7.1), (-8., 8.9), (9.4, -3.7), (19., -23.)])
FIELD_ATOL = 2e-12


def pupil_cases():
    """Explicit reference centres as complex pupil coordinates, independent of the presets."""
    horizontal = np.array([-75., 75.]) * 1e-6
    triangle = (150e-6 / math.sqrt(3)) * np.exp(1j * np.deg2rad([90., 210., 330.]))
    rectangle = np.array([-75.-65j, -75.+65j, 75.-65j, 75.+65j]) * 1e-6
    dense = np.array([-85.-62.5j, -85.+62.5j, 85.-62.5j, 85.+62.5j]) * 1e-6
    return ((PAIR, horizontal), (replace(PAIR, angle_deg=45.), horizontal*np.exp(1j*np.pi/4)),
            (TRIANGLE, triangle), (RECTANGLE, rectangle), (DENSE, dense*np.exp(1j*np.deg2rad(35))))


def disk_integral(p, centers, points, order=32, azimuths=160, *, fresnel=False):
    """Integrate unit transmission over the open disks without a Bessel or array formula."""
    nodes, weights = leggauss(order)
    r = (1 + nodes) / 2
    unit_circle = np.exp(2j * np.pi * np.arange(azimuths) / azimuths)
    local = p.diameter_m / 2 * r[:, None] * unit_circle
    pupil = centers[:, None, None] + local
    # Normalized integration measure per disk is 2*r*dr*dtheta/(2*pi).
    area_weights = (weights*r)[None, :, None] / (len(centers)*azimuths)
    scale = np.pi / (p.wavelength_m * p.distance_m)
    pupil_phase = scale * np.abs(pupil)**2 if fresnel else 0.
    result = []
    for x, y in points:
        phase = pupil_phase - 2*scale*(x*pupil.real + y*pupil.imag)
        result.append(np.sum(area_weights * np.exp(1j * phase)))
    return np.array(result)


class MultiAperturePhysicsTests(unittest.TestCase):
    def test_presets_have_the_declared_centroid_radius_and_distances(self):
        for p, expected in pupil_cases():
            with self.subTest(layout=p.layout, angle=p.angle_deg):
                assessment = assess_model(p)
                self.assertEqual(assessment.status, "MODEL_VALID")
                g = assessment.geometry
                actual = np.array([complex(x, y) for x, y in g.centers_m])
                self.assertLess(abs(actual.mean()), 1e-19)
                for point in expected:
                    self.assertLess(float(np.min(np.abs(actual-point))), 1e-18)
                distances = [abs(a-b) for i, a in enumerate(expected) for b in expected[:i]]
                self.assertAlmostEqual(g.minimum_spacing_m, min(distances), delta=1e-18)
                self.assertAlmostEqual(g.radius_m, np.max(abs(expected))+p.diameter_m/2, delta=1e-18)
                self.assertEqual(amplitude(p, 0., 0.), 1.+0j)
                self.assertEqual(intensity(p, 0., 0.), 1.)

    def test_one_disk_limit_and_pair_bisector_against_frozen_circular_model(self):
        root = single.J1_FIRST_ZERO
        u = np.array([0., 1e-13, 1e-7, np.nextafter(1e-3, 0), 1e-3, np.nextafter(1e-3, 1),
                      0.2, 1.2, root-1e-8, root, root+1e-8, 9., 17., 21.])
        positions = u / (np.pi * PAIR.diameter_m / (PAIR.wavelength_m*PAIR.distance_m))
        frozen = single.CircularParameters(PAIR.wavelength_m, PAIR.diameter_m, PAIR.distance_m)
        # Exercise the actual coherent kernel with one open disk. User presets still start at two.
        one = model._coherent_field(PAIR, ((0., 0.),), positions, 0., np.abs(positions))
        np.testing.assert_allclose(one, single.normalized_amplitude(u), atol=FIELD_ATOL, rtol=0)
        np.testing.assert_allclose(abs(one)**2, single.intensity(frozen, positions), atol=FIELD_ATOL, rtol=0)
        # On the perpendicular bisector both holes have exactly the same phase.
        np.testing.assert_allclose(amplitude(PAIR, 0., positions), one, atol=FIELD_ATOL, rtol=0)
        self.assertGreater(one[8].real, 0.)
        self.assertLess(one[10].real, 0.)
        self.assertLess(abs(one[9]), 1e-14)

    def test_pair_array_period_first_null_and_rotation(self):
        period = PAIR.wavelength_m * PAIR.distance_m / PAIR.spacing_m
        x = np.linspace(-1.6e-3, 3.1e-3, 23)
        frozen = single.CircularParameters(PAIR.wavelength_m, PAIR.diameter_m, PAIR.distance_m)
        for position in (x, x + period):
            envelope = single.intensity(frozen, position)
            np.testing.assert_allclose(intensity(PAIR, position)/envelope, np.cos(np.pi*x/period)**2,
                                       atol=FIELD_ATOL, rtol=0)
        self.assertLess(intensity(PAIR, period/2), 1e-28)
        x, y = OBSERVATIONS.T
        turned = (x+1j*y) * np.exp(1j*np.deg2rad(45))
        np.testing.assert_allclose(amplitude(replace(PAIR, angle_deg=45), turned.real, turned.imag),
                                   amplitude(PAIR, x, y), atol=FIELD_ATOL, rtol=0)

    def test_triangle_sixfold_intensity_and_signed_complex_field(self):
        x, y = OBSERVATIONS.T
        field = amplitude(TRIANGLE, x, y)
        rotated = (x+1j*y) * np.exp(1j*np.pi/3)
        np.testing.assert_allclose(intensity(TRIANGLE, rotated.real, rotated.imag), abs(field)**2,
                                   atol=FIELD_ATOL, rtol=0)
        np.testing.assert_allclose(amplitude(TRIANGLE, -x, -y), np.conj(field), atol=FIELD_ATOL, rtol=0)
        self.assertGreater(np.max(np.abs(field.imag)), .02)

    def test_rectangle_cosine_product_and_square_quarter_turn(self):
        x, y = OBSERVATIONS.T
        scale = RECTANGLE.wavelength_m * RECTANGLE.distance_m
        disk = single.normalized_amplitude(np.pi*RECTANGLE.diameter_m*np.hypot(x, y)/scale)
        expected = disk*np.cos(np.pi*150e-6*x/scale)*np.cos(np.pi*130e-6*y/scale)
        np.testing.assert_allclose(amplitude(RECTANGLE, x, y), expected, atol=FIELD_ATOL, rtol=0)
        square = replace(PAIR, layout=Layout.SQUARE)
        np.testing.assert_allclose(amplitude(square, x, y), amplitude(square, -y, x), atol=FIELD_ATOL, rtol=0)

    def test_direct_pupil_integration_and_refinement(self):
        for p, centers in pupil_cases():
            with self.subTest(layout=p.layout, angle=p.angle_deg):
                fine = disk_integral(p, centers, OBSERVATIONS)
                coarse = disk_integral(p, centers, OBSERVATIONS, 20, 96)
                np.testing.assert_allclose(coarse, fine, atol=FIELD_ATOL, rtol=0)
                np.testing.assert_allclose(amplitude(p, *OBSERVATIONS.T), fine, atol=FIELD_ATOL, rtol=0)

    def test_tangent_presets_and_one_ulp_overlap_before_rotation(self):
        d = PAIR.diameter_m
        for p in (replace(PAIR, angle_deg=47.), TRIANGLE, replace(PAIR, layout=Layout.SQUARE, angle_deg=33.),
                  replace(RECTANGLE, angle_deg=35., spacing_y_m=d)):
            with self.subTest(layout=p.layout):
                tangent = replace(p, spacing_m=d)
                self.assertEqual(assess_model(tangent).geometry.minimum_spacing_m, d)
                self.assertTrue(assess_model(tangent).valid)
                self.assertFalse(assess_model(replace(tangent, spacing_m=math.nextafter(d, 0))).valid)
        self.assertFalse(assess_model(replace(RECTANGLE, spacing_y_m=math.nextafter(d, 0))).valid)

    def test_whole_array_far_field_boundary_and_next_float(self):
        distant = replace(PAIR, spacing_m=500e-6)
        self.assertLess((distant.diameter_m/2)**2 / (distant.wavelength_m*distant.distance_m), .05)
        assessment = assess_model(distant)
        self.assertEqual(assessment.status, "MODEL_INVALID")
        self.assertGreater(assessment.fresnel_number, .15)
        with self.assertRaises(MultiApertureError):
            intensity(distant, 0., 0.)
        # Binary-exact input lengths give F = 1/20 at z = 2.
        radius = 2.**-12
        edge = replace(PAIR, diameter_m=radius/2, spacing_m=1.5*radius,
                       wavelength_m=10*radius**2, distance_m=2.)
        self.assertTrue(assess_model(edge).valid)
        self.assertEqual(assess_model(edge).fresnel_number, model.MAX_ARRAY_FRESNEL)
        self.assertFalse(assess_model(replace(edge, distance_m=math.nextafter(2., 0.))).valid)

    def test_paraxial_field_and_point_boundaries(self):
        # The binary64 value written .05 is strictly above 1/20 at z=1.
        self.assertTrue(np.isfinite(intensity(PAIR, math.nextafter(.05, 0.), 0.)))
        with self.assertRaises(MultiApertureError):
            intensity(PAIR, .05, 0.)
        with self.assertRaises(MultiApertureError):
            intensity(PAIR, math.nextafter(.05, 1.), 0.)
        self.assertFalse(assess_model(PAIR, Field(.04, .04)).valid)
        self.assertFalse(assess_model(PAIR, Field(0., .02)).valid)
        self.assertFalse(assess_model(PAIR, Field(float("nan"), .02)).valid)
        for z in (.5, 1., 1.131370849898476, 3.):
            p = replace(PAIR, distance_m=z)
            field = assess_model(p).field
            self.assertLessEqual(math.hypot(field.half_x_m, field.half_y_m), .05*z)
            self.assertTrue(np.isfinite(intensity(p, field.half_x_m, field.half_y_m)))

    def test_radius_rounded_to_limit_cannot_admit_an_external_corner(self):
        self.assertEqual(math.hypot(.05, 1e-12), .05)
        self.assertFalse(assess_model(PAIR, Field(.05, 1e-12)).valid)
        with self.assertRaises(MultiApertureError):
            intensity(PAIR, np.array([[0., .05]]), np.array([[0.], [1e-12]]))

    def test_exact_whole_array_limit_with_adjacent_diameters(self):
        unit = 2.**-15
        # The quadrilateral uses a 3:4:5 centre rectangle, independent of its rotation.
        rectangle = replace(RECTANGLE, diameter_m=2*unit, spacing_m=3*unit, spacing_y_m=4*unit,
                            wavelength_m=490*unit**2, distance_m=.5, angle_deg=37.)
        audit = replace(PAIR, wavelength_m=2.**-21, distance_m=2.5,
                        diameter_m=2.**-13, spacing_m=3*2.**-13)
        for p, centre_diameter in ((audit, audit.spacing_m), (rectangle, 5*unit)):
            for d in (math.nextafter(p.diameter_m, 0.), p.diameter_m, math.nextafter(p.diameter_m, 1.)):
                with self.subTest(layout=p.layout, d=d.hex()):
                    excess = 5*(Fraction(d) + Fraction(centre_diameter))**2 - Fraction(p.wavelength_m)*Fraction(p.distance_m)
                    self.assertEqual(excess == 0, d == p.diameter_m)
                    trial = replace(p, diameter_m=d)
                    self.assertEqual(assess_model(trial).valid, excess <= 0)
                    if excess <= 0:
                        self.assertEqual(intensity(trial, 0., 0.), 1.)
                    else:
                        with self.assertRaises(MultiApertureError):
                            intensity(trial, 0., 0.)

    def test_default_square_at_three_quarters_is_maximally_inward(self):
        p = replace(PAIR, distance_m=.75)
        half = assess_model(p).field.half_x_m
        old_outer = .026516504294495535
        self.assertEqual(math.nextafter(half, math.inf), old_outer)
        for value, valid in ((half, True), (old_outer, False)):
            self.assertEqual(800*Fraction(value)**2 <= Fraction(p.distance_m)**2, valid)
            self.assertEqual(assess_model(p, Field(value, value)).valid, valid)
        self.assertTrue(np.isfinite(intensity(p, half, half)))
        with self.assertRaises(MultiApertureError):
            intensity(p, old_outer, old_outer)

    def test_explicit_paraxial_rectangle_and_broadcast_points_share_exact_gate(self):
        p = replace(PAIR, distance_m=3.)
        for x, y in ((.12000000000000001, .09000000000000001), (.15000000000000002, 0.)):
            self.assertGreater(400*(Fraction(x)**2 + Fraction(y)**2), Fraction(p.distance_m)**2)
            if y:
                self.assertFalse(assess_model(p, Field(x, y)).valid)
            with self.assertRaises(MultiApertureError):
                amplitude(p, x, y)
        p = replace(PAIR, distance_m=25/16)
        x, y = 3/64, 4/64
        self.assertEqual(400*(Fraction(x)**2 + Fraction(y)**2), Fraction(p.distance_m)**2)
        for xx, allowed in ((math.nextafter(x, 0.), True), (x, True), (math.nextafter(x, 1.), False)):
            self.assertEqual(assess_model(p, Field(xx, y)).valid, allowed)
            if allowed:
                self.assertTrue(np.isfinite(amplitude(p, xx, y)))
            else:
                with self.assertRaises(MultiApertureError):
                    amplitude(p, [0., xx], [y, y])
        # The bounding box exceeds the disk, while both actual points are on it.
        radius = 5/64
        self.assertTrue(np.isfinite(amplitude(p, [radius, 0.], [0., radius])).all())

    def test_invalid_inputs_and_coordinates_fail_closed(self):
        for changes in (dict(layout="single"), dict(layout=6), dict(wavelength_m=math.nextafter(380e-9, 0.)),
                        dict(wavelength_m=751e-9), dict(diameter_m=19e-6), dict(distance_m=3.001),
                        dict(spacing_m=0.), dict(spacing_m=True), dict(diameter_m="80"),
                        dict(angle_deg=np.inf), dict(spacing_m=float("nan")), dict(spacing_m=10**400),
                        dict(spacing_y_m=120e-6), dict(layout=Layout.RECTANGLE),
                        dict(layout=Layout.TRIANGLE, angle_deg=30.)):
            with self.subTest(changes=changes):
                self.assertFalse(assess_model(replace(PAIR, **changes)).valid)
        for x, y in ((True, 0), (0, np.nan), ([1j], 0.), ([.01, .02], [.01, .02, .03])):
            with self.subTest(x=x, y=y), self.assertRaises(MultiApertureError):
                amplitude(PAIR, x, y)

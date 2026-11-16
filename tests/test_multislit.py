"""Independent finite complex sums/integrals; no production formula as oracle."""
from dataclasses import replace
import math
import unittest
from unittest.mock import patch
import numpy as np

from lightfringe.model import Parameters, Mode, ModelError, intensity as old_intensity
from lightfringe.sampling import prepare_display as old_display
from lightfringe.multislit import MultiParameters, validate, intensity, prepare_display


def independent(x, p):
    x = np.asarray(x, dtype=float)
    beta = np.pi*p.slit_width*x/(p.wavelength*p.distance)
    amp = np.ones_like(beta)
    np.divide(np.sin(beta), beta, out=amp, where=beta != 0)
    centers = np.arange(p.slit_count) - (p.slit_count-1)/2
    phase = -2j*np.pi*p.separation*x[..., None]*centers/(p.wavelength*p.distance)
    return amp**2*np.abs(np.exp(phase).mean(axis=-1))**2


class MultislitPhysicsTests(unittest.TestCase):
    def test_all_six_counts_independent_dense_complex_sum(self):
        for n in range(3,9):
            p = MultiParameters(slit_count=n)
            x = np.linspace(-.04,.04,16001)
            y = intensity(x,p)
            np.testing.assert_allclose(y,independent(x,p),atol=8e-14,rtol=0)
            self.assertTrue(np.all(np.isfinite(y)))
            self.assertGreaterEqual(float(y.min()),0)
            self.assertLessEqual(float(y.max()),1)
            np.testing.assert_allclose(y,y[::-1],atol=2e-14)

    def test_singular_limits_center_and_representable_neighbours(self):
        for n in range(3,9):
            p = MultiParameters(slit_count=n)
            delta = p.wavelength*p.distance/p.separation
            x = np.arange(-5,6)*delta
            x = np.r_[x,np.nextafter(x,np.inf),np.nextafter(x,-np.inf),-1e-300,0,1e-300]
            with np.errstate(all='raise',under='ignore'):
                actual = intensity(x,p)
            np.testing.assert_allclose(actual,independent(x,p),atol=8e-14,rtol=0)
            self.assertEqual(float(intensity(0,p)),1)

    def test_principal_factors_envelope_and_internal_zeros(self):
        for n in range(3,9):
            p = MultiParameters(slit_count=n)
            delta = p.wavelength*p.distance/p.separation
            # At first interference principal: envelope = 27/(4*pi^2).
            self.assertAlmostEqual(float(intensity(delta,p)),27/(4*math.pi**2),places=14)
            zeros = np.arange(1,n)*delta/n
            self.assertTrue(np.all(intensity(zeros,p)<1e-27))
            # Every inner lobe exists between consecutive array zeros; its
            # full envelope-modulated peak is checked against a complex sum.
            for j in range(1,n-1):
                x = np.linspace(j*delta/n,(j+1)*delta/n,301)
                y = intensity(x,p);ref=independent(x,p)
                self.assertGreater(float(y.max()),1e-5)
                self.assertEqual(int(y.argmax()),int(ref.argmax()))
                np.testing.assert_allclose(y,ref,atol=4e-15)

    def test_missing_orders_integer_and_rational_geometry(self):
        for n in range(3,9):
            p = MultiParameters(n)
            delta = p.wavelength*p.distance/p.separation
            self.assertLess(float(intensity(3*delta,p)),1e-27)
            self.assertGreater(float(intensity(2*delta,p)),.17)
            # d/a=5/2; the first missing principal is m=5, within API's
            # paraxial field, even though it is outside this GUI's 40mm view.
            p = MultiParameters(n,380e-9,20e-6,50e-6,2.)
            delta = p.wavelength*p.distance/p.separation
            self.assertLess(float(intensity(5*delta,p)),1e-27)
            self.assertGreater(float(intensity(4*delta,p)),.03)

    def test_full_open_aperture_quadrature_for_every_count(self):
        nodes,weights=np.polynomial.legendre.leggauss(96)
        for n in range(3,9):
            p = MultiParameters(n)
            x=np.linspace(-.04,.04,61)
            centers=(np.arange(n)-(n-1)/2)*p.separation
            opening=centers[:,None]+nodes[None,:]*p.slit_width/2
            amplitude=(np.exp(-2j*np.pi*x[:,None,None]*opening/(p.wavelength*p.distance))*weights).sum(axis=-1).mean(axis=-1)/2
            np.testing.assert_allclose(intensity(x,p),np.abs(amplitude)**2,atol=2e-14,rtol=0)

    def test_N6_N7_tabulated_values(self):
        # t=1/4: factor N6=1/18, N7=1/49, envelope sinc(pi/12)^2.
        env=(12*math.sin(math.pi/12)/math.pi)**2
        for n,factor in ((6,1/18),(7,1/49)):
            p=MultiParameters(n)
            x=p.wavelength*p.distance/p.separation/4
            self.assertAlmostEqual(float(intensity(x,p)),env*factor,places=14)

    def test_N_and_nonfinite_invalid_inputs(self):
        for n in (1,2,0,9,20,True,3.,float('nan')):
            with self.assertRaises(ModelError):validate(MultiParameters(n))
        for field in ('wavelength','slit_width','separation','distance'):
            for value in (0,-1,float('nan'),float('inf')):
                with self.assertRaises(ModelError):validate(replace(MultiParameters(),**{field:value}))
        for x in (float('nan'),float('inf'),.101):
            with self.assertRaises(ModelError):intensity(x,MultiParameters())

    def test_far_field_uses_N_and_geometry_does_not_overlap(self):
        for n in range(3,9):
            with self.assertRaisesRegex(ModelError,'远场'):
                validate(MultiParameters(n,550e-9,30e-6,150e-6,.5))
        for d in (40e-6,50e-6):
            with self.assertRaises(ModelError):validate(MultiParameters(3,550e-9,50e-6,d,2))
        p=MultiParameters(8)
        self.assertAlmostEqual(p.aperture_extent,440e-6)
        self.assertAlmostEqual(p.fresnel_number,.044)

    def test_local_peak_sampling_and_pixel_mean(self):
        nodes,weights=np.polynomial.legendre.leggauss(32)
        for n in range(3,9):
            p=MultiParameters(n);span=.04
            period=p.wavelength*p.distance/p.aperture_extent
            width=math.ceil(12*.08/period)+2
            d=prepare_display(p,width)
            dense=np.linspace(-span,span,width*64+1)
            error=np.abs(np.interp(dense,d.x,d.intensity)-independent(dense,p)).max()
            self.assertLess(error,.002)
            # Independent complex-sum pixel integration, selected central and side pixels.
            j=np.array([width//2,width//2+4,width//3])
            dx=.08/width;centers=-span+(j+.5)*dx
            x=centers[:,None]+nodes*dx/2
            ref=(independent(x,p)*weights).sum(axis=1)/2
            np.testing.assert_allclose(d.pixel_mean[j],ref,atol=5e-5)
            with self.assertRaisesRegex(ModelError,'采样不足'):prepare_display(p,50)

    def test_legacy_dispatch_is_bitwise_unchanged(self):
        for mode in (Mode.SINGLE,Mode.DOUBLE):
            p=Parameters(mode=mode)
            old=old_display(p,1000)
            with patch('lightfringe.multislit.intensity',side_effect=AssertionError('legacy rerouted')):
                new=prepare_display(p,1000)
            for name in ('x','intensity','envelope','pixel_mean'):
                np.testing.assert_array_equal(getattr(old,name),getattr(new,name))

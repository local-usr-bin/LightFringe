import unittest
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from lightfringe.gui import MainWindow
from lightfringe.model import Parameters


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        QTest.qWait(40)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_defaults_and_mode_switch(self):
        w = self.window
        self.assertEqual(w.parameters(), Parameters())
        self.assertIsNotNone(w.view.data)
        double = w.view.data.intensity.copy()
        w.mode.setCurrentIndex(0)
        self.app.processEvents()
        self.assertFalse(w.separation.isEnabled())
        self.assertTrue(np.all(w.view.data.intensity >= double-1e-15))

    def test_slider_keyboard_updates_both_views(self):
        w = self.window
        before = w.view.revision
        old_curve = w.view.data.intensity.copy()
        old_screen = w.view.data.pixel_mean.copy()
        w.wavelength.slider.setFocus()
        QTest.keyClick(w.wavelength.slider, Qt.Key.Key_Right)
        self.app.processEvents()
        self.assertEqual(w.wavelength.value(), 551)
        self.assertGreater(w.view.revision, before)
        self.assertFalse(np.array_equal(old_curve, w.view.data.intensity))
        self.assertFalse(np.array_equal(old_screen, w.view.data.pixel_mean))

    def test_geometry_constraints_and_single_to_double(self):
        w = self.window
        w.separation.spin.setValue(40)
        w.width_control.spin.setValue(80)
        self.assertEqual(w.width_control.value(), 35)
        self.assertGreater(w.parameters().separation, w.parameters().slit_width)
        w.mode.setCurrentIndex(0)
        w.width_control.spin.setValue(80)
        w.mode.setCurrentIndex(1)
        self.assertEqual(w.separation.value(), 85)
        self.assertIn('已增大', w.geometry_note.text())

    def test_far_field_failure_clears_previous_prediction_and_reset(self):
        w = self.window
        w.separation.spin.setValue(250)
        w.width_control.spin.setValue(80)
        w.wavelength.spin.setValue(380)
        w.distance.spin.setValue(.5)
        self.assertIsNone(w.view.data)
        self.assertIsNone(w.view._image)
        self.assertIn('远场', w.view.error)
        QTest.mouseClick(w.reset, Qt.MouseButton.LeftButton)
        self.assertEqual(w.parameters(), Parameters())
        self.assertIsNotNone(w.view.data)

    def test_sampling_failure_and_resize_recovery(self):
        # A small physical view must not show stale/aliased predictions.
        view = self.window.view
        view.setParent(None)
        view.setMinimumSize(1, 1)
        view.resize(150, 420)
        view.show()
        self.app.processEvents()
        self.assertIsNone(view.data)
        self.assertIn('采样不足', view.error)
        view.resize(1100, 600)
        self.app.processEvents()
        self.assertIsNotNone(view.data)
        view.close()

    def test_endpoint_units_and_spin_slider_sync(self):
        w = self.window
        w.width_control.spin.setValue(10)
        w.wavelength.spin.setValue(380)
        w.distance.spin.setValue(3)
        self.assertEqual(w.width_control.slider.value(), 10)
        self.assertEqual(w.wavelength.slider.value(), 380)
        self.assertIsNotNone(w.view.data)

import unittest
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QTextBrowser
from lightfringe import __version__
from lightfringe.gui import MainWindow
from lightfringe.model import Mode, Parameters


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
        self.assertEqual(w.mode.currentText(), '单缝衍射')
        self.assertEqual(w.parameters(), Parameters(mode=Mode.SINGLE))
        self.assertEqual(w.view.params, w.parameters())
        self.assertEqual(w.apparatus.slit_count, 1)
        self.assertFalse(w.separation.isEnabled())
        self.assertIn('单缝模式', w.geometry_note.text())
        self.assertIn('远场准则通过', w.status.text())
        self.assertIsNotNone(w.view.data)
        self.assertIsNotNone(w.view._image)
        single = w.view.data.intensity.copy()
        w.mode.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(w.parameters(), Parameters())
        self.assertTrue(w.separation.isEnabled())
        self.assertTrue(np.all(single >= w.view.data.intensity - 1e-15))

    def test_about_dialog_uses_current_version_and_closes_at_small_size(self):
        QTest.mouseClick(self.window.about_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        dialog = self.app.activeModalWidget()
        self.assertIsInstance(dialog, QDialog)
        try:
            self.assertEqual(dialog.windowTitle(), '关于光纹')
            body = dialog.findChild(QTextBrowser).toPlainText()
            for phrase in (__version__, '单缝衍射', '艾里斑', '安全关键决策', 'MIT', 'THIRD-PARTY-NOTICES.md'):
                self.assertIn(phrase, body)
            dialog.resize(360, 260)
            self.app.processEvents()
            buttons = dialog.findChild(QDialogButtonBox)
            close = buttons.button(QDialogButtonBox.StandardButton.Close)
            self.assertTrue(dialog.rect().contains(buttons.geometry()))
            self.assertTrue(close.isVisible())
            QTest.mouseClick(close, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertIsNone(self.app.activeModalWidget())
        finally:
            if self.app.activeModalWidget() is dialog:
                dialog.reject()

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
        w.mode.setCurrentIndex(1)
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
        w.mode.setCurrentIndex(1)
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
        self.window.mode.setCurrentIndex(1)
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

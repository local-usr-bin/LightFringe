"""Fifth-mode integration at the application's real window and data entry points."""
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QThread, QTimer, Qt
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lightfringe.__main__ import AiryPdfMainWindow
from lightfringe.multiaperture_model import Layout
from lightfringe import multiaperture_sampling as science
from lightfringe.multiaperture_view import DEFAULT_PARAMS, plot_geometry
from lightfringe.report import ReportError


def wait_for(predicate, timeout_ms=8000):
    if predicate():
        return
    loop = QEventLoop()
    poll, deadline = QTimer(), QTimer()
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start(8)
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()
    if not predicate():
        raise AssertionError('Timed out waiting for the requested Qt state')


def grab_rgb(window):
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(),image.bytesPerLine())
    return pixels[:, :image.width()*4].reshape(image.height(),image.width(),4)[:,:,:3].copy()


def pupil_marks(view):
    """Record what the pupil painter receives, keeping the two caption rows separate from the axes."""
    geometry = view.geometry_data()
    painter = Mock()
    painter.font.return_value = view.font()
    painter.fontMetrics.return_value = view.fontMetrics()
    view._draw_pupil(painter, geometry)
    bottom = geometry.pupil.bottom()
    lines = [call.args for call in painter.drawLine.call_args_list if call.args[0].y() > bottom]
    labels = {call.args[2]: call.args[0] for call in painter.drawText.call_args_list
              if len(call.args) == 3 and call.args[0].top() > bottom}
    return lines, labels, [call.args for call in painter.drawEllipse.call_args_list]


class MultiApertureGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setFont(QFont('Microsoft YaHei UI', 10))

    def setUp(self):
        self.w = AiryPdfMainWindow()
        self.addCleanup(self.close_window)
        self.w.resize(1220, 820)
        self.w.show()
        self.app.processEvents()

    def close_window(self):
        self.w.close()
        self.app.processEvents()
        self.assertFalse(self.w.airy_view._thread.isRunning())
        if self.w.array_view is not None:
            self.assertFalse(self.w.array_view._thread.isRunning())

    def enter(self):
        self.w.mode.setCurrentIndex(4)
        self.presented()
        return self.w.array_controls, self.w.array_view

    def presented(self):
        v = self.w.array_view
        wait_for(lambda: v.result is not None and v._presented_revision == v.revision)
        self.assertEqual(v.result.request.params, self.w.parameters())
        self.assertEqual(v.result.request.key, v.desired_key())

    def test_default_entry_native_area_means_and_horizontal_point_profile(self):
        self.assertEqual(self.w.mode.currentText(), '单缝衍射')
        self.assertEqual(self.w.mode.count(), 5)
        _, v = self.enter()
        self.assertEqual(self.w.mode.currentText(), '多圆孔干涉与衍射')
        self.assertEqual(self.w.parameters(), DEFAULT_PARAMS)
        self.assertEqual(v.state, 'DISPLAY_VALID')
        self.assertEqual(v.decision.status, 'GUI_SAMPLE_VALID')
        g = v.geometry_data()
        self.assertEqual(v.result.screen.sampling.counts_xy, (g.side,g.side))
        self.assertEqual(v.result.profile.sampling.points, g.curve_pixels)
        self.assertEqual(v.result.profile.sampling.direction_xy, (1.,0.))
        ref = science.prepare_profile(DEFAULT_PARAMS, g.curve_pixels, field=v.decision.model.field)
        np.testing.assert_array_equal(v.result.profile.position_m, ref.position_m)
        np.testing.assert_array_equal(v.result.profile.point_intensity, ref.point_intensity)
        origin = v.mapTo(self.w, QPoint())
        x = round((origin.x()+g.screen.x())*g.dpr)
        y = round((origin.y()+g.screen.y())*g.dpr)
        expected = np.rint(255*np.sqrt(v.result.screen.pixel_mean[::-1])).astype(np.uint8)
        pixels = grab_rgb(self.w)[y:y+g.side,x:x+g.side]
        np.testing.assert_array_equal(pixels, np.repeat(expected[:,:,None],3,axis=2))
        self.assertGreater(pixels.max(), pixels.min())

    def test_layout_specific_controls_and_rotation_follow_c1(self):
        c, v = self.enter()
        horizontal = v.result.screen.pixel_mean.copy()
        c.angle.spin.setValue(90)
        self.presented()
        np.testing.assert_allclose(v.result.screen.pixel_mean, horizontal.T, rtol=0, atol=3e-15)
        for idx, kind, count in ((1,Layout.TRIANGLE,3),(2,Layout.SQUARE,4),(3,Layout.RECTANGLE,4)):
            c.preset.setCurrentIndex(idx)
            self.presented()
            p = self.w.parameters()
            self.assertEqual(p.layout, kind)
            self.assertEqual(p.angle_deg, 0 if kind == Layout.TRIANGLE else 90)
            self.assertEqual(c.angle.isVisible(), kind != Layout.TRIANGLE)
            self.assertEqual(c.spacing_y.isVisible(), kind == Layout.RECTANGLE)
            centers = np.array(v.decision.model.geometry.centers_m)
            self.assertEqual(len(centers),count)
            if kind == Layout.TRIANGLE:
                for i in range(3):
                    self.assertAlmostEqual(np.linalg.norm(centers[i]-centers[i-1]), p.spacing_m)
            if kind == Layout.RECTANGLE:
                c.spacing_y.spin.setValue(85)
                self.presented()
                self.assertEqual(self.w.parameters().spacing_y_m,85/1e6)
            else:
                self.assertIsNone(p.spacing_y_m)
        c.preset.setCurrentIndex(0)
        self.presented()
        self.assertIsNone(self.w.parameters().spacing_y_m)
        self.assertEqual(self.w.parameters().angle_deg,90)
        self.w.reset.click()
        self.presented()
        self.assertEqual(self.w.parameters(), DEFAULT_PARAMS)

    def test_invalid_overlap_and_far_field_clear_both_and_recover(self):
        c, v = self.enter()
        for spacing, why in ((50,'重叠'),(700,'远场')):
            c.spacing.spin.setValue(spacing)
            self.assertEqual(c.spacing.value(),spacing)
            self.assertEqual(self.w.parameters().diameter_m,60e-6)
            self.assertEqual(v.state,'MODEL_INVALID')
            self.assertIn(why,self.w.status.text())
            self.assertIsNone(v._image)
            self.assertIsNone(v._polygon)
            self.assertIsNone(v.result)
            self.assertIsNone(v.decision.grid)
            c.spacing.spin.setValue(100)
            self.presented()
            self.assertEqual(v.state,'DISPLAY_VALID')
        c.preset.setCurrentIndex(3)
        c.spacing_y.spin.setValue(50)
        self.assertIn('重叠',v.reason)
        self.assertEqual(c.spacing_y.value(),50)

    def test_independent_screen_and_profile_at_small_window(self):
        if self.w.devicePixelRatioF() != 1:
            self.skipTest('Specific 980×660 physical budgets are exercised at DPR 1')
        c, v = self.enter()
        self.w.resize(980,660)
        self.presented()
        self.assertEqual(v.state,'DISPLAY_VALID')
        c.spacing.spin.setValue(105)
        self.presented()
        self.assertTrue(v.decision.grid.valid)
        self.assertFalse(v.decision.profile.valid)
        self.assertIn('截面采样不足',v.reason)
        self.assertIsNotNone(v._image)
        self.assertIsNone(v._polygon)
        c.spacing.spin.setValue(150)
        self.assertEqual(v.state,'DISPLAY_UNDERSAMPLED')
        self.assertIsNone(v.result)
        c.angle.spin.setValue(90)
        self.presented()
        self.assertEqual(v.state,'DISPLAY_PARTIAL')
        self.assertFalse(v.decision.grid.valid)
        self.assertTrue(v.decision.profile.valid)
        self.assertIn('二维采样不足',v.reason)
        self.assertIsNone(v._image)
        self.assertIsNotNone(v._polygon)
        self.assertEqual(science.assess_pdf(self.w.parameters()).status,'PDF_SAMPLE_VALID')
        self.assertFalse(self.w.export_button.isEnabled())
        self.w.resize(1220,820)
        self.presented()
        self.assertEqual(v.state,'DISPLAY_VALID')

    def test_numeric_edit_invalidates_until_confirmed(self):
        c, v = self.enter()
        spin = c.wavelength.spin
        spin.setFocus()
        spin.selectAll()
        QTest.keyClicks(spin, '560')
        self.assertEqual(v.state,'INPUT_PENDING')
        self.assertIsNone(v.result)
        self.assertIsNone(v._image)
        QTest.keyClick(spin,Qt.Key.Key_Return)
        self.presented()
        self.assertEqual(v.params.wavelength_m,560e-9)
        self.assertEqual(c.wavelength.slider.value(),560)

    def test_latest_request_only_and_mode_switch_suppresses_old_paint(self):
        c, v = self.enter()
        start, release = threading.Event(), threading.Event()
        main_thread = self.w.thread()
        actual = science.prepare_screen
        calls, painted = [], []
        def slow(p,*args,**kw):
            calls.append((p,QThread.currentThread() == main_thread))
            start.set()
            if not release.wait(5):
                raise RuntimeError('test worker timeout')
            return actual(p,*args,**kw)
        v.presented.connect(lambda revision,ms: painted.append((revision,QThread.currentThread()==main_thread)))
        with patch('lightfringe.multiaperture_view.prepare_screen',side_effect=slow):
            try:
                c.wavelength.spin.setValue(551)
                wait_for(start.is_set)
                for wl in range(552,566):
                    c.wavelength.spin.setValue(wl)
                self.assertIsNone(v.result)
                self.assertEqual(v._pending.params.wavelength_m,565e-9)
                self.assertEqual(len(calls),1)
                release.set()
                self.presented()
                self.assertEqual([p.wavelength_m for p,_ in calls],[551e-9,565e-9])
                self.assertTrue(all(not is_gui for _,is_gui in calls))
                self.assertEqual(painted,[(v.revision,True)])
                start.clear()
                release.clear()
                c.wavelength.spin.setValue(566)
                wait_for(start.is_set)
                self.w.mode.setCurrentIndex(3)
                release.set()
                wait_for(lambda: not v._busy)
                self.assertEqual(v.state,'INACTIVE')
                self.assertIsNone(v.result)
                self.assertEqual(len(painted),1)
                self.assertGreaterEqual(v.discarded,2)
                self.w.mode.setCurrentIndex(4)
                self.presented()
                self.assertEqual(v.params.wavelength_m,566e-9)
            finally:
                release.set()

    def test_close_while_worker_is_computing(self):
        c, v = self.enter()
        started, release = threading.Event(), threading.Event()
        def held(*args,**kw):
            started.set()
            release.wait(3)
            return science.prepare_screen(*args,**kw)
        with patch('lightfringe.multiaperture_view.prepare_screen',side_effect=held):
            try:
                c.spacing.spin.setValue(101)
                wait_for(started.is_set)
                timer = threading.Timer(.04,release.set)
                timer.start()
                self.w.close()
                timer.join()
                self.app.processEvents()
                self.assertTrue(v.closed)
                self.assertIsNone(v.result)
                self.assertFalse(v._thread.isRunning() or self.w.airy_view._thread.isRunning())
            finally:
                release.set()

    def test_pdf_guard_and_return_to_each_legacy_mode(self):
        self.enter()
        self.assertFalse(self.w.export_button.isEnabled() or self.w._report_is_current())
        with self.assertRaisesRegex(ReportError,'多圆孔'):
            self.w.report_snapshot()
        with patch.object(self.w,'_choose_report_path') as slit, patch.object(self.w,'_choose_circular_path') as disk:
            self.w.export_report()
            slit.assert_not_called()
            disk.assert_not_called()
            for index in range(4):
                self.w.mode.setCurrentIndex(index)
                wait_for(lambda: self.w.export_button.isEnabled())
                if index==3:
                    wait_for(lambda: self.w.airy_view.result is not None)
                else:
                    self.assertEqual(self.w.view.params,self.w.parameters())
                target = disk if index==3 else slit
                target.return_value=None
                self.w.export_button.click()
                self.assertTrue(target.called)
                target.reset_mock()
                self.assertEqual(self.w.export_button.text(),'导出 PDF 报告')

    def test_fractional_pixel_geometry_and_native_viewport_cap(self):
        for factor in (1.,1.25,1.5,2.):
            origin = QPoint(347,71)
            g = plot_geometry(1050,750,factor,origin)
            self.assertAlmostEqual(g.side, g.screen.width()*factor)
            for pos,off in ((g.screen.x(),origin.x()),(g.screen.y(),origin.y())):
                self.assertAlmostEqual((pos+off)*factor,round((pos+off)*factor))
            self.assertAlmostEqual(g.curve.width()*factor,g.curve_pixels-1)
            self.assertLessEqual(g.side,767)

    def test_pupil_scale_uses_drawn_diameter_and_separation_for_every_layout(self):
        controls, view = self.enter()
        controls.distance.spin.setValue(1.50)
        diameters = []
        values = []
        for preset, diameter, spacing, angle in ((0,60,100,0), (0,60,220,0), (0,90,220,0),
                                                  (1,60,130,0), (2,60,105,30), (3,60,145,22)):
            with self.subTest(preset=preset, diameter=diameter, spacing=spacing, angle=angle):
                controls.preset.setCurrentIndex(preset)
                controls.diameter.spin.setValue(diameter)
                controls.spacing.spin.setValue(spacing)
                controls.spacing_y.spin.setValue(83)
                controls.angle.spin.setValue(angle)
                self.presented()
                lines, labels, circles = pupil_marks(view)
                label, rect = next((s,r) for s,r in labels.items() if s.endswith('μm · 自动缩放'))
                value = float(label.split()[0])
                self.assertRegex(label, r'^[125]0* μm · 自动缩放$')
                self.assertEqual(len(lines), 3)
                (start, end), *ticks = lines
                self.assertEqual(start.y(), end.y())
                for (top, bottom), endpoint in zip(ticks, (start, end)):
                    self.assertEqual(top.x(), endpoint.x())
                    self.assertEqual(bottom.x(), endpoint.x())
                    self.assertLess(top.y(), endpoint.y())
                    self.assertGreater(bottom.y(), endpoint.y())
                width = end.x() - start.x()
                box = view.geometry_data().pupil
                self.assertTrue(.15 < width / box.width() < .40)
                self.assertGreater(start.x(), box.left())
                self.assertLess(end.x(), rect.left())
                self.assertTrue(view.rect().contains(rect.toAlignedRect()))
                self.assertLessEqual(view.fontMetrics().tightBoundingRect(label).height(), rect.height())
                caption = next(r for s,r in labels.items() if s.startswith('孔径'))
                self.assertFalse(caption.intersects(rect))
                centers = view.decision.model.geometry.centers_m
                self.assertEqual(len(circles), len(centers))
                drawn_centers = np.array([(pt.x(),pt.y()) for pt,_,_ in circles])
                for _, rx, ry in circles:
                    self.assertEqual(rx, ry)
                    self.assertAlmostEqual(width / value, 2*rx / diameter)
                expected = (np.array(centers) - centers[0]) * [1e6,-1e6] * (width / value)
                np.testing.assert_allclose(drawn_centers-drawn_centers[0], expected, rtol=0, atol=1e-10)
                diameters.append(2*circles[0][1])
                values.append(value)
        self.assertLess(diameters[1], diameters[0])   # Same hole, wider spacing.
        self.assertGreater(diameters[2], diameters[1])  # Same spacing, larger hole.
        self.assertNotEqual(values[0], values[1])
        controls.spacing.spin.setValue(50)
        self.assertIsNone(view.decision.model.geometry)
        self.assertEqual(pupil_marks(view), ([], {}, []))

"""PDFium parsing and draw-command checks independently verify exported data."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import hashlib
from uuid import uuid4
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lightfringe.annotations import missing_order_note, missing_order_relation
from lightfringe.gui import MainWindow
from lightfringe.model import Mode, ModelError
from lightfringe import report

EVIDENCE = Path(__file__).resolve().parents[1] / 'artifacts/LF-P0-A2-R1'


def parsed(path):
    doc = QPdfDocument()
    if doc.load(str(path)) != QPdfDocument.Error.None_:
        raise AssertionError(f'PDFium cannot open {path}')
    assert doc.pageCount() == 1
    size = doc.pagePointSize(0)
    assert abs(size.width() - 842) < 2 and abs(size.height() - 595) < 2
    text = ''.join(doc.getAllText(0).text().split())
    doc.close()
    return text


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setFont(QFont('Microsoft YaHei UI', 10))

    def setUp(self):
        # Stable F-drive scratch area, never Windows Temp.
        self.folder = EVIDENCE / 'test-output' / ('report-' + uuid4().hex)
        self.folder.mkdir(parents=True)
        self.w = MainWindow()
        self.w.show()
        QTest.qWait(30)

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def test_single_nondefault_pdf_parameters_units_and_normalization(self):
        w = self.w
        w.mode.setCurrentIndex(0)
        w.wavelength.spin.setValue(632)
        w.width_control.spin.setValue(25)
        w.distance.spin.setValue(1.25)
        s = w.report_snapshot()
        path = report.write_pdf(s, self.folder/'中文单缝报告.pdf')
        text = parsed(path)
        for expected in ('《光纹》光学模拟报告', '单缝衍射', '632nm', '25μm', '1.25m',
                         '±40mm', '31.6000mm', '63.2000mm', '相对光强I/I₀',
                         'x/mm', '无量纲', 'LF-P0-A2-R1', '模型有效性检查',
                         report.SIMULATION_NOTICE, report.NORMALIZATION):
            self.assertIn(''.join(expected.split()), text)
        self.assertNotIn('双缝中心距', text)
        self.assertGreater(path.stat().st_size, 5000)

    def test_double_noninteger_rational_pdf(self):
        w = self.w
        w.width_control.spin.setValue(40)
        w.separation.spin.setValue(100)
        s = w.report_snapshot()
        text = parsed(report.write_pdf(s, self.folder/'双缝报告.pdf'))
        for expected in ('有限缝宽', '100μm', '5.5000mm', 'd/a=5/2',
                         '每第5级理论缺级', '±5级', '±27.5000mm'):
            self.assertIn(expected, text)

    def test_snapshot_is_copied_and_deeply_immutable(self):
        s = self.w.report_snapshot()
        old = s.data.intensity.copy()
        self.w.view.data.intensity[:] = 0
        np.testing.assert_array_equal(s.data.intensity, old)
        with self.assertRaises(FrozenInstanceError):
            s.revision = 0
        with self.assertRaises(FrozenInstanceError):
            s.params.distance = 2
        for name in ('x', 'intensity', 'envelope', 'pixel_mean'):
            with self.assertRaises(ValueError):
                getattr(s.data, name).setflags(write=True)

    def test_curve_and_screen_commands_use_exact_snapshot_arrays(self):
        s = self.w.report_snapshot()
        curves, images = [], []
        original_curve, original_image = QPainter.drawPolyline, QPainter.drawImage

        def curve(painter, polygon):
            curves.append(np.array([(p.x(), p.y()) for p in polygon]))
            return original_curve(painter, polygon)

        def screen(painter, rect, image):
            images.append([image.pixelColor(i, 0).red() for i in range(image.width())])
            return original_image(painter, rect, image)

        # The numerical model must never be invoked during PDF generation.
        with patch('lightfringe.model.intensity', side_effect=AssertionError('recalculation')), \
             patch('lightfringe.sampling.prepare_display', side_effect=AssertionError('resampling')), \
             patch.object(QPainter, 'drawPolyline', curve), patch.object(QPainter, 'drawImage', screen):
            report.write_pdf(s, self.folder/'data.pdf')
        self.assertEqual(len(curves), 2)
        expected_x = 286 + (s.data.x + s.data.span) / (2*s.data.span) * 476
        for actual, values in zip(curves, (s.data.envelope, s.data.intensity)):
            np.testing.assert_allclose(actual[:, 0], expected_x, atol=1e-12)
            np.testing.assert_allclose(actual[:, 1], 381 - values * 155, atol=1e-12)
        np.testing.assert_array_equal(images[0], np.rint(255*np.sqrt(s.data.pixel_mean)).astype(np.uint8))

    def test_out_of_view_zeros_are_not_invented(self):
        self.w.mode.setCurrentIndex(0)
        self.w.width_control.spin.setValue(10)
        self.w.wavelength.spin.setValue(750)
        self.w.distance.spin.setValue(3)
        s = self.w.report_snapshot()
        self.assertIn('当前范围不可确定', '\n'.join(report.result_lines(s)))
        text = parsed(report.write_pdf(s, self.folder/'视场外.pdf'))
        self.assertIn('当前范围不可确定', text)
        self.assertNotIn('225.0000mm', text)

    def test_short_distance_pdf_preserves_current_span(self):
        self.w.distance.spin.setValue(.5)
        s = self.w.report_snapshot()
        self.assertEqual(s.data.span, .025)
        text = parsed(report.write_pdf(s, self.folder/'短屏距.pdf'))
        self.assertIn('±25mm', text)
        self.assertNotIn('±40mm', text)

    def test_failure_is_atomic_for_new_and_existing_files(self):
        s = self.w.report_snapshot()
        existing = self.folder/'已有.pdf'
        existing.write_bytes(b'original report sentinel')
        new = self.folder/'新报告.pdf'
        with patch('lightfringe.report._paint_page', side_effect=RuntimeError('draw failed')):
            for path in (existing, new):
                with self.assertRaisesRegex(RuntimeError, 'draw failed'):
                    report.write_pdf(s, path)
        self.assertEqual(existing.read_bytes(), b'original report sentinel')
        self.assertFalse(new.exists())
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['已有.pdf'])

    def test_commit_failure_never_replaces_existing_file(self):
        path = self.folder/'已有.pdf'
        path.write_bytes(b'keep original')
        with patch.object(report.QSaveFile, 'commit', return_value=False):
            with self.assertRaises(OSError):
                report.write_pdf(self.w.report_snapshot(), path)
        self.assertEqual(path.read_bytes(), b'keep original')
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_write_failure_and_extension(self):
        for path in (self.folder/'missing'/'file.pdf', self.folder/'folder.pdf'):
            if path.name == 'folder.pdf':
                path.mkdir()
            with self.assertRaises(OSError):
                report.write_pdf(self.w.report_snapshot(), path)
        with self.assertRaises(report.ReportError):
            report.write_pdf(self.w.report_snapshot(), self.folder/'x.txt')

    def test_capture_rejects_invalid_geometry_far_field_and_sampling(self):
        s = self.w.report_snapshot()
        invalid = replace(s.params, slit_width=80e-6, separation=40e-6)
        with self.assertRaises(ModelError):
            report.capture_snapshot(invalid, s.data, 1, 80, 40)
        invalid = replace(s.params, slit_width=80e-6, separation=250e-6,
                          wavelength=380e-9, distance=.5)
        with self.assertRaises(ModelError):
            report.capture_snapshot(invalid, s.data, 1, 80, 250)
        with self.assertRaises(report.ReportError):
            report.capture_snapshot(s.params, replace(s.data, pixels_per_period=11.99), 1, 30, 150)
        with self.assertRaises(report.ReportError):
            report.capture_snapshot(s.params, s.data, 1, 31, 150)

    def test_low_note_uses_exact_integer_inputs(self):
        self.assertEqual(missing_order_relation(40, 100), (5, 2))
        self.assertEqual(missing_order_relation(40, 140), (7, 2))
        self.assertEqual(missing_order_relation(30, 150), (5, 1))
        self.assertEqual(missing_order_relation(79, 197), (197, 79))
        self.assertIn('每第 5 级', missing_order_note(40, 100))
        with self.assertRaises(ValueError):
            missing_order_relation(40., 100.0000000001)

    def test_nominal_outputs_and_protected_physics_sources_unchanged(self):
        from lightfringe.model import Parameters, Mode, intensity
        from lightfringe.sampling import prepare_display
        import json
        root = EVIDENCE.parents[1]
        for item in json.loads((EVIDENCE/'BEGIN_nominal_outputs.json').read_text(encoding='utf-8')):
            p = Parameters(Mode(item['mode']), *item['inputs'])
            values = intensity(np.linspace(-.04, .04, 10001), p)
            self.assertEqual(hashlib.sha256(values.tobytes()).hexdigest(), item['intensity_10001_sha256'])
            data = prepare_display(p, 1000)
            for name, digest in item['arrays'].items():
                self.assertEqual(hashlib.sha256(getattr(data, name).tobytes()).hexdigest(), digest)
        for name in ('model.py', 'sampling.py', 'rendering.py'):
            self.assertEqual((root/'lightfringe'/name).read_bytes(),
                             (EVIDENCE/'baseline/lightfringe'/name).read_bytes())

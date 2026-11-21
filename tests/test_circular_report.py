"""Verify circular PDF rendering against the fixed independent science data."""
from uuid import uuid4
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QFont, QImage, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from lightfringe import circular_report as report
from lightfringe.circular_model import CircularParameters, ModelStatus
from lightfringe.circular_sampling import DisplayStatus, assess_sampling, prepare_profile, prepare_screen
from test_report import PDF_TEST_OUTPUT


class CircularReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setFont(QFont('Microsoft YaHei UI', 10))

    def setUp(self):
        self.folder = PDF_TEST_OUTPUT / ('circle-' + uuid4().hex)
        self.folder.mkdir(parents=True)

    def test_actual_pdf_uses_fixed_science_image_and_all_profile_points(self):
        params = CircularParameters()
        snapshot = report.build_snapshot(report.capture_request(params))
        reference = prepare_screen(params, 383).data
        expected_profile = prepare_profile(params, 1533).data
        self.assertEqual(snapshot.screen.data.pixel_mean.tobytes(), reference.pixel_mean.tobytes())
        self.assertEqual(snapshot.profile.data.x.tobytes(), expected_profile.x.tobytes())
        self.assertEqual(snapshot.profile.data.intensity.tobytes(), expected_profile.intensity.tobytes())

        images, curves, audit = [], [], {}
        draw_image = QPainter.drawImage
        draw_curve = QPainter.drawPolyline

        def record_image(painter, rect, image):
            gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
            data = np.frombuffer(gray.constBits(), dtype=np.uint8)
            images.append(data.reshape(gray.height(), gray.bytesPerLine())[:, :gray.width()].copy())
            return draw_image(painter, rect, image)

        def record_curve(painter, polygon):
            curves.append(np.array([(point.x(), point.y()) for point in polygon]))
            return draw_curve(painter, polygon)

        with patch.object(report, 'prepare_screen', side_effect=AssertionError('resampled PDF image')), \
             patch.object(report, 'prepare_profile', side_effect=AssertionError('resampled PDF profile')), \
             patch.object(QPainter, 'drawImage', record_image), \
             patch.object(QPainter, 'drawPolyline', record_curve):
            path = report.write_pdf(snapshot, self.folder/'圆孔.pdf', layout_audit=audit)

        items = {item['key']: item for item in audit['ledger'] if item['kind'] == 'graphic'}
        square, plot = items['airy-image'], items['linear-profile']
        self.assertEqual(square['page'], 1)
        self.assertEqual(square['source_grid'], [383, 383])
        self.assertEqual(square['rect'][2], square['rect'][3])
        self.assertGreaterEqual(square['rect'][2], 340)
        self.assertEqual(plot['page'], 2)
        self.assertEqual(plot['point_count'], 1533)
        self.assertEqual(len(images), 1)
        np.testing.assert_array_equal(images[0], np.rint(255*np.sqrt(reference.pixel_mean[::-1])).astype(np.uint8))
        self.assertEqual(len(curves), 1)
        self.assertEqual(curves[0].shape, (1533, 2))
        left, top, width, height = plot['rect']
        x = left + (expected_profile.x + snapshot.half_span_m) / (2*snapshot.half_span_m) * width
        y = top + height - expected_profile.intensity * height
        np.testing.assert_allclose(curves[0], np.column_stack((x, y)), rtol=0, atol=1e-12)

        document = QPdfDocument()
        self.assertEqual(document.load(str(path)), QPdfDocument.Error.None_)
        try:
            self.assertEqual(document.pageCount(), audit['pages'])
            first, second = (''.join(document.getAllText(i).text().split()) for i in (0, 1))
            self.assertIn('6.708184mm', first)
            self.assertIn('二维艾里斑观察屏', first)
            self.assertIn('I(x,0)/I(0)', second)
            self.assertIn('1,533', second)
            self.assertIn('贝塞尔函数', second)
        finally:
            document.close()

    def test_independent_gate_and_above_383_rejection(self):
        params = CircularParameters.from_display_units(550, 210, 1)
        self.assertEqual(assess_sampling(params, 224).status, DisplayStatus.UNDERSAMPLED)
        request = report.capture_request(params)
        self.assertEqual(request.eligibility.status, 'PDF_READY')
        self.assertEqual(request.eligibility.sampling.required_count, 324)
        self.assertEqual(report.build_snapshot(request).screen.data.pixel_mean.shape, (383, 383))

        over_limit = CircularParameters.from_display_units(550, 270, 1)
        gate = report.assess_pdf(over_limit)
        self.assertEqual(gate.model.status, ModelStatus.VALID)
        self.assertEqual(gate.sampling.required_count, 417)
        with self.assertRaises(report.CircularReportError) as rejected:
            report.capture_request(over_limit)
        self.assertEqual(rejected.exception.status, 'PDF_SAMPLE_LIMIT')

        with self.assertRaises(report.CircularReportError) as invalid:
            report.capture_request(CircularParameters.from_display_units(380, 500, .5))
        self.assertEqual(invalid.exception.status, 'MODEL_INVALID')

    def test_write_failures_preserve_destination(self):
        snapshot = report.build_snapshot(report.capture_request(CircularParameters()))
        existing = self.folder/'已有.pdf'
        existing.write_bytes(b'preserved report')
        with patch.object(QPdfWriter, 'newPage', return_value=False):
            with self.assertRaises(OSError):
                report.write_pdf(snapshot, existing)
            with self.assertRaises(OSError):
                report.write_pdf(snapshot, self.folder/'新报告.pdf')
        with patch.object(report.QSaveFile, 'commit', return_value=False):
            with self.assertRaises(OSError):
                report.write_pdf(snapshot, existing)
        self.assertEqual(existing.read_bytes(), b'preserved report')
        self.assertEqual(list(self.folder.iterdir()), [existing])
        with self.assertRaises(report.CircularReportError):
            report.write_pdf(snapshot, self.folder/'后缀.txt')

"""Fifth-mode scientific data, page geometry and transactional publication."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from lightfringe import multiaperture_report as report
from lightfringe import multiaperture_sampling as science
from lightfringe.multiaperture_model import Field, Layout, MultiApertureParameters
from lightfringe.report import ReportError


PAIR = MultiApertureParameters(diameter_m=60e-6, spacing_m=100e-6)
TRIANGLE = replace(PAIR, layout=Layout.TRIANGLE, spacing_m=125e-6)
SQUARE = replace(PAIR, layout=Layout.SQUARE, wavelength_m=480e-9, spacing_m=135e-6, angle_deg=25)
RECTANGLE = replace(PAIR, layout=Layout.RECTANGLE, wavelength_m=405e-9, diameter_m=65e-6,
                    spacing_m=170e-6, spacing_y_m=125e-6, angle_deg=35)


class ScienceTests(unittest.TestCase):
    def test_four_presets_match_frozen_c1_arrays_and_gray(self):
        for p in (PAIR, TRIANGLE, SQUARE, RECTANGLE):
            with self.subTest(layout=p.layout):
                snap = report.build_snapshot(report.capture_request(p))
                field = snap.request.field
                decision = science.assess_pdf(p, field=field, profile_angle_deg=0)
                side = decision.selected_pdf_side
                grid = science.prepare_screen(p, side, side, field=field)
                line = science.prepare_profile(p, 1025, field=field, profile_angle_deg=0)
                for actual, expected in ((snap.screen.x_centers_m, grid.x_centers_m),
                                         (snap.screen.y_centers_m, grid.y_centers_m),
                                         (snap.screen.pixel_mean, grid.pixel_mean),
                                         (snap.profile.position_m, line.position_m),
                                         (snap.profile.point_intensity, line.point_intensity)):
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertFalse(actual.flags.writeable)
                    with self.assertRaises(ValueError):
                        actual.setflags(write=True)
                self.assertEqual(snap.plan.profile.direction_xy, (1., 0.))
                self.assertEqual(line.point_intensity[512], 1.)
                self.assertEqual(line.position_m[[0, -1]].tolist(), [-field.half_x_m, field.half_x_m])
                expected_gray = np.rint(255*np.sqrt(grid.pixel_mean))[::-1].astype(np.uint8)
                np.testing.assert_array_equal(report.display_gray(snap.screen), expected_gray)

    def test_three_minimum_tiers_and_gui_independence(self):
        for p, field, expected in ((PAIR, None, 383), (RECTANGLE, Field(.03, .03), 511),
                                   (RECTANGLE, None, 767)):
            self.assertEqual(science.assess_gui(p, 50, 50, 51, field=field).status, 'GUI_SAMPLE_INVALID')
            self.assertEqual(report.pdf_plan(p, field).selected_pdf_side, expected)

    def test_real_invalid_model_and_grid_reject_before_computation(self):
        dense = replace(PAIR, wavelength_m=380e-9, diameter_m=80e-6, spacing_m=166e-6, distance_m=.8)
        cases = ((replace(PAIR, spacing_m=40e-6), None, '重叠'),
                 (replace(PAIR, spacing_m=700e-6), None, '远场'),
                 (dense, Field(.0399, .001), '775'))
        with patch.object(report, 'prepare_screen') as screen, patch.object(report, 'prepare_profile') as line:
            for p, field, reason in cases:
                with self.assertRaisesRegex(ReportError, reason):
                    report.capture_request(p, field=field)
            screen.assert_not_called()
            line.assert_not_called()

    def test_full_decision_required_even_with_selected_767(self):
        # A real C1 oblique counterexample exercises the report's refusal branch.
        # The production request itself is always horizontal.
        p = replace(PAIR, wavelength_m=380e-9, distance_m=3., diameter_m=100e-6,
                    spacing_m=370e-6, angle_deg=45.)
        field = Field(.09, .09)
        rejected = science.assess_pdf(p, field=field, profile_angle_deg=45)
        self.assertEqual(rejected.selected_pdf_side, 767)
        uncertain = replace(rejected, profile=replace(rejected.profile, required_points=1025, _axes=None))
        for decision, message in ((rejected, '1261'), (uncertain, '可靠表示')):
            with patch.object(report, 'assess_pdf', return_value=decision) as gate:
                with self.assertRaisesRegex(ReportError, message):
                    report.capture_request(p, field=field)
                gate.assert_called_once_with(p, field=field, profile_angle_deg=0)

    def test_cancelled_snapshot_does_not_start_science(self):
        request = report.capture_request(PAIR)
        control = report.ExportControl()
        control.cancel()
        with patch.object(report, 'prepare_screen') as screen, self.assertRaises(report.ExportCancelled):
            report.build_snapshot(request, control)
        screen.assert_not_called()


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.snapshot = report.build_snapshot(report.capture_request(RECTANGLE))

    def setUp(self):
        root = os.environ.get("LIGHTFRINGE_PDF_TEST_OUTPUT")
        if root:
            folder = Path(root) / ("array-" + uuid4().hex)
            folder.mkdir(parents=True)
        else:
            temp = TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            folder = Path(temp.name)
        self.path = folder / "旋转矩形.pdf"

    def test_two_portrait_pages_content_and_geometry_for_all_layouts(self):
        long_labels = replace(RECTANGLE, wavelength_m=750e-9, distance_m=3., diameter_m=100e-6,
                              spacing_m=400e-6, spacing_y_m=181e-6, angle_deg=-179.)
        for i, p in enumerate((PAIR, TRIANGLE, SQUARE, RECTANGLE, long_labels)):
            with self.subTest(layout=p.layout):
                snap = report.build_snapshot(report.capture_request(p))
                audit = {}
                target = self.path.with_name(f"layout-{i}.pdf")
                report.write_pdf(snap, target, layout_audit=audit)
                doc = QPdfDocument()
                self.assertEqual(doc.load(str(target)), QPdfDocument.Error.None_)
                try:
                    self.assertEqual(doc.pageCount(), 2)
                    for i in range(2):
                        size = doc.pagePointSize(i)
                        self.assertAlmostEqual(size.width(), 595, delta=1)
                        self.assertAlmostEqual(size.height(), 842, delta=1)
                    pages = ["".join(doc.getAllText(i).text().split()) for i in range(2)]
                finally:
                    doc.close()
                for token in (report.LAYOUT_NAMES[p.layout], report.SOFTWARE, "λ", "μm",
                              f"{snap.plan.selected_pdf_side}×{snap.plan.selected_pdf_side}", "灰度", "mm"):
                    self.assertIn("".join(token.split()), pages[0])
                for token in ("1025", "Gauss-Legendre", "不模拟偏振效应", "I(x,y)/I(0)", "Σ",
                              "完全相干", "孔心坐标", "0.05", "物理比例尺", "第2页/共2页"):
                    self.assertIn(token, pages[1])
                elements = audit["elements"]
                graphics = {g["key"]: g for g in elements if g["kind"] == "graphic"}
                self.assertGreaterEqual(graphics["screen"]["rect"][2], 349)
                self.assertEqual(graphics["linear-profile"]["point_count"], 1025)
                sx = graphics["pupil-scale"]
                scale = sx["rect"][2] / (sx["length_um"] * 1e-6)
                for i, (cx, cy) in enumerate(snap.plan.model.geometry.centers_m):
                    r = QRectF(*graphics[f"hole-{i}"]["rect"])
                    base = QRectF(*graphics["hole-0"]["rect"])
                    x0, y0 = snap.plan.model.geometry.centers_m[0]
                    self.assertAlmostEqual(r.width(), p.diameter_m*scale)
                    self.assertAlmostEqual(r.width(), r.height())
                    self.assertAlmostEqual(r.center().x()-base.center().x(), (cx-x0)*scale)
                    self.assertAlmostEqual(r.center().y()-base.center().y(), (y0-cy)*scale)
                for g in graphics.values():
                    for t in elements:
                        if t["page"] == g["page"] and t["kind"] == "text":
                            overlap = QRectF(*g["rect"]).intersected(QRectF(*t["bounds"]))
                            self.assertFalse(overlap.width() > .1 and overlap.height() > .1,
                                             (g["key"], t["key"]))

    def test_painter_receives_actual_pixels_and_all_linear_points(self):
        snap = self.snapshot
        images, curves = [], []
        draw_image, draw_polyline = QPainter.drawImage, QPainter.drawPolyline

        def image(painter, rect, img):
            raster = img.convertToFormat(QImage.Format.Format_Grayscale8)
            pixels = np.frombuffer(raster.constBits(), np.uint8).reshape(raster.height(), raster.bytesPerLine())
            images.append(pixels[:, :raster.width()].copy())
            return draw_image(painter, rect, img)

        def curve(painter, poly):
            curves.append(np.array([(point.x(), point.y()) for point in poly]))
            return draw_polyline(painter, poly)

        audit = {}
        with patch.object(QPainter, "drawImage", image), patch.object(QPainter, "drawPolyline", curve):
            report.write_pdf(snap, self.path, layout_audit=audit)
        self.assertEqual(len(images), 1)
        np.testing.assert_array_equal(images[0], report.display_gray(snap.screen))
        plot = next(x for x in audit["elements"] if x["key"] == "linear-profile")["rect"]
        x, y, w, h = plot
        half = snap.profile.sampling.half_length_m
        self.assertEqual(len(curves), 1)
        np.testing.assert_allclose(curves[0][:, 0], x + (snap.profile.position_m+half)/(2*half)*w, atol=1e-10, rtol=0)
        np.testing.assert_allclose(curves[0][:, 1], y + h - snap.profile.point_intensity*h, atol=1e-10, rtol=0)

    def test_failure_or_cancellation_preserves_existing_destination(self):
        self.path.write_bytes(b"prior contents")
        class CancelBeforeCommit(report.ExportControl):
            def commit(self, device):
                self.cancel()
                super().commit(device)

        with self.assertRaises(report.ExportCancelled):
            report.write_pdf(self.snapshot, self.path, control=CancelBeforeCommit())
        self.assertEqual(self.path.read_bytes(), b"prior contents")
        failures = ((QPdfWriter, "newPage"), (report.QSaveFile, "write"),
                    (report.QSaveFile, "flush"), (report.QSaveFile, "commit"))
        for cls, method in failures:
            with self.subTest(method=method), patch.object(cls, method, return_value=False):
                with self.assertRaises((OSError, ReportError)):
                    report.write_pdf(self.snapshot, self.path)
                self.assertEqual(self.path.read_bytes(), b"prior contents")
        with self.assertRaises(OSError):
            report.write_pdf(self.snapshot, self.path.parent/"missing"/"bad.pdf")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        published = report.ExportControl()
        report.write_pdf(self.snapshot, self.path, control=published)
        published.cancel()
        self.assertTrue(published.committed)
        self.assertTrue(self.path.read_bytes().rstrip().endswith(b"%%EOF"))

    def test_public_writer_rejects_mismatched_request_or_data_before_paint(self):
        snap = self.snapshot
        other = replace(snap.request, params=replace(snap.request.params, angle_deg=-35.))
        altered = replace(snap.profile, point_intensity=np.zeros(1025))
        for invalid in (replace(snap, request=other), replace(snap, profile=altered)):
            with patch.object(report, "_paint_document") as draw, self.assertRaises(ReportError):
                report.write_pdf(invalid, self.path)
            draw.assert_not_called()
            self.assertFalse(self.path.exists())

    def test_worker_cannot_start_qt_page_painting(self):
        with ThreadPoolExecutor(max_workers=1) as worker, patch.object(report, "_paint_document") as paint:
            future = worker.submit(report.render_pdf, self.snapshot)
            with self.assertRaisesRegex(ReportError, "主线程"):
                future.result(timeout=2)
            paint.assert_not_called()

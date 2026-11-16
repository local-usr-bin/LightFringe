from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4
import hashlib
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lightfringe.gui import MainWindow
from lightfringe.multislit import MultiParameters
from lightfringe.report import ReportError, write_pdf
from test_report import parsed

E=Path(__file__).resolve().parents[1]/'artifacts/LF-P0-A3-MULTISLIT-R1'


class MultislitGuiPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setFont(QFont('Microsoft YaHei UI',10))

    def setUp(self):
        self.w=MainWindow();self.w.show();QTest.qWait(40)
        self.folder=E/'test-output'/('multi-'+uuid4().hex);self.folder.mkdir(parents=True)
        self.warn_patch=patch('lightfringe.gui.QMessageBox.warning')
        self.warnings=self.warn_patch.start()

    def tearDown(self):
        self.w.close();self.app.processEvents();self.warn_patch.stop()
        self.assertEqual(self.warnings.call_count,0,str(self.warnings.call_args))

    def set_multi(self,n,values=(550,20,60,2.)):
        self.w.mode.setCurrentIndex(2)
        self.w._load_values(values);self.w.slit_count.setValue(n);self.w._changed()
        self.app.processEvents()

    def test_all_integer_counts_change_curves_and_share_physical_parameters(self):
        self.w.mode.setCurrentIndex(2)
        self.assertEqual(self.w.parameters(),MultiParameters())
        self.assertEqual((self.w.slit_count.minimum(),self.w.slit_count.maximum()),(3,8))
        previous=None
        for n in range(3,9):
            before=self.w._control_values()
            self.w.slit_count.setValue(n);self.app.processEvents()
            s=self.w.report_snapshot()
            self.assertEqual(s.params.slit_count,n)
            self.assertEqual(self.w._control_values(),before)
            self.assertIsNotNone(self.w.view.data)
            if previous is not None:self.assertFalse(np.array_equal(previous,s.data.intensity))
            previous=s.data.intensity.copy()

    def test_legacy_and_multi_settings_survive_switching(self):
        self.w._load_values((620,25,110,1.7));self.w._changed()
        old=self.w.parameters()
        self.set_multi(5,(633,20,80,1.5));multi=self.w.parameters()
        self.w.mode.setCurrentIndex(1);self.assertEqual(self.w.parameters(),old)
        self.w.mode.setCurrentIndex(0)
        self.assertEqual(self.w._control_values(),(620,25,110,1.7))
        self.w.mode.setCurrentIndex(2);self.assertEqual(self.w.parameters(),multi)
        self.w.restore_defaults();self.assertEqual(self.w.parameters(),MultiParameters())
        self.w.mode.setCurrentIndex(1);self.assertEqual(self.w.parameters(),old)

    def test_N_keyboard_and_wavelength_slider_refresh_both_buffers(self):
        self.set_multi(3)
        old=self.w.report_snapshot();rev=self.w.view.revision
        self.w.slit_count.setFocus();QTest.keyClick(self.w.slit_count,Qt.Key.Key_Up)
        self.app.processEvents()
        self.assertEqual(self.w.slit_count.value(),4)
        self.assertGreater(self.w.view.revision,rev)
        self.assertFalse(np.array_equal(old.data.intensity,self.w.view.data.intensity))
        self.assertFalse(np.array_equal(old.data.pixel_mean,self.w.view.data.pixel_mean))
        QTest.keyClick(self.w.wavelength.slider,Qt.Key.Key_Right);self.app.processEvents()
        self.assertEqual(self.w.wavelength.value(),551)
        self.assertTrue(self.w.export_button.isEnabled())

    def test_N_far_field_gate_clears_old_data_and_recovers(self):
        self.set_multi(3,(550,30,150,1.))
        self.assertIsNotNone(self.w.view.data)
        before=self.w._control_values()
        self.w.slit_count.setValue(8)
        self.assertEqual(before,self.w._control_values())
        self.assertIsNone(self.w.view.data);self.assertIsNone(self.w.view._image)
        self.assertEqual(self.w.view._paths,[])
        self.assertIn('完整孔径',self.w.status.text())
        self.assertFalse(self.w.export_button.isEnabled())
        with self.assertRaises(ReportError):self.w.report_snapshot()
        self.w.slit_count.setValue(3)
        self.assertIsNotNone(self.w.view.data)

    def test_insufficient_local_bandwidth_sampling_hides_and_recovers(self):
        self.set_multi(8)
        view=self.w.view;view.setParent(None);view.setMinimumSize(1,1);view.resize(150,420);view.show()
        self.app.processEvents()
        self.assertIn('采样不足',view.error);self.assertIsNone(view.data)
        self.assertFalse(self.w.export_button.isEnabled())
        with self.assertRaises(ReportError):self.w.report_snapshot()
        view.resize(1100,600);self.app.processEvents()
        self.assertIsNotNone(view.data);view.close()

    def test_pending_N_cannot_export_an_old_curve(self):
        self.set_multi(3)
        self.w.slit_count.blockSignals(True);self.w.slit_count.setValue(5);self.w.slit_count.blockSignals(False)
        with self.assertRaises(ReportError):self.w.report_snapshot()
        self.w._changed();self.assertEqual(self.w.report_snapshot().params.slit_count,5)
        self.w.slit_count.lineEdit().setText('7')
        with self.assertRaises(ReportError):self.w.report_snapshot()

    def test_three_PDFs_actual_parsing_N_parameters_and_units(self):
        cases=[(3,(550,30,150,1.3),330),(5,(633,20,80,1.5),340),(8,(550,20,60,2.),440)]
        for n,values,W in cases:
            self.set_multi(n,values)
            text=parsed(write_pdf(self.w.report_snapshot(),self.folder/f'多缝N{n}.pdf'))
            for token in ('多缝干涉',f'N={n}',f'{values[0]}nm',f'{values[1]}μm',f'{values[2]}μm',
                          f'{values[3]:.2f}m',f'W={W}μm','相对光强I/Imax','同相等幅',
                          '非实测','矢量','缩小查看','有效显示密度'):
                # The mandatory statement uses “并非实测数据”.
                self.assertIn(token,text)

    def test_all_six_counts_PDF_layout_and_out_of_view_reporting(self):
        for n in range(3,9):
            self.set_multi(n)
            text=parsed(write_pdf(self.w.report_snapshot(),self.folder/f'layout{n}.pdf'))
            self.assertIn(f'N={n}',text)
            self.assertIn('当前范围不可确定',text) # Envelope first zero is 55mm.

    def test_multi_PDF_curve_and_image_are_exact_snapshot_sources(self):
        self.set_multi(8);s=self.w.report_snapshot();curves=[];images=[]
        original=QPainter.drawPolyline;original_image=QPainter.drawImage
        def curve(p,polygon):
            curves.append(np.array([(v.x(),v.y()) for v in polygon]));return original(p,polygon)
        def image(p,rect,img):
            images.append([img.pixelColor(i,0).red() for i in range(img.width())]);return original_image(p,rect,img)
        with patch('lightfringe.multislit.intensity',side_effect=AssertionError('PDF recomputation')), \
             patch.object(QPainter,'drawPolyline',curve),patch.object(QPainter,'drawImage',image):
            write_pdf(s,self.folder/'source.pdf')
        self.assertEqual(len(curves),2)
        for actual,y in zip(curves,(s.data.envelope,s.data.intensity)):
            np.testing.assert_allclose(actual[:,0],286+(s.data.x+s.data.span)/(2*s.data.span)*476,atol=1e-12)
            np.testing.assert_allclose(actual[:,1],381-y*155,atol=1e-12)
        np.testing.assert_array_equal(images[0],np.rint(255*np.sqrt(s.data.pixel_mean)).astype(np.uint8))
        with self.assertRaises(FrozenInstanceError):s.params.slit_count=3
        with self.assertRaises(ValueError):s.data.intensity.setflags(write=True)

    def test_dialog_state_changes_preserve_frozen_N_and_data(self):
        self.set_multi(3,(550,30,150,1.3));path=self.folder/'frozen.pdf'
        def choose(s):
            self.w.slit_count.setValue(8);self.w.mode.setCurrentIndex(0)
            self.assertEqual(s.params.slit_count,3)
            return str(path)
        with patch.object(self.w,'_choose_report_path',side_effect=choose),patch('lightfringe.gui.QMessageBox.information'):
            self.w.export_report()
        text=parsed(path);self.assertIn('N=3',text);self.assertNotIn('N=8',text)

    def test_cancel_reject_overwrite_allow_overwrite_and_failure_contract(self):
        self.set_multi(3);path=self.folder/'existing.pdf'
        write_pdf(self.w.report_snapshot(),path);old=hashlib.sha256(path.read_bytes()).hexdigest()
        # None is the native dialog's cancel/rejected-overwrite result contract.
        with patch.object(self.w,'_choose_report_path',return_value=None),patch('lightfringe.gui.write_pdf') as writer:
            self.w.export_report()
        writer.assert_not_called();self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),old)
        self.set_multi(5)
        with patch.object(self.w,'_choose_report_path',return_value=str(path)),patch('lightfringe.gui.QMessageBox.information'):
            self.w.export_report()
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(),old)
        self.assertIn('N=5',parsed(path))
        with patch.object(self.w,'_choose_report_path',return_value=str(self.folder/'missing/x.pdf')), \
             patch('lightfringe.gui.QMessageBox.warning') as warning,patch('lightfringe.gui.QMessageBox.information') as success:
            self.w.export_report()
        warning.assert_called_once();success.assert_not_called()

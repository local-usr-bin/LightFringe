from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from lightfringe.gui import MainWindow
from lightfringe.model import ModelError
from lightfringe.report import ReportError
from test_report import PDF_TEST_OUTPUT, parsed


class ExportGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = MainWindow()
        self.w.mode.setCurrentIndex(1)
        self.w.show()
        QTest.qWait(30)
        self.folder = PDF_TEST_OUTPUT / ('gui-' + uuid4().hex)
        self.folder.mkdir(parents=True)
        self.warning_patch = patch('lightfringe.gui.QMessageBox.warning')
        self.unexpected_warning = self.warning_patch.start()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()
        self.warning_patch.stop()
        self.assertEqual(self.unexpected_warning.call_count, 0, str(self.unexpected_warning.call_args))

    def test_cancel_creates_no_file(self):
        with patch.object(self.w, '_choose_report_path', return_value=None), \
             patch('lightfringe.gui.write_pdf') as write, \
             patch('lightfringe.gui.QMessageBox.information') as success:
            self.w.export_report()
        write.assert_not_called()
        success.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertTrue(self.w.export_button.isEnabled())

    def test_native_dialog_configuration_and_cancel(self):
        # Instance configuration guarantees default suffix and native overwrite
        # confirmation; no manual name rewriting after the dialog is accepted.
        real_dialog = QFileDialog(self.w)
        real_dialog.exec = MagicMock(return_value=QFileDialog.DialogCode.Rejected)
        with patch('lightfringe.gui.QFileDialog', return_value=real_dialog) as cls:
            cls.AcceptMode = QFileDialog.AcceptMode
            cls.FileMode = QFileDialog.FileMode
            cls.DialogCode = QFileDialog.DialogCode
            self.assertIsNone(self.w._choose_report_path(self.w.report_snapshot()))
        self.assertEqual(real_dialog.acceptMode(), QFileDialog.AcceptMode.AcceptSave)
        self.assertEqual(real_dialog.defaultSuffix(), 'pdf')
        self.assertFalse(real_dialog.testOption(QFileDialog.Option.DontConfirmOverwrite))
        self.assertFalse(real_dialog.testOption(QFileDialog.Option.DontUseNativeDialog))
        real_dialog.close()

    def test_success_feedback_after_valid_pdf(self):
        path = self.folder/'中文保存.pdf'
        with patch.object(self.w, '_choose_report_path', return_value=str(path)), \
             patch('lightfringe.gui.QMessageBox.information') as success, \
             patch('lightfringe.gui.QMessageBox.warning') as failure:
            self.w.export_report()
        self.assertIn('双缝', parsed(path))
        success.assert_called_once()
        failure.assert_not_called()
        self.assertIn(str(path), success.call_args.args[2])

    def test_failure_feedback_never_claims_success(self):
        path = str(self.folder/'missing'/'报告.pdf')
        with patch.object(self.w, '_choose_report_path', return_value=path), \
             patch('lightfringe.gui.QMessageBox.information') as success, \
             patch('lightfringe.gui.QMessageBox.warning') as failure:
            self.w.export_report()
        success.assert_not_called()
        failure.assert_called_once()
        self.assertIn('报告未保存', failure.call_args.args[2])
        self.assertFalse(Path(path).exists())

    def test_invalid_far_field_disables_and_refuses_export(self):
        self.w.separation.spin.setValue(250)
        self.w.width_control.spin.setValue(80)
        self.w.wavelength.spin.setValue(380)
        self.w.distance.spin.setValue(.5)
        self.assertFalse(self.w.export_button.isEnabled())
        with self.assertRaises(ReportError):
            self.w.report_snapshot()

    def test_undersampling_disables_and_refuses_export(self):
        v = self.w.view
        v.setParent(None);v.setMinimumSize(1, 1);v.resize(150, 420);v.show()
        self.app.processEvents()
        self.assertIn('采样不足', v.error)
        self.assertFalse(self.w.export_button.isEnabled())
        with self.assertRaises(ReportError):
            self.w.report_snapshot()
        v.close()

    def test_pending_or_failed_result_cannot_mix_inputs(self):
        w = self.w
        # Spin value changes with its signals blocked: params differ from data.
        w.wavelength.spin.blockSignals(True)
        w.wavelength.spin.setValue(650)
        w.wavelength.spin.blockSignals(False)
        with self.assertRaises(ReportError):
            w.report_snapshot()
        w._changed()
        self.assertAlmostEqual(w.report_snapshot().params.wavelength, 650e-9)
        w.view.computing = True
        with self.assertRaises(ReportError):
            w.report_snapshot()
        w.view.computing = False
        w.view.result_key = None  # An interrupted/failed calculation never stamps a result.
        with self.assertRaises(ReportError):
            w.report_snapshot()

    def test_uncommitted_numeric_edit_is_not_exported_as_old_result(self):
        self.w.wavelength.spin.lineEdit().setText('650 nm')
        with self.assertRaises(ReportError):
            self.w.report_snapshot()

    def test_dialog_state_changes_cannot_mutate_captured_report(self):
        path = self.folder/'快照.pdf'
        before = self.w.report_snapshot()

        def choose(snapshot):
            self.assertFalse(self.w.export_button.isEnabled())
            self.w.mode.setCurrentIndex(0)
            self.w.wavelength.spin.setValue(700)
            self.assertEqual(snapshot.data_sha256, before.data_sha256)
            return str(path)

        with patch.object(self.w, '_choose_report_path', side_effect=choose), \
             patch('lightfringe.gui.QMessageBox.information'):
            self.w.export_report()
        text = parsed(path)
        self.assertIn('550nm', text)
        self.assertIn('双缝中心距d150μm', text)
        self.assertNotIn('700nm', text)
        self.assertTrue(self.w.export_button.isEnabled())

    def test_low_note_covers_audit_case(self):
        self.w.width_control.spin.setValue(40)
        self.w.separation.spin.setValue(140)
        self.assertIn('7/2', self.w.metrics.text())
        self.assertIn('每第 7 级', self.w.metrics.text())

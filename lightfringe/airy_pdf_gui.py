"""Minimal PDF-only successor; frozen A4-2 views and their messages are intact."""
from PySide6.QtWidgets import QFileDialog,QMessageBox
from .circular_gui import AiryMainWindow
from .circular_report import assess_pdf,capture_request,build_snapshot,write_pdf,CircularReportError

class AiryPdfMainWindow(AiryMainWindow):
    def __init__(self):
        self._pdf_ready=False
        super().__init__()
        self._pdf_ready=True
        self._update_status()
    def _pdf_circle(self):return self._pdf_ready and self.is_circular()
    def _confirmed_circular_input(self):
        return all(c.spin.hasAcceptableInput() and c.spin.cleanText()==c.spin.textFromValue(c.value()) for c in self._circular_controls())
    def _changed(self):
        super()._changed()
        if self._pdf_circle():
            self.geometry_note.setText('D 为圆孔直径；不自动改写参数。PDF使用独立383×383科学网格。')
    def _update_status(self):
        super()._update_status()
        if not self._pdf_circle():return
        if not self._confirmed_circular_input():
            self.export_button.setEnabled(False);self.export_button.setToolTip('请先确认当前数值输入，再导出PDF。');return
        eligibility=assess_pdf(self.circular_parameters())
        self.export_button.setEnabled(eligibility.allowed and not self._exporting)
        self.export_button.setToolTip('PDF使用独立383×383采样，当前窗口无法显示不影响报告导出。'
            if eligibility.allowed else eligibility.reason)
    def _report_is_current(self):
        if not self._pdf_circle():return super()._report_is_current()
        return self._confirmed_circular_input() and assess_pdf(self.circular_parameters()).allowed
    def _capture_circular_request(self):
        if not self._confirmed_circular_input():raise CircularReportError('请先确认当前数值输入')
        return capture_request(self.circular_parameters())
    def report_snapshot(self):
        if not self._pdf_circle():return super().report_snapshot()
        return build_snapshot(self._capture_circular_request())
    def _choose_circular_path(self,request):
        dialog=QFileDialog(self,'导出圆孔PDF报告')
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter('PDF 报告 (*.pdf)');dialog.setDefaultSuffix('pdf')
        dialog.selectFile(f'光纹_圆孔_{request.captured_at:%Y%m%d_%H%M%S}.pdf')
        if dialog.exec()!=QFileDialog.DialogCode.Accepted:return None
        files=dialog.selectedFiles();return files[0] if files else None
    def export_report(self):
        if not self._pdf_circle():return super().export_report()
        if self._exporting:return
        self._exporting=True;self.export_button.setEnabled(False)
        try:
            # Freeze the experiment before the nested save-dialog event loop.
            request=self._capture_circular_request()
            path=self._choose_circular_path(request)
            if not path:return
            snapshot=build_snapshot(request)
            saved=write_pdf(snapshot,path)
            QMessageBox.information(self,'PDF报告已保存',f'保存成功：\n{saved}')
        except Exception as exc:
            QMessageBox.warning(self,'无法导出圆孔PDF报告',f'报告未保存。\n{exc}')
        finally:
            self._exporting=False;self._update_status()

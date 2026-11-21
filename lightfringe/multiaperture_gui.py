"""Fifth experiment controls and routing in the existing Qt window."""
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .circular_gui import AiryMainWindow
from .gui import ParameterControl
from .multiaperture_model import (DIAMETER_RANGE_M, DISTANCE_RANGE_M, WAVELENGTH_RANGE_M,
                                  Layout, MultiApertureParameters)
from .multiaperture_view import DEFAULT_PARAMS, PRESETS, MultiApertureView
from .report import ReportError


MODE_ID = 'multiaperture'
PDF_NOTE = '多圆孔报告将在后续版本接入。'


class ArrayControls(QWidget):
    changed = Signal()
    editing = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet('QDoubleSpinBox {padding:2px;} QSlider {min-height:16px; max-height:16px;}')
        box = QVBoxLayout(self)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(2)
        row = QHBoxLayout()
        row.addWidget(QLabel('圆孔排列'))
        self.preset = QComboBox()
        self.preset.setAccessibleName('圆孔排列')
        for kind, name in PRESETS.items():
            self.preset.addItem(name, kind.value)
        row.addWidget(self.preset, 1)
        box.addLayout(row)
        wl = [round(x*1e9) for x in WAVELENGTH_RANGE_M]
        diam = [round(x*1e6) for x in DIAMETER_RANGE_M]
        self.wavelength = ParameterControl('波长 λ','nm',*wl,1,550)
        self.diameter = ParameterControl('圆孔直径 D','μm',*diam,1,60)
        self.distance = ParameterControl('屏距 z','m',*DISTANCE_RANGE_M,.01,1.,2)
        self.spacing = ParameterControl('孔中心距 d₁','μm',20,700,1,100)
        self.spacing_y = ParameterControl('第二方向中心距 d₂','μm',20,700,1,80)
        self.angle = ParameterControl('排列方向 θ','°',-180,180,1,0)
        self.controls = (self.wavelength, self.diameter, self.distance, self.spacing,
                         self.spacing_y, self.angle)
        for control in self.controls:
            control.layout().setContentsMargins(0,1,0,2)
            control.layout().setSpacing(0)
            box.addWidget(control)
            control.changed.connect(self.changed)
            control.spin.lineEdit().textEdited.connect(self.editing)
            control.spin.editingFinished.connect(self.changed)
        self.preset.currentIndexChanged.connect(self._layout_changed)
        self._layout_changed()

    def _layout_changed(self):
        kind = Layout(self.preset.currentData())
        self.spacing_y.setVisible(kind == Layout.RECTANGLE)
        self.angle.setVisible(kind != Layout.TRIANGLE)
        self.changed.emit()

    def confirmed(self):
        return all(c.spin.hasAcceptableInput() and c.spin.cleanText()==c.spin.textFromValue(c.value())
                   for c in self.controls if not c.isHidden())

    def parameters(self):
        kind = Layout(self.preset.currentData())
        return MultiApertureParameters(layout=kind, wavelength_m=self.wavelength.value()/1e9,
            diameter_m=self.diameter.value()/1e6, distance_m=self.distance.value(),
            spacing_m=self.spacing.value()/1e6,
            spacing_y_m=self.spacing_y.value()/1e6 if kind == Layout.RECTANGLE else None,
            angle_deg=0. if kind == Layout.TRIANGLE else self.angle.value())

    def reset(self):
        p = DEFAULT_PARAMS
        for control, value in zip(self.controls, (p.wavelength_m*1e9,p.diameter_m*1e6,
                                  p.distance_m,p.spacing_m*1e6,80.,0.)):
            control.set_value(value)
        if self.preset.currentIndex() == 0:
            self.changed.emit()
        else:
            self.preset.setCurrentIndex(0)


class MultiApertureWindow(AiryMainWindow):
    def __init__(self):
        self.array_view = None
        self.array_controls = None
        super().__init__()
        panel = ArrayControls()
        self.array_controls = panel
        controls = self.mode.parentWidget().layout()
        controls.insertWidget(controls.indexOf(self.wavelength), panel)
        panel.hide()
        panel.changed.connect(self._changed)
        panel.editing.connect(self._array_input_pending)
        self.mode.addItem('多圆孔干涉与衍射', MODE_ID)
        QApplication.instance().aboutToQuit.connect(self._stop_views)

    def is_array(self):
        return self.array_controls is not None and self.mode.currentData() == MODE_ID

    def parameters(self):
        return self.array_controls.parameters() if self.is_array() else super().parameters()

    def _mode_changed(self):
        if not self.is_array():
            if self.array_view is not None and self.array_view.active:
                self.array_view.set_active(False)
                self.array_controls.hide()
                self.apparatus_stack.show()
                self.export_button.setText('导出 PDF 报告')
            return super()._mode_changed()

        if self.array_view is None:
            self.array_view = MultiApertureView()
            self.view_stack.addWidget(self.array_view)
            self.array_view.stateChanged.connect(self._update_status)
        self.airy_view.set_active(False)
        for control in (self.circular_controls, self.wavelength, self.width_control, self.separation,
                        self.distance, self.slit_count_row, self.apparatus_stack):
            control.hide()
        self.array_controls.show()
        self.status.setFixedHeight(2*self.fontMetrics().lineSpacing()+12)
        self.export_button.setText('导出 PDF 报告（暂未接入）')
        self.export_button.setToolTip(PDF_NOTE)
        self.export_button.setEnabled(False)
        self.view_stack.setCurrentWidget(self.array_view)
        self._changed()
        self.array_view.set_active(True)
        if not self.array_controls.confirmed():
            self.array_view.input_pending()

    def _array_input_pending(self):
        if self.is_array():
            self.array_view.input_pending()

    def _changed(self):
        if not self.is_array():
            return super()._changed()
        p = self.array_controls.parameters()
        self.geometry_note.setText({
            Layout.PAIR: '方向从水平向右起，逆时针为正。',
            Layout.TRIANGLE: '中心距为等边三角形边长，顶点朝上。',
            Layout.SQUARE: '中心距为正方形边长，方向从水平向右起算。',
            Layout.RECTANGLE: '两组中心距沿孔阵列自身的两条边，随阵列一起旋转。',
        }[p.layout])
        self.model_note.setText('等径圆孔受同相、均匀的单色平面波垂直照明，复振幅叠加后按中心光强归一化。\n'
                                '标量、傍轴、夫琅禾费远场。整阵 F ≤ 0.05，观察半径 r/z ≤ 0.05。')
        if self.array_controls.confirmed():
            self.array_view.set_parameters(p)
        else:
            self.array_view.input_pending()
        self._update_status()

    def _update_status(self):
        if not self.is_array():
            return super()._update_status()
        v = self.array_view
        plan = v.decision
        lines = []
        if plan is not None:
            if plan.model.fresnel_number is not None:
                lines.append(f'整阵菲涅耳数 F = {plan.model.fresnel_number:.4f}')
            if plan.model.valid:
                lines.append(f'观察范围  x、y 各 ±{plan.model.field.half_x_m*1000:.2f} mm')
        self.metrics.setText('\n'.join(lines) or v.reason or '等待确认参数')
        states = {'DISPLAY_VALID':'模型与显示采样合格', 'DISPLAY_PARTIAL':'部分图样暂停',
                  'DISPLAY_UNDERSAMPLED':'显示采样不足', 'MODEL_INVALID':'模型不适用',
                  'INPUT_PENDING':'等待确认', 'COMPUTE_FAILED':'计算失败'}
        prefix = states.get(v.state)
        self.status.setText(prefix+'  |  '+v.reason if prefix else v.reason)
        color = '#28634c' if v.state == 'DISPLAY_VALID' else (
            '#526477' if v.state in ('CALCULATING','INPUT_PENDING') else '#a33020')
        self.status.setStyleSheet(f'color:{color};padding:4px;')
        self.export_button.setEnabled(False)

    def _report_is_current(self):
        return False if self.is_array() else super()._report_is_current()

    def report_snapshot(self):
        if self.is_array():
            raise ReportError(PDF_NOTE)
        return super().report_snapshot()

    def export_report(self):
        if self.is_array():
            return
        return super().export_report()

    def restore_defaults(self):
        if self.is_array():
            self.array_controls.reset()
        else:
            super().restore_defaults()

    @Slot()
    def _stop_views(self):
        if self.array_view is not None:
            self.array_view.shutdown()
        self.airy_view.shutdown()

    def closeEvent(self, event):
        if self.array_view is not None:
            self.array_view.shutdown()
        super().closeEvent(event)

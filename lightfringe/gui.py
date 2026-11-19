"""Qt Widgets UI; all physical predictions come from model.py."""
import time
from dataclasses import dataclass
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget, QFileDialog, QMessageBox,
)

from .model import Mode, ModelError, Parameters
from .multislit import MultiParameters, is_multi, prepare_display, characteristic_lengths
from .rendering import curve_vertex_indices
from . import __version__, __build__
from .annotations import missing_order_note
from .report import ReportError, capture_snapshot, write_pdf


class ParameterControl(QWidget):
    changed = Signal()

    def __init__(self, title, unit, low, high, step, default, decimals=0):
        super().__init__()
        self.step = step
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 7)
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(low, high)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(" " + unit)
        self.spin.setKeyboardTracking(False)
        self.spin.setAccessibleName(title)
        row.addWidget(self.spin)
        layout.addLayout(row)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName(title + "滑块")
        self.slider.setRange(round(low / step), round(high / step))
        self.slider.setValue(round(default / step))
        self.spin.setValue(default)
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, value):
        self.spin.blockSignals(True)
        self.spin.setValue(value * self.step)
        self.spin.blockSignals(False)
        self.changed.emit()

    def _from_spin(self, value):
        # Controls represent the same discrete, physically meaningful value.
        value = round(value / self.step) * self.step
        self.set_value(value)
        self.changed.emit()

    def set_value(self, value):
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setValue(value)
        self.slider.setValue(round(self.spin.value() / self.step))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def set_limits(self, low, high):
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setRange(low, high)
        self.slider.setRange(round(low / self.step), round(high / self.step))
        self.slider.setValue(round(self.spin.value() / self.step))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def value(self):
        return self.spin.value()


class PatternView(QWidget):
    computed = Signal()

    def __init__(self):
        super().__init__()
        self.params = Parameters()
        self.data = None
        self.error = ""
        self.last_compute_ms = 0.0
        self.paint_times_ms = []
        self.revision = 0
        self._key = None
        self._image = None
        self._paths = []
        self.result_key = None
        self.computing = False
        self.setMinimumSize(450, 350)
        self.setAccessibleName("观察屏与线性归一化光强曲线")

    def set_parameters(self, params):
        self.params = params
        self._key = None
        self.recompute()
        self.update()

    def plot_rect(self):
        return QRectF(66, 188, max(1, self.width() - 94), max(70, self.height() - 280))

    def recompute(self):
        width = max(1, round(self.plot_rect().width() * self.devicePixelRatioF()))
        key = (self.params, width, self.height())
        if key == self._key:
            return
        self.result_key = None
        self.computing = True
        start = time.perf_counter()
        self.data, self._image, self.error = None, None, ""
        self._paths = []
        try:
            self.data = prepare_display(self.params, width)
            # Display transfer only; numerical curve and model remain linear.
            level = np.rint(255 * np.sqrt(self.data.pixel_mean)).astype(np.uint8)
            rgb = np.repeat(level[:, None], 3, axis=1).copy()
            self._image = QImage(rgb.data, width, 1, width * 3, QImage.Format.Format_RGB888).copy()
            rect = self.plot_rect()
            px = rect.left() + (self.data.x + self.data.span) / (2 * self.data.span) * rect.width()
            for values in (self.data.intensity, self.data.envelope):
                py = rect.bottom() - values * rect.height()
                indices = curve_vertex_indices(px, py, 0.15 / self.devicePixelRatioF())
                self._paths.append(QPolygonF([QPointF(float(px[i]), float(py[i])) for i in indices]))
        except ModelError as exc:
            self.error = str(exc)
        finally:
            self.computing = False
        self.last_compute_ms = (time.perf_counter() - start) * 1000
        self.revision += 1
        self._key = key
        if self.data is not None and not self.error:
            self.result_key = key
        self.computed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recompute()

    def paintEvent(self, event):
        start = time.perf_counter()
        self.recompute()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        rect = self.plot_rect()
        left, right = rect.left(), rect.right()
        painter.setPen(QColor("#152a3d"))
        painter.drawText(QPointF(left, 27), "观察屏 · 与下方曲线共用横向坐标")
        strip = QRectF(left, 42, rect.width(), 78)
        if self.error:
            painter.fillRect(strip, QColor("#eef1f4"))
            painter.setPen(QColor("#a33020"))
            painter.drawText(QRectF(left, 140, rect.width(), 180), Qt.TextFlag.TextWordWrap, self.error)
            painter.end()
            self.paint_times_ms.append((time.perf_counter() - start) * 1000)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(strip, self._image)
        painter.setPen(QColor("#526477"))
        painter.drawText(QPointF(left, 143), "灰度亮度 = √(像素平均 I/I₀)；仅辅助观察，非测量 RGB")
        painter.setPen(QColor("#152a3d"))
        painter.drawText(QPointF(left, 175), "相对光强 I/Imax（Imax = I(0)，线性）" if is_multi(self.params)
                         else "相对光强 I/I₀（线性）")
        for value in (0, 0.25, 0.5, 0.75, 1):
            y = rect.bottom() - value * rect.height()
            painter.setPen(QPen(QColor("#e2e8ee"), 1))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            painter.setPen(QColor("#526477"))
            painter.drawText(QRectF(5, y - 9, 51, 20), Qt.AlignmentFlag.AlignRight, f"{value:g}")
        span = self.data.span
        for i in range(9):
            px = left + rect.width() * i / 8
            painter.setPen(QPen(QColor("#e2e8ee"), 1))
            painter.drawLine(QPointF(px, rect.top()), QPointF(px, rect.bottom()))
            painter.setPen(QColor("#526477"))
            painter.drawText(QRectF(px - 30, rect.bottom() + 7, 60, 22), Qt.AlignmentFlag.AlignCenter,
                             f"{(-span + 2 * span * i / 8) * 1000:g}")
        painter.setPen(QColor("#152a3d"))
        painter.drawText(QRectF(left, rect.bottom() + 34, rect.width(), 24),
                         Qt.AlignmentFlag.AlignCenter, "观察屏横向位置 x / mm")

        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        if self.params.mode == Mode.DOUBLE or is_multi(self.params):
            pen = QPen(QColor("#bb8844"), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPolyline(self._paths[1])
        pen = QPen(QColor("#1266a6"), 1.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPolyline(self._paths[0])
        painter.restore()
        painter.setPen(QColor("#526477"))
        caption = "蓝线：有限缝宽双缝光强    虚线：单缝包络" if self.params.mode == Mode.DOUBLE else "蓝线：单缝衍射光强"
        if is_multi(self.params):
            caption = f"蓝线：N={self.params.slit_count} 有限宽多缝光强    虚线：单缝包络"
        painter.drawText(QPointF(left, self.height() - 12), caption)
        painter.end()
        self.paint_times_ms.append((time.perf_counter() - start) * 1000)
        self.paint_times_ms = self.paint_times_ms[-1000:]


@dataclass(frozen=True)
class ApertureSlit:
    left: float
    center: float
    right: float
    top: float = 24.0
    bottom: float = 40.0


@dataclass(frozen=True)
class ApertureDimension:
    symbol: str
    x1: float
    x2: float
    y: float


@dataclass(frozen=True)
class ApertureGeometry:
    width: float
    split: float
    slits: tuple[ApertureSlit, ...]
    dimensions: tuple[ApertureDimension, ...]


def aperture_schematic_geometry(width, slit_count):
    """GUI-only non-scale coordinates; dimensions share the drawn slit edges.

    These lengths never represent optical parameters or enter calculations.
    """
    width = float(width)
    if not 180 <= width <= 32768:
        raise ValueError("schematic width out of range")
    if type(slit_count) is not int or not 1 <= slit_count <= 8:
        raise ValueError("schematic slit count must be an integer from 1 to 8")
    split = width * .34
    left, right = 34.0, split - 16.0
    available = right - left
    slit_width = min(12.0, available / (2 * slit_count))
    pitch = min(32.0, (available - slit_width) / (slit_count - 1)) if slit_count > 1 else 0.0
    middle = (left + right) / 2
    centers = tuple(middle + (i - (slit_count - 1) / 2) * pitch for i in range(slit_count))
    slits = tuple(ApertureSlit(c - slit_width / 2, c, c + slit_width / 2) for c in centers)
    dimensions = [ApertureDimension("a", slits[0].left, slits[0].right, 45.0)]
    if slit_count > 1:
        dimensions += [ApertureDimension("d", slits[0].center, slits[1].center, 60.0),
                       ApertureDimension("D" if slit_count == 2 else "W", slits[0].left, slits[-1].right, 75.0)]
    return ApertureGeometry(width, split, slits, tuple(dimensions))


class Apparatus(QWidget):
    FRONT_TITLE = "缝面示意（不按比例）"
    DEVICE_TITLE = "装置示意（不按比例）"
    PLATE_LABEL = "狭缝板"

    def __init__(self):
        super().__init__()
        self.mode = Mode.DOUBLE
        self.slit_count = 2
        self.setFixedHeight(83)
        self.setAccessibleName("缝面与装置示意（不按比例）")

    def schematic_geometry(self):
        count = 1 if self.mode == Mode.SINGLE else (2 if self.mode == Mode.DOUBLE else self.slit_count)
        return aperture_schematic_geometry(self.width(), count)

    def paintEvent(self, event):
        geometry = self.schematic_geometry()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#526477"))
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(QRectF(12, 0, geometry.split - 24, 22), align, self.FRONT_TITLE)
        painter.setPen(QPen(QColor("#d4dfe7"), 1))
        painter.drawLine(QPointF(geometry.split, 6), QPointF(geometry.split, 77))

        # One front-facing plate; every white rectangle is an actual drawn slit.
        first, last = geometry.slits[0], geometry.slits[-1]
        plate = QRectF(first.left - 6, 23, last.right - first.left + 12, 18)
        painter.fillRect(plate, QColor("#dce5ec"))
        painter.setPen(QPen(QColor("#8697a6"), 1))
        painter.drawRect(plate)
        for slit in geometry.slits:
            opening = QRectF(slit.left, slit.top, slit.right - slit.left, slit.bottom - slit.top)
            painter.fillRect(opening, QColor("#ffffff"))
            painter.setPen(QPen(QColor("#526477"), 1))
            painter.drawRect(opening)

        # d extensions pass through the two centers; a and D/W use outer edges.
        painter.setPen(QPen(QColor("#9bacb8"), 1, Qt.PenStyle.DotLine))
        for dimension in geometry.dimensions:
            start_y = first.top - 2 if dimension.symbol == "d" else first.bottom + 1
            for x in (dimension.x1, dimension.x2):
                painter.drawLine(QPointF(x, start_y), QPointF(x, dimension.y + 2))
        painter.setPen(QPen(QColor("#1266a6"), 1))
        for dimension in geometry.dimensions:
            painter.drawLine(QPointF(dimension.x1, dimension.y), QPointF(dimension.x2, dimension.y))
            for x in (dimension.x1, dimension.x2):
                painter.drawLine(QPointF(x, dimension.y - 2), QPointF(x, dimension.y + 2))
            painter.drawText(QRectF(first.left - 24, dimension.y - 7, 18, 14),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dimension.symbol)

        # Compressed side view, without changing the existing 83-pixel row.
        right_left = geometry.split + 12
        right_width = self.width() - right_left - 12
        title = self.DEVICE_TITLE + " · 相干平面波垂直入射"
        if painter.fontMetrics().horizontalAdvance(title) > right_width:
            title = self.DEVICE_TITLE
        painter.setPen(QColor("#526477"))
        painter.drawText(QRectF(right_left, 0, right_width, 22), align, title)
        board_x, screen_x = right_left + 80, self.width() - 36
        painter.setPen(QPen(QColor("#8697a6"), 2))
        painter.drawLine(QPointF(board_x, 27), QPointF(board_x, 62))
        painter.drawLine(QPointF(screen_x, 27), QPointF(screen_x, 62))
        count = len(geometry.slits)
        gaps = (44.5,) if count == 1 else ((37.0, 52.0) if count == 2 else
                tuple(30 + i * 29 / (count - 1) for i in range(count)))
        gap_height = 6.0 if count <= 2 else 1.5
        for y in gaps:
            painter.fillRect(QRectF(board_x - 3, y - gap_height / 2, 6, gap_height), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#1266a6"), 1))
        for y in (35, 45, 55):
            end = board_x - 15
            painter.drawLine(QPointF(right_left + 8, y), QPointF(end, y))
            painter.drawLine(QPointF(end - 4, y - 3), QPointF(end, y))
            painter.drawLine(QPointF(end - 4, y + 3), QPointF(end, y))
        distance_left, distance_right = board_x + 18, screen_x - 12
        painter.drawLine(QPointF(distance_left, 47), QPointF(distance_right, 47))
        painter.drawText(QRectF(distance_left, 26, distance_right - distance_left, 18),
                         Qt.AlignmentFlag.AlignCenter, "屏距 z")
        painter.setPen(QColor("#526477"))
        painter.drawText(QRectF(board_x - 28, 64, 56, 18), Qt.AlignmentFlag.AlignCenter, self.PLATE_LABEL)
        painter.drawText(QRectF(screen_x - 30, 64, 60, 18), Qt.AlignmentFlag.AlignCenter, "观察屏")
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"光纹 LightFringe {__version__} · {__build__}")
        self.resize(1220, 820)
        self.setMinimumSize(980, 660)
        self.setStyleSheet("QMainWindow {background:#f2f5f8;} QLabel{color:#203448;}"
                           "QPushButton{padding:7px;} QComboBox{padding:5px;}"
                           "QDoubleSpinBox{padding:4px;} QSlider{min-height:22px;}")
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("光纹  LightFringe")
        title.setStyleSheet("font-size:24px;font-weight:600;padding:5px;")
        layout.addWidget(title)
        subtitle = QLabel(f"波动光学实验 · {__version__}    |    夫琅禾费远场 · 相干、单色、等幅照明")
        layout.addWidget(subtitle)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        side = QWidget()
        side.setFixedWidth(310)
        controls = QVBoxLayout(side)
        self.mode = QComboBox()
        self.mode.setAccessibleName("实验模式")
        self.mode.addItems(["单缝衍射", "双缝干涉 + 衍射", "多缝干涉 + 衍射"])
        self.mode.setCurrentIndex(1)
        controls.addWidget(QLabel("实验模式"))
        controls.addWidget(self.mode)
        self.slit_count_row = QWidget()
        count_layout = QHBoxLayout(self.slit_count_row)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.addWidget(QLabel("缝数 N（同相等幅）"))
        self.slit_count = QSpinBox()
        self.slit_count.setRange(3, 8)
        self.slit_count.setValue(8)
        self.slit_count.setKeyboardTracking(False)
        self.slit_count.setAccessibleName("缝数 N")
        self.slit_count.valueChanged.connect(self._changed)
        count_layout.addWidget(self.slit_count)
        controls.addWidget(self.slit_count_row)
        self.slit_count_row.setVisible(False)
        self._active_group = 'legacy'
        self._legacy_values = (550, 30, 150, 1.)
        self._multi_values = (550, 20, 60, 2.)
        self.wavelength = ParameterControl("波长 λ", "nm", 380, 750, 1, 550)
        self.width_control = ParameterControl("缝宽 a", "μm", 10, 80, 1, 30)
        self.separation = ParameterControl("中心间距 d", "μm", 40, 250, 1, 150)
        self.distance = ParameterControl("观察屏距离 z", "m", 0.5, 3.0, 0.01, 1.0, 2)
        for control in (self.wavelength, self.width_control, self.separation, self.distance):
            controls.addWidget(control)
            control.changed.connect(self._changed)
        self.reset = QPushButton("恢复默认参数")
        self.reset.clicked.connect(self.restore_defaults)
        controls.addWidget(self.reset)
        self.export_button = QPushButton("导出 PDF 报告")
        self.export_button.setToolTip("导出当前已完成的有效结果；数值输入请先回车确认。")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_report)
        controls.addWidget(self.export_button)
        self._exporting = False
        self.geometry_note = QLabel("双缝保持至少 5 μm 间隙；范围随几何联动。")
        self.geometry_note.setWordWrap(True)
        controls.addWidget(self.geometry_note)
        self.metrics = QLabel()
        self.metrics.setWordWrap(True)
        self.metrics.setStyleSheet("background:#e5edf4;padding:10px;")
        controls.addWidget(self.metrics)
        controls.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(side)
        scroll.setFixedWidth(332)
        body.addWidget(scroll)
        right = QVBoxLayout()
        body.addLayout(right, 1)
        self.view = PatternView()
        right.addWidget(self.view, 1)
        self.apparatus = Apparatus()
        right.addWidget(self.apparatus)
        self.model_note = QLabel(
            "模型：单缝 sinc²(πax/λz)；双缝再乘 cos²(πdx/λz)。此处 sinc(t)=sin(t)/t。\n"
            "条件：标量、长直缝；F=(D/2)²/(λz) ≤ 0.05，D 为完整孔径宽；|x|/z ≤ 0.05。\n"
            "各配置按自身 I(0) 归一化，不能据此比较绝对功率。未计算近场或屏面绝对照度。"
        )
        self.model_note.setWordWrap(True)
        self.model_note.setStyleSheet("background:#e5edf4;padding:9px;")
        layout.addWidget(self.model_note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.view.computed.connect(self._update_status)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._changed()
        available = self.screen().availableGeometry()
        self.resize(min(1220, available.width() - 24), min(820, available.height() - 48))

    def parameters(self):
        if self.mode.currentIndex() == 2:
            return MultiParameters(self.slit_count.value(), self.wavelength.value()/1e9,
                                   self.width_control.value()/1e6, self.separation.value()/1e6,
                                   self.distance.value())
        return Parameters(Mode.SINGLE if self.mode.currentIndex() == 0 else Mode.DOUBLE,
                          self.wavelength.value() / 1e9,
                          self.width_control.value() / 1e6,
                          self.separation.value() / 1e6,
                          self.distance.value())

    def _control_values(self):
        return tuple(c.value() for c in (self.wavelength, self.width_control, self.separation, self.distance))

    def _load_values(self, values):
        self.width_control.set_limits(10, 80)
        self.separation.set_limits(40, 250)
        for control, value in zip((self.wavelength, self.width_control, self.separation, self.distance), values):
            control.set_value(value)

    def _mode_changed(self):
        group = 'multi' if self.mode.currentIndex() == 2 else 'legacy'
        if group != self._active_group:
            if self._active_group == 'legacy':
                self._legacy_values = self._control_values()
            else:
                self._multi_values = self._control_values()
            self._load_values(self._multi_values if group == 'multi' else self._legacy_values)
            self._active_group = group
        self._changed()

    def _changed(self):
        multi = self.mode.currentIndex() == 2
        self.slit_count_row.setVisible(multi)
        double = self.mode.currentIndex() != 0
        self.separation.setEnabled(double)
        if double:
            # A single-slit edit can have widened a beyond the stored d; make
            # the necessary adjustment explicit before entering double mode.
            adjusted = self.separation.value() < self.width_control.value() + 5
            if adjusted:
                self.separation.set_value(self.width_control.value() + 5)
            self.width_control.set_limits(10, min(80, self.separation.value() - 5))
            self.separation.set_limits(max(40, self.width_control.value() + 5), 250)
            self.geometry_note.setText("切换时已增大 d，保持 5 μm 间隙。" if adjusted else
                                       "双缝保持至少 5 μm 间隙；范围随几何联动。")
        else:
            self.width_control.set_limits(10, 80)
            self.separation.set_limits(40, 250)
            self.geometry_note.setText("单缝模式：中心间距不参与计算。")
        p = self.parameters()
        self.apparatus.mode = p.mode
        self.apparatus.slit_count = p.slit_count if is_multi(p) else (1 if p.mode == Mode.SINGLE else 2)
        self.apparatus.update()
        if multi:
            self.geometry_note.setText("多缝保持至少 5 μm 间隙；N 改变完整孔径，参数不会自动改写。")
            self.model_note.setText(
                "多缝模型：单缝有限宽包络 × 同相等幅 N 缝干涉因子；Imax = I(0)。\n"
                "理想长缝、标量、傍轴远场；W=(N−1)d+a，F=(W/2)²/(λL) ≤ 0.05，|x|/L ≤ 0.05。\n"
                "光纹为辅助灰度；不同参数及缝数的归一化峰高不能比较实际透射功率。")
        else:
            self.model_note.setText(
                "模型：单缝 sinc²(πax/λz)；双缝再乘 cos²(πdx/λz)。此处 sinc(t)=sin(t)/t。\n"
                "条件：标量、长直缝；F=(D/2)²/(λz) ≤ 0.05，D 为完整孔径宽；|x|/z ≤ 0.05。\n"
                "各配置按自身 I(0) 归一化，不能据此比较绝对功率。未计算近场或屏面绝对照度。")
        self.view.set_parameters(p)
        self._update_status()

    def _update_status(self):
        p = self.view.params
        symbol = 'W' if is_multi(p) else 'D'
        text = f"完整孔径 {symbol} = {p.aperture_extent * 1e6:.0f} μm\nF = {p.fresnel_number:.4f}（上限 0.05）"
        if not self.view.error:
            first_zero, fringe = characteristic_lengths(p)
            text += f"\n包络首零点：±{first_zero * 1000:.2f} mm"
            if fringe:
                text += f"\n干涉因子周期：{fringe * 1000:.3f} mm"
                text += "\n" + missing_order_note(round(self.width_control.value()), round(self.separation.value()))
        self.metrics.setText(text)
        if self.view.error:
            self.status.setText("预测暂停  |  " + self.view.error)
            self.status.setStyleSheet("color:#a33020;padding:4px;")
        elif self.view.data is not None:
            self.status.setText(f"远场准则通过  |  最短周期 {self.view.data.pixels_per_period:.1f} 像素"
                                f"  |  计算 {self.view.last_compute_ms:.2f} ms  |  视场 ±{self.view.data.span * 1000:g} mm")
            self.status.setStyleSheet("color:#28634c;padding:4px;")
        self.export_button.setEnabled(not self._exporting and self._report_is_current())

    def _report_is_current(self):
        view = self.view
        if self.mode.currentIndex() == 2 and (not self.slit_count.hasAcceptableInput() or
                self.slit_count.cleanText() != self.slit_count.textFromValue(self.slit_count.value())):
            return False
        for control in (self.wavelength, self.width_control, self.separation, self.distance):
            if (not control.spin.hasAcceptableInput() or
                    control.spin.cleanText() != control.spin.textFromValue(control.value())):
                return False
        key = (self.parameters(), max(1, round(view.plot_rect().width() * view.devicePixelRatioF())), view.height())
        return (not view.computing and not view.error and view.data is not None
                and view.revision > 0 and view.params == self.parameters()
                and view.result_key == key and view._key == key)

    def report_snapshot(self):
        if not self._report_is_current():
            raise ReportError("当前尚无与参数和视场一致的已完成有效结果，不能导出")
        return capture_snapshot(self.view.params, self.view.data, self.view.revision,
                                round(self.width_control.value()), round(self.separation.value()))

    def _choose_report_path(self, snapshot):
        dialog = QFileDialog(self, "导出 PDF 报告")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("PDF 报告 (*.pdf)")
        dialog.setDefaultSuffix("pdf")
        # Native dialog by default; do not bypass its overwrite confirmation.
        label = "单缝" if snapshot.params.mode == Mode.SINGLE else "双缝"
        if is_multi(snapshot.params):
            label = f"多缝_N{snapshot.params.slit_count}"
        dialog.selectFile(f"光纹_{label}_{snapshot.captured_at:%Y%m%d_%H%M%S}.pdf")
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return None
        files = dialog.selectedFiles()
        return files[0] if files else None

    def export_report(self):
        if self._exporting:
            return
        self._exporting = True
        self.export_button.setEnabled(False)
        try:
            # Capture before entering the modal dialog's nested event loop.
            snapshot = self.report_snapshot()
            path = self._choose_report_path(snapshot)
            if not path:
                return
            saved = write_pdf(snapshot, path)
            QMessageBox.information(self, "PDF 报告已保存", f"保存成功：\n{saved}")
        except Exception as exc:
            QMessageBox.warning(self, "无法导出 PDF 报告", f"报告未保存。\n{exc}")
        finally:
            self._exporting = False
            self.export_button.setEnabled(self._report_is_current())

    def restore_defaults(self):
        if self.mode.currentIndex() == 2:
            self.slit_count.blockSignals(True)
            self.slit_count.setValue(8)
            self.slit_count.blockSignals(False)
            self._load_values((550, 20, 60, 2.))
            self._changed()
            return
        self._active_group = 'legacy'
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(1)
        self.mode.blockSignals(False)
        # Restore values even when the current geometry has narrower limits.
        self.width_control.set_limits(10, 80)
        self.separation.set_limits(40, 250)
        for control, value in ((self.wavelength, 550), (self.width_control, 30),
                               (self.separation, 150), (self.distance, 1)):
            control.set_value(value)
        self._changed()

"""Small fourth-mode Qt branch; the approved circular scientific core is unchanged.

One numerical worker, one replaceable pending request, GUI-thread-only painting.
Images use linear pixel means through an explicitly labelled sqrt display transfer.
"""
from collections import deque
from dataclasses import dataclass
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal, Slot, QEvent, QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QMessageBox
from .gui import MainWindow, ParameterControl
from .report import ReportError
from .circular_model import (CircularParameters, ModelStatus, RingVisibility,
    assess_model, first_dark_radius, observation_half_span)
from .circular_sampling import (MAX_SCREEN_SIDE, MAX_PROFILE_POINTS, DisplayStatus,
    assess_sampling, prepare_screen, prepare_profile)

CIRCULAR_INDEX = 3
RING_TEXT = {RingVisibility.FULL: '第一暗环完整位于观察范围内',
             RingVisibility.PARTIAL: '第一暗环部分进入角区，中轴截面无首暗纹',
             RingVisibility.OUTSIDE: '第一暗环位于当前观察范围外'}


@dataclass(frozen=True)
class AiryGeometry:
    split: float
    screen: QRectF
    curve: QRectF
    side: int
    curve_pixels: int
    dpr: float


def airy_geometry(width, height, dpr):
    """Native physical-pixel square; unused area stays blank above the 383 cap."""
    split = float(round(width * .44))
    available = max(1., min(split - 70., height - 174.))
    side = min(MAX_SCREEN_SIDE, max(1, math.floor(available * dpr)))
    side -= int(side % 2 == 0)
    size = side / dpr
    left = round((54. + (split - 70. - size) / 2) * dpr) / dpr
    top = round((78. + max(0., height - 174. - size) / 2) * dpr) / dpr
    square = QRectF(left, top, size, size)
    curve = QRectF(split + 54., 78., max(1., width - split - 76.), max(1., height - 174.))
    return AiryGeometry(split, square, curve, side, max(1, math.floor(curve.width()*dpr)), float(dpr))


@dataclass(frozen=True)
class AiryRequest:
    revision: int
    key: tuple
    params: CircularParameters
    side: int
    curve_pixels: int
    profile_points: int
    input_ns: int


@dataclass(frozen=True)
class AiryResult:
    request: AiryRequest
    screen: object = None
    profile: object = None
    compute_ms: float = 0.
    error: str = ''


class _NumericalWorker(QObject):
    finished = Signal(object)

    @Slot(object)
    def compute(self, request):
        start = time.perf_counter_ns()
        try:
            screen = prepare_screen(request.params, request.side)
            profile = prepare_profile(request.params, request.profile_points)
            if screen.data is None or profile.data is None:
                raise RuntimeError('科学核心未返回当前请求的有效数据')
            payload = AiryResult(request, screen, profile, (time.perf_counter_ns()-start)/1e6)
        except Exception as exc:
            payload = AiryResult(request, compute_ms=(time.perf_counter_ns()-start)/1e6,
                                 error=f'{type(exc).__name__}: {exc}')
        self.finished.emit(payload)


class AiryView(QWidget):
    stateChanged = Signal()
    presented = Signal(int, float)
    _compute = Signal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(450, 350)
        self.setAccessibleName('艾里斑二维观察屏与过圆心线性相对光强截面')
        self.params = CircularParameters()
        self.active = False
        self.closed = False
        self.state = 'INACTIVE'
        self.reason = ''
        self.revision = 0
        self.request_key = None
        self.input_waiting = False
        self.result = None
        self._image = None
        self._polygon = None
        self._pending = None
        self._busy = False
        self._presented_revision = -1
        self.screen_assessment = None
        self.curve_assessment = None
        self.jobs_started = self.jobs_completed = self.discarded = 0
        self.max_inflight = 0
        self.paint_samples = deque(maxlen=1000)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._launch)
        self._thread = QThread(self)
        self._worker = _NumericalWorker()
        self._worker.moveToThread(self._thread)
        self._compute.connect(self._worker.compute, Qt.ConnectionType.QueuedConnection)
        self._worker.finished.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def geometry_data(self):
        return airy_geometry(self.width(), self.height(), self.devicePixelRatioF())

    def desired_key(self):
        g = self.geometry_data()
        return (self.params, g.side, g.curve_pixels, g.dpr, self.width(), self.height())

    def _clear(self):
        self.result, self._image, self._polygon = None, None, None

    def set_active(self, active):
        if self.closed: return
        if self.active == active: return
        self.active = active
        self.revision += 1
        self.request_key = None
        self._pending = None
        self._timer.stop()
        self._clear()
        if active: self.request_refresh()
        else:
            self.state = 'INACTIVE'
            self.stateChanged.emit()

    def set_parameters(self, params):
        self.input_waiting = False
        if self.state == 'COMPUTE_FAILED': self.request_key = None
        self.params = params
        self.request_refresh()

    def input_pending(self):
        if not self.active or self.closed: return
        self.input_waiting = True
        self.revision += 1
        self.request_key = None
        self._pending = None
        self._timer.stop()
        self._clear()
        self.state, self.reason = 'INPUT_PENDING', '请按回车或完成数值输入后计算'
        self.update(); self.stateChanged.emit()

    def request_refresh(self):
        if not self.active or self.closed or self.input_waiting: return
        key = self.desired_key()
        if key == self.request_key: return
        self.revision += 1
        self.request_key = key
        self._pending = None
        self._timer.stop()
        self._clear()
        model = assess_model(self.params)
        self.screen_assessment = self.curve_assessment = None
        if model.status != ModelStatus.VALID:
            self.state, self.reason = 'MODEL_INVALID', '远场模型不适用：' + model.reason
        else:
            g = self.geometry_data()
            self.screen_assessment = assess_sampling(self.params, g.side)
            # M endpoint points have M-1 physical display intervals, independently
            # of the denser numerical polyline used below.
            self.curve_assessment = assess_sampling(self.params, g.curve_pixels+1, endpoint_points=True)
            if self.screen_assessment.status != DisplayStatus.VALID:
                a = self.screen_assessment
                self.state = 'DISPLAY_UNDERSAMPLED'
                self.reason = (f'二维显示采样不足：当前 {g.side} 物理像素，至少需要 '
                               f'{a.required_count}；计算预算上限383。两图暂停。')
            elif self.curve_assessment.status != DisplayStatus.VALID:
                a = self.curve_assessment
                self.state = 'DISPLAY_UNDERSAMPLED'
                self.reason = (f'截面显示采样不足：横向 {g.curve_pixels} 物理像素，至少需要 '
                               f'{a.required_count-1}。两图暂停。')
            else:
                points = min(MAX_PROFILE_POINTS, 4*g.curve_pixels+1)
                self._pending = AiryRequest(self.revision, key, self.params, g.side,
                                            g.curve_pixels, points, time.perf_counter_ns())
                self.state, self.reason = 'CALCULATING', '正在计算当前参数…'
                self._timer.start()
        self.update(); self.stateChanged.emit()

    @Slot()
    def _launch(self):
        if self.closed or not self.active or self._busy or self._pending is None: return
        request, self._pending = self._pending, None
        self._busy = True
        self.jobs_started += 1
        self.max_inflight = max(self.max_inflight, 1)
        self._compute.emit(request)

    @Slot(object)
    def _completed(self, payload):
        assert QThread.currentThread() == self.thread(), 'GUI completion must run on the GUI thread'
        self._busy = False
        self.jobs_completed += 1
        request = payload.request
        if (self.closed or not self.active or request.revision != self.revision or
                request.key != self.request_key or request.key != self.desired_key()):
            self.discarded += 1
        elif payload.error:
            self._clear()
            self.state, self.reason = 'COMPUTE_FAILED', '计算失败，预测暂停：' + payload.error
            self.update(); self.stateChanged.emit()
        else:
            # QImage ownership, paths and every QWidget mutation stay on GUI thread.
            level = np.rint(255*np.sqrt(payload.screen.data.pixel_mean)).astype(np.uint8)
            rgb = np.repeat(level[::-1, :, None], 3, axis=2).copy()
            image = QImage(rgb.data, request.side, request.side, request.side*3,
                           QImage.Format.Format_RGB888).copy()
            image.setDevicePixelRatio(request.key[3])
            rect = self.geometry_data().curve
            p = payload.profile.data
            px = rect.left() + (p.x+p.half_span_m)/(2*p.half_span_m)*rect.width()
            py = rect.bottom() - p.intensity*rect.height()
            self._polygon = QPolygonF([QPointF(float(x), float(y)) for x,y in zip(px,py)])
            self.result, self._image = payload, image
            self.state, self.reason = 'DISPLAY_VALID', RING_TEXT[payload.screen.visibility]
            self.update(); self.stateChanged.emit()
        if self._pending is not None and not self._timer.isActive(): self._launch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.request_refresh()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, '_timer'):
            self.request_key = None
            self.request_refresh()
        return result

    def shutdown(self):
        if self.closed: return
        self.closed = True
        self.active = False
        self.revision += 1
        self._pending = None
        self._timer.stop()
        self._clear()
        # At most one running numerical job; no unbounded queued calculation.
        self._thread.quit()
        self._thread.wait()

    def screen_point(self, x_m, y_m):
        rect = self.geometry_data().screen
        s = observation_half_span(self.params)
        return QPointF(rect.left()+(x_m+s)/(2*s)*rect.width(),
                       rect.bottom()-(y_m+s)/(2*s)*rect.height())

    def curve_point(self, x_m, relative_intensity):
        rect = self.geometry_data().curve
        s = observation_half_span(self.params)
        return QPointF(rect.left()+(x_m+s)/(2*s)*rect.width(),
                       rect.bottom()-relative_intensity*rect.height())

    def paintEvent(self, event):
        if self.active and self.request_key != self.desired_key() and self.state != 'INPUT_PENDING':
            self.request_refresh()
        g = self.geometry_data()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#152a3d'))
        painter.drawText(QPointF(12, 27), '二维观察屏 · 艾里斑')
        painter.drawText(QPointF(g.split+12, 27), '过圆心截面 · I(x,0)/I(0)')
        painter.setPen(QColor('#526477'))
        painter.drawText(QPointF(g.split+12, 51), '线性相对光强；中心 I(0)=1')
        painter.setPen(QPen(QColor('#e2e8ee'), 1))
        painter.drawLine(QPointF(g.split, 12), QPointF(g.split, self.height()-12))
        painter.fillRect(g.screen, QColor('#eef1f4'))
        valid = self.result is not None and self.state == 'DISPLAY_VALID'
        if valid:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            # The point overload draws at native image DPR; no interpolation,
            # stretch, rescale or invented physical samples.
            painter.drawImage(g.screen.topLeft(), self._image)
        else:
            painter.setPen(QColor('#a33020' if self.state != 'CALCULATING' else '#526477'))
            painter.drawText(g.screen.adjusted(8,8,-8,-8),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                '正在计算…' if self.state == 'CALCULATING' else '预测暂停')
            painter.drawText(g.curve.adjusted(8,12,-8,-12), Qt.TextFlag.TextWordWrap, self.reason)
        painter.setPen(QPen(QColor('#8697a6'), 1))
        painter.drawRect(g.screen)
        if self.result is not None:
            span = self.result.profile.data.half_span_m
        elif assess_model(self.params).status == ModelStatus.VALID:
            span = observation_half_span(self.params)
        else: span = None
        if span is not None:
            for f in (0., .5, 1.):
                x = g.screen.left()+f*g.screen.width()
                y = g.screen.bottom()-f*g.screen.height()
                label = f'{(2*f-1)*span*1000:.2f}'
                painter.drawText(QRectF(x-29,g.screen.bottom()+5,58,20),Qt.AlignmentFlag.AlignCenter,label)
                painter.drawText(QRectF(g.screen.left()-49,y-10,42,20),Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,label)
            painter.drawText(QRectF(g.screen.left(),g.screen.bottom()+26,g.screen.width(),20),Qt.AlignmentFlag.AlignCenter,'x / mm')
            painter.drawText(QRectF(4,g.screen.top()-31,43,18),Qt.AlignmentFlag.AlignRight,'y / mm')
        painter.setPen(QColor('#526477'))
        painter.drawText(QRectF(12,self.height()-65,g.split-22,59),Qt.TextFlag.TextWordWrap,
            f'灰度=√(像素平均 I/I(0))，仅辅助观察\n{g.side}×{g.side} 原生物理像素；上限383\n灰度及RGB不作为测量光强')
        if valid:
            rect = g.curve
            for value in (0.,.25,.5,.75,1.):
                y = rect.bottom()-value*rect.height()
                painter.setPen(QPen(QColor('#e2e8ee'),1))
                painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
                painter.setPen(QColor('#526477'))
                painter.drawText(QRectF(g.split+4,y-10,42,20),Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,f'{value:g}')
            for f in (0.,.25,.5,.75,1.):
                x = rect.left()+f*rect.width()
                painter.setPen(QPen(QColor('#e2e8ee'),1))
                painter.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
                painter.setPen(QColor('#526477'))
                painter.drawText(QRectF(x-29,rect.bottom()+7,58,20),Qt.AlignmentFlag.AlignCenter,f'{(2*f-1)*span*1000:.2f}')
            painter.save(); painter.setClipRect(rect.adjusted(-1,-1,1,1))
            pen = QPen(QColor('#1266a6'),1.8); pen.setCosmetic(True); painter.setPen(pen)
            painter.drawPolyline(self._polygon); painter.restore()
        painter.setPen(QColor('#526477'))
        painter.drawText(QRectF(g.curve.left(),g.curve.bottom()+32,g.curve.width(),22),Qt.AlignmentFlag.AlignCenter,'横向位置 x / mm')
        painter.drawText(QRectF(g.split+12,self.height()-49,self.width()-g.split-20,42),Qt.TextFlag.TextWordWrap,
                         '蓝线：连续点光强；二维为像素面积均值\n共同视场、同一参数；不由灰度反推光强')
        painter.end()
        if valid and self._presented_revision != self.result.request.revision:
            self._presented_revision = self.result.request.revision
            ms = (time.perf_counter_ns()-self.result.request.input_ns)/1e6
            self.paint_samples.append(dict(revision=self._presented_revision,input_to_paint_ms=ms,
                compute_ms=self.result.compute_ms,side=g.side,curve_pixels=g.curve_pixels,dpr=g.dpr))
            self.presented.emit(self._presented_revision, ms)


@dataclass(frozen=True)
class CircularApertureGeometry:
    split: float
    opening: QRectF
    diameter_start: QPointF
    diameter_end: QPointF


def circular_aperture_geometry(width, diameter_um):
    split = width*.34
    # Schematic deliberately non-scale; diameter changes remain perceptible.
    radius = 9.+7.*(diameter_um-20.)/480.
    cx,cy = split/2.,41.
    opening = QRectF(cx-radius,cy-radius,2*radius,2*radius)
    return CircularApertureGeometry(split,opening,
        QPointF(opening.left(),opening.center().y()),QPointF(opening.right(),opening.center().y()))


class CircularApparatus(QWidget):
    def __init__(self):
        super().__init__(); self.setFixedHeight(83); self.diameter_um=100.
        self.setAccessibleName('圆孔正面示意：D为圆孔直径，不按比例')
    def schematic_geometry(self):return circular_aperture_geometry(self.width(),self.diameter_um)
    def set_diameter(self,value):self.diameter_um=value; self.update()
    def paintEvent(self,event):
        g=self.schematic_geometry(); p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#526477')); align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        p.drawText(QRectF(12,0,g.split-20,22),align,'圆孔正面示意（不按比例）')
        p.fillRect(g.opening.adjusted(-6,-3,6,3),QColor('#dce5ec'))
        p.setBrush(QColor('#ffffff')); p.setPen(QPen(QColor('#526477'),1)); p.drawEllipse(g.opening)
        p.setPen(QPen(QColor('#1266a6'),1)); p.drawLine(g.diameter_start,g.diameter_end)
        for x in (g.diameter_start.x(),g.diameter_end.x()):
            p.drawLine(QPointF(x,62),QPointF(x,g.diameter_start.y()))
            p.drawLine(QPointF(x,59),QPointF(x,65))
        p.drawLine(QPointF(g.diameter_start.x(),62),QPointF(g.diameter_end.x(),62))
        p.drawText(QRectF(g.opening.center().x()-68,65,136,17),Qt.AlignmentFlag.AlignCenter,f'D = {self.diameter_um:g} μm')
        p.setPen(QPen(QColor('#d4dfe7'),1));p.drawLine(QPointF(g.split,6),QPointF(g.split,77))
        left=g.split+12; right=self.width()-12
        p.setPen(QColor('#526477'));p.drawText(QRectF(left,0,right-left,22),align,'装置示意（不按比例）')
        board=left+70; screen=right-25
        p.setPen(QPen(QColor('#8697a6'),2));p.drawLine(QPointF(board,29),QPointF(board,60));p.drawLine(QPointF(screen,29),QPointF(screen,60))
        p.fillRect(QRectF(board-3,39,6,10),QColor('#ffffff'))
        p.setPen(QPen(QColor('#1266a6'),1))
        for y in (34,44,54):p.drawLine(QPointF(left+5,y),QPointF(board-12,y))
        p.drawLine(QPointF(board+16,46),QPointF(screen-12,46))
        p.drawText(QRectF(board+16,26,screen-board-28,18),Qt.AlignmentFlag.AlignCenter,'屏距 z')
        p.setPen(QColor('#526477'));p.drawText(QRectF(board-32,64,64,18),Qt.AlignmentFlag.AlignCenter,'圆孔板')
        p.drawText(QRectF(screen-30,64,60,18),Qt.AlignmentFlag.AlignCenter,'观察屏');p.end()


class AiryMainWindow(MainWindow):
    def __init__(self):
        # super initializes signals and calls the overridable _changed method.
        self._airy_ready = False
        super().__init__()
        controls = self.mode.parentWidget().layout()
        self.circular_controls = QWidget()
        box = QVBoxLayout(self.circular_controls);box.setContentsMargins(0,0,0,0)
        self.circular_wavelength=ParameterControl('波长 λ','nm',380,750,1,550)
        self.circular_diameter=ParameterControl('圆孔直径 D','μm',20,500,1,100)
        self.circular_distance=ParameterControl('观察屏距离 z','m',.5,3.,.01,1.,2)
        for control in self._circular_controls():
            box.addWidget(control);control.changed.connect(self._changed)
            control.spin.lineEdit().textEdited.connect(self._pending_circular_input)
            control.spin.editingFinished.connect(self._changed)
        controls.insertWidget(controls.indexOf(self.wavelength),self.circular_controls)
        self.circular_controls.hide()
        right=self.centralWidget().layout().itemAt(2).layout().itemAt(1).layout()
        self.view_stack=QStackedWidget(); self.view_stack.setContentsMargins(0,0,0,0)
        right.removeWidget(self.view);right.insertWidget(0,self.view_stack,1)
        self.view_stack.addWidget(self.view)
        self.airy_view=AiryView();self.view_stack.addWidget(self.airy_view)
        self.apparatus_stack=QStackedWidget();self.apparatus_stack.setFixedHeight(83)
        right.removeWidget(self.apparatus);right.addWidget(self.apparatus_stack)
        self.apparatus_stack.addWidget(self.apparatus)
        self.circular_apparatus=CircularApparatus();self.apparatus_stack.addWidget(self.circular_apparatus)
        self.airy_view.stateChanged.connect(self._update_status)
        self.mode.addItem('圆孔夫琅禾费衍射')
        self._airy_ready=True
        self._update_status()

    def _circular_controls(self):
        return (self.circular_wavelength,self.circular_diameter,self.circular_distance)

    def is_circular(self):return self._airy_ready and self.mode.currentIndex()==CIRCULAR_INDEX

    def circular_parameters(self):
        return CircularParameters.from_display_units(*(c.value() for c in self._circular_controls()))

    def parameters(self):
        return self.circular_parameters() if self.is_circular() else super().parameters()

    def _mode_changed(self):
        if not self._airy_ready:return super()._mode_changed()
        circular=self.is_circular()
        if circular:
            # A stable two-line status row prevents compute/valid text wrapping
            # from repeatedly resizing the scientific viewport and invalidating it.
            self.status.setFixedHeight(2*self.fontMetrics().lineSpacing()+12)
        else:
            self.status.setMinimumHeight(0);self.status.setMaximumHeight(16777215)
        self.circular_controls.setVisible(circular)
        for control in (self.wavelength,self.width_control,self.separation,self.distance):control.setVisible(not circular)
        self.view_stack.setCurrentWidget(self.airy_view if circular else self.view)
        self.apparatus_stack.setCurrentWidget(self.circular_apparatus if circular else self.apparatus)
        self.airy_view.set_active(circular)
        if circular:self._changed()
        else:super()._mode_changed()

    def _pending_circular_input(self):
        if self.is_circular():self.airy_view.input_pending()

    def _changed(self):
        if not self.is_circular():return super()._changed()
        self.slit_count_row.hide()
        self.geometry_note.setText('D 为圆孔直径；不自动改写参数。圆孔 PDF 本轮暂不可用。')
        self.export_button.setToolTip('圆孔 PDF 尚未实现；A4-3 再接入。原三种实验模式可正常导出。')
        self.model_note.setText('模型：理想圆孔，单色相干均匀平面波垂直入射；标量、傍轴、夫琅禾费远场。\n'
            'I/I(0)=[2J₁(u)/u]²，u=πDρ/(λz)，ρ=√(x²+y²)；F=(D/2)²/(λz)≤0.05，ρ/z≤0.05。\n'
            '二维为像素面积均值，截面为连续点光强；相对归一化峰高不可比较实际透射功率。')
        if any(not c.spin.hasAcceptableInput() or c.spin.cleanText()!=c.spin.textFromValue(c.value()) for c in self._circular_controls()):
            self.airy_view.input_pending();return
        self.circular_apparatus.set_diameter(self.circular_diameter.value())
        self.airy_view.set_parameters(self.circular_parameters())
        self._update_status()

    def _update_status(self):
        if not self.is_circular():
            if self._airy_ready:self.export_button.setToolTip('导出当前已完成的有效结果；数值输入请先回车确认。')
            return super()._update_status()
        v=self.airy_view;p=self.circular_parameters();model=assess_model(p)
        text=f'圆孔直径 D = {p.diameter*1e6:g} μm\nF = {model.fresnel_number:.6f}（上限0.05）'
        if model.status==ModelStatus.VALID and v.state!='INPUT_PENDING':
            text+=f'\n第一暗环理论半径：{first_dark_radius(p)*1e3:.3f} mm'
            text+=f'\n观察范围：x、y各 ±{observation_half_span(p)*1e3:.2f} mm'
        else:text+='\n当前不提供可靠图样预测'
        self.metrics.setText(text)
        good=v.state=='DISPLAY_VALID' and v.result is not None
        if good:
            self.status.setText(f'远场准则通过  |  {v.reason}  |  二维 {v.screen_assessment.pixels_per_period:.1f} 像素/最短周期'
                f'  |  截面 {v.curve_assessment.pixels_per_period:.1f} 像素/最短周期')
        else:self.status.setText(('计算中  |  ' if v.state=='CALCULATING' else '预测暂停  |  ')+v.reason)
        self.status.setStyleSheet('color:#28634c;padding:4px;' if good else 'color:#a33020;padding:4px;')
        self.export_button.setEnabled(False)

    def _report_is_current(self):return False if self.is_circular() else super()._report_is_current()

    def report_snapshot(self):
        if self.is_circular():raise ReportError('圆孔 PDF 尚未实现，不能调用狭缝报告捕获器')
        return super().report_snapshot()

    def export_report(self):
        if self.is_circular():
            QMessageBox.information(self,'圆孔报告暂不可用','本轮仅提供圆孔 GUI。圆孔 PDF 将在 A4-3 实现。');return
        return super().export_report()

    def restore_defaults(self):
        if not self.is_circular():return super().restore_defaults()
        for c,value in zip(self._circular_controls(),(550,100,1.)):c.set_value(value)
        self._changed()

    def closeEvent(self,event):
        if self._airy_ready:self.airy_view.shutdown()
        super().closeEvent(event)

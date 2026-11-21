"""Native-pixel multi-aperture observation screen, horizontal profile and pupil."""
from dataclasses import dataclass
import math
import time

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from .circular_gui import AiryRequest, AiryView
from .multiaperture_model import Layout, MultiApertureParameters
from .multiaperture_sampling import SamplingDecision, assess_gui, prepare_profile, prepare_screen


# Bound the drawn native-pixel square and the corresponding allocation together.
MAX_GUI_SIDE = 767
PRESETS = {Layout.PAIR: '双圆孔', Layout.TRIANGLE: '等边三圆孔',
           Layout.SQUARE: '正方形四圆孔', Layout.RECTANGLE: '矩形四圆孔'}
DEFAULT_PARAMS = MultiApertureParameters(diameter_m=60e-6, spacing_m=100e-6)
INK = QColor('#203448')
MUTED = QColor('#526477')
RULE = QColor('#dce5ec')
BLUE = QColor('#1266a6')
CENTER = Qt.AlignmentFlag.AlignCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


@dataclass(frozen=True)
class PlotGeometry:
    split: int
    screen: QRectF
    curve: QRectF
    pupil: QRectF
    side: int
    curve_pixels: int
    dpr: float


def plot_geometry(width, height, dpr, origin):
    """Align image edges and the first/last curve pixel centres to the backing store."""
    ox, oy = origin.x(), origin.y()
    split = round(width*.51)
    left, right = math.ceil((ox+44)*dpr), math.floor((ox+split-12)*dpr)
    top, bottom = math.ceil((oy+82)*dpr), math.floor((oy+height-61)*dpr)
    side = max(1, min(right-left, bottom-top, MAX_GUI_SIDE))
    sx = (left + (right-left-side)//2)/dpr - ox
    sy = (top + (bottom-top-side)//2)/dpr - oy
    screen = QRectF(sx, sy, side/dpr, side/dpr)
    first = math.ceil((ox+split+38)*dpr)
    last = max(first+1, math.floor((ox+width-16)*dpr)-1)
    divider = round(height*.56)
    curve = QRectF((first+.5)/dpr-ox, 66., (last-first)/dpr, divider-112.)
    pupil = QRectF(split+12., divider+35., width-split-24., height-divider-76.)
    return PlotGeometry(split, screen, curve, pupil, side, last-first+1, dpr)


@dataclass(frozen=True)
class ArrayRequest(AiryRequest):
    params: MultiApertureParameters
    sampling: SamplingDecision


def _array_data(request):
    """Worker entry. Each data call has its own frozen C1 admission check."""
    plan = request.sampling
    field = plan.model.field
    screen = (prepare_screen(request.params, *plan.grid.counts_xy, field=field)
              if plan.grid.valid else None)
    profile = (prepare_profile(request.params, plan.profile.points, field=field)
               if plan.profile.valid else None)
    return screen, profile


def _heading(painter, x, y, title):
    painter.save()
    font = painter.font()
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(INK)
    painter.drawText(QPointF(x, y), title)
    painter.restore()


def _draw_pupil_scale(painter, row, pixels_per_m):
    """Use the disks' isotropic Qt coordinate scale for the tick-to-tick distance."""
    pixels_per_um = pixels_per_m * 1e-6
    target_um = 0.275 * row.width() / pixels_per_um
    decade = 10 ** math.floor(math.log10(target_um))
    length_um = min((step * decade for step in (1, 2, 5, 10)),
                    key=lambda value: abs(value - target_um))
    length = length_um * pixels_per_um
    label = f'{length_um:g} μm · 自动缩放'
    label_width = painter.fontMetrics().horizontalAdvance(label) + 4
    gap = 8
    left = row.center().x() - (length + gap + label_width) / 2
    right = left + length
    y = row.center().y()
    painter.setPen(QPen(INK, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.drawLine(QPointF(left, y), QPointF(right, y))
    for x in (left, right):
        painter.drawLine(QPointF(x, y - 3.5), QPointF(x, y + 3.5))
    painter.setPen(MUTED)
    painter.drawText(QRectF(right + gap, row.top(), label_width, row.height()), LEFT, label)


class MultiApertureView(AiryView):
    def __init__(self):
        super().__init__(_array_data)
        self.params = DEFAULT_PARAMS
        self.decision = None
        self.setAccessibleName('多圆孔二维观察屏、水平中心截面与孔径正面排列')

    def geometry_data(self):
        return plot_geometry(self.width(), self.height(), self.devicePixelRatioF(),
                             self.mapTo(self.window(), QPoint(0, 0)))

    def desired_key(self):
        g = self.geometry_data()
        return (self.params, g.side, g.curve_pixels, g.dpr, g.screen.getRect(), g.curve.getRect(),
                self.width(), self.height())

    def _clear(self):
        super()._clear()
        self.decision = None

    def request_refresh(self):
        if not self.active or self.closed or self.input_waiting:
            return
        started = time.perf_counter_ns()
        key = self.desired_key()
        if key == self.request_key:
            return
        self.request_key = key
        self.revision += 1
        self._pending = None
        self._timer.stop()
        self._clear()
        _, side, points, *_ = key
        plan = assess_gui(self.params, side, side, points)
        self.decision = plan
        if not plan.model.valid:
            self.state = 'MODEL_INVALID'
            if plan.model.reason.startswith('Holes overlap'):
                self.reason = '圆孔发生重叠。每个方向的中心距都须大于或等于孔径。'
            elif plan.model.reason.startswith('Whole-array'):
                self.reason = '整个孔阵列超出远场条件。可增大屏距，或减小孔径、中心距。'
            else:
                self.reason = '模型参数或观察范围超出适用条件。'
        elif plan.grid.valid or plan.profile.valid:
            self.state, self.reason = 'CALCULATING', '正在计算当前参数…'
            self._pending = ArrayRequest(self.revision, key, self.params, side, points, points,
                                         started, plan)
            self._timer.start()
        else:
            self.state, self.reason = 'DISPLAY_UNDERSAMPLED', self.sampling_note()
        self.update()
        self.stateChanged.emit()

    def sampling_note(self):
        plan = self.decision
        nx, ny = plan.grid.required_xy
        side = plan.grid.counts_xy[0]
        points = plan.profile.points
        screen = (f'二维 {side}×{side} 像素' if plan.grid.valid else
                  f'二维采样不足（当前 {side}×{side}，至少 {nx}×{ny}）')
        if plan.profile.valid:
            line = f'截面 {points} 点'
        elif points < plan.profile.required_points:
            line = f'截面采样不足（当前 {points} 点，至少 {plan.profile.required_points} 点）'
        else:
            line = '截面坐标无法可靠表示'
        return screen + '  |  ' + line

    def _display_result(self, payload):
        g = self.geometry_data()
        if payload.screen is not None:
            gray = np.ascontiguousarray(np.rint(255*np.sqrt(payload.screen.pixel_mean[::-1])).astype(np.uint8))
            self._image = QImage(gray.data, g.side, g.side, gray.strides[0],
                                 QImage.Format.Format_Grayscale8).copy()
            self._image.setDevicePixelRatio(g.dpr)
        if payload.profile is not None:
            line = payload.profile
            half = self.decision.model.field.half_x_m
            x = g.curve.left() + (line.position_m+half)/(2*half)*g.curve.width()
            y = g.curve.bottom() - line.point_intensity*g.curve.height()
            self._polygon = QPolygonF([QPointF(float(a), float(b)) for a,b in zip(x, y)])
        self.result = payload
        self.state = 'DISPLAY_VALID' if self.decision.status == 'GUI_SAMPLE_VALID' else 'DISPLAY_PARTIAL'
        self.reason = self.sampling_note()

    def _placeholder(self, screen):
        plan = self.decision
        if plan is not None and plan.model.valid:
            if screen and not plan.grid.valid:
                nx, ny = plan.grid.required_xy
                return f'二维采样不足\n至少需要 {nx}×{ny} 物理像素'
            if not screen and not plan.profile.valid:
                if plan.profile.points < plan.profile.required_points:
                    return f'截面采样不足\n至少需要 {plan.profile.required_points} 个显示点'
                return '截面坐标无法可靠表示'
        if self.state == 'CALCULATING':
            return '正在计算…'
        if self.state == 'INPUT_PENDING':
            return '等待确认输入'
        return '模型不适用' if self.state == 'MODEL_INVALID' else '预测暂停'

    def _draw_screen(self, p, g, half):
        r = g.screen
        _heading(p, 12, 25, '二维观察屏')
        p.setPen(MUTED)
        p.drawText(QPointF(12, 49), '灰度 √⟨I/I(0)⟩ · 像素面积均值')
        edge = 1/g.dpr
        p.fillRect(r.adjusted(-edge,-edge,edge,edge), RULE)
        if self._image is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawImage(r.topLeft(), self._image)
        else:
            p.fillRect(r, QColor('#f2f5f8'))
            p.drawText(r.adjusted(5,0,-5,0), CENTER, self._placeholder(True))
        if half is not None:
            for f in (0., .5, 1.):
                label = f'{(2*f-1)*half*1000:.1f}'
                x, y = r.left()+f*r.width(), r.bottom()-f*r.height()
                box = QRectF(max(2., min(x-25, g.split-52.)),r.bottom()+3,50,20)
                p.drawText(box, CENTER, label)
                p.drawText(QRectF(r.left()-43,y-10,39,20), RIGHT, label)
            p.drawText(QRectF(max(4.,r.left()-39),r.top()-28,83,20), LEFT, 'y / mm')
            p.drawText(QRectF(r.left(),r.bottom()+23,r.width(),20), CENTER, 'x / mm')

    def _draw_curve(self, p, g, half):
        r = g.curve
        _heading(p, g.split+12, 25, '水平中心截面')
        p.setPen(MUTED)
        p.drawText(QPointF(g.split+12, 49), '线性相对光强 I(x, 0) / I(0)')
        for f in (0., .5, 1.):
            x, y = r.left()+f*r.width(), r.bottom()-f*r.height()
            p.setPen(QPen(RULE, 1))
            p.drawLine(QPointF(r.left(),y), QPointF(r.right(),y))
            p.drawLine(QPointF(x,r.top()), QPointF(x,r.bottom()))
            p.setPen(MUTED)
            p.drawText(QRectF(r.left()-34,y-10,28,20), RIGHT, f'{f:g}')
            if half is not None:
                label = f'{(2*f-1)*half*1000:.1f}'
                box = QRectF(x-25, r.bottom()+3, 50, 20)
                box.moveLeft(min(box.left(), self.width()-box.width()-2))
                p.drawText(box, CENTER, label)
        p.drawText(QRectF(r.left(), r.bottom()+22, r.width(), 20), CENTER, 'x / mm')
        if self._polygon is None:
            p.drawText(r, CENTER, self._placeholder(False))
        else:
            p.save()
            p.setClipRect(r.adjusted(-1,-1,1,1))
            pen = QPen(BLUE, 1.6)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPolyline(self._polygon)
            p.restore()

    def _draw_pupil(self, p, g):
        box = g.pupil
        y = box.top()-35
        p.setPen(QPen(RULE, 1))
        p.drawLine(QPointF(g.split+10,y), QPointF(self.width()-12,y))
        _heading(p, g.split+12, y+24, '孔径正面 · '+PRESETS[self.params.layout])
        p.fillRect(box, QColor('#e5edf4'))
        model = self.decision.model if self.decision is not None else None
        if model is None or model.geometry is None:
            p.setPen(MUTED)
            p.drawText(box, CENTER, '等待确认输入' if self.input_waiting else '孔径几何无效')
            return
        centers = model.geometry.centers_m
        radius = self.params.diameter_m/2
        xx, yy = zip(*centers)
        scale = min((box.width()-34)/(max(xx)-min(xx)+2*radius),
                    (box.height()-24)/(max(yy)-min(yy)+2*radius))
        cx, cy = (max(xx)+min(xx))/2, (max(yy)+min(yy))/2
        p.setPen(QPen(MUTED, 1.2))
        p.setBrush(QColor('white'))
        for x, y in centers:
            point = box.center()+QPointF((x-cx)*scale, (cy-y)*scale)
            p.drawEllipse(point, radius*scale, radius*scale)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(MUTED)
        p.drawText(box.adjusted(6,3,-6,-3), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, 'y ↑')
        p.drawText(box.adjusted(6,3,-6,-3), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, 'x →')
        a = self.params
        gap = f'{a.spacing_m*1e6:g}'
        if a.layout == Layout.RECTANGLE:
            gap += f' × {a.spacing_y_m*1e6:g}'
        # Two caption rows below the pupil leave its fit, circles and axes intact.
        row = QRectF(box.left(), box.bottom()+1, box.width(), (self.height()-box.bottom()-2)/2)
        _draw_pupil_scale(p, row, scale)
        p.drawText(row.translated(0, row.height()), CENTER,
                   f'孔径 {a.diameter_m*1e6:g} μm    中心距 {gap} μm')

    def paintEvent(self, event):
        if self.active and not self.input_waiting and self.request_key != self.desired_key():
            self.request_refresh()
        g = self.geometry_data()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('white'))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(RULE, 1))
        p.drawLine(QPointF(g.split,12), QPointF(g.split,self.height()-12))
        field = self.decision.model.field if self.decision is not None else None
        half = field.half_x_m if field is not None else None
        self._draw_screen(p, g, half)
        self._draw_curve(p, g, half)
        self._draw_pupil(p, g)
        p.end()
        if self.result is not None:
            self._record_paint(g)

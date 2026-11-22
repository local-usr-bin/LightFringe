"""Independent two-page PDF reports for the coherent circular-aperture presets."""
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import math
from pathlib import Path
from threading import Lock

import numpy as np
from PySide6.QtCore import QBuffer, QFileDevice, QIODevice, QRectF, QSaveFile, QThread, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPdfWriter, QPen

from .multiaperture_model import Field, Layout, MultiApertureParameters, assess_model
from .multiaperture_sampling import (
    MIN_INTERVALS_PER_PERIOD, PDF_PROFILE_POINTS, ProfileData, SamplingDecision, ScreenData,
    assess_pdf, prepare_profile, prepare_screen,
)
from .report import ReportError, local_now
from .report_layout import (
    INK, MUTED, RULE, SOFT, SOFTWARE, TEAL, Page, configure_writer, draw_profile,
)


LAYOUT_NAMES = {Layout.PAIR: "双圆孔", Layout.TRIANGLE: "等边三圆孔",
                Layout.SQUARE: "正方形四圆孔", Layout.RECTANGLE: "矩形四圆孔"}
LAYOUT_NOTES = {
    Layout.PAIR: "两孔中心连线决定干涉条纹的法向。",
    Layout.TRIANGLE: "三组孔对方向不同，构成二维干涉图样。",
    Layout.SQUARE: "两个正交方向具有相同的孔心距。",
    Layout.RECTANGLE: "两条正交边的中心距分别决定各自的干涉周期。",
}


class ExportCancelled(ReportError):
    """Cancellation before the atomic replacement of the destination."""


class ExportControl:
    """Serialize the last cancellation check with the atomic commit."""

    def __init__(self):
        self._lock = Lock()
        self._cancelled = False
        self.committed = False

    def cancel(self):
        with self._lock:
            if not self.committed:
                self._cancelled = True

    def checkpoint(self):
        with self._lock:
            self._check_locked()

    def _check_locked(self):
        if self._cancelled:
            raise ExportCancelled("多圆孔报告导出已取消")

    def commit(self, device):
        with self._lock:
            self._check_locked()
            if not device.commit():
                raise OSError(f"PDF 原子保存失败：{device.errorString()}")
            self.committed = True


def _model_error(reason):
    if reason.startswith("Holes overlap"):
        return "圆孔重叠，中心距须大于或等于孔径。"
    if reason.startswith("Whole-array"):
        return f"整阵远场条件未通过。{reason}"
    return f"模型不适用：{reason}"


def pdf_plan(params, field=None):
    """Resolve the physical field, then apply C1's complete horizontal PDF gate."""
    model = assess_model(params, field)
    if not model.valid:
        raise ReportError(_model_error(model.reason))
    plan = assess_pdf(params, field=model.field, profile_angle_deg=0)
    if plan.status == "PDF_SAMPLE_VALID":
        return plan
    if not plan.model.valid:
        raise ReportError(_model_error(plan.model.reason))
    reasons = []
    if not plan.grid.valid:
        nx, ny = plan.grid.required_xy
        width, height = plan.grid.counts_xy
        reasons.append(f"二维采样至少需要 {nx} × {ny}，最高档为 {width} × {height}")
    if not plan.profile.valid:
        if plan.profile.points < plan.profile.required_points:
            reasons.append(f"水平截面至少需要 {plan.profile.required_points} 点，预算为 {plan.profile.points} 点")
        else:
            reasons.append("水平截面坐标或实际步距无法可靠表示")
    raise ReportError("PDF 采样不合格：" + "。".join(reasons))


@dataclass(frozen=True)
class ReportRequest:
    params: MultiApertureParameters
    field: Field
    captured_at: datetime


@dataclass(frozen=True)
class ReportSnapshot:
    request: ReportRequest
    plan: SamplingDecision
    screen: ScreenData
    profile: ProfileData
    data_sha256: str


def capture_request(params, *, field=None):
    plan = pdf_plan(params, field)
    return ReportRequest(params, plan.model.field, local_now())


def _freeze(array):
    # A bytes-backed view cannot be made writable by a second consumer.
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def _data_identity(request, screen, profile):
    digest = hashlib.sha256(repr((request.params, request.field, request.captured_at)).encode())
    for values in (screen.x_centers_m, screen.y_centers_m, screen.pixel_mean,
                   profile.position_m, profile.point_intensity):
        digest.update(values.dtype.str.encode())
        digest.update(memoryview(values).cast("B"))
    return digest.hexdigest()


def build_snapshot(request, control=None):
    control = control or ExportControl()
    control.checkpoint()
    p, field = request.params, request.field
    plan = pdf_plan(p, field)
    side = plan.selected_pdf_side
    screen = prepare_screen(p, side, side, field=field)
    control.checkpoint()
    profile = prepare_profile(p, PDF_PROFILE_POINTS, field=field, profile_angle_deg=0)
    control.checkpoint()
    screen = replace(screen, x_centers_m=_freeze(screen.x_centers_m), y_centers_m=_freeze(screen.y_centers_m),
                     pixel_mean=_freeze(screen.pixel_mean))
    profile = replace(profile, position_m=_freeze(profile.position_m), point_intensity=_freeze(profile.point_intensity))
    return ReportSnapshot(request, plan, screen, profile, _data_identity(request, screen, profile))


def _validate_snapshot(s):
    if not isinstance(s, ReportSnapshot):
        raise ReportError("多圆孔 PDF 需要已完成的科学快照")
    plan = pdf_plan(s.request.params, s.request.field)
    n = plan.selected_pdf_side
    if (s.plan != plan or s.screen.sampling != plan.grid or s.profile.sampling != plan.profile
            or s.screen.pixel_mean.shape != (n, n) or s.screen.x_centers_m.shape != (n,)
            or s.screen.y_centers_m.shape != (n,) or s.profile.position_m.shape != (PDF_PROFILE_POINTS,)
            or s.profile.point_intensity.shape != (PDF_PROFILE_POINTS,)
            or _data_identity(s.request, s.screen, s.profile) != s.data_sha256):
        raise ReportError("多圆孔快照与请求或采样数据不一致")


def display_gray(screen):
    """Only the display transform changes intensity; the top raster row is +y."""
    return np.ascontiguousarray(np.rint(255 * np.sqrt(screen.pixel_mean[::-1])).astype(np.uint8))


def _arrangement(params):
    spacing = f"{params.spacing_m * 1e6:g}"
    if params.layout == Layout.RECTANGLE:
        spacing += f" × {params.spacing_y_m * 1e6:g}"
    direction = "顶点朝上" if params.layout == Layout.TRIANGLE else f"{params.angle_deg:g}°"
    return spacing + " μm", direction


def _screen_plot(page, snapshot):
    field = snapshot.request.field
    side = 380.0
    scale = side / (2 * max(field.half_x_m, field.half_y_m))
    width, height = 2 * field.half_x_m * scale, 2 * field.half_y_m * scale
    rect = QRectF((page.w-width)/2, 291+(side-height)/2, width, height)
    gray = display_gray(snapshot.screen)
    ny, nx = gray.shape
    image = QImage(gray.data, nx, ny, gray.strides[0], QImage.Format.Format_Grayscale8).copy()
    page.graphic("screen", rect, grid=[nx, ny], points_per_m=scale)
    page.p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    page.p.drawImage(rect, image)
    page.p.setBrush(Qt.BrushStyle.NoBrush)
    page.p.setPen(QPen(RULE, .65))
    page.p.drawRect(rect)
    # Only space tick labels as densely as their physical plot dimensions allow.
    for axis, extent, span in (("x", width, field.half_x_m), ("y", height, field.half_y_m)):
        fractions = (-1., -.5, 0., .5, 1.) if extent >= 215 else ((-1., 0., 1.) if extent >= 112 else (0.,))
        for i, f in enumerate(fractions):
            value = f"{f * span * 1000:.2f}"
            if axis == "x":
                x = rect.center().x() + f*width/2
                page.line(x, rect.bottom(), x, rect.bottom()+4, MUTED)
                box = QRectF(x-25, rect.bottom()+6, 50, 17)
                align = Qt.AlignmentFlag.AlignHCenter
            else:
                y = rect.center().y() - f*height/2
                page.line(rect.left()-4, y, rect.left(), y, MUTED)
                box = QRectF(0, y-7, rect.left()-8, 16)
                align = Qt.AlignmentFlag.AlignRight
            page.text(f"screen-{axis}-{i}", box, value, 9.5, align=align, color=MUTED)
    page.text("screen-x-unit", QRectF(0, 697, page.w, 18), "观察屏横向位置 x / mm", 9.5,
              align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)


def _first_page(page, s):
    p, field = s.request.params, s.request.field
    name = LAYOUT_NAMES[p.layout]
    spacing, direction = _arrangement(p)
    side = s.plan.selected_pdf_side
    page.header("多圆孔干涉与衍射", f"{name}  ·  {SOFTWARE}", s.request.captured_at)
    page.cards("inputs", 130, 49, [("波长 λ", f"{p.wavelength_m*1e9:g} nm"),
               ("圆孔直径 D", f"{p.diameter_m*1e6:g} μm"), ("屏距 z", f"{p.distance_m:.2f} m")])
    page.cards("array", 186, 49, [("孔心距" if p.layout != Layout.RECTANGLE else "孔心距（两条边）", spacing),
               ("排列方向", direction), ("PDF 科学网格", f"{side} × {side}")], results=True)
    page.heading("image-heading", 246, "二维相对光强")
    page.text("mapping", QRectF(156, 250, page.w-156, 18), "灰度 = round(255 × √I)，I 为单元平均相对光强",
              9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    page.text("field", QRectF(0, 271, page.w, 16),
              f"x、y 半宽分别为 {field.half_x_m*1000:.4f}、{field.half_y_m*1000:.4f} mm。纵轴 y / mm 向上。", 9.5, color=MUTED)
    _screen_plot(page, s)
    page.footer(2)


def _pupil(page, s):
    p = s.request.params
    centers = s.plan.model.geometry.centers_m
    xs, ys = zip(*centers)
    d = p.diameter_m
    box = QRectF(0, 310, 201, 98)
    page.p.fillRect(box, SOFT)
    scale = min((box.width()-22)/(max(xs)-min(xs)+d), (box.height()-14)/(max(ys)-min(ys)+d))
    cx, cy = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2
    page.p.setBrush(QColor("white"))
    page.p.setPen(QPen(TEAL, 1.05))
    for i, (x, y) in enumerate(centers):
        circle = QRectF(box.center().x()+(x-cx-d/2)*scale,
                        box.center().y()+(cy-y-d/2)*scale, d*scale, d*scale)
        page.graphic(f"hole-{i}", circle, center_m=[x, y], points_per_m=scale)
        page.p.drawEllipse(circle)
    x = box.right()+16
    w = page.w-x
    spacing, direction = _arrangement(p)
    page.text("pupil-name", QRectF(x, 309, w, 18), LAYOUT_NAMES[p.layout]+"  ·  x 向右，y 向上", 11, True)
    page.text("pupil-sizes", QRectF(x, 331, w, 17), f"直径 {d*1e6:g} μm   孔心距 {spacing}", 10.5)
    page.text("pupil-direction", QRectF(x, 351, w, 17),
              f"排列方向 {direction}"+("（从 +x 逆时针）" if p.layout != Layout.TRIANGLE else ""), 10.5)
    page.text("pupil-note", QRectF(x, 371, w, 17), LAYOUT_NOTES[p.layout], 9.5, color=MUTED)
    target_um = 58 / (scale*1e-6)
    decade = 10**math.floor(math.log10(target_um))
    length_um = min((n*decade for n in (1, 2, 5, 10)), key=lambda v: abs(v-target_um))
    length = length_um*1e-6*scale
    y = 400
    page.graphic("pupil-scale", QRectF(x, y-3, length, 6), length_um=length_um, points_per_m=scale)
    page.line(x, y, x+length, y, INK, 1.1)
    for tick in (x, x+length):
        page.line(tick, y-3, tick, y+3, INK, 1.1)
    page.text("scale-label", QRectF(x+length+8, y-7, w-length-8, 16), f"{length_um:g} μm", 9.5)


def _second_page(page, s):
    page.header("过圆心截面与科学方法", f"{LAYOUT_NAMES[s.request.params.layout]}  ·  {SOFTWARE}")
    page.text("curve-title", QRectF(0, 105, page.w, 20), "水平截面  ·  线性相对光强 I(x,0)/I(0)", 12, True)
    plot = QRectF(38, 135, page.w-64, 101)
    draw_profile(page, plot, s.profile.position_m, s.profile.point_intensity,
                 s.profile.sampling.half_length_m, decimals=2)
    page.heading("pupil-heading", 282, "孔径正面与物理比例尺")
    _pupil(page, s)
    page.heading("formula-heading", 421, "单圆孔衍射包络与阵列干涉")
    page.formula(448, "I(x,y)/I(0) = [2 J₁(u)/u]² × |S|²",
                 "u = π D r/(λ z)，S = (1/N) Σ exp[−iφ(j)]，对 j = 1 至 N 求和。", height=57)
    page.text("variables", QRectF(0, 509, page.w, 57),
              "φ(j) = 2π[x X(j) + y Y(j)]/(λ z)。x、y 为屏坐标，X(j)、Y(j) 为孔心坐标，i² = −1。\n"
              "r 为离轴距离。D、λ、z、N 分别为孔径、波长、屏距与孔数。\n"
              "J₁ 为第一类一阶贝塞尔函数。方括号平方为单孔包络，|S|² 为阵列因子，轴上极限为 1。")
    page.heading("sampling-heading", 568, "数值采样")
    nx, ny = s.plan.grid.required_xy
    page.text("method", QRectF(0, 593, page.w, 50),
              f"二维至少需要 {nx} × {ny} 格，实际采用 {s.plan.selected_pdf_side} × {s.plan.selected_pdf_side}。"
              "每格用 2 × 2 Gauss-Legendre 面积均值。水平截面取 1025 个含两端点的线性点值。"
              f"二维各轴及截面分别检查每最短周期至少 {MIN_INTERVALS_PER_PERIOD} 个采样间隔。")
    page.heading("limits-heading", 647, "模型适用范围")
    page.text("limits", QRectF(0, 673, page.w, 53),
              "等径圆孔互不重叠，单色均匀平面波垂直入射，各孔同相且完全相干。"
              "标量夫琅禾费远场要求整阵 F = R²/(λ z) ≤ 0.05，R 为整阵包围半径。"
              "傍轴视场满足 r/z ≤ 0.05。不模拟偏振效应。")
    page.footer(2)


def _paint_document(device, snapshot, control):
    writer = QPdfWriter(device)
    configure_writer(writer, "多圆孔干涉与衍射 · "+LAYOUT_NAMES[snapshot.request.params.layout], SOFTWARE)
    painter = QPainter()
    if not painter.begin(writer):
        raise ReportError("无法开始绘制 PDF")
    ledger = []
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        _first_page(Page(painter, writer.width(), writer.height(), 1, ledger, ReportError), snapshot)
        control.checkpoint()
        if not writer.newPage():
            raise ReportError("无法创建 PDF 第二页")
        _second_page(Page(painter, writer.width(), writer.height(), 2, ledger, ReportError), snapshot)
    finally:
        ended = painter.end()
    if not ended:
        raise ReportError("PDF 绘图未正常结束")
    return ledger


def render_pdf(snapshot, *, control=None, layout_audit=None):
    """Use the GUI thread's font engine and return a detached, complete document."""
    app = QGuiApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise ReportError("PDF 字体与页面绘制须在 Qt 应用主线程执行")
    control = control or ExportControl()
    control.checkpoint()
    _validate_snapshot(snapshot)
    control.checkpoint()
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(buffer.errorString())
    try:
        ledger = _paint_document(buffer, snapshot, control)
        data = bytes(buffer.data())
    finally:
        buffer.close()
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise ReportError("两页 PDF 未完整结束")
    if layout_audit is not None:
        layout_audit.update(pages=2, elements=ledger)
    return data


def save_pdf_bytes(data, destination, control):
    """Qt owns the temporary file until the final, cancellable replacement."""
    control.checkpoint()
    if not isinstance(data, bytes) or not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise ReportError("无法保存未完整结束的 PDF")
    path = Path(destination)
    if path.suffix.lower() != ".pdf":
        raise ReportError("保存文件须使用 .pdf 扩展名")
    device = QSaveFile(str(path))
    device.setDirectWriteFallback(False)
    if not device.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(device.errorString())
    try:
        if (device.write(data) != len(data) or not device.flush()
                or device.error() != QFileDevice.FileError.NoError):
            raise OSError(f"PDF 写入未完成：{device.errorString()}")
        control.commit(device)
    except BaseException:
        device.cancelWriting()
        raise
    return path


def write_pdf(snapshot, destination, *, control=None, layout_audit=None):
    control = control or ExportControl()
    data = render_pdf(snapshot, control=control, layout_audit=layout_audit)
    return save_pdf_bytes(data, destination, control)

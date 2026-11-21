"""Fixed383 circular PDF sampling, immutable experiment capture and atomic save.

GUI visibility/resolution is deliberately absent from this module. All physical
evaluation is delegated to the two approved F01 scientific files.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib,json
import numpy as np
from PySide6.QtCore import QBuffer,QIODevice,QRectF,Qt,QSaveFile
from PySide6.QtGui import QPdfWriter,QPainter,QPen,QImage
from .report import ReportError,local_now
from .report_layout import (
    MUTED, NORMALIZATION, RULE, SOFT, SOFTWARE, Page,
    apparatus, configure_writer, draw_profile,
)
from .circular_model import CircularParameters,ModelStatus,RingVisibility,assess_model,observation_half_span,first_dark_radius,first_ring_visibility
from .circular_sampling import MAX_SCREEN_SIDE,DisplayStatus,assess_sampling,prepare_screen,prepare_profile

PDF_GRID=383
PROFILE_POINTS=4*PDF_GRID+1
assert PDF_GRID==MAX_SCREEN_SIDE
RING_TEXT={RingVisibility.FULL:'完整位于观察范围内',RingVisibility.PARTIAL:'部分进入角区，中轴无首暗纹',RingVisibility.OUTSIDE:'第一暗环位于观察范围外'}

class CircularReportError(ReportError):
    def __init__(self,message,status='REPORT_ERROR'):
        super().__init__(message);self.status=status

@dataclass(frozen=True)
class PdfEligibility:
    status:str
    reason:str
    model:object
    sampling:object=None
    profile_sampling:object=None
    half_span_m:float|None=None
    @property
    def allowed(self):return self.status=='PDF_READY'

def assess_pdf(params):
    model=assess_model(params)
    if model.status!=ModelStatus.VALID:
        return PdfEligibility('MODEL_INVALID','物理模型不适用，不能导出科学结果报告：'+model.reason,model)
    grid=assess_sampling(params,PDF_GRID)
    profile=assess_sampling(params,PROFILE_POINTS,endpoint_points=True)
    span=observation_half_span(params)
    if grid.status!=DisplayStatus.VALID:
        return PdfEligibility('PDF_SAMPLE_LIMIT',
            f'本软件PDF计算采样上限不足：所需 {grid.required_count}×{grid.required_count}，上限383×383。物理模型已通过。',
            model,grid,profile,span)
    if profile.status!=DisplayStatus.VALID:
        return PdfEligibility('PDF_SAMPLE_LIMIT','本软件PDF截面计算采样上限不足。物理模型已通过。',model,grid,profile,span)
    return PdfEligibility('PDF_READY','PDF使用独立383×383科学采样',model,grid,profile,span)

@dataclass(frozen=True)
class CircularReportRequest:
    params:CircularParameters
    eligibility:PdfEligibility
    captured_at:object
    software:str
    grid:int=PDF_GRID
    profile_points:int=PROFILE_POINTS

@dataclass(frozen=True)
class CircularReportSnapshot:
    request:CircularReportRequest
    screen:object
    profile:object
    first_dark_radius_m:float
    visibility:RingVisibility
    generated_at:object
    data_sha256:str
    @property
    def params(self):return self.request.params
    @property
    def half_span_m(self):return self.request.eligibility.half_span_m

def capture_request(params):
    eligibility=assess_pdf(params)
    if not eligibility.allowed:raise CircularReportError(eligibility.reason,eligibility.status)
    return CircularReportRequest(params,eligibility,local_now(),SOFTWARE)

def data_digest(params,screen,profile):
    h=hashlib.sha256(json.dumps(dict(wavelength=params.wavelength,diameter=params.diameter,distance=params.distance),sort_keys=True).encode())
    for values in (screen.x_edges,screen.y_edges,screen.x_centers,screen.y_centers,screen.pixel_mean,profile.x,profile.intensity):h.update(values.tobytes())
    return h.hexdigest()

def build_snapshot(request):
    if not isinstance(request,CircularReportRequest) or request.grid!=PDF_GRID or request.profile_points!=PROFILE_POINTS:
        raise CircularReportError('报告请求不是固定383科学网格')
    eligibility=assess_pdf(request.params)
    if not eligibility.allowed:raise CircularReportError(eligibility.reason,eligibility.status)
    if eligibility!=request.eligibility:raise CircularReportError('冻结请求与模型/采样状态不一致')
    screen=prepare_screen(request.params,PDF_GRID)
    profile=prepare_profile(request.params,PROFILE_POINTS)
    if screen.data is None or profile.data is None:raise CircularReportError('PDF科学计算未返回有效结果')
    snapshot=CircularReportSnapshot(request,screen,profile,first_dark_radius(request.params),
        first_ring_visibility(request.params),local_now(),data_digest(request.params,screen.data,profile.data))
    validate_snapshot(snapshot)
    return snapshot

def validate_snapshot(s):
    if not isinstance(s,CircularReportSnapshot):raise CircularReportError('没有圆孔报告快照')
    e=assess_pdf(s.params)
    if not e.allowed:raise CircularReportError(e.reason,e.status)
    d,p=s.screen.data,s.profile.data
    if (s.request.grid!=PDF_GRID or s.request.profile_points!=PROFILE_POINTS or
        d is None or p is None or d.params!=s.params or p.params!=s.params or
        d.pixel_mean.shape!=(PDF_GRID,PDF_GRID) or len(p.x)!=PROFILE_POINTS or
        d.half_span_m!=s.half_span_m or p.half_span_m!=s.half_span_m or
        s.request.eligibility!=e or s.first_dark_radius_m!=first_dark_radius(s.params) or
        s.visibility!=first_ring_visibility(s.params)):
        raise CircularReportError('圆孔报告参数、网格、曲线或观察范围不一致')
    if data_digest(s.params,d,p)!=s.data_sha256:raise CircularReportError('圆孔快照数据身份不一致')

def display_image(snapshot):
    # Display transfer only; raw linear scientific arrays never change.
    level=np.rint(255*np.sqrt(snapshot.screen.data.pixel_mean)).astype(np.uint8)
    rgb=np.repeat(level[::-1,:,None],3,axis=2).copy()
    return QImage(rgb.data,PDF_GRID,PDF_GRID,PDF_GRID*3,QImage.Format.Format_RGB888).copy()

class PageLayoutError(CircularReportError):pass

EXPERIMENT_TITLE = "圆孔夫琅禾费衍射"
LIMITS = ("理想圆孔、单色相干均匀平面波垂直入射。采用标量、傍轴、夫琅禾费远场模型。"
          "F = (D/2)²/(λ z) ≤ 0.05，ρ/z ≤ 0.05。门槛不等于固定的强度误差百分比。"
          f"{NORMALIZATION}模型未包含近场、像差、偏振及绝对屏面照度。")


def page_one(page, s, total):
    p = s.params
    e = s.request.eligibility
    span_mm = s.half_span_m * 1000
    page.header(EXPERIMENT_TITLE, s.request.software, s.generated_at)
    page.heading("inputs", 123, "输入参数")
    page.cards("inputs", 146, 47, [
        ("波长 λ", f"{p.wavelength*1e9:g} nm"),
        ("圆孔直径 D", f"{p.diameter*1e6:g} μm"),
        ("屏距 z", f"{p.distance:.2f} m"),
    ])
    page.heading("results", 201, "关键结果")
    page.cards("results", 224, 49, [
        ("第一暗环理论半径", f"{s.first_dark_radius_m*1000:.6f} mm"),
        ("x、y 各自观察半宽", f"±{span_mm:.6f} mm"),
        ("二维科学计算网格", f"{PDF_GRID} × {PDF_GRID}"),
    ], results=True)
    page.text("science-state", QRectF(0, 280, page.w, 27),
              f"{RING_TEXT[s.visibility]}。F = {e.model.fresnel_number:.8f} ≤ 0.05。"
              "远场与傍轴检查通过。", color=MUTED)

    page.heading("screen-title", 307, "二维艾里斑观察屏")
    page.text("gray-note", QRectF(166, 311, page.w-166, 19),
              "灰度 = √(像素面积平均 I/I(0))，仅辅助观察。",
              9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    # In page points this is close to the original 360 pt square. The embedded
    # 383 × 383 scientific image and the horizontal/vertical scale are retained.
    side = 349
    square = QRectF((page.w-side)/2, 335, side, side)
    page.graphic("airy-image", square, source_grid=[PDF_GRID, PDF_GRID], isotropic=True)
    page.p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    page.p.drawImage(square, display_image(s))
    page.p.setPen(QPen(RULE, .7))
    page.p.drawRect(square)
    page.text("y-unit", QRectF(0, square.top()+17, square.left()-7, 18), "y / mm",
              9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    for i, fraction in enumerate((0., .5, 1.)):
        x = square.left() + fraction * square.width()
        y = square.bottom() - fraction * square.height()
        label = f"{(2*fraction-1)*span_mm:.3f}"
        page.text(f"screen-x-tick-{i}", QRectF(x-26, square.bottom()+8, 52, 16), label,
                  9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)
        page.text(f"screen-y-tick-{i}", QRectF(0, y-7, square.left()-7, 17), label,
                  9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    page.text("x-unit", QRectF(square.left(), square.bottom()+22, square.width(), 17),
              "x / mm · x、y 等比例", 9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)
    page.footer(total)


def page_two(page, s, total):
    p = s.params
    page.header("过圆心截面与实验说明", f"{EXPERIMENT_TITLE} · {s.request.software}")
    page.text("curve-title", QRectF(0, 103, page.w, 20),
              "一维相对光强 I(x,0)/I(0)（无量纲，线性）", 11.5, True)
    profile = s.profile.data
    draw_profile(page, QRectF(36, 127, page.w-60, 154), profile.x, profile.intensity,
                 s.half_span_m, decimals=3)
    page.text("curve-legend", QRectF(0, 322, page.w, 22),
              "截面取 y = 0，中心点为 1，与二维图共用同一参数及横向范围。", color=MUTED)

    page.heading("geometry", 346, "孔径与光学装置")
    apparatus(page, 371, p.diameter*1e6, p.distance)
    page.text("geometry-note", QRectF(0, 465, page.w, 18), "示意图不按比例，尺寸以报告输入为准。",
              9.5, color=MUTED)

    page.heading("science", 486, "科学公式与物理解释")
    page.formula(510, "I(ρ)/I(0) = [2 J1(u)/u]²",
                 "u = π D ρ/(λ z)，ρ = √(x² + y²)，u = 0 时取极限 1。"
                 "第一暗环由第一类一阶贝塞尔函数 J1 的首个正零点决定。", height=62)

    page.heading("method", 577, "数值计算与采样")
    sampling = s.request.eligibility.sampling
    page.text("sampling", QRectF(0, 602, page.w, 46),
              f"固定 {PDF_GRID} × {PDF_GRID} 独立网格，所需 {sampling.required_count} × {sampling.required_count}，"
              f"当前每最短周期 {sampling.pixels_per_period:.2f} 像素。"
              "像素强度为 2 × 2 Gauss-Legendre 面积均值。"
              f"截面保留 {PROFILE_POINTS:,} 个含端点的线性点值。"
              "二维图和截面分别检查 12 像素/最短周期门槛。缩放只改变显示大小。")
    if total == 3:
        page.text("limits-next-page", QRectF(0, 672, page.w, 24), "适用范围与限制见第 3 页。")
    else:
        page.heading("conditions", 652, "适用范围与限制")
        page.p.fillRect(QRectF(0, 675, page.w, page.h-704), SOFT)
        page.text("limits", QRectF(9, 679, page.w-18, page.h-712), LIMITS)
    page.footer(total)


def _paint_document(device, snapshot):
    writer = QPdfWriter(device)
    configure_writer(writer, f"《光纹》{EXPERIMENT_TITLE}报告", snapshot.request.software)
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError("无法开始PDF绘制")
    ledger = []
    w, h = float(writer.width()), float(writer.height())
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        first = Page(painter, w, h, 1, ledger, PageLayoutError)
        total = 3 if first.measure(LIMITS, w-18) > h-712 else 2
        page_one(first, snapshot, total)
        if not writer.newPage():
            raise OSError("无法创建PDF第2页")
        page_two(Page(painter, w, h, 2, ledger, PageLayoutError), snapshot, total)
        if total == 3:
            if not writer.newPage():
                raise OSError("无法创建PDF第3页")
            page = Page(painter, w, h, 3, ledger, PageLayoutError)
            page.header("适用范围与限制", f"{EXPERIMENT_TITLE} · {snapshot.request.software}")
            page.text("limits", QRectF(0, 119, w, h-165), LIMITS)
            page.footer(total)
    finally:
        ended = painter.end()
    if not ended:
        raise OSError("PDF绘制未正常结束")
    return dict(pages=total, paper="A4 portrait", margins_mm=15, paintable_pt=[w, h],
                body_font_pt=10.5, annotation_min_font_pt=9.5, text_overlap=False,
                text_clipping=False, ledger=ledger)

def render_bytes(snapshot):
    validate_snapshot(snapshot)
    device=QBuffer()
    if not device.open(QIODevice.OpenModeFlag.ReadWrite):raise OSError('无法打开PDF内存缓冲区')
    try:
        layout=_paint_document(device,snapshot)
        data=bytes(device.data())
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:raise OSError('PDF未完整结束')
        return data,layout
    finally:device.close()

def _commit_bytes(data,path):
    device=QSaveFile(str(path));device.setDirectWriteFallback(False)
    if not device.open(QIODevice.OpenModeFlag.WriteOnly):raise OSError(device.errorString())
    try:
        if device.write(data)!=len(data):raise OSError('PDF写入不完整：'+device.errorString())
        if not device.commit():raise OSError('PDF保存失败：'+device.errorString())
    except BaseException:
        device.cancelWriting();del device;raise

def write_pdf(snapshot,destination,*,layout_audit=None):
    path=Path(destination)
    if path.suffix.lower()!='.pdf':raise CircularReportError('请选择以.pdf结尾的文件名')
    data,layout=render_bytes(snapshot)
    if layout_audit is not None:layout_audit.update(layout)
    _commit_bytes(data,path)
    return path

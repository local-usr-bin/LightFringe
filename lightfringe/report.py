"""Immutable capture of completed GUI results and atomic, single-page PDF export.

No intensity evaluation or resampling is performed in this module. The curve,
envelope, pixel means and span are copied from the completed DisplayData object.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import math

import numpy as np
from PySide6.QtCore import QIODevice, QMarginsF, QPointF, QRectF, QSaveFile, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QPageLayout, QPageSize,
    QPainter, QPdfWriter, QPen, QPolygonF,
)

from . import __version__, __build__, __baseline__
from .annotations import missing_order_note, missing_order_relation
from .model import Mode, ModelError, Parameters
from .multislit import MultiParameters, is_multi, characteristic_lengths, validate
from .sampling import DisplayData, MIN_PIXELS_PER_PERIOD


class ReportError(ValueError):
    """No completed trustworthy result, or no readable single-page layout."""


def local_now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _freeze(values):
    # The immutable bytes backing prevents even setflags(write=True).
    return np.frombuffer(np.asarray(values, dtype=np.float64).tobytes(), dtype=np.float64)


@dataclass(frozen=True)
class ReportSnapshot:
    params: Parameters | MultiParameters
    data: DisplayData
    revision: int
    captured_at: datetime
    software: str
    width_um: int
    separation_um: int
    first_zero: float
    fringe_period: float | None
    data_sha256: str


def capture_snapshot(params: Parameters, data: DisplayData, revision: int,
                     width_um: int, separation_um: int) -> ReportSnapshot:
    """Called only after the GUI has checked its result key and current inputs."""
    validate(params)  # Reuse the original gate, without a second physical model.
    if data is None or revision < 1:
        raise ReportError("尚无已完成的有效模拟结果")
    if (type(width_um) is not int or type(separation_um) is not int or
            width_um / 1e6 != params.slit_width or separation_um / 1e6 != params.separation):
        raise ReportError("参数与当前输入栅格不一致")
    if not np.isfinite(data.pixels_per_period) or data.pixels_per_period < MIN_PIXELS_PER_PERIOD:
        raise ReportError("显示采样不足，不能导出")
    arrays = [np.asarray(getattr(data, name)) for name in ('x', 'intensity', 'envelope', 'pixel_mean')]
    if any(a.ndim != 1 or a.size < 2 or not np.all(np.isfinite(a)) for a in arrays):
        raise ReportError("计算数据不完整或无效")
    x, values, envelope, pixels = arrays
    if (len(x) != len(values) or len(x) != len(envelope) or not np.all(np.diff(x) > 0)
            or not np.isfinite(data.span) or data.span <= 0
            or x[0] != -data.span or x[-1] != data.span):
        raise ReportError("曲线与显示范围不一致")
    if any(np.any((a < 0) | (a > 1)) for a in (values, envelope, pixels)):
        raise ReportError("相对归一化结果无效")
    # No production data object or array is retained by reference.
    frozen = DisplayData(*(_freeze(a) for a in arrays),
                         float(data.pixels_per_period), float(data.span))
    digest = hashlib.sha256()
    for a in arrays:
        digest.update(np.asarray(a, dtype=np.float64).tobytes())
    zero, fringe = characteristic_lengths(params)
    software = (f"光纹 LightFringe {__version__} ({__build__})" if is_multi(params) else
                f"光纹 LightFringe {__version__} · A3（核心基线 {__baseline__}）")
    return ReportSnapshot(params, frozen, revision, local_now(), software,
                          width_um, separation_um, zero, fringe, digest.hexdigest())


def input_lines(s: ReportSnapshot) -> tuple[str, ...]:
    p = s.params
    lines = [f"波长 λ：{p.wavelength * 1e9:g} nm", f"缝宽 a：{s.width_um} μm"]
    if p.mode == Mode.DOUBLE:
        lines.append(f"双缝中心距 d：{s.separation_um} μm")
    elif is_multi(p):
        lines.append(f"缝中心距 d：{s.separation_um} μm")
    lines.extend((f"缝到屏幕距离 z：{p.distance:.2f} m",
                  f"当前模拟范围 x：±{s.data.span * 1000:g} mm"))
    return tuple(lines)


def result_lines(s: ReportSnapshot) -> tuple[str, ...]:
    """Use existing characteristic lengths; explicitly scope zeros to the view."""
    in_view = s.first_zero <= s.data.span
    if s.params.mode == Mode.SINGLE:
        if in_view:
            return (f"第一暗纹：x = ±{s.first_zero * 1000:.4f} mm",
                    f"中央峰宽度（两首暗纹之间）：{2 * s.first_zero * 1000:.4f} mm")
        return ("第一暗纹：当前范围不可确定（首暗纹在视场外）",
                "中央峰宽度：当前范围不可确定")
    lines = [f"理论干涉因子周期：{s.fringe_period * 1000:.4f} mm",
             "有限包络下的所有侧峰并非严格等距。"]
    if is_multi(s.params):
        lines[1] = f"中央主峰首零点间宽：{2*s.fringe_period/s.params.slit_count*1000:.4f} mm"
    lines.append(f"包络首暗纹：x = ±{s.first_zero * 1000:.4f} mm" if in_view else
                 "包络首暗纹：当前范围不可确定（在视场外）")
    lines.append(missing_order_note(s.width_um, s.separation_um))
    order, _ = missing_order_relation(s.width_um, s.separation_um)
    missing_x = order * s.fringe_period
    if missing_x <= s.data.span:
        lines.append(f"首组缺级：±{order} 级，x = ±{missing_x * 1000:.4f} mm")
    else:
        lines.append("当前视场内无理论缺级位置。")
    return tuple(lines)


NORMALIZATION = "光强使用相对归一化表示，不同参数下的峰值高度不可直接用于比较实际透射光功率。"
SIMULATION_NOTICE = "本报告为数值模拟结果，并非实测数据。"


def _font(size, bold=False):
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _text(painter, rect, text, size=10, bold=False, align=Qt.AlignmentFlag.AlignLeft):
    painter.setFont(_font(size, bold))
    painter.setPen(QColor("#203448"))
    flags = int(align | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
    bounds = QFontMetricsF(painter.font(), painter.device()).boundingRect(rect, flags, text)
    if bounds.height() > rect.height() + .5 or bounds.width() > rect.width() + .5:
        raise ReportError("A4 横向单页无法清晰容纳当前内容，已停止导出；未缩小字体")
    painter.drawText(rect, flags, text)


def _paint_page(painter: QPainter, s: ReportSnapshot, generated_at: datetime):
    # A4 landscape with 12 mm margins, approximately 774 x 527 pt.
    _text(painter, QRectF(0, 0, 774, 31), "《光纹》光学模拟报告", 22, True)
    mode = "单缝衍射" if s.params.mode == Mode.SINGLE else "双缝干涉 + 衍射（有限缝宽）"
    if is_multi(s.params):
        mode = f"多缝干涉（N = {s.params.slit_count}，等宽等距、同相等幅）"
    _text(painter, QRectF(0, 39, 470, 17), f"实验类型：{mode}", 11)
    _text(painter, QRectF(470, 39, 304, 17), f"PDF 生成时间：{generated_at:%Y-%m-%d %H:%M:%S} +08:00", 10)
    _text(painter, QRectF(0, 60, 774, 18), f"{s.software}    |    计算模型：标量傍轴夫琅禾费远场", 10)
    painter.setPen(QPen(QColor("#cfdae4"), .8))
    painter.drawLine(QPointF(0, 84), QPointF(774, 84))
    _text(painter, QRectF(0, 96, 230, 20), "输入参数与当前范围", 12, True)
    for i, line in enumerate(input_lines(s)):
        _text(painter, QRectF(0, 124 + i * 21, 230, 20), line, 11)
    _text(painter, QRectF(0, 242, 230, 20), "关键结果（理想远场模型）", 12, True)
    _text(painter, QRectF(0, 270, 233, 126), "\n".join(result_lines(s)), 10)
    symbol = 'W' if is_multi(s.params) else 'D'
    _text(painter, QRectF(0, 405, 234, 35),
          f"完整孔径 {symbol} = {s.params.aperture_extent * 1e6:g} μm\n"
          f"F = {s.params.fresnel_number:.6f} ≤ 0.05", 10)

    left, width = 286.0, 476.0
    _text(painter, QRectF(left, 96, width, 18), "观察屏光纹示意（与曲线共用 x 坐标）", 11, True)
    level = np.rint(255 * np.sqrt(s.data.pixel_mean)).astype(np.uint8)
    rgb = np.repeat(level[:, None], 3, axis=1).copy()
    image = QImage(rgb.data, len(level), 1, len(level)*3, QImage.Format.Format_RGB888).copy()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(QRectF(left, 120, width, 40), image)
    _text(painter, QRectF(left, 167, width, 28),
          "灰度亮度 = √(像素平均 I/I₀)，仅辅助显示，非测量 RGB。\n"
          "屏幕高度仅重复一维截面；非二维有限孔径模拟。", 9)
    _text(painter, QRectF(left, 202, width, 17), "相对光强 I/Imax（Imax=I(0)，无量纲，线性）" if is_multi(s.params)
          else "相对光强 I/I₀（无量纲，线性）", 10)
    plot = QRectF(left, 226, width, 155)
    for value in (0, .25, .5, .75, 1):
        y = plot.bottom() - value * plot.height()
        painter.setPen(QPen(QColor("#e2e8ee"), .6))
        painter.drawLine(QPointF(left, y), QPointF(plot.right(), y))
        _text(painter, QRectF(247, y - 6, 32, 15), f"{value:g}", 9, align=Qt.AlignmentFlag.AlignRight)
    for i in range(9):
        px = left + width * i / 8
        painter.setPen(QPen(QColor("#e2e8ee"), .6))
        painter.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
        _text(painter, QRectF(px-22, plot.bottom()+6, 44, 16),
              f"{(-s.data.span + 2*s.data.span*i/8)*1000:g}", 9, align=Qt.AlignmentFlag.AlignHCenter)
    _text(painter, QRectF(left, 409, width, 17), "观察屏横向位置 x / mm", 10, align=Qt.AlignmentFlag.AlignHCenter)
    px = left + (s.data.x + s.data.span) / (2*s.data.span) * width
    painter.save()
    painter.setClipRect(plot.adjusted(-1, -1, 1, 1))
    for values, color, style in (
        (s.data.envelope, "#b17c35", Qt.PenStyle.DashLine),
        (s.data.intensity, "#1266a6", Qt.PenStyle.SolidLine),
    ):
        if values is s.data.envelope and s.params.mode == Mode.SINGLE:
            continue
        py = plot.bottom() - values * plot.height()
        polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in zip(px, py)])
        painter.setPen(QPen(QColor(color), 1.0, style))
        painter.drawPolyline(polygon)
    painter.restore()
    legend = "蓝线：有限缝宽双缝光强；虚线：单缝包络" if s.params.mode == Mode.DOUBLE else "蓝线：单缝衍射光强"
    if is_multi(s.params):
        legend = f"蓝线：N={s.params.slit_count} 有限宽多缝光强；虚线：单缝包络"
    _text(painter, QRectF(left, 430, width, 16), legend, 9)
    painter.setPen(QPen(QColor("#cfdae4"), .8))
    painter.drawLine(QPointF(0, 453), QPointF(774, 453))
    _text(painter, QRectF(0, 462, 774, 18), SIMULATION_NOTICE, 11, True)
    _text(painter, QRectF(0, 484, 774, 17), NORMALIZATION, 10)
    footer = (f"理想长缝、标量、傍轴、远场模型；本次输入已通过模型有效性检查。"
              f"显示采样：{s.data.pixels_per_period:.1f} 像素/最短周期（要求 ≥ {MIN_PIXELS_PER_PERIOD}）。")
    if is_multi(s.params):
        min_dpi = 12*2*s.data.span*s.params.aperture_extent/(s.params.wavelength*s.params.distance)/476*72
        footer = (f"理想长缝、标量傍轴远场；有效性检查通过。最短周期采样 {s.data.pixels_per_period:.1f} 像素 ≥ 12。\n"
                  f"曲线为矢量；缩小查看可能失去细峰，建议有效显示密度 ≥ {math.ceil(min_dpi)} dpi（放大可提高）；灰度图仅辅助观察。")
    _text(painter, QRectF(0, 501, 774, 26) if is_multi(s.params) else QRectF(0, 505, 774, 19), footer, 9)


def _write_document(device, snapshot, generated_at):
    """Keep writer lifetime inside this scope: finalize it before commit."""
    writer = QPdfWriter(device)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    writer.setResolution(144)
    writer.setTitle("《光纹》光学模拟报告")
    writer.setCreator(snapshot.software)
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError("无法开始 PDF 绘制")
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(writer.width() / 774, writer.height() / 527)
        _paint_page(painter, snapshot, generated_at)
    finally:
        ended = painter.end()
    if not ended:
        raise OSError("PDF 绘制未能正常结束")
    # CPython releases painter and writer on function return, completing xref.


def write_pdf(snapshot: ReportSnapshot, destination) -> Path:
    """Atomically replace destination only after a complete successful render.

    The GUI's save dialog handles overwrite consent. Direct-write fallback is
    disabled so failed exports cannot truncate an existing report.
    """
    validate(snapshot.params)
    if snapshot.data.pixels_per_period < MIN_PIXELS_PER_PERIOD:
        raise ReportError("显示采样不足，不能导出")
    path = Path(destination)
    if path.suffix.lower() != '.pdf':
        raise ReportError("请选择以 .pdf 结尾的文件名")
    device = QSaveFile(str(path))
    device.setDirectWriteFallback(False)
    if not device.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(device.errorString())
    try:
        _write_document(device, snapshot, local_now())
        if not device.commit():
            raise OSError(device.errorString())
    except BaseException:
        device.cancelWriting()
        raise
    return path

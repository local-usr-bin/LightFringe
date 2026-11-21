"""Immutable capture of completed GUI results and atomic PDF export.

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
from PySide6.QtCore import QIODevice, QRectF, QSaveFile, Qt
from PySide6.QtGui import QImage, QPainter, QPdfWriter

from . import __baseline__
from .annotations import missing_order_note, missing_order_relation
from .model import Mode, ModelError, Parameters
from .multislit import MultiMode, MultiParameters, is_multi, characteristic_lengths, validate
from .report_layout import (
    MUTED, NORMALIZATION, REPORT_TITLE, SIMULATION_NOTICE, SOFT, SOFTWARE,
    Page, apparatus, configure_writer, draw_profile,
)
from .sampling import DisplayData, MIN_PIXELS_PER_PERIOD, SUBPIXELS


class ReportError(ValueError):
    """No completed trustworthy result, or no readable PDF layout."""


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
    software = SOFTWARE if is_multi(params) else f"{SOFTWARE} · 核心基线 {__baseline__}"
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


_SCIENCE = {
    Mode.SINGLE: (
        "I(x)/I(0) = sinc²(u)",
        "u = π a x/(λ z)，sinc(u) = sin(u)/u。u = 0 时取 1。",
        "缝宽 a 决定衍射包络。两侧首暗纹位于 x = ±λz/a，中央亮纹宽度为两首暗纹的距离。",
    ),
    Mode.DOUBLE: (
        "I(x)/I(0) = sinc²(u) cos²(v)",
        "u = π a x/(λ z)，v = π d x/(λ z)。sinc(u) = sin(u)/u，sinc(0) = 1。",
        "有限缝宽形成单缝包络。干涉因子的周期是 λz/d，实际侧峰间距会受包络影响。"
        "包络零点与理论主极大重合时形成缺级。",
    ),
    MultiMode.MULTI: (
        "I(x)/I(0) = sinc²(u) [sin(Nv)/(N sin(v))]²",
        "u = π a x/(λ z)，v = π d x/(λ z)。sinc(u) = sin(u)/u，sinc(0) = 1。"
        "sin(v) = 0 时，平方比值取连续极限 1。",
        "等宽等距、同相等幅的 N 缝叠加。干涉因子的周期是 λz/d，中央主峰两侧最近零点的间距为 2λz/(Nd)。"
        "包络零点与理论主极大重合时形成缺级。",
    ),
}


def _experiment_title(params):
    if is_multi(params):
        return "多缝干涉与衍射"
    if params.mode == Mode.SINGLE:
        return "单缝衍射"
    return "双缝干涉与衍射"


def _paint_page(painter, s, generated_at, width, height, ledger):
    page = Page(painter, width, height, 1, ledger, ReportError)
    params = s.params
    multi = is_multi(params)
    page.header(_experiment_title(params), s.software, generated_at)
    fields = input_lines(s)
    inputs = [line.split("：", 1) for line in fields[:-1]]
    if multi:
        inputs.insert(-1, ("缝数 N", f"N = {params.slit_count}"))
    page.heading("inputs", 123, "输入参数")
    page.cards("inputs", 146, 49, inputs)

    results = result_lines(s)
    if params.mode == Mode.SINGLE:
        cards = [*results, fields[-1]]
        comments = []
    elif multi:
        cards = list(results[:3])
        comments = list(results[3:])
        if "当前范围不可确定" in cards[2]:
            comments.insert(0, "首暗纹位置：当前范围不可确定。")
            cards[2] = "包络首暗纹：位于视场外"
    else:
        cards = [results[0], results[2]]
        comments = [results[3]]
        missing = results[-1]
        if missing.startswith("首组缺级："):
            order, position = missing.split("，", 1)
            cards.append(order)
            comments.insert(1, f"首组缺级位置：{position}。")
        else:
            cards.append("首组缺级：位于视场外")
            comments.append(missing)
    page.heading("results", 203, "关键结果")
    page.cards("results", 226, 62, [line.split("：", 1) for line in cards], results=True)
    aperture = (f"完整孔径 W = {params.aperture_extent * 1e6:g} μm。"
                f"F = {params.fresnel_number:.6f} ≤ 0.05。")
    notes = aperture
    if comments:
        observations = "  ".join(comments).replace("；", "。")
        notes = f"{observations}\n{fields[-1]}。{aperture}"
    page.text("result-notes", QRectF(0, 293, width, 53), notes, 10.5, color=MUTED)

    page.heading("figures", 349, "观察屏光纹与相对光强")
    page.text("screen-label", QRectF(36, 375, width-60, 18), "一维灰度光纹带", 10.5, True)
    plot = QRectF(36, 469, width-60, 156)
    strip = QRectF(plot.left(), 395, plot.width(), 39)
    level = np.rint(255 * np.sqrt(s.data.pixel_mean)).astype(np.uint8)
    rgb = np.repeat(level[:, None], 3, axis=1).copy()
    image = QImage(rgb.data, len(level), 1, len(level)*3, QImage.Format.Format_RGB888).copy()
    page.graphic("slit-screen", strip, source_pixels=len(level))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(strip, image)

    page.text("curve-title", QRectF(36, 441, 222, 20), "相对光强 I/I(0)（无量纲，线性）", 10.5, True)
    envelope = None if params.mode == Mode.SINGLE else s.data.envelope
    legend = "蓝线：相对光强" if envelope is None else "蓝线：相对光强    虚线：单缝包络"
    page.text("curve-legend", QRectF(264, 441, width-288, 20), legend,
              9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    draw_profile(page, plot, s.data.x, s.data.intensity, s.data.span, envelope=envelope)
    page.text("gray-note", QRectF(0, 680, width, 34),
              "光纹带和曲线共用横坐标。灰度 = √(像素平均 I/I(0))，仅辅助观察。"
              "带状图高度重复一维截面，不表示二维有限孔径计算。", color=MUTED)
    page.footer(2)
    return plot.width()


def _paint_methods(page, s, plot_width):
    p = s.params
    multi = is_multi(p)
    width = page.w
    page.header("孔径、原理与数值方法", f"{_experiment_title(p)} · {s.software}")
    page.heading("geometry", 116, "孔径与光学装置")
    slit_count = p.slit_count if multi else (1 if p.mode == Mode.SINGLE else 2)
    apparatus(page, 141, s.width_um, p.distance, slit_count=slit_count, separation_um=s.separation_um)
    page.text("geometry-note", QRectF(0, 239, width, 18), "示意图不按比例，尺寸以报告输入为准。",
              9.5, color=MUTED)

    equation, symbols, explanation = _SCIENCE[p.mode]
    page.heading("science", 277, "科学公式与物理解释")
    page.formula(303, equation, symbols)
    page.text("physics", QRectF(0, 379, width, 57), explanation)

    page.heading("method", 451, "数值计算与采样")
    sampling = (f"使用同一已完成的 GUI 科学快照。灰度带有 {len(s.data.pixel_mean):,} 个物理像素，"
                f"每像素取 {SUBPIXELS} 个中点强度的均值。最短周期采样为 {s.data.pixels_per_period:.1f} 像素"
                f"（要求 ≥ {MIN_PIXELS_PER_PERIOD}）。矢量曲线保留 {len(s.data.x):,} 个含端点的线性点值。")
    if multi:
        min_dpi = math.ceil(MIN_PIXELS_PER_PERIOD * 2*s.data.span*p.aperture_extent
                            / (p.wavelength * p.distance) / plot_width * 72)
        sampling += (f"阵列因子在整数周期附近按连续极限求值。缩小查看可能漏掉细峰，"
                     f"建议有效显示密度 ≥ {min_dpi} dpi，可放大查看。")
    page.text("sampling", QRectF(0, 477, width, 91), sampling)
    page.heading("conditions", 584, "适用范围与限制")
    page.p.fillRect(QRectF(0, 611, width, 91), SOFT)
    conditions = ("理想长直缝与单色、相干、等幅照明。采用标量、傍轴、夫琅禾费远场模型。"
                  "输入已通过模型有效性检查。完整孔径 W 满足 F = (W/2)²/(λ z) ≤ 0.05，且 |x|/z ≤ 0.05。"
                  f"{NORMALIZATION}数值模拟不提供绝对照度。")
    page.text("limits", QRectF(11, 619, width-22, 74), conditions)
    page.footer(2)


def _write_document(device, snapshot, generated_at):
    """Finalize both pages before allowing QSaveFile to replace the destination."""
    writer = QPdfWriter(device)
    configure_writer(writer, REPORT_TITLE, snapshot.software)
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError("无法开始 PDF 绘制")
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        width, height = float(writer.width()), float(writer.height())
        ledger = []
        plot_width = _paint_page(painter, snapshot, generated_at, width, height, ledger)
        if not writer.newPage():
            raise OSError("无法创建 PDF 第 2 页")
        _paint_methods(Page(painter, width, height, 2, ledger, ReportError), snapshot, plot_width)
    finally:
        ended = painter.end()
    if not ended:
        raise OSError("PDF 绘制未能正常结束")
    # The writer is released on return, before the caller commits QSaveFile.


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

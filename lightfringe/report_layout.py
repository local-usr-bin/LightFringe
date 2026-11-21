"""Visual primitives for LightFringe's A4 PDF reports.

Callers choose the page composition and supply their existing scientific data.
All coordinates are typographic points within the printable area.
"""
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPen, QPolygonF

from . import __version__, __build__


SOFTWARE = f"光纹 LightFringe {__version__} · 构建 {__build__}"
REPORT_TITLE = "《光纹》光学模拟报告"
SIMULATION_NOTICE = "本报告为数值模拟结果，并非实测数据。"
NORMALIZATION = "光强使用相对归一化表示，不同参数下的峰值高度不可直接用于比较实际透射光功率。"
INK, MUTED = QColor("#173147"), QColor("#405a6c")
RULE, SOFT, PALE = QColor("#cbd9e0"), QColor("#f2f5f7"), QColor("#eaf3f4")
TEAL, BLUE, GOLD = QColor("#106a69"), QColor("#146497"), QColor("#925814")


def configure_writer(writer, title, creator):
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Portrait)
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)
    writer.setTitle(title)
    writer.setCreator(creator)


def _font(size, bold):
    font = QFont("Microsoft YaHei UI")
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


class Page:
    """Measure text before painting and retain the existing circular layout ledger."""

    def __init__(self, painter, width, height, number, ledger, error_type):
        self.p = painter
        self.w, self.h = width, height
        self.number = number
        self.ledger = ledger
        self.error_type = error_type

    def measure(self, value, width, size=10.5):
        metrics = QFontMetricsF(_font(size, False), self.p.device())
        return metrics.boundingRect(QRectF(0, 0, width, 10000),
                                    int(Qt.TextFlag.TextWordWrap), value).height()

    def _check_area(self, key, rect):
        if (rect.left() < 0 or rect.top() < 0 or
                rect.right() > self.w + .01 or rect.bottom() > self.h + .01):
            raise self.error_type(f"内容越过页面有效绘制区域：{key}")

    def text(self, key, rect, value, size=10.5, bold=False,
             align=Qt.AlignmentFlag.AlignLeft, color=INK):
        self._check_area(key, rect)
        self.p.setFont(_font(size, bold))
        self.p.setPen(color)
        flags = int(align | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        bounds = QFontMetricsF(self.p.font(), self.p.device()).boundingRect(rect, flags, value)
        if bounds.width() > rect.width() + .1 or bounds.height() > rect.height() + .1:
            raise self.error_type(f"文字区域不足，未缩小字体：{key} "
                                  f"{bounds.width():.2f}×{bounds.height():.2f} > "
                                  f"{rect.width():.2f}×{rect.height():.2f}")
        for old in self.ledger:
            if old["page"] == self.number and old["kind"] == "text":
                overlap = bounds.intersected(QRectF(*old["bounds"]))
                if overlap.width() > .1 and overlap.height() > .1:
                    raise self.error_type(f"文字重叠：{key} / {old['key']}")
        self.ledger.append(dict(page=self.number, kind="text", key=key, text=value, font_pt=size,
                                rect=list(rect.getRect()), bounds=list(bounds.getRect())))
        self.p.drawText(rect, flags, value)

    def graphic(self, key, rect, **extra):
        self._check_area(key, rect)
        self.ledger.append(dict(page=self.number, kind="graphic", key=key, rect=list(rect.getRect()), **extra))

    def line(self, x1, y1, x2, y2, color=RULE, width=.7):
        self.p.setPen(QPen(color, width))
        self.p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def header(self, title, subtitle, generated_at=None):
        self.text("brand", QRectF(0, 0, 230, 20), "光纹 LightFringe", 12, True)
        self.text("report-title", QRectF(self.w - 210, 1, 210, 19), REPORT_TITLE,
                  9.5, align=Qt.AlignmentFlag.AlignRight, color=MUTED)
        self.line(0, 27, self.w, 27)
        self.text("title", QRectF(0, 37, self.w, 38), title, 25, True)
        self.text("subtitle", QRectF(0, 79, self.w, 19), subtitle, 11, color=MUTED)
        if generated_at is not None:
            offset = generated_at.strftime("%z")
            zone = f" {offset[:3]}:{offset[3:]}" if offset else ""
            self.text("generation", QRectF(0, 102, self.w, 18),
                      f"PDF 生成时间 {generated_at:%Y-%m-%d %H:%M:%S}{zone} · Asia/Shanghai",
                      9.5, color=MUTED)

    def heading(self, key, y, title):
        self.text(key, QRectF(0, y, self.w, 23), title, 14, True)

    def cards(self, key, y, height, entries, *, results=False):
        gap = 7
        width = (self.w - gap * (len(entries) - 1)) / len(entries)
        for i, (label, value) in enumerate(entries):
            x = i * (width + gap)
            self.p.fillRect(QRectF(x, y, width, height), PALE if results else SOFT)
            if results:
                self.p.fillRect(QRectF(x, y, 2, height), TEAL)
            self.text(f"{key}-label-{i}", QRectF(x+9, y+5, width-18, 17),
                      label, 9.5, color=MUTED)
            self.text(f"{key}-value-{i}", QRectF(x+9, y+24, width-18, height-26),
                      value, 14, True)

    def formula(self, y, equation, symbols, *, height=63):
        self.p.fillRect(QRectF(0, y, self.w, height), PALE)
        self.text("equation", QRectF(11, y+4, self.w-22, 25), equation, 16, True)
        self.text("symbols", QRectF(11, y+31, self.w-22, height-33), symbols, 10.5)

    def footer(self, total):
        self.line(0, self.h-27, self.w, self.h-27)
        self.text("footer-notice", QRectF(0, self.h-21, self.w-134, 17),
                  SIMULATION_NOTICE, 9.5, color=MUTED)
        self.text("footer-pages", QRectF(self.w-128, self.h-21, 128, 17),
                  f"第 {self.number} 页 / 共 {total} 页", 9.5,
                  align=Qt.AlignmentFlag.AlignRight, color=MUTED)


def draw_profile(page, rect, x, intensity, span, *, envelope=None, decimals=None):
    """Draw all original linear points using only an affine page transform."""
    page.graphic("linear-profile", rect, point_count=len(x), linear=True)
    for i, value in enumerate((0, .25, .5, .75, 1)):
        y = rect.bottom() - value * rect.height()
        page.line(rect.left(), y, rect.right(), y)
        page.text(f"curve-y-{i}", QRectF(0, y-7, rect.left()-7, 16), f"{value:g}", 9.5,
                  align=Qt.AlignmentFlag.AlignRight, color=MUTED)
    for i, fraction in enumerate((0, .25, .5, .75, 1)):
        px = rect.left() + fraction * rect.width()
        value = (2*fraction-1) * span * 1000
        label = f"{value:g}" if decimals is None else f"{value:.{decimals}f}"
        page.line(px, rect.top(), px, rect.bottom())
        page.text(f"curve-x-{i}", QRectF(px-22, rect.bottom()+8, 44, 16), label, 9.5,
                  align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)
    page.line(rect.left(), rect.top(), rect.left(), rect.bottom(), MUTED)
    page.line(rect.left(), rect.bottom(), rect.right(), rect.bottom(), MUTED)
    page.text("curve-x-unit", QRectF(rect.left(), rect.bottom()+22, rect.width(), 17),
              "观察屏横向位置 x / mm", 9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)

    px = rect.left() + (x + span) / (2 * span) * rect.width()
    layers = [(intensity, BLUE, Qt.PenStyle.SolidLine)]
    if envelope is not None:
        layers.insert(0, (envelope, GOLD, Qt.PenStyle.DashLine))
    page.p.save()
    try:
        page.p.setClipRect(rect.adjusted(-1, -1, 1, 1))
        for values, color, style in layers:
            py = rect.bottom() - values * rect.height()
            polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in zip(px, py)])
            page.p.setPen(QPen(color, 1.05, style))
            page.p.drawPolyline(polygon)
    finally:
        page.p.restore()


def apparatus(page, top, width_um, distance_m, *, slit_count=None, separation_um=None):
    """Front aperture and side-view geometry, shown without claiming scale."""
    p = page.p
    front, side, height = 142, 156, 91
    page.graphic("apparatus", QRectF(0, top, page.w, height))
    p.fillRect(QRectF(0, top, front, height), SOFT)
    p.fillRect(QRectF(side, top, page.w-side, height), SOFT)
    page.text("front-label", QRectF(10, top+4, front-20, 18),
              "圆孔正面" if slit_count is None else "孔径正面", 10, True)
    page.text("device-label", QRectF(side+10, top+4, page.w-side-20, 18),
              "均匀平面波垂直入射", 10, True)

    center, cy = front/2, top+44
    p.fillRect(QRectF(12, top+27, front-24, 34), INK)
    if slit_count is None:
        opening = QRectF(center-13, cy-13, 26, 26)
        page.graphic("aperture-circle", opening, isotropic=True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawEllipse(opening)
        p.setBrush(Qt.BrushStyle.NoBrush)
        page.line(opening.left(), cy, opening.right(), cy, BLUE)
        page.ledger.append(dict(page=page.number, kind="geometry", key="diameter-endpoints",
                                opening=list(opening.getRect()), start=[opening.left(), cy],
                                end=[opening.right(), cy]))
        aperture_label = f"D = {width_um:g} μm"
    else:
        spacing = 14 if slit_count > 2 else 32
        for i in range(slit_count):
            x = center + (i - (slit_count-1)/2) * spacing
            p.fillRect(QRectF(x-3, cy-11, 6, 22), QColor("white"))
        aperture_label = f"a = {width_um:g} μm"
        if slit_count > 1:
            aperture_label += f" · d = {separation_um:g} μm"
    page.text("aperture-size", QRectF(5, top+66, front-10, 18), aperture_label,
              9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)

    board, screen = side + 93, page.w - 29
    for offset in (31, 42, 53):
        y = top + offset
        tip = board - 11
        page.line(side+17, y, tip, y, BLUE, .9)
        page.line(tip-5, y-3, tip, y, BLUE)
        page.line(tip-5, y+3, tip, y, BLUE)
    # The gap in the aperture plate is schematic. The opening is labeled in front view.
    page.line(board, top+24, board, top+39, INK, 1.2)
    page.line(board, top+46, board, top+62, INK, 1.2)
    page.line(screen, top+24, screen, top+62, INK, 1.2)
    page.line(board+10, top+42, screen-8, top+42, BLUE, .9)
    page.text("distance", QRectF(board+12, top+24, screen-board-24, 17),
              f"z = {distance_m:.2f} m", 9.5, align=Qt.AlignmentFlag.AlignHCenter, color=BLUE)
    page.text("aperture-board", QRectF(board-32, top+64, 64, 17),
              "孔径板", 9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)
    page.text("observation-screen", QRectF(screen-28, top+64, 56, 17),
              "观察屏", 9.5, align=Qt.AlignmentFlag.AlignHCenter, color=MUTED)

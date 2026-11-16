"""Fixed383 circular PDF sampling, immutable experiment capture and atomic save.

GUI visibility/resolution is deliberately absent from this module. All physical
evaluation is delegated to the two approved F01 scientific files.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib,json
import numpy as np
from PySide6.QtCore import QBuffer,QIODevice,QMarginsF,QPointF,QRectF,Qt,QSaveFile
from PySide6.QtGui import QPdfWriter,QPageSize,QPageLayout,QPainter,QFont,QFontMetricsF,QColor,QPen,QImage,QPolygonF
from . import __version__,__build__
from .report import ReportError,local_now
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
    return CircularReportRequest(params,eligibility,local_now(),f'光纹 LightFringe {__version__} / build {__build__}')

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

class Page:
    def __init__(self,painter,width,height,number,ledger):
        self.p=painter;self.w=width;self.h=height;self.number=number;self.ledger=ledger
    def font(self,size,bold=False):
        f=QFont('Microsoft YaHei UI');f.setPointSizeF(size);f.setBold(bold);return f
    def measure(self,value,width,size=10.5,bold=False):
        f=self.font(size,bold);m=QFontMetricsF(f,self.p.device())
        return m.boundingRect(QRectF(0,0,width,10000),int(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap),value)
    def text(self,key,rect,value,size=10.5,bold=False,align=Qt.AlignmentFlag.AlignLeft):
        self.p.setFont(self.font(size,bold));self.p.setPen(QColor('#203448'))
        flags=int(align|Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap)
        bounds=QFontMetricsF(self.p.font(),self.p.device()).boundingRect(rect,flags,value)
        if bounds.width()>rect.width()+.1 or bounds.height()>rect.height()+.1:
            raise PageLayoutError(f'文字区域不足，未缩小字体：{key} {bounds.width():.2f}x{bounds.height():.2f} > {rect.width():.2f}x{rect.height():.2f}')
        if rect.left()<0 or rect.top()<0 or rect.right()>self.w+.01 or rect.bottom()>self.h+.01:
            raise PageLayoutError('文字越过页面有效绘制区域：'+key)
        for old in self.ledger:
            if old['page']==self.number and old['kind']=='text':
                overlap=bounds.intersected(QRectF(*old['bounds']))
                if overlap.width()>.1 and overlap.height()>.1:raise PageLayoutError('文字重叠：'+key+' / '+old['key'])
        self.ledger.append(dict(page=self.number,kind='text',key=key,text=value,font_pt=size,
            rect=[rect.x(),rect.y(),rect.width(),rect.height()],bounds=[bounds.x(),bounds.y(),bounds.width(),bounds.height()]))
        self.p.drawText(rect,flags,value)
    def graphic(self,key,rect,**extra):
        if rect.left()<0 or rect.top()<0 or rect.right()>self.w+.01 or rect.bottom()>self.h+.01:raise PageLayoutError('图形越过有效区域：'+key)
        self.ledger.append(dict(page=self.number,kind='graphic',key=key,rect=[rect.x(),rect.y(),rect.width(),rect.height()],**extra))
    def footer(self,total):
        self.text('footer',QRectF(0,self.h-14,self.w,14),f'光纹 | 数值模拟，非实测 | 第{self.number}页 / 共{total}页',9.5,align=Qt.AlignmentFlag.AlignHCenter)

SCIENCE_TEXT=(
 'I(ρ)/I(0) = [2 J1(u)/u]^2；u = π D ρ/(λ z)；ρ = sqrt(x^2+y^2)。\n'
 'u=0取极限1。J1为一阶贝塞尔函数；D为圆孔直径。\n'
 '理想圆孔、单色相干均匀平面波垂直入射；标量、傍轴夫琅禾费远场。\n'
 'F=(D/2)^2/(λz)≤0.05；ρ/z≤0.05。门槛不等于固定的强度误差百分比。\n'
 '本报告为数值模拟结果，并非实测数据。\n'
 '光强相对I(0)归一化；不同参数峰值不能比较实际透射光功率。\n'
 '二维为2×2 Gauss像素面积均值，灰度仅辅助；截面为线性连续点值。\n'
 '计算未包含近场、像差、偏振及绝对屏面照度。')

def page_one(page,s,total):
    p=s.params;W=page.w
    page.text('title',QRectF(0,0,W,30),'《光纹》光学模拟报告',20,True)
    page.text('model',QRectF(0,37,W,19),'圆孔夫琅禾费衍射 / Airy pattern',12.5,True)
    page.text('generation',QRectF(0,64,W,16),f'PDF生成时间：{s.generated_at:%Y-%m-%d %H:%M:%S} +08:00')
    page.text('software',QRectF(0,84,W,16),s.request.software)
    page.text('parameters',QRectF(0,111,W,17),f'波长 λ = {p.wavelength*1e9:g} nm    圆孔直径 D = {p.diameter*1e6:g} μm    屏距 z = {p.distance:.2f} m',11)
    page.text('range',QRectF(0,133,W,17),f'观察范围：x、y各 [-{s.half_span_m*1000:.6f}, +{s.half_span_m*1000:.6f}] mm')
    e=s.request.eligibility
    state=(f'F = {e.model.fresnel_number:.8f} ≤ 0.05；模型适用性：通过；傍轴范围已检查。\n'
      f'第一暗环理论半径：{s.first_dark_radius_m*1000:.6f} mm；{RING_TEXT[s.visibility]}。\n'
      f'二维科学计算网格：383×383；所需 {e.sampling.required_count}×{e.sampling.required_count}；最短周期 {e.sampling.pixels_per_period:.2f} 像素。')
    page.text('science-state',QRectF(0,159,W,64),state)
    page.text('screen-title',QRectF(0,236,W,18),'二维艾里斑观察屏',12.5,True)
    square=QRectF((W-360)/2,280,360,360);page.graphic('airy-image',square,source_grid=[383,383],isotropic=True)
    page.p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
    page.p.drawImage(square,display_image(s))
    page.p.setPen(QPen(QColor('#8697a6'),.6));page.p.drawRect(square)
    page.text('y-unit',QRectF(0,255,65,15),'y / mm',10.5,align=Qt.AlignmentFlag.AlignRight)
    for i,f in enumerate((0.,.5,1.)):
        x=square.left()+f*square.width();y=square.bottom()-f*square.height()
        value=f'{(2*f-1)*s.half_span_m*1000:.3f}'
        page.text('screen-x-tick-'+str(i),QRectF(x-32,647,64,15),value,10.5,align=Qt.AlignmentFlag.AlignHCenter)
        page.text('screen-y-tick-'+str(i),QRectF(0,y-7,65,15),value,10.5,align=Qt.AlignmentFlag.AlignRight)
    page.text('x-unit',QRectF(square.left(),670,square.width(),18),'x / mm',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    page.text('gray-note',QRectF(0,698,W,34),
        '灰度 = sqrt(像素面积平均 I/I(0))，仅辅助观察，RGB并非实测光强。\n页面缩放不增加383×383网格的科学信息；图中x、y比例相同。')
    page.footer(total)

def diagrams(page,s):
    p=page.p;page.text('diagram-heading',QRectF(0,418,page.w,20),'圆孔与光学装置示意（不按比例）',12.5,True)
    page.text('front-label',QRectF(0,445,182,16),'圆孔正面',10.5)
    page.text('device-label',QRectF(213,445,page.w-213,16),'均匀平面波垂直入射',10.5)
    opening=QRectF(60,468,48,48);page.graphic('aperture-circle',opening,isotropic=True)
    p.setPen(QPen(QColor('#526477'),.8));p.setBrush(QColor('#ffffff'));p.drawEllipse(opening);p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor('#1266a6'),.8))
    left,right,cy=opening.left(),opening.right(),opening.center().y()
    p.drawLine(QPointF(left,cy),QPointF(right,cy))
    for x in (left,right):p.drawLine(QPointF(x,cy),QPointF(x,534));p.drawLine(QPointF(x,529),QPointF(x,537))
    p.drawLine(QPointF(left,533),QPointF(right,533))
    page.text('diameter-label',QRectF(0,541,182,16),f'D = {s.params.diameter*1e6:g} μm',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    page.ledger.append(dict(page=page.number,kind='geometry',key='diameter-endpoints',
        opening=[opening.x(),opening.y(),opening.width(),opening.height()],start=[left,cy],end=[right,cy]))
    board,screen=273.,page.w-30
    p.setPen(QPen(QColor('#8697a6'),1.1))
    for x in (board,screen):p.drawLine(QPointF(x,474),QPointF(x,519))
    p.fillRect(QRectF(board-2,491,4,12),QColor('#ffffff'));p.setPen(QPen(QColor('#1266a6'),.8))
    for y in (483.,496.,509.):
        p.drawLine(QPointF(223,y),QPointF(board-12,y));p.drawLine(QPointF(board-16,y-3),QPointF(board-12,y));p.drawLine(QPointF(board-16,y+3),QPointF(board-12,y))
    p.drawLine(QPointF(board+15,497),QPointF(screen-12,497))
    page.text('distance-label',QRectF(board+18,474,screen-board-35,17),f'z = {s.params.distance:.2f} m',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    page.text('board-label',QRectF(board-35,525,70,16),'圆孔板',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    page.text('observation-label',QRectF(screen-30,525,60,16),'观察屏',10.5,align=Qt.AlignmentFlag.AlignHCenter)

def page_two(page,s,total,third):
    page.text('page2-title',QRectF(0,0,page.w,28),'过圆心截面与实验说明',17,True)
    p=s.params
    page.text('page2-parameters',QRectF(0,36,page.w,17),f'λ={p.wavelength*1e9:g} nm；D={p.diameter*1e6:g} μm；z={p.distance:.2f} m；二维网格383×383')
    page.text('curve-title',QRectF(0,63,page.w,18),'一维相对光强 I(x,0)/I(0)',12.5,True)
    rect=QRectF(58,96,page.w-98,208);page.graphic('linear-profile',rect,point_count=PROFILE_POINTS,linear=True)
    for i,value in enumerate((0.,.25,.5,.75,1.)):
        y=rect.bottom()-value*rect.height();page.p.setPen(QPen(QColor('#e2e8ee'),.5))
        page.p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
        page.text('curve-y-'+str(i),QRectF(0,y-7,47,15),f'{value:g}',10.5,align=Qt.AlignmentFlag.AlignRight)
    for i,f in enumerate((0.,.25,.5,.75,1.)):
        x=rect.left()+f*rect.width();page.p.setPen(QPen(QColor('#e2e8ee'),.5))
        page.p.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
        page.text('curve-x-'+str(i),QRectF(x-34,320,68,15),f'{(2*f-1)*s.half_span_m*1000:.3f}',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    page.text('curve-x-unit',QRectF(rect.left(),344,rect.width(),18),'横向位置 x / mm',10.5,align=Qt.AlignmentFlag.AlignHCenter)
    d=s.profile.data;xs=rect.left()+(d.x+s.half_span_m)/(2*s.half_span_m)*rect.width();ys=rect.bottom()-d.intensity*rect.height()
    poly=QPolygonF([QPointF(float(x),float(y)) for x,y in zip(xs,ys)])
    page.p.save();page.p.setClipRect(rect.adjusted(-1,-1,1,1));page.p.setPen(QPen(QColor('#1266a6'),1.1));page.p.drawPolyline(poly);page.p.restore()
    page.text('curve-legend',QRectF(0,376,page.w,32),
        '蓝线：I(x,0)/I(0)，线性连续点光强。\n截面与二维图使用同一参数和观察范围；中心点为1。')
    diagrams(page,s)
    if third:
        page.text('science-next-page',QRectF(0,603,page.w,35),'科学公式与适用限制见第3页。')
    else:
        page.text('science-heading',QRectF(0,575,page.w,19),'科学公式与适用限制',12.5,True)
        page.text('science-notes',QRectF(0,603,page.w,129),SCIENCE_TEXT)
    page.footer(total)

def _paint_document(device,snapshot):
    writer=QPdfWriter(device);writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Portrait)
    writer.setPageMargins(QMarginsF(15,15,15,15),QPageLayout.Unit.Millimeter)
    # One logical unit is one typographic point. Embedded image retains its
    # original383 pixels; vector text/curve remains resolution-independent.
    writer.setResolution(72);writer.setTitle('《光纹》圆孔夫琅禾费衍射报告');writer.setCreator(snapshot.request.software)
    painter=QPainter()
    if not painter.begin(writer):raise OSError('无法开始PDF绘制')
    ledger=[];W,H=float(writer.width()),float(writer.height())
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering,True)
        page=Page(painter,W,H,1,ledger);third=page.measure(SCIENCE_TEXT,W).height()>129
        total=3 if third else 2
        page_one(page,snapshot,total)
        if not writer.newPage():raise OSError('无法创建PDF第2页')
        page_two(Page(painter,W,H,2,ledger),snapshot,total,third)
        if third:
            if not writer.newPage():raise OSError('无法创建PDF第3页')
            page=Page(painter,W,H,3,ledger)
            page.text('page3-title',QRectF(0,0,W,28),'科学公式与适用限制',17,True)
            page.text('page3-science',QRectF(0,53,W,H-100),SCIENCE_TEXT)
            page.footer(total)
    finally:ended=painter.end()
    if not ended:raise OSError('PDF绘制未正常结束')
    return dict(pages=total,paper='A4 portrait',margins_mm=15,paintable_pt=[W,H],
        body_font_pt=10.5,annotation_min_font_pt=9.5,text_overlap=False,text_clipping=False,ledger=ledger)

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

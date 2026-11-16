# LF-P0-A2-R1 使用与数据契约

本轮只增加 PDF 实验报告并修正缺级说明。软件版本仍为源码声明的 0.1.0，新构建标识为 `LF-P0-A2-R1`；报告不声称有 Git 提交或发行包身份。原物理模型、采样、渲染模块及 A1 两个测试文件逐字节保留。

## 导出 PDF

使用原入口 `F:\DevProjects\LightFringe\run.cmd`。在恢复默认按钮下方点击“导出 PDF 报告”。数值框输入请先回车确认。通过 Windows 系统保存对话框选择 `.pdf` 文件；同名文件沿用该对话框的覆盖确认。成功后提示完整路径，失败提示未保存，取消不生成文件。

报告为 A4 横向单页，使用 Windows 中文字体及 QPdfWriter/QPainter，文字与曲线可缩放。若内容无法在既定字号下清晰容纳，导出中止并报错，不通过极小字体塞入。

包含实验类型、真实版本/构建标识、生成时间（Asia/Shanghai）、当前参数和单位、实际视场、原始线性归一化曲线、同源像素平均光纹、适用性指标及科学说明。单缝不显示无关的双缝中心距；首暗纹在视场外时标注“当前范围不可确定”。双缝的 λz/d 明确称理论干涉因子周期，不宣称有限包络的所有侧峰严格等距。

## 快照和有效性

1. 在进入保存对话框前，核对当前控件参数、视场尺寸/DPR、已完成结果键及修订号；拒绝未确认数值输入、计算中、失败、陈旧或缺失结果。
2. 复用现有 `DisplayData.x/intensity/envelope/pixel_mean/span`，不调用强度求解器或另行采样。参数为原有 frozen Parameters，数组复制到不可变 bytes 的只读视图，连 `setflags(write=True)` 也不能修改。
3. 保存对话框的嵌套事件循环即使改变界面，报告仍使用同一份快照。关键长度调用现有 `characteristic_lengths`；准入调用原有 `validate` 和同一采样门槛，不引入第二套物理判据。
4. 曲线使用快照的全部原采样顶点；光纹沿用 GUI 的 `sqrt(pixel_mean)` 灰度显示口径。报告明确指出这是辅助显示，相对光强不是绝对透射功率。
5. QSaveFile 禁用直接写入回退；PDF writer 完成并释放后才原子提交。绘制/提交失败取消临时写入，保护已有同名文件。

## 缺级 LOW 修正

GUI 的 a、d 是准确的整数微米输入。以整数 Fraction 约分得 d/a=p/q（互质），则每第 p 级纯干涉极大与第 q 级包络暗纹重合；只修正说明，不修改强度。

例如 d/a=5/2，每第 5 级理论缺级；d/a=7/2，每第 7 级理论缺级。使用整数输入本身，不对浮点比值做 `limit_denominator` 或“足够接近”的有理数猜测。报告同时判断首组缺级是否在当前视场内，避免把理论条件当作视场中的已观测峰。真实有限距离实验不保证缺级处严格为零。

## 测试及证据

```powershell
Set-Location F:\DevProjects\LightFringe
& F:\Tools\Anaconda3\envs\lightfringe-p0\python.exe -B -X utf8 scripts\test_a2.py
```

共 46 项：A1 原有 24 项，加 A2 22 项。A2 还使用现有 Qt PDFium 解析生成报告，并核对实际绘图命令与快照数组；没有新增依赖。

性能与样例重生成：`scripts/qa_a2.py`（不加参数会退出窗口并保存样例/计时）。`--native-flow` 是施工对话框自动验收夹具，当前不能在本机通过 Qt 定时器完成原生对话框确认，已保留失败证据，不应当作已通过的验收入口。

本轮全部证据位于 `F:\DevProjects\LightFringe\artifacts\LF-P0-A2-R1`。详见其中 `FINAL_REPORT.md`、`final_tests.log`、`DIFF.patch`、BEGIN/END 哈希和 `acceptance_status.json`。

最终状态为 READY_FOR_INDEPENDENT_REVIEW。外部桌面截图/原生点击工具失败记录为 NOT_RUN / TOOL_FAILURE；两份 PDF 的内容、中文、页面渲染和应用服务层保存行为已经验证。原生保存/取消/覆盖的真人点击仍建议独立审计及试玩补测。没有进入 A3。

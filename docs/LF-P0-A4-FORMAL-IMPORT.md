# A4圆孔正式导入说明

## 已完成状态与正式基线

A4圆孔夫琅禾费衍射已通过LF-P0-A4-FORMAL-IMPORT-OWNER-RISK-ACCEPTED-R1导入正式工程。导入范围为ADD10、MODIFY4、DELETE0、PRESERVE380，四份原始修改前文件有回滚备份。原384项文件路径保留，新增10项后正式集合为394文件、191目录。

后续Post-Import独立审计归档为LF-P0-A4-FORMAL-IMPORT-POST-IMPORT-INDEPENDENT-AUDIT-R1；其身份核验和caveat按原记录保留。本次DOC-001补充只提供文档候选，不重新执行394项考古、导入或独立审计。Clean Git Seed拟选48项目标也不是原394项正式集合的重新封存。

四模式为：单缝衍射、双缝干涉与衍射、多缝干涉与衍射、圆孔夫琅禾费衍射。主入口使用AiryPdfMainWindow，继承旧三模式并接入圆孔GUI及PDF。airy_main.py作为已有兼容入口保留，不替代正式-m入口。

## 启动及环境

双击源码根run.cmd为主要启动方式；run.ps1为可选方式，不修改PowerShell执行策略。两者在自身源码根用固定A4-R1解释器执行-E -s -B -m lightfringe，run.cmd同时保持OPENBLAS_NUM_THREADS=1。包内相对拓扑不变，不引入src-layout。

A4依赖由requirements-a4.txt和runtime-a4.json记录：Python 3.12.16 x64、NumPy 2.2.6、SciPy 1.16.3、PySide6/Qt 6.8.3及固定附属包、tzdata。A4-R1位于F:\DevProjects\_Envs\LightFringe\A4-R1，依赖原lightfringe-p0基础Python的标准库/DLL。环境前缀保持原位，不是可直接移动的独立发行包；不向原环境安装构建依赖。

PDF使用Microsoft YaHei UI系统字体和Asia/Shanghai时区数据。相对PDF输出目标依赖调用方工作目录，GUI保存对话框则使用用户选择的目标。字体替换和新系统运行条件需要单独验证。

## 冻结科学与采样契约

圆孔采用标量、傍轴、夫琅禾费模型：

I(ρ)/I(0) = [2J1(u)/u]^2，u = πDρ/(λz)，ρ = sqrt(x²+y²)。

λ为波长，D为圆孔直径，z为屏距；中心强度按连续极限取1。维持F=(D/2)^2/(λz)≤0.05、ρ/z≤0.05、每最短周期至少12个物理像素及383×383计算预算。二维屏幕数据为像素面积均值，sqrt灰度仅辅助观察；一维曲线是线性归一化连续点值，不把灰度当作光强。

三份冻结文件SHA256：

| 文件 | SHA256 |
|---|---|
| lightfringe/circular_model.py | c2aafe33709b6a8982c94986f4864aed566016d33cde17e78355ea84440c460d |
| lightfringe/circular_sampling.py | 299c9c322ea5809d85f3eaab0058c46391ee087bf9a63b6378de61a3575d3aa6 |
| lightfringe/circular_report.py | 259ddc5bc856ed0646bd72c4fe4a6c84bd6d170828b9b9e1df7c6ba8a6cfad55 |

FULL、PARTIAL、OUTSIDE描述第一暗环相对正方形观察视场的覆盖。令第一暗环半径为r1、视场半宽为s：r1≤s为FULL（整环在视场内）；s<r1≤sqrt(2)s为PARTIAL（环仅部分落入视场，边界按核心判定）；r1>sqrt(2)s为OUTSIDE（第一暗环不在视场内）。核心枚举值分别为FIRST_RING_FULL、FIRST_RING_PARTIAL、FIRST_RING_OUTSIDE_VIEW。覆盖状态不替代物理模型有效性，OUTSIDE不等于MODEL_INVALID。

## GUI与PDF独立资格

GUI网格随窗口尺寸和DPR变化，上限383×383；275或340等当前网格不是PDF计算网格。圆孔PDF从同一冻结实验参数快照，调用已验收科学核心重新计算383×383二维数据，不放大GUI截图冒充科学计算。

| 情况 | GUI行为 | PDF行为 |
|---|---|---|
| 模型有效，GUI275，所需332 | 显示采样不足，暂停显示 | 独立383计算足够，允许导出 |
| 模型有效，GUI340，所需332 | 正常显示 | 仍用383计算，不复用340图像 |
| 模型有效，所需405 | 383预算不足，暂停显示 | 拒绝；理由是软件PDF采样上限不足 |
| MODEL_INVALID | 按冻结模型契约暂停有效结果 | 不生成正常科学结果报告 |

波长、孔径、屏距、观察范围、模型状态、PDF资格及图文须对应同一快照。PDF注明二维科学计算网格383×383。原三模式科学模型、PDF结构及U1/U2示意和术语保留；不扩张采样预算、不更改旧提示文案。

## 历史验收及各轮测试口径

以下为已存在的历史记录，不是本次文档补充、新种子或新一轮独立测试。

| 轮次/来源 | 原有结论 | 使用边界 |
|---|---|---|
| A4-1科学核心 | 已完成独立复审及验收 | 本次不重新计算科学结果 |
| A4-2 GUI | 独审及Owner为PASS_WITH_CAVEAT | Owner接受383网格既有响应速度、紧凑窗口文字重叠P3和原采样不足提示 |
| A4-3 PDF | 独审PASS_WITH_CAVEAT；Owner四项真人验收4/4 PASS | 不冒充本次重新视觉验收 |
| LF-P0-A4-RUNTIME-ENV-R1 | 该环境验收轮191/191，另有PDF28/28，合计219/219 | 来自ENV-VERIFICATION.md及对应分组日志；不同于后继契约轮 |
| 后继契约及其独审 | 保留190 PASS/1 FAIL；G10旧范围断言已记录为过时范围问题；PDF历史28/28 | 不修改原断言，不把190/1改写成191/191；独审还保留旧67原生中止证据 |
| Owner风险接受正式导入轮 | run.cmd有界入口冒烟及正常关闭记录；旧67、191聚合、A4科学和PDF28未重跑 | 入口截图/自动切换有工具限制，不能据此声称本轮四模式视觉或PDF重新通过 |
| 本次DOC-001补充 | 三文件内容、补丁重建和字节身份检查 | Python、Qt、GUI及产品测试均未执行 |

历史234项旧夹具的六项FAIL分类及原始失败证据继续保留。可选PDF第三页字体后备未被专门强制验收；本次不扩大既有排版验收范围。旧test.ps1、scripts/run_tests.py及部分性能入口会写旧artifacts，不能直接在正式工程重跑来换取新PASS。

Owner历史验收与风险接受源于各阶段Owner裁决；本说明不生成新的Owner验收。相关原件保留在外部审计根F:\DevProjects\_Audits\LightFringe，以任务ID和SHA定位，不复制历史大包进源码种子。

## 原生风险与发行边界

历史已记录0xC0000374及0xC0000005原生异常。Owner接受潜在风险、批准A4纳入1.0及正式导入；历史失败报告不改写，NATIVE_ROOT_CAUSE=UNRESOLVED、HISTORICAL_NATIVE_GATE=CLOSED、STABILITY_TOOLCHAIN=FROZEN。风险接受不等于原生稳定性技术PASS，也不授权恢复30轮实验或观测器研发。

既定GUI响应、紧凑窗口P3及原采样提示caveat保留。本次不改科学核心、GUI、PDF实现、版本或构建标签。EXE制作、跨电脑冷启动、实际发行许可和最终科学等价性有各自门槛，不能由正式导入或文档补充推导为已经完成。Clean Git Seed和Git初始化仍需后续明确授权。

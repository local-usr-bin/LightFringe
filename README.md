# 光纹 LightFringe

Windows 波动光学实验程序。A1～A4产品功能已纳入正式工程；正式入口为AiryPdfMainWindow。本说明对应Clean Git Seed拟保留的根目录布局，种子建立和Git初始化仍需另行批准。

## 已完成的产品能力

| 阶段 | 已实现范围 |
|---|---|
| A1 | 单缝衍射、有限缝宽双缝干涉与衍射；参数输入、观察屏、线性归一化光强曲线和模型/采样提示 |
| A2 | 原有模式PDF报告、参数与科学状态说明、保存取消及失败保护 |
| A3 | 有限缝宽多缝干涉与衍射，整数N=3～8；GUI、采样判定及PDF |
| A4 | 圆孔夫琅禾费衍射；圆孔正面示意、二维艾里斑/同心环、一维强度曲线，以及独立383×383科学计算的圆孔PDF |

单缝、双缝、多缝和圆孔均可从正式GUI选择。滑块与数值输入同步；恢复默认参数和实验模式切换按已有契约处理。显示灰度的平方根映射用于辅助观察弱条纹，科学曲线保持线性I/I(0)；各配置分别按中央强度归一化，不能据此比较绝对功率。

采用标量、傍轴、夫琅禾费远场模型。无效模型或当前显示采样不足时，GUI暂停相应科学显示，不自动修改参数来消除提示。圆孔PDF独立判断模型及383×383采样资格：当前窗口不足以显示，不必然禁止报告导出；所需PDF采样超过383时拒绝，不能误称物理模型无效。

原三模式PDF能力保留。通过“导出PDF报告”选择保存位置；取消不生成报告，失败不替换已有报告。圆孔报告使用同一参数快照，GUI显示网格与PDF计算网格可能不同。完整圆孔科学/采样契约、历史验收和局限见[说明](docs/LF-P0-A4-FORMAL-IMPORT.md)。

## 当前同机源码启动

使用已经验收、保持原位的A4-R1环境。主要方式是在本源码根目录双击run.cmd；它切换到自身目录，以固定解释器和参数启动-m lightfringe，不要求把源码放回旧正式工程目录。

解释器位于：

F:\DevProjects\_Envs\LightFringe\A4-R1\Scripts\pythonw.exe

run.cmd保留-E -s -B以及OPENBLAS_NUM_THREADS=1。可选run.ps1使用同一解释器并将工作目录设为脚本所在目录；如受Windows执行策略限制，使用CMD入口，不修改策略或使用Bypass。

需要控制台时，在当前源码根目录打开PowerShell后运行：

~~~powershell
$env:OPENBLAS_NUM_THREADS = '1'
& 'F:\DevProjects\_Envs\LightFringe\A4-R1\Scripts\python.exe' -E -s -B -m lightfringe
~~~

此命令要求当前工作目录是包含lightfringe包的源码根。-E会忽略Python环境变量，不能依赖PYTHONPATH替代正确工作目录。正常关闭使用窗口关闭按钮。

## 环境与依赖

运行身份为Python 3.12.16 x64、NumPy 2.2.6、SciPy 1.16.3、PySide6/Qt 6.8.3；PySide6附属包和shiboken6同为6.8.3，tzdata为2025.2。精确包版本及哈希见requirements-a4.txt，环境前缀和基础解释器身份见runtime-a4.json。该JSON是身份记录，不会动态改变启动器使用的解释器。

A4-R1仍依赖原基础Python前缀F:\Tools\Anaconda3\envs\lightfringe-p0的标准库和DLL。不要移动A4-R1或A4-BUILD-R1，不将venv复制到源码仓库，不向已验收环境安装构建工具。本说明不提供覆盖已有环境的安装命令；未来重建应使用新环境、精确锁及独立验证。旧requirements.txt、environment.yml和历史Conda命令不作为A4重建入口。

GUI及PDF依赖系统Microsoft YaHei UI字体，报告使用Asia/Shanghai时区数据；换电脑后需单独验证字体、度量、原生依赖及运行条件。当前源码启动方式不构成跨电脑便携运行证明。

## 代码、测试与参考数据

| 路径 | 用途 |
|---|---|
| lightfringe/ | 16个现有产品模块；保留科学、GUI及PDF之间的包内相对导入 |
| lightfringe/__main__.py | 正式-m入口，创建AiryPdfMainWindow |
| tests/ | 六份既有测试源码，保留原断言；静态67个测试方法不等于已执行67项 |
| artifacts/LF-P0-A2-R1/与artifacts/LF-P0-A3-MULTISLIT-R1/ | 仅八项活动夹具：各自BEGIN_nominal_outputs.json和baseline/lightfringe下三份科学/渲染源码 |
| docs/SCIENTIFIC_MODEL.md | 原单缝/双缝模型与验证策略 |
| docs/LF-P0-A2-R1.md、docs/LF-P0-A3-MULTISLIT-R1.md | 对应阶段的科学/报告参考；历史执行结论按原轮次解释 |
| docs/LF-P0-A4-FORMAL-IMPORT.md | A4正式接入、383采样、历史验收及风险说明 |
| requirements-a4.txt、runtime-a4.json | 当前运行锁与环境身份 |

八项夹具依赖当前相对位置；不得只移动参考数据而忽略tests/test_report.py的根目录推导。六份测试不含完整A4圆孔专项；历史191/191、后继190 PASS/1 FAIL及PDF28/28来自不同轮次，不是本说明或新种子的运行结果。当前文档补充未执行Python、GUI或任何测试。

旧test.ps1及八个开发脚本为CONDITIONAL，初始种子不纳入。它们有旧解释器、写artifacts或旧任务清单等约束；不能把旧命令直接当作当前A4验收入口。未来只在获准的隔离运行范围验证，保留原失败记录，不为全绿修改旧断言。

## 状态、风险与后续维护

A4已按Owner风险接受决定正式导入；历史0xC0000374及0xC0000005风险仍保留，原生根因UNRESOLVED，历史Native Gate保持CLOSED。风险接受不等于原生稳定性技术PASS。GUI响应速度、紧凑窗口P3和原采样提示的既定caveat继续保留。

产品代码的版本/构建标签仍保留现有0.2.0及阶段标识；面向1.0的源码整理不是已完成的1.0发行。没有依据在此宣称EXE已生成、独立分发已通过或跨电脑运行已验收。

Clean Seed计划只包含48个初始目标。精确纳入名单与SHA、Git属性及实际索引/检出字节验证共同保护首基线；.gitignore本身不批准纳入，也不能取消已经跟踪的文件。23项CONDITIONAL继续暂缓，历史审计和原始产物留在外部原位。

CHANGELOG、维护说明、project-control最小索引、packaging说明及第三方通知属于后续种子计划，本次三文件补充未创建这些文件。未来新增实验、升级NumPy/SciPy或更换打包器须各自验证科学、GUI/PDF和依赖许可，保持当前冻结科学核心不变。第三方组件保留各自许可，源码种子通过不代表最终发行许可已经闭合。

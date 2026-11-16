# 维护规则与项目状态

本文件是本候选的项目级维护入口；任务开始先读本文件与project-control/BASELINE-LINK.json，再读取实际工作树及所引用的封存证据。任务结束更新项目状态、受影响的依赖/科学参考记录及实际验证结果，不能依赖聊天历史认定正式基线。

## 工程责任

1. Codex负责日常维护源码基线、目录、环境记录和项目状态，核验实际路径与文件身份。
2. Git负责源码历史、差异和变更追踪；本候选尚未初始化Git，写操作需另行授权。
3. SHA256用于外部二进制、科学参考数据及审计证据身份，不把Git对象ID当作文件SHA。
4. 普通功能开发由Codex在已授权范围自主施工并做针对性测试，保留真实失败。
5. 科学模型/数值契约、原生依赖及发行重大节点安排专项独立审计。
6. Owner负责产品方向及重大决策；本地事实和验证由Codex持续维护。
7. 不重复开发事务发布器、LPM或复杂项目管理系统。三份project-control文件仅作最小追溯和状态记录。
8. 不擅自修改持久User/Machine PATH、注册表或系统策略。Process PATH与持久PATH分别记录。
9. 不移动A4-R1、A4-BUILD-R1、基础Python或历史证据；产品环境与构建环境隔离。
10. 状态记录只写已发生的动作、实际测试及未解决事项；未运行填NOT_RUN，失败记录不能重写为PASS。

## 当前状态与来源

原正式工程为F:\DevProjects\LightFringe，394文件/191目录；本候选48文件不取代该正式工程。37项原字节、3项已独审文档后继及8项新管理文件的来源身份由project-control/BASELINE-394-MAP.csv、BASELINE-LINK.json与外部本轮审计记录关联。

本轮唯一候选位于F:\DevProjects\Candidates\LightFringe\LF-GIT-SEED-R1；施工归档位于F:\DevProjects\Audits\LightFringe\LF-GIT-SEED-01-CANDIDATE-BUILD-R1。历史封存仍在原_Audits下，不搬迁、不复制大包。项目状态首次为CANDIDATE_BUILT_PENDING_REVIEW。Git、正式切换、发行及新的产品执行均未由本轮完成。

## 运行与路径边界

产品包保持根lightfringe/的16模块拓扑，不引入src-layout，不改__main__.py或测试断言。run.cmd为主入口，固定原位A4-R1解释器、-E -s -B及OPENBLAS_NUM_THREADS=1。run.ps1可选，不修改ExecutionPolicy、不用Bypass。-m调用需从源码根运行；CMD自行切到脚本根。运行锁在requirements-a4.txt，runtime-a4.json是身份记录而非动态解释器选择器。

A4-R1为Python3.12.16、NumPy2.2.6、SciPy1.16.3、PySide6/Qt6.8.3及同版附属包、tzdata2025.2；仍依赖基础Python前缀，不能复制venv冒充便携发行。当前目标为Windows x64；历史支持说明为Windows10 1809及以后，本机历史记录为22H2/19045，不代表其他系统已验收。Microsoft YaHei UI系统字体和Asia/Shanghai时区数据须在目标系统验证。

## 科学、参考与测试

三份circular_model.py、circular_sampling.py、circular_report.py冻结SHA见BASELINE-LINK.json。科学核心保持原字节；新功能不借机优化旧科学实现。新增实验可以增加具体模型及对应测试，再做小范围GUI/PDF接线，不预建插件架构或空抽象层。

八项选定参考必须保留各自路径：A2四项由当前test_report直接读取；A3四项用于历史test_a3包装器兼容，不能算当前默认67项的新增覆盖。科学登记同时记录14项未纳入的NPZ/CSV；不得按SHA合并同字节的不同路径，不把历史计算输出自动提升为金标准。23项CONDITIONAL及331项EXCLUDE继续暂缓/排除。

六份测试源码合计67个静态方法，主要覆盖旧三模式；不是完整A4专项。本轮未执行这些测试。后续产品执行先获准确范围和输出授权，保护八项夹具，不在旧正式工程重跑会写历史artifacts的入口。A4科学、四模式、GUI/PDF383、视觉与数值参考验证按外部独审A4-ACCEPTANCE-GAP-PLAN.md另行安排；历史191/191、190/1、PDF28/28分别保留，不冒充新候选结果，不改断言换取全绿。

历史0xC0000374/0xC0000005根因UNRESOLVED，历史Native Gate=CLOSED，稳定性工具链FROZEN；Owner接受风险与技术PASS分开。Owner精确4/4验收的原始决定/time/SHA尚有独审证据限制，归档复用前核实，不能从阶段独审推导新验收。

## Git与升级

.gitignore的48项例外只保护未跟踪文件选择；实际纳入必须同时满足Ordinal精确路径、普通文件/无重解析祖先、批准SHA/大小和最终索引集合。大小写变体、强制add及已跟踪文件不能由ignore单独阻止。

.gitattributes默认及48项明确unset text/filter/ident/working-tree-encoding/eol。实际Git引擎、有效属性、原始blob SHA和首次checkout SHA均NOT_RUN；后续授权后应固定Git路径与本地配置并逐项验证，不用文本管道读取blob，不改系统Git配置。

依赖升级使用新隔离环境和精确版本/wheel SHA锁，验证科学门槛、原生加载、GUI/PDF及许可，不向A4-R1安装工具。构建器配置与锁仅在packaging/分离，运行锁不掺构建依赖，build/dist/EXE不进入源码。版本仍为0.2.0/A3标签；1.0版本元数据及真实发行记录在另行授权任务更新CHANGELOG。

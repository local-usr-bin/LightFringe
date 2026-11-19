# 光纹 LightFringe 1.0
Windows波动光学实验程序：单缝、双缝、多缝、圆孔GUI及代表性PDF导出。

本地1.0源码发行快照，计划仓库标识local-usr-bin/LightFringe；尚未创建远程或公开。PUBLIC_RELEASE=HOLD。本轮只收口源码、构建依据及许可文档，没有构建或动态测试。
版权© 2026 猫太郎；公开联系233345754@qq.com。自有代码及明确列名的两份参考JSON采用[MIT](LICENSE)，第三方按[各自许可](THIRD-PARTY-NOTICES.md)。

## 产品与科学范围
A1单缝及有限缝宽双缝；A2旧模式PDF；A3多缝N=3～8；A4圆孔夫琅禾费衍射、二维艾里斑、一维相对强度与独立383×383圆孔PDF。
采用标量、傍轴、夫琅禾费远场模型。灰度平方根映射只辅助观察，科学曲线保持线性I/I(0)。FULL/PARTIAL/OUTSIDE及PDF独立采样资格不变，超过383网格拒绝，不放宽容差。
入口仍为lightfringe.__main__，创建AiryPdfMainWindow；16模块相对拓扑不变。[圆孔历史契约](docs/LF-P0-A4-FORMAL-IMPORT.md)和[科学模型](docs/SCIENTIFIC_MODEL.md)保留。

## 从源码运行
以下命令本轮未执行。先准备并核验Windows x64、Python3.12.16、PySide6/Qt/Shiboken6.8.3、NumPy2.2.6、SciPy1.16.3、tzdata2025.2的独立环境；精确产品包锁见requirements-a4.txt。不要向冻结A4环境安装构建工具。
在含lightfringe/的仓库根，使用已激活并核验的匹配环境：
~~~powershell
$env:OPENBLAS_NUM_THREADS = '1'
pythonw.exe -E -s -B -m lightfringe
# 需要控制台时：
python.exe -E -s -B -m lightfringe
~~~
-E忽略Python环境变量，不能靠PYTHONPATH代替工作目录。需系统Microsoft YaHei UI字体及Asia/Shanghai时区数据。
run.cmd/run.ps1原字节保留，仍绑定维护机A4-R1绝对解释器；换电脑用明确的匹配环境和模块入口，不修改执行策略或用Bypass。runtime-a4.json是原环境身份/历史字段记录，不是当前版本声明或可移植安装配置；旧venv不能复制冒充绿色包。

## 目录与验证边界
- lightfringe/：16模块；本提交同步已批准的__init__/gui/report三份1.0标识后继，其余13模块原字节，三圆孔科学核心冻结。
- tests/：六份旧测试原断言；67为静态方法数，不是本轮执行数，也不等于完整A4覆盖。
- artifacts/：八项活动夹具原位。23项CONDITIONAL及其它历史文件没有自动纳入。
- [references/](references/README.md)：两份原字节、Owner授权MIT的计算/历史检查JSON，PASS/FAIL不改，不自动当新PASS或全部金标准。
- [packaging/](packaging/README.md)：实际GUI-R1入口/spec/hook/资源及外部前置；不是无需准备即可完整构建的环境。
- [源码与EXE对应](docs/SOURCE-RELEASE.md)、[维护](docs/MAINTENANCE.md)。

当前源码对应封存1.0程序的产品输入与构建依据；本轮未重建，不保证同SHA重建。封存Runtime/ZIP不入库、不改动；六份第三方源码档仍随二进制ZIP提供。
Owner已有Win11限定验收；Win10仅启动/GUI外观，功能/PDF NOT_RUN；未捕获退出码UNKNOWN。历史原生异常根因UNRESOLVED、NativeGate CLOSED、工具链FROZEN。
当前无远程、Tag、Push或Release，后续公开需Owner最终授权。

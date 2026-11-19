# GUI-R1构建来源（本轮未执行）
本目录对应现封存1.0 GUI EXE的既有构建依据；只作路径整理，不承诺clone即可完整构建或生成同SHA。
默认launcher调用lightfringe.__main__.main；两个显式诊断分支及早期hook为对应实际EXE保留，不是新的执行授权。

## 文件与适配
launcher.py、early-origin-hook.py、lfdiagnostics.py、releasechecks.py从实际GUI-R1输入RAW EXACT复制，无历史诊断合同/环境快照。
version-resource.txt仅纠正旧DRAFT注释，资源字段原值不变。
LightFringe.spec与hooks/hook-PySide6.QtGui.py仅将本机绑定改成本地配置、仓库根相对路径；不删除任何断言。
build-roots.example.json是结构示例，build_env留null，必须另行提供真实受控外部环境。复制为build-roots.local.json再填值，该本地文件不入Git。

## 路径和输入
所有相对值以仓库根解析，hook读同一配置。source为根，scripts/hooks为本目录；audit是新隔离证据目录，事先建立且不得覆盖旧结果。
science-data只收references两JSON；science-source只收lightfringe三冻结圆孔.py，目标名/Runtime相对结构不变，不收README或整个产品目录。
输出、work、缓存及临时目录必须在获准隔离范围；不能写冻结工程或发行包。

必要前置：
1. 已核验Python3.12.16 x64、PySide/Qt/Shiboken6.8.3、NumPy2.2.6、SciPy1.16.3、tzdata2025.2的独立原生环境。历史build_env不是普通venv，旧python312._pth含现场source/scripts路径，不能原样作为通用重建配置。
2. B0已修复的NumPy _core/_multiarray_umath与fft/_pocketfft_umath两PE：哈希MSVCP导入名改msvcp140.dll，OpenBLAS原名/字节保留。本库不附PE，不重新修复或编译。
3. PyInstaller6.22.3、hooks2026.10、pefile2024.8.26、altgraph0.17.4、setuptools80.9.0；仅pip精确版本不证明原生来源/环境等同。
4. 受控环境提供libssl-3-x64.dll/libcrypto-3-x64.dll；子进程DLL搜索排除未批准Poppler等，spec的来源断言保留。
5. spec在Analysis/EXE.dependencies/COLLECT边界排除环境VC；之后从有授权/已核验官方制品原字节装配msvcp140.dll、msvcp140_1.dll、msvcp140_2.dll、vcruntime140.dll、vcruntime140_1.dll（14.52.37029.0）到输出Runtime。不是System32副本，也不由本spec自动下载/附加。
6. 最后附加已审文档、许可、六源档并做最终包和目标机验证；这些材料不在本库重复存放。

## 保留的行为与限制
console=False、contents_directory=Runtime、strip/upx关闭、未处理异常提示保留；PySide/Shiboken纯Python外置；QtCore/Gui/Widgets及必要五插件；Mesa精确SHA排除、原生来源断言、OpenSSL唯一来源、三处VC过滤均不变。
原ux-postbuild不改EXE/native或重打base_library.zip；只比较PyInstaller自然生成的成员顺序变化，装配已核验VC/文档/许可/source-offer，并产审计记录。旧TASK/SEAL绑定控制器不被删门禁改成新框架；replacement-witness准备也非正常构建入口。
前置和新隔离目录经另行授权备齐后，用受控build_env解释器的-B -m PyInstaller，显式传此spec及独立distpath/workpath。本轮未运行该命令/spec/hook/诊断入口；路径适配可改变co_filename/产物SHA，不称重建已验证。

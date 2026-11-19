# 构建材料与发行边界
[gui-r1/README.md](gui-r1/README.md)保存实际入口、spec、Qt hook、资源及诊断模块来源和最小路径适配。
本轮未执行这些文件，没有新EXE、安装、环境或同SHA可复现构建声明。
产品锁见根requirements-a4.txt、历史环境身份见runtime-a4.json，A4-R1/A4-BUILD-R1不改。GUI-R1使用外部PyInstaller6.22.3/hooks2026.10等，不把早期Nuitka阻断方案当本次打包器。
普通新venv不自动等于已验隔离原生环境；NumPy两PE预处理、OpenSSL、官方VC及最终许可/源码附加都有外部前置。
本仓库无Runtime/EXE/DLL/PYD、wheel、六大型源码档及审计大包；源码审阅ZIP不是运行包。科学/GUI/PDF/Qt替换或旧回归均未运行，PUBLIC_RELEASE=HOLD。

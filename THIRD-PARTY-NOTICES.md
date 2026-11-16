# 第三方依赖与通知登记

范围：本源码候选的外部依赖身份及待办。这里没有第三方二进制、环境或发行包；本文件不是许可证全文合集，也不授予任何组件再分发权。LightFringe自身源码许可由Owner决定，当前不推定为MIT或商业许可。

## 当前运行依赖

精确版本及安装介质SHA由requirements-a4.txt原字节保留；安装路径在外部A4-R1。以下为本轮只读安装METADATA记录的标签，不能替代实际分发组件和原始许可文本审查。

| 组件 | 版本 | 本地许可标签/来源 |
|---|---|---|
| Python | 3.12.16 | 外部基础解释器；Python原始许可与构建随带组件待发行核对 |
| NumPy | 2.2.6 | METADATA含NumPy Developers版权及完整多组件许可段落；官方来源https://numpy.org / https://github.com/numpy/numpy |
| SciPy | 1.16.3 | METADATA含SciPy Developers版权及完整多组件许可段落；官方来源https://scipy.org / https://github.com/scipy/scipy |
| PySide6 | 6.8.3 | METADATA标注LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；来源https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| PySide6_Addons / PySide6_Essentials | 6.8.3 | 同版，安装METADATA同上；Qt实际模块及插件许可须逐组件审查 |
| shiboken6 | 6.8.3 | 安装METADATA同上，实际许可选项及义务须按来源文本核对 |
| tzdata | 2025.2 | METADATA标注Apache-2.0并列LICENSE及licenses/LICENSE_APACHE；来源https://github.com/python/tzdata |

上述PySide METADATA列出LicenseRef-Qt-Commercial.txt不证明本项目拥有商业授权，本文件不作这种声明。Qt6.8.3原生库、插件及其捆绑第三方成分不能只凭PySide包名推断完整许可。NumPy/SciPy的BLAS/Fortran等原生成分须按真实wheel/发行包核对，当前未把环境整体搬入候选。

## 构建和系统依赖

pip25.0.1为外部环境管理工具，非当前产品包纳入对象；Nuitka、ordered-set、zstandard等属外部构建环境。未来实际使用/随包成分分别登记版本、文件来源、SHA与许可；源码种子不复制其二进制或默认推定许可完成。

Microsoft VC Runtime、Windows系统组件、字体和Qt/第三方运行库的实际分发与系统前置条件分开处理。Microsoft YaHei UI是系统字体依赖，本候选不打包字体。源码MIT假设或携带EULA均不能覆盖微软DLL、字体及其他第三方权利。当前没有下载/复制微软DLL。

## 发行待办

LICENSE_INVENTORY=INCOMPLETE。最终包必须有实际组件清单、适用原始许可全文及来源、必要通知、许可条件和再分发权核对。此文件只记录依赖，不宣称已完全合规、可便携运行或已发行。外部00B/00C和构建阻断继续有效。

# 许可证与第三方依赖
自有代码与references/下两份明确列名资料采用根LICENSE标准MIT：
Copyright (c) 2026 猫太郎；公开联系233345754@qq.com。
Git作者/提交者沿用既有配置，与发行署名和公开邮箱分开，旧历史不改。

## 实际纳入
16产品模块、两JSON、旧测试/夹具、本方GUI-R1构建/诊断支持源码及文档。不附Python/Qt/NumPy/SciPy二进制、微软DLL、六大型源码档、环境或内部审计报告。
本方hook调用PyInstaller公开API，不复制完整工具包。外部组件的使用/构建/分发仍按其许可；MIT不重许可它们。

## 两份参考资料（Owner明确授权MIT）
- references/numerical-reference.json：869dd9df4290302bbde1e7807e528ebc1dbf8d2fb409f74c38292a0c64724d78。
- references/independent-science.json：8d26b74bb102c2912a1b4a391d70a1221b3453097f737df1f6b9f3a3e4ee2b6e。
保留项目生成记录的原字节/组织/历史结果/路径，不扩为任意外部资料许可。见references/README.md。

## 外部依赖与二进制边界
| 组件 | 已用版本 | 许可/通知范围 |
|---|---|---|
| CPython | 3.12.16 | PSF及历史/逐文件许可；Conda来源和上游源码边界另记 |
| NumPy / SciPy | 2.2.6 / 1.16.3 | BSD3及内含组件，OpenBLAS/LAPACK/GCC运行库例外 |
| PySide6 / Qt / Shiboken | 6.8.3 | 已验二进制选择LGPLv3共享库路径，保留实际嵌入宽松许可，非商业Qt声明 |
| tzdata | 2025.2 | Apache2.0包与IANA数据声明 |
| PyInstaller / hooks | 6.22.3 / 2026.10 | bootloader/loader GPL例外与实际Apache运行时分项，工具包不入库 |
| pefile / altgraph / setuptools | 2024.8.26 / 0.17.4 / 80.9.0 | 外部构建身份，各自许可 |

包名不能代替实际分发审查。完整运行包通知、208项原第三方材料及五微软14.52条款在封存绿色版，不把包内路径当本仓库已有文件。
六份source-offer档对应QtBase/QtTranslations/PySide-Shiboken6.8.3、NumPy2.2.6、SciPy1.16.3、CPython3.12.16，继续随二进制ZIP完整交付；GitHub自动仓库源码附件不替代它们。目录名不自动三年要约，原供源安排保持。
LGPL库修改、兼容替换及调试权保留；微软专属条件不扩大到MIT源码，单独用自有源码不以接受无关微软条款为前提。MIT不授微软DLL分发权。
PUBLIC_RELEASE=HOLD，静态快照不是重建验证、全面法律PASS或公开GO。

# 打包与发行边界

本目录当前仅保存说明，不含可执行spec、构建入口或产物。Clean Seed可审阅不等于standalone可发行。本轮EXE_BUILD=NOT_RUN，SCIENCE_PARITY=NOT_RUN，RELEASE_STATUS=CANDIDATE_NOT_RELEASED。

现有A4-R1是只读运行环境；A4-BUILD-R1是外部独立构建环境，两者原位保留并依赖基础Python，不复制进仓库。七包运行版本以requirements-a4.txt为准。预检记录已有Nuitka2.5.1、ordered-set4.1.0、zstandard0.22.0为构建身份；本轮不重新安装、运行或认证工具链。

外部00B结论保留NO_GO：既有Nuitka/Python组合与MSVC家族要求不闭合。00C的静态PE依赖和哈希VC映射不证明动态加载、ABI、最低补丁、再分发权或科学等价。本说明不批准PyInstaller、Nuitka或原生启动器研发。

后续构建任务应在独立环境及隔离源码副本中固定入口、工具版本、依赖锁、输出根和完整原始日志；PyInstaller/Nuitka配置各自隔离，不修改产品科学模块以适应构建器，不把全局PATH变更作为依赖。不得把DLL/PYD/EXE、wheel、venv、build/dist和历史审计放进源码首基线。

真实发行需分别关闭：实际包依赖闭合、系统VC/Windows前置条件、微软再分发来源及权利、Qt及实际随包第三方许可证、源码对打包数值等价、跨电脑冷启动、四模式GUI和PDF/字体/Owner视觉验收。携带Microsoft EULA或签名不等于开发者已获再分发授权；本轮没有复制微软DLL、许可证大包或创建发行包。

真实包的许可证文本及通知应按实际随包组件建立来源清单，获准后再加入对应文件。详见THIRD-PARTY-NOTICES.md、docs/MAINTENANCE.md及project-control/BASELINE-LINK.json。切换构建器、升级原生依赖和发行节点单独审计。

# 光纹科学资料索引

各实验在标量、傍轴、夫琅禾费远场条件下计算归一化相对光强。缝类观察屏沿缝方向重复同一横向截面。圆孔类按二维坐标计算模拟光强。灰度映射负责呈现图样，光强曲线和截面使用线性相对光强。

## 按实验查阅

| 实验组 | 模型与实现入口 |
|---|---|
| 单缝、双缝 | [狭缝模型与适用条件](SCIENTIFIC_MODEL.md)，主要说明单缝与有限缝宽双缝。 |
| 多缝 | [有限多缝模型记录](LF-P0-A3-MULTISLIT-R1.md) · [实现](../lightfringe/multislit.py)。 |
| 单圆孔 | [圆孔导入历史与科学契约](LF-P0-A4-FORMAL-IMPORT.md#冻结科学与采样契约) · [模型](../lightfringe/circular_model.py)。 |
| 多圆孔 | [孔列几何与复振幅模型](../lightfringe/multiaperture_model.py) · [二维和截面采样](../lightfringe/multiaperture_sampling.py)。 |

历史文档中的版本、路径和阶段信息保留其记录时点。源码启动以当前 README 为入口。

## 观察屏与 PDF 实验报告

- **缝类**的报告使用已确认且当前有效的显示快照。采样检查按横向完整孔径决定的最短周期评估实际物理像素。[单缝和双缝采样](../lightfringe/sampling.py) · [快照及报告](../lightfringe/report.py)
- **单圆孔**的显示与 PDF 分别检查采样资格。PDF 使用独立的 383×383 二维网格和 1,533 个含端点的线性截面点。[圆孔采样](../lightfringe/circular_sampling.py) · [圆孔报告](../lightfringe/circular_report.py)
- **多圆孔**的显示与 PDF 分别检查采样资格。PDF 在 383、511、767 三档正方形网格中选取满足要求的最小档，并检查 1,025 点水平截面的资格。二维网格与截面同时通过才生成正常报告。[多圆孔采样](../lightfringe/multiaperture_sampling.py) · [多圆孔报告](../lightfringe/multiaperture_report.py)

[数值参考资料说明](../references/README.md)

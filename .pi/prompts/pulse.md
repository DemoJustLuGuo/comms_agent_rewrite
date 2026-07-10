---
description: 脉冲成形 / 匹配滤波 / 眼图分析
argument-hint: "[调制/β/sps/output]"
---
调用 `pulse_shaping` 工具分析成形滤波与码间串扰(ISI)：

- RRC/RC 滤波器冲激响应与占用带宽（output=impulse）。
- 发端成形 + 收端匹配滤波后的眼图张开度与峰值 ISI（output=eye）。
- 成形信号功率谱（output=psd）。

参数：$ARGUMENTS

要求：定量结果必须调用工具，不要心算；标注单位（时间以符号周期 T、频率以符号率 Rs 归一化、幅度无量纲）。如需眼图图形，把工具输出的 `PLOT_EYE_INPUT` 交给 `plot`。

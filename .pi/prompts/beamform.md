---
description: 波束成形 / 预编码（ULA 方向图 / MRT / 多用户 ZF）
argument-hint: "[阵元数/间距/指向 或 信道向量/矩阵]"
---
根据下面的场景做波束成形/预编码分析：$ARGUMENTS

要求：
1. 必须调用 `beamforming` 工具，不要心算：
   - `mode=pattern`：均匀线阵(ULA)方向图——给 num_elements、spacing_wavelength（半波长 0.5 常用）、steer_deg，报理想阵列增益 10log10(N)、3dB 波束宽度、峰值旁瓣电平。
   - `mode=mrt`：单用户最大比发射——给 channel_i/channel_q（下行信道向量），报相对单阵元的阵列增益 dB。
   - `mode=zf`：多用户迫零预编码——给 channel_matrix（行=用户、列=阵元，元素 [re,im]，需 N≥K），报用户间残余干扰与 HHᴴ 条件数。
2. 标注单位（角度 度、增益/电平 dB、间距 波长无量纲）；间距 >0.5 波长且波束扫描时提示栅瓣风险。
3. 结论转述工具口径：阵列增益上界 = 10log10(N)（相干合并）；ZF 在信道病态（条件数大）时功率代价高，此时 MMSE/正则化 ZF 更稳。

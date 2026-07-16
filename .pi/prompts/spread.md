---
description: 扩频分析——处理增益 / 抗干扰余量 / 解扩演示（DSSS/FHSS）
argument-hint: "<码片率/比特率 或 扩频因子 或 跳频点数>"
---
根据下面的扩频场景做分析：$ARGUMENTS

要求：
1. 必须调用 `spread_spectrum` 工具，不要心算：
   - `mode=gain`：处理增益与带宽扩展——DSSS 给 chip_rate_hz+data_rate_hz 或 spread_factor；FHSS 给 hops。
   - `mode=jam`：抗干扰余量——追加 required_ebn0_db（解调所需 Eb/N0），可给 jammer_to_signal_db 输出净余量结论。
   - `mode=despread`：小规模解扩数值演示——给 data_bits（0/1）+ code（±1 序列）。
2. 标注单位（速率 Hz、增益/余量 dB）；DSSS 处理增益 Gp=10log10(Rc/Rb)=10log10(扩频因子)，FHSS Gp=10log10(跳频点数)。
3. 口径转述：处理增益把窄带干扰在解扩时摊薄（GPS/CDMA 靠此在负 SNR 工作）；FHSS 靠躲避而非压制。抗干扰余量忽略实现损耗，工程需另计。

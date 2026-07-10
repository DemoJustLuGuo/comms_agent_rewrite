---
description: OFDM / 多载波链路仿真（PAPR / BER / 频谱）
argument-hint: "[n_fft/CP/调制/信道/metric]"
---
调用 `ofdm` 工具搭建最小 OFDM 收发链并按 metric 输出：

- `papr`：峰均比及 CCDF（多载波高 PAPR 的根因）。
- `ber`：AWGN 或多径（`channel_taps_db`）下经验 BER；CP 是否足够会给出提示。
- `spectrum`：子载波间隔、占用带宽、带外抑制。

参数：$ARGUMENTS

要求：定量结果必须调用工具，不要心算；标注单位（频率以采样率 fs 归一化、PAPR/dB）。多径时注意 CP 长度需 ≥ 时延扩展，否则残留 ISI/ICI。

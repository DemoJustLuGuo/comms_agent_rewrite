---
description: 信道编码 / FEC 编码增益仿真（卷积码/Hamming/RS）
argument-hint: "<码型/调制/信道/Eb-N0 扫点>"
---
根据下面的场景做信道编码/FEC 仿真：$ARGUMENTS

要求：
1. 必须调用 `channel_coding` 工具：按需选 code（conv_k7_r12 / hamming_7_4 / rs_255_223）、modulation、channel（awgn/rayleigh）、ebn0_db 扫点；卷积码可用 decision=soft 获得更大增益。
2. 报告每个 Eb/N0 的 coded/uncoded BER 与编码增益（dB），并标注 Eb/N0 定义与码率归一化假设；不要用 ber_snr 的手填 coding_gain_db 臆测编码增益。

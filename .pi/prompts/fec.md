---
description: 信道编码 / FEC 编码增益仿真（卷积/Hamming/RS/LDPC/Turbo/Polar）
argument-hint: "<码型/调制/信道/Eb-N0 扫点>"
---
根据下面的场景做信道编码/FEC 仿真：$ARGUMENTS

要求：
1. 必须调用 `channel_coding` 工具：按需选 code——经典码 conv_k7_r12 / hamming_7_4 / rs_255_223，现代码 ldpc_wimax_r12（5G/WiFi 量级 LDPC）/ turbo_r13（3G/4G Turbo）/ polar_sc_r12（5G 控制信道 Polar，N=256/K=128，SC 译码）；再选 modulation、channel（awgn/rayleigh）、ebn0_db 扫点；卷积码可用 decision=soft 获得更大增益。
2. 现代码口径注意：turbo_r13 与 polar_sc_r12 固定 BPSK 承载（其余调制参数不生效，须转述）；ldpc_wimax_r12 用 commpy 自带 WiMAX 设计文件（1440,720 rate-1/2）；三者为纯 Python 迭代/递归译码，较慢，num_bits 上限更严——报告运行较久时可减小扫点或比特数。polar_sc_r12 依赖 polarcodes 库，若报「API 不符」按提示核对版本。
3. 报告每个 Eb/N0 的 coded/uncoded BER 与编码增益（dB），并标注 Eb/N0 定义与码率归一化假设；不要用 ber_snr 的手填 coding_gain_db 臆测编码增益。

---
description: 香农 / MIMO 容量与频谱效率速算
argument-hint: "<带宽/SNR/天线数等参数>"
---
根据下面的参数计算信息论容量与频谱效率：$ARGUMENTS

要求：
1. 必须调用 `capacity` 工具，不要心算：AWGN 香农容量用 mode=awgn（需带宽 Hz、SNR dB）；MIMO 遍历容量用 mode=mimo（需 nt、nr、SNR dB，可选 equal/waterfilling）；Eb/N0↔SNR↔频谱效率换算用 mode=ebn0（需 spectral_efficiency）。
2. 给出结果并标注单位（bit/s、bit/s/Hz、dB）与假设（信道模型、是否遍历平均），说明香农容量是高斯输入的理论上界。

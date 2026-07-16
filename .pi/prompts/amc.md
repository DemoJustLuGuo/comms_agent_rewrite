---
description: 链路自适应 / AMC——按信道质量选最优调制编码档
argument-hint: "<SNR/SINR [目标BER] [带宽]>"
---
根据下面的信道质量选最优 MCS（调制+编码）：$ARGUMENTS

要求：
1. 必须调用 `link_adaptation` 工具，不要心算：给 snr_db（并说明是 Es/N0 还是 Eb/N0，见 snr_type）、target_ber（默认 1e-3）、可选 coding_gain_db 与 bandwidth_hz。
2. 报推荐档位、各档所需 SNR 与频谱效率、相对香农上界的利用率；给了带宽则报估算吞吐（注明未计导频/CP/协议开销）。
3. 口径转述：所需 SNR 为 AWGN 理论门限，实际系统含实现损耗、衰落与开销；精确编码增益用 `channel_coding` 仿真，不要拍脑袋填 coding_gain_db。信道质量不足时给降 BER 要求 / 加强 FEC / 提升 SNR 的方向。

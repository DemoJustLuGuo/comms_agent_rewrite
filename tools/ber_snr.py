"""BER/SNR 理论性能计算（被 ber_snr 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    modulation: str       — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM
    mode: str             — snr_to_ber | ber_to_snr
    snr_db: float?        — Eb/N0 (dB)，mode=snr_to_ber 时必填
    target_ber: float?    — 目标 BER，mode=ber_to_snr 时必填
    coding_gain_db: float — 编码增益 (dB)，默认 0
输出：BER 或所需 SNR 的文本报告。
单位：SNR 为 Eb/N0 (dB)，BER 无量纲。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy.special import erfc
from scipy.optimize import brentq


# 每符号比特数
BITS_PER_SYMBOL = {
    "BPSK": 1, "QPSK": 2, "8PSK": 3,
    "16QAM": 4, "64QAM": 6, "256QAM": 8,
}


def ber_bpsk(eb_n0_linear: float) -> float:
    return 0.5 * erfc(math.sqrt(eb_n0_linear))


def ber_qpsk(eb_n0_linear: float) -> float:
    return 0.5 * erfc(math.sqrt(eb_n0_linear))


def ber_8psk(eb_n0_linear: float) -> float:
    # Gray-coded 8PSK 近似
    return (2.0 / 3.0) * erfc(math.sqrt(3.0 * eb_n0_linear / 2.0) * math.sin(math.pi / 8.0))


def ber_mqam(m: int, eb_n0_linear: float) -> float:
    """Gray-coded M-QAM BER 近似。"""
    k = math.log2(m)
    return (2.0 * (1.0 - 1.0 / math.sqrt(m)) / k) * erfc(
        math.sqrt(3.0 * k * eb_n0_linear / (2.0 * (m - 1)))
    )


BER_FUNCS = {
    "BPSK": ber_bpsk,
    "QPSK": ber_qpsk,
    "8PSK": ber_8psk,
    "16QAM": lambda x: ber_mqam(16, x),
    "64QAM": lambda x: ber_mqam(64, x),
    "256QAM": lambda x: ber_mqam(256, x),
}


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

    modulation = payload["modulation"]
    mode = payload["mode"]
    coding_gain_db = float(payload.get("coding_gain_db", 0.0))

    ber_func = BER_FUNCS.get(modulation)
    if ber_func is None:
        print(f"错误：不支持的调制方式 '{modulation}'")
        return

    if mode == "snr_to_ber":
        snr_db = float(payload["snr_db"])
        effective_snr_db = snr_db + coding_gain_db
        eb_n0_linear = 10.0 ** (effective_snr_db / 10.0)
        ber = float(ber_func(eb_n0_linear))

        print(f"=== BER 计算结果 ===")
        print(f"调制方式     : {modulation}")
        print(f"Eb/N0 输入   : {snr_db:.2f} dB")
        print(f"编码增益     : {coding_gain_db:.2f} dB")
        print(f"有效 Eb/N0   : {effective_snr_db:.2f} dB")
        print(f"理论 BER     : {ber:.6e}")
        if ber < 1e-15:
            print(f"评估         : BER 极低，链路裕量充足")
        elif ber < 1e-6:
            print(f"评估         : BER 可接受（典型 FEC 可纠正）")
        elif ber < 1e-3:
            print(f"评估         : BER 偏高，建议增加 SNR 或降低调制阶数")
        else:
            print(f"评估         : BER 过高，通信质量不可接受")

    elif mode == "ber_to_snr":
        target_ber = float(payload["target_ber"])
        if target_ber <= 0 or target_ber >= 0.5:
            print("错误：target_ber 需在 (0, 0.5) 范围内。")
            return

        def objective(snr_db_val: float) -> float:
            eb_n0_lin = 10.0 ** (snr_db_val / 10.0)
            return ber_func(eb_n0_lin) - target_ber

        try:
            required_snr_db = brentq(objective, -10.0, 80.0, xtol=1e-4)
        except ValueError:
            print("错误：在 -10~80 dB 范围内无法找到满足目标 BER 的 SNR。")
            return

        actual_snr_needed = required_snr_db - coding_gain_db

        print(f"=== 所需 SNR 计算结果 ===")
        print(f"调制方式     : {modulation}")
        print(f"目标 BER     : {target_ber:.2e}")
        print(f"理论所需 Eb/N0 : {required_snr_db:.2f} dB")
        print(f"编码增益     : {coding_gain_db:.2f} dB")
        print(f"实际所需 Eb/N0 : {actual_snr_needed:.2f} dB")
    else:
        print(f"错误：不支持的 mode '{mode}'，可选 snr_to_ber / ber_to_snr")


if __name__ == "__main__":
    main()

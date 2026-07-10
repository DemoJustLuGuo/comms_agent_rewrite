"""无线信道端到端仿真（被 channel 工具调用）。

打通 调制 → 信道 → 解调 → BER 闭环：对随机比特做调制，过 AWGN / Rayleigh / Rician
信道（含 AWGN），完美 CSI 均衡后解调，统计经验 BER，并与 AWGN 理论 BER 对比。

复用同目录 modulation.py（星座/映射）与 ber_snr.py（理论 BER）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    modulation: str   — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM
    snr_db: float     — Eb/N0，dB
    fading: str       — awgn | rayleigh | rician，默认 awgn
    rician_k_db: float— Rician K 因子，dB，默认 6（fading=rician 时用）
    num_bits: int     — 仿真比特数，默认 100000（上限 5,000,000）
    seed: int?        — 随机种子（可复现）
输出：经验 BER / 理论 AWGN BER / 误比特数 文本报告。单位：SNR 为 Eb/N0 (dB)，BER 无量纲。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

# 复用同目录的调制与理论 BER 实现，保证与其它工具一致
sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import BITS_PER_SYMBOL, modulate_bits, demodulate_symbols  # noqa: E402
from ber_snr import BER_FUNCS  # noqa: E402

MAX_BITS = 5_000_000


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def make_fading(fading: str, n: int, rng, rician_k_db: float):
    """返回长度 n 的复信道系数，E[|h|^2]=1。"""
    if fading == "awgn":
        return np.ones(n, dtype=complex)
    scatter = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / math.sqrt(2.0)
    if fading == "rayleigh":
        return scatter
    if fading == "rician":
        k_lin = 10.0 ** (rician_k_db / 10.0)
        los = math.sqrt(k_lin / (k_lin + 1.0))
        sca = math.sqrt(1.0 / (k_lin + 1.0))
        return los + sca * scatter
    raise ValueError(f"不支持的 fading '{fading}'，可选 awgn/rayleigh/rician。")


def main() -> None:
    payload = load_payload()
    modulation = payload.get("modulation", "")
    if modulation not in BITS_PER_SYMBOL:
        print(f"错误：不支持的调制方式 '{modulation}'。")
        return
    if "snr_db" not in payload:
        print("错误：缺少 snr_db（Eb/N0，dB）。")
        return

    snr_db = float(payload["snr_db"])
    fading = payload.get("fading", "awgn")
    rician_k_db = float(payload.get("rician_k_db", 6.0))
    num_bits = int(payload.get("num_bits", 100_000))
    if num_bits > MAX_BITS:
        num_bits = MAX_BITS
    seed = payload.get("seed")
    rng = np.random.default_rng(seed if seed is None else int(seed))

    k = BITS_PER_SYMBOL[modulation]
    num_bits = (num_bits // k) * k
    if num_bits <= 0:
        print("错误：num_bits 太小，不足一个符号。")
        return

    bits = rng.integers(0, 2, num_bits)
    symbols, n_sym, _ = modulate_bits(bits, modulation)  # 平均符号能量 Es=1

    # 噪声：Eb/N0 -> Es/N0 -> N0（Es=1）；复噪声每维方差 N0/2
    eb_n0_lin = 10.0 ** (snr_db / 10.0)
    es_n0_lin = eb_n0_lin * k
    n0 = 1.0 / es_n0_lin
    noise = math.sqrt(n0 / 2.0) * (rng.standard_normal(n_sym) + 1j * rng.standard_normal(n_sym))

    try:
        h = make_fading(fading, n_sym, rng, rician_k_db)
    except ValueError as e:
        print(f"错误：{e}")
        return

    rx = h * symbols + noise
    equalized = rx / h  # 完美 CSI 均衡
    bits_rx = demodulate_symbols(equalized, modulation)

    bit_errors = int(np.sum(bits[: bits_rx.size] != bits_rx))
    total_bits = bits_rx.size
    emp_ber = bit_errors / total_bits

    theo_awgn = float(BER_FUNCS[modulation](eb_n0_lin))

    print(f"=== {modulation} 端到端信道仿真 ===")
    print(f"信道         : {fading}" + (f"（K={rician_k_db:.1f} dB）" if fading == "rician" else ""))
    print(f"Eb/N0        : {snr_db:.2f} dB")
    print(f"仿真比特     : {total_bits}（{n_sym} 符号）")
    print(f"误比特数     : {bit_errors}")
    print(f"经验 BER     : {emp_ber:.3e}")
    print(f"理论 BER(AWGN): {theo_awgn:.3e}")
    if fading != "awgn":
        print(f"说明         : 衰落信道 BER 高于 AWGN 属预期；提高 Eb/N0 或加分集可改善。")
    if bit_errors == 0:
        print(f"提示         : 0 误码，经验 BER 上界约 {1.0 / total_bits:.1e}，增大 num_bits 可测更低 BER。")


if __name__ == "__main__":
    main()

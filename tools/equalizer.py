"""信道均衡演示（被 equalizer 工具调用）：ZF / MMSE / DFE 线性均衡。

给定频选信道抽头，仿真「均衡前 vs 均衡后」的残余 ISI 与 EVM，补 channel_profile
判"频率选择性→需均衡"却无演示算子的闭环断点（见 knowledge/工程评估速查.md）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    equalizer: str        — zf | mmse | dfe，默认 mmse
    channel_taps: list[float] | list[[re,im]] — 信道冲激响应抽头（实或复；第一抽头为主径）
    modulation: str?      — 承载调制，默认 QPSK（BPSK/QPSK/8PSK/16QAM/...）
    snr_db: float?        — Es/N0，dB，默认 20（mmse 用其构造正则；zf 忽略噪声）
    num_symbols: int?     — 仿真符号数，默认 2000（上限 50000）
    num_taps: int?        — 均衡器抽头数（FIR 长度），默认 21（奇数，中心对称）
    seed: int?            — 随机种子（复现）

输出：均衡前后 EVM/残余 ISI、均衡器类型、信道条件数（频响谷深）文本报告。
口径：
    ZF：迫零，用信道逆，深谷处放大噪声（噪声增强）。
    MMSE：最小均方误差，在 ISI 抑制与噪声增强间折中（含 1/SNR 正则）。
    DFE：判决反馈，前馈抑制前导 ISI + 反馈消除后拖尾（假设判决正确，演示无误差传播）。
单位：EVM 百分比、抽头无量纲、SNR/dB、残余 ISI（dB，相对主径）。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import build_constellation, BITS_PER_SYMBOL  # noqa: E402


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def parse_taps(raw) -> np.ndarray:
    arr = np.asarray(raw, dtype=float)
    if arr.ndim == 2 and arr.shape[1] == 2:  # [[re,im],...]
        return arr[:, 0] + 1j * arr[:, 1]
    return arr.astype(complex)


def random_symbols(modulation: str, n: int, rng) -> np.ndarray:
    constel, _ = build_constellation(modulation)
    idx = rng.integers(0, constel.size, n)
    return constel[idx]


def nearest_symbol(sym, constel):
    dist = np.abs(sym[:, None] - constel[None, :])
    return constel[np.argmin(dist, axis=1)]


def evm_pct(meas, constel):
    ref = nearest_symbol(meas, constel)
    err = meas - ref
    return math.sqrt(float(np.mean(np.abs(err) ** 2)) / float(np.mean(np.abs(constel) ** 2))) * 100.0


def design_linear_eq(h, num_taps, kind, snr_lin):
    """最小二乘设计 FIR 均衡器 w，使级联 h*w ≈ δ（延迟中心）。

    构造卷积矩阵 H（(N+L-1)×N），目标 d 为单位脉冲（延迟 = 中心）。
    ZF：解 H w = d 的最小二乘；MMSE：加 1/snr 正则（Tikhonov）。
    """
    L = h.size
    N = num_taps
    rows = N + L - 1
    H = np.zeros((rows, N), dtype=complex)
    for k in range(N):
        H[k:k + L, k] = h
    delay = (rows - 1) // 2
    d = np.zeros(rows, dtype=complex)
    d[delay] = 1.0
    HH = H.conj().T @ H
    if kind == "mmse":
        HH = HH + (1.0 / snr_lin) * np.eye(N)
    w = np.linalg.solve(HH, H.conj().T @ d)
    return w, delay


def main() -> None:
    payload = load_payload()
    kind = payload.get("equalizer", "mmse")
    if kind not in ("zf", "mmse", "dfe"):
        print("错误：equalizer 只能是 zf | mmse | dfe。")
        return
    taps_raw = payload.get("channel_taps")
    if not taps_raw:
        print("错误：需要 channel_taps（信道冲激响应抽头，实数或 [re,im] 复数列表）。")
        return
    h = parse_taps(taps_raw)
    if h.size < 2:
        print("错误：channel_taps 至少 2 个抽头才构成频选信道（单抽头无 ISI）。")
        return

    modulation = payload.get("modulation", "QPSK").upper()
    if modulation not in BITS_PER_SYMBOL:
        print(f"错误：不支持的调制方式 '{modulation}'。")
        return
    constel, _ = build_constellation(modulation)
    snr_db = float(payload.get("snr_db", 20.0))
    snr_lin = 10.0 ** (snr_db / 10.0)
    num_symbols = min(int(payload.get("num_symbols", 2000)), 50_000)
    num_taps = int(payload.get("num_taps", 21))
    if num_taps < 3 or num_taps % 2 == 0:
        print("错误：num_taps 需为 ≥3 的奇数（中心对称 FIR）。")
        return
    seed = payload.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))

    # 信道频响谷深（条件数感知：频选严重程度）
    H_f = np.fft.fft(h, 512)
    mag = np.abs(H_f)
    valley_db = 20.0 * math.log10(float(np.min(mag)) / float(np.max(mag))) if np.min(mag) > 0 else float("-inf")

    tx = random_symbols(modulation, num_symbols, rng)
    # 过信道（线性卷积）+ 加噪（Es=1，Es/N0=snr）
    rx_clean = np.convolve(tx, h)
    n0 = 1.0 / snr_lin
    noise = math.sqrt(n0 / 2.0) * (rng.standard_normal(rx_clean.size) + 1j * rng.standard_normal(rx_clean.size))
    rx = rx_clean + noise

    # 均衡前 EVM：主径归一化后与理想点比（截取有效段）
    main_tap = h[np.argmax(np.abs(h))]
    pre = rx[:num_symbols] / main_tap
    evm_pre = evm_pct(pre, constel)

    print(f"=== 信道均衡演示：{kind.upper()} / {modulation} / Es-N0={snr_db:.1f} dB ===")
    print(f"信道抽头     : {['%.3f' % v if abs(v.imag) < 1e-9 else '%.3f%+.3fj' % (v.real, v.imag) for v in h]}")
    print(f"频响谷深     : {valley_db:.2f} dB（相对峰值；越深频选越严重、ZF 噪声增强越大）")
    print(f"仿真符号数   : {num_symbols}")

    if kind in ("zf", "mmse"):
        w, delay = design_linear_eq(h, num_taps, kind, snr_lin)
        eq = np.convolve(rx, w)
        # 对齐：级联延迟 = 均衡器中心 + 信道主径位置附近，取 delay 段
        est = eq[delay:delay + num_symbols]
        evm_post = evm_pct(est, constel)
        # 残余 ISI：级联响应 h*w 除主抽头外的能量占比
        casc = np.convolve(h, w)
        peak = int(np.argmax(np.abs(casc)))
        isi_energy = float(np.sum(np.abs(casc) ** 2) - np.abs(casc[peak]) ** 2)
        isi_db = 10.0 * math.log10(isi_energy / (np.abs(casc[peak]) ** 2)) if isi_energy > 0 else float("-inf")
        print(f"均衡器       : {kind.upper()} 线性 FIR，{num_taps} 抽头"
              + ("（迫零，忽略噪声）" if kind == "zf" else "（含 1/SNR 正则，折中噪声增强）"))
        print(f"残余 ISI     : {isi_db:.2f} dB（相对主径；越低越干净）")
        print(f"EVM 均衡前   : {evm_pre:.2f} %")
        print(f"EVM 均衡后   : {evm_post:.2f} %")
        improve = evm_pre - evm_post
        print(f"EVM 改善     : {improve:+.2f} 个百分点"
              + ("（ZF 在深谷信道可能因噪声增强而改善有限，此时选 MMSE）" if kind == "zf" else ""))
    else:  # dfe
        # 判决反馈：前馈用 MMSE 短滤波抑制前导 ISI，反馈抵消已判决符号引入的后拖尾。
        # 演示口径：假设反馈判决正确（无误差传播），展示 DFE 相对线性均衡的上界。
        ff_taps = num_taps
        w_ff, delay = design_linear_eq(h, ff_taps, "mmse", snr_lin)
        casc = np.convolve(h, w_ff)
        peak = int(np.argmax(np.abs(casc)))
        # 后拖尾抽头（峰值之后）作为反馈系数
        fb = casc[peak + 1:]
        ff_out = np.convolve(rx, w_ff)
        est = np.empty(num_symbols, dtype=complex)
        # 逐符号判决反馈（理想判决）
        decided = np.empty(num_symbols, dtype=complex)
        for n in range(num_symbols):
            y = ff_out[delay + n]
            # 减去已判决符号经后拖尾的贡献
            for j, c in enumerate(fb):
                if n - 1 - j >= 0:
                    y = y - c * decided[n - 1 - j]
            est[n] = y
            decided[n] = nearest_symbol(np.array([y]), constel)[0]
        evm_post = evm_pct(est, constel)
        print(f"均衡器       : DFE（前馈 MMSE {ff_taps} 抽头 + {fb.size} 抽头判决反馈，理想判决演示）")
        print(f"反馈抽头数   : {fb.size}（抵消主径后的拖尾 ISI）")
        print(f"EVM 均衡前   : {evm_pre:.2f} %")
        print(f"EVM 均衡后   : {evm_post:.2f} %")
        print(f"EVM 改善     : {evm_pre - evm_post:+.2f} 个百分点")
        print("注：本演示假设反馈判决正确（无误差传播上界）；实际 DFE 在低 SNR 会因错误判决恶化。")

    print("解读：频选信道（谷深大）需均衡或改用 OFDM；线性 ZF 深谷噪声增强严重，"
          "MMSE 折中更稳，DFE 对后拖尾主导的信道最优但有误差传播风险。")


if __name__ == "__main__":
    main()

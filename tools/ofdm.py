"""OFDM / 多载波链路（被 ofdm 工具调用）。

搭最小 OFDM 收发链，解释子载波 / 循环前缀(CP) / PAPR，并在频选（多径）信道下仿真性能。
复用同目录 modulation.py 的星座与比特映射。纯 NumPy 实现。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    n_fft: int?          — FFT 点数（子载波总数），默认 64
    n_used: int?         — 使用的数据子载波数（≤ n_fft），默认 52
    cp_len: int?         — 循环前缀长度（样点），默认 16
    modulation: str      — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM，默认 QPSK
    channel: str?        — awgn | multipath，默认 awgn
    channel_taps_db: number[]? — multipath 各径功率(dB，第 1 径为 0)，默认 [0,-3,-6]
    snr_db: float?       — Eb/N0，dB，默认 20
    metric: str?         — papr | ber | spectrum，默认 papr
    n_symbols: int?      — OFDM 符号数（ber/papr 统计用），默认 200
    seed: int?           — 随机种子（复现）
输出：按 metric 给 PAPR CCDF / 经验 BER / 频谱占用 文本报告。
单位：PAPR 为 dB；BER 无量纲；SNR 为 Eb/N0 (dB)；子载波以归一化频点计。
假设：功率归一化使每 OFDM 符号平均样点功率≈1；multipath 用已知信道做频域单抽头(ZF)均衡；
      CP 长度须 ≥ 信道时延扩展(taps-1)，否则残留 ICI/ISI（工具会提示）。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import BITS_PER_SYMBOL, modulate_bits, demodulate_symbols  # noqa: E402

MAX_FFT = 4096
MAX_SYMBOLS = 5000


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def used_indices(n_fft: int, n_used: int) -> np.ndarray:
    """选取以 DC 为中心、跳过 DC(第 0 号) 的连续数据子载波索引（FFT 顺序）。"""
    # 数据放在 DC 两侧：正频 1..half，负频 n_fft-half..n_fft-1
    half = n_used // 2
    pos = np.arange(1, half + 1)
    neg = np.arange(n_fft - (n_used - half), n_fft)
    return np.concatenate([pos, neg])


def make_multipath(taps_db, rng):
    """由各径功率(dB)生成复基带信道抽头，功率归一化(∑|h|²=1)。第 1 径含 LOS 相位 0。"""
    p_lin = 10.0 ** (np.asarray(taps_db, dtype=float) / 10.0)
    p_lin = p_lin / p_lin.sum()
    # 每径瑞利幅度 + 随机相位；第 1 径设为实数正值当作参考
    h = np.sqrt(p_lin / 2.0) * (rng.standard_normal(p_lin.size) + 1j * rng.standard_normal(p_lin.size))
    h = h / math.sqrt(np.sum(np.abs(h) ** 2))  # 再次归一，E 随机波动
    return h


def build_ofdm_symbols(n_symbols, n_fft, idx, modulation, rng):
    """生成 n_symbols 个 OFDM 时域符号（未加 CP），返回 (时域矩阵, 发送数据符号, 发送比特)。"""
    k = BITS_PER_SYMBOL[modulation]
    n_data = idx.size
    bits = rng.integers(0, 2, n_symbols * n_data * k)
    data_syms, n_sym_made, _ = modulate_bits(bits, modulation)
    n_sym_made = (n_sym_made // n_data) * n_data
    data_syms = data_syms[:n_sym_made]
    n_symbols = n_sym_made // n_data
    grid = np.zeros((n_symbols, n_fft), dtype=complex)
    grid[:, idx] = data_syms.reshape(n_symbols, n_data)
    # IFFT（正交子载波调制）；乘 sqrt(n_fft) 使时域每样点平均功率与频域一致
    time = np.fft.ifft(grid, axis=1) * math.sqrt(n_fft)
    return time, data_syms.reshape(n_symbols, n_data), bits[: n_symbols * n_data * k]


def metric_papr(time_syms, n_fft, cp_len):
    """PAPR CCDF：逐 OFDM 符号峰均功率比(dB)，报几个 CCDF 分位。"""
    # 加 CP 后再算（真实发射波形包含 CP）
    withcp = np.hstack([time_syms[:, n_fft - cp_len:], time_syms]) if cp_len > 0 else time_syms
    p = np.abs(withcp) ** 2
    peak = p.max(axis=1)
    avg = p.mean(axis=1)
    papr_db = 10.0 * np.log10(peak / avg)
    return papr_db


def metric_ber(time_syms, tx_syms, tx_bits, n_fft, cp_len, idx, modulation,
               channel, taps_db, snr_db, rng):
    """加 CP → 过信道(+噪声) → 去 CP → FFT → (multipath) 单抽头均衡 → 解调 → 经验 BER。"""
    n_symbols = time_syms.shape[0]
    k = BITS_PER_SYMBOL[modulation]
    # 加 CP
    if cp_len > 0:
        tx = np.hstack([time_syms[:, n_fft - cp_len:], time_syms])
    else:
        tx = time_syms
    sym_len = n_fft + cp_len
    stream = tx.reshape(-1)

    # 信道
    if channel == "multipath":
        h = make_multipath(taps_db, rng)
        rx_stream = np.convolve(stream, h, mode="full")[: stream.size]
        H = np.fft.fft(h, n_fft)  # 频域信道
    else:
        h = np.array([1.0 + 0j])
        rx_stream = stream.copy()
        H = np.ones(n_fft, dtype=complex)

    # 噪声：Eb/N0 -> N0。时域每样点平均功率≈1（含 CP 略变，近似）
    eb_n0_lin = 10.0 ** (snr_db / 10.0)
    es_n0_lin = eb_n0_lin * k
    # 每数据子载波 Es≈1；时域功率经 IFFT·sqrt(N) 后每样点≈(n_used/n_fft)。
    # 简化：按每样点噪声 N0，使子载波解调后 Es/N0 一致。
    n0 = 1.0 / es_n0_lin
    noise = math.sqrt(n0 / 2.0) * (rng.standard_normal(rx_stream.size) + 1j * rng.standard_normal(rx_stream.size))
    rx_stream = rx_stream + noise

    rx = rx_stream[: n_symbols * sym_len].reshape(n_symbols, sym_len)
    # 去 CP
    rx_nocp = rx[:, cp_len:] if cp_len > 0 else rx
    # FFT 解调
    freq = np.fft.fft(rx_nocp, axis=1) / math.sqrt(n_fft)
    # 单抽头频域均衡（multipath 用已知 H；awgn 时 H=1）
    freq_eq = freq / H[None, :]
    rx_data = freq_eq[:, idx].reshape(-1)
    bits_rx = demodulate_symbols(rx_data, modulation)
    n = min(bits_rx.size, tx_bits.size)
    bit_errors = int(np.sum(bits_rx[:n] != tx_bits[:n]))
    return bit_errors, n, h


def main() -> None:
    payload = load_payload()
    n_fft = int(payload.get("n_fft", 64))
    if n_fft < 4 or n_fft > MAX_FFT or (n_fft & (n_fft - 1)) != 0:
        print(f"错误：n_fft 必须是 4~{MAX_FFT} 之间的 2 的幂。")
        return
    n_used = int(payload.get("n_used", min(52, n_fft - 1)))
    if n_used < 1 or n_used >= n_fft:
        print(f"错误：n_used 必须在 1~{n_fft - 1} 之间（需留 DC/保护）。")
        return
    cp_len = int(payload.get("cp_len", 16))
    if cp_len < 0 or cp_len >= n_fft:
        print(f"错误：cp_len 必须在 0~{n_fft - 1} 之间。")
        return
    modulation = payload.get("modulation", "QPSK")
    if modulation not in BITS_PER_SYMBOL:
        print(f"错误：不支持的调制方式 '{modulation}'。")
        return
    channel = payload.get("channel", "awgn")
    if channel not in ("awgn", "multipath"):
        print("错误：channel 只能是 awgn 或 multipath。")
        return
    taps_db = payload.get("channel_taps_db", [0.0, -3.0, -6.0])
    if channel == "multipath":
        if not isinstance(taps_db, list) or not taps_db:
            print("错误：multipath 需要非空 channel_taps_db（各径功率 dB）。")
            return
        try:
            taps_db = [float(x) for x in taps_db]
        except (TypeError, ValueError):
            print("错误：channel_taps_db 元素必须是数字。")
            return
    snr_db = float(payload.get("snr_db", 20.0))
    metric = payload.get("metric", "papr")
    if metric not in ("papr", "ber", "spectrum"):
        print("错误：metric 只能是 papr | ber | spectrum。")
        return
    n_symbols = min(int(payload.get("n_symbols", 200)), MAX_SYMBOLS)
    if n_symbols < 1:
        print("错误：n_symbols 至少为 1。")
        return
    seed = payload.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))

    idx = used_indices(n_fft, n_used)
    sc_spacing = 1.0 / n_fft  # 归一化子载波间隔（相对采样率）
    cp_frac = cp_len / (n_fft + cp_len)

    time_syms, tx_syms, tx_bits = build_ofdm_symbols(n_symbols, n_fft, idx, modulation, rng)
    n_symbols = time_syms.shape[0]

    header = (f"=== OFDM 链路（n_fft={n_fft}, 数据子载波={n_used}, CP={cp_len}, "
              f"{modulation}, {channel}）===")

    if metric == "papr":
        papr_db = metric_papr(time_syms, n_fft, cp_len)
        # CCDF：P(PAPR > x)
        levels = [4.0, 6.0, 8.0, 10.0]
        print(header)
        print(f"OFDM 符号数  : {n_symbols}")
        print(f"CP 开销      : {cp_frac * 100:.1f}%（CP/(FFT+CP)）")
        print(f"PAPR 均值    : {papr_db.mean():.2f} dB")
        print(f"PAPR 最大    : {papr_db.max():.2f} dB")
        print("PAPR CCDF（P(PAPR>门限)）:")
        for x in levels:
            ccdf = float(np.mean(papr_db > x))
            print(f"  > {x:>4.1f} dB : {ccdf:.4f}")
        print("说明          : 多载波叠加致高 PAPR，是 OFDM 需要功放回退/削峰的根因；"
              "子载波越多尾部越接近理论 CCDF。")
        return

    if metric == "spectrum":
        # 单个 OFDM 符号（含 CP）的功率谱占用
        withcp = np.hstack([time_syms[:, n_fft - cp_len:], time_syms]) if cp_len > 0 else time_syms
        sig = withcp.reshape(-1)
        n_win = 1024
        segs = sig.size // n_win
        if segs < 1:
            spec = np.abs(np.fft.fftshift(np.fft.fft(sig))) ** 2
        else:
            acc = np.zeros(n_win)
            for i in range(segs):
                s = sig[i * n_win:(i + 1) * n_win]
                acc += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
            spec = acc / segs
        spec_db = 10.0 * np.log10(spec / spec.max() + 1e-15)
        occupied = n_used / n_fft
        print(header)
        print(f"OFDM 符号数  : {n_symbols}")
        print(f"子载波间隔   : {sc_spacing:.4g}·fs（fs=采样率；间隔=fs/n_fft）")
        print(f"占用带宽     : {occupied:.4f}·fs（数据子载波数/n_fft）")
        print(f"谱峰         : {spec_db.max():.2f} dB（相对，位于占用带内）")
        # 带外一点（0.5·fs 处，Nyquist 边缘）
        edge = spec_db[-1]
        print(f"带边(±0.5fs) : {edge:.2f} dB（带外抑制指示）")
        print("说明          : 频率以采样率 fs 归一化；OFDM 占用带宽≈数据子载波占比。")
        return

    # metric == "ber"
    bit_errors, n_bits, h = metric_ber(time_syms, tx_syms, tx_bits, n_fft, cp_len, idx,
                                       modulation, channel, taps_db, snr_db, rng)
    emp_ber = bit_errors / n_bits if n_bits else float("nan")
    print(header)
    print(f"OFDM 符号数  : {n_symbols}")
    print(f"Eb/N0        : {snr_db:.2f} dB")
    print(f"CP 开销      : {cp_frac * 100:.1f}%")
    if channel == "multipath":
        delay_spread = len(taps_db) - 1
        print(f"信道径数     : {len(taps_db)}（时延扩展 {delay_spread} 样点，功率 {taps_db} dB）")
        if cp_len < delay_spread:
            print(f"⚠ CP 不足    : CP={cp_len} < 时延扩展 {delay_spread}，将残留 ISI/ICI（BER 偏高）。")
        else:
            print(f"CP 充足      : CP={cp_len} ≥ 时延扩展 {delay_spread}，频域单抽头均衡有效。")
    print(f"仿真比特     : {n_bits}")
    print(f"误比特数     : {bit_errors}")
    print(f"经验 BER     : {emp_ber:.3e}")
    if bit_errors == 0:
        print(f"提示         : 0 误码，经验 BER 上界约 {1.0 / n_bits:.1e}，增大 n_symbols 可测更低 BER。")


if __name__ == "__main__":
    main()

"""脉冲成形 / 匹配滤波 / 眼图（被 pulse_shaping 工具调用）。

补全「发端成形 → 收端匹配滤波」链路，解释码间串扰(ISI)与眼图。复用同目录 modulation.py
的星座与比特映射。纯 NumPy 实现根升余弦(RRC)/升余弦(RC)滤波器，处理 β=0 与 t=0、
t=±T/(4β) 两处奇点。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    modulation: str    — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM
    filter: str?       — rrc | rc，默认 rrc（根升余弦，发/收各一半，级联即 RC）
    beta: float?       — 滚降系数 0≤β≤1，默认 0.35（无量纲）
    sps: int?          — 每符号采样数(samples per symbol)，默认 8
    span_symbols: int? — 滤波器长度（符号数），默认 10（抽头数 = span_symbols·sps+1）
    num_symbols: int?  — 随机符号数，默认 500
    output: str?       — eye | impulse | psd，默认 eye
    seed: int?         — 随机种子（复现）
输出：
    impulse — 滤波器抽头（无量纲）、理论带宽 (1+β)/(2T)（以符号率归一化）；
    eye     — 匹配滤波后波形与眼图指标（眼张开度、峰值 ISI），并附可直接交 plot 工具画眼图的字段；
    psd     — 成形后信号功率谱（dB，相对峰值）。
单位：滤波器抽头与 I/Q 幅度为无量纲（能量归一化星座）；时间以符号周期 T 为单位；
      频率以符号率 Rs=1/T 归一化；PSD 为相对 dB。RRC 峰值归一化为 1（∑h² 归一）。
约定：RRC 发端 + RRC 收端 = RC，故用 rrc 时匹配滤波后在符号采样点满足奈奎斯特无 ISI。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import BITS_PER_SYMBOL, build_constellation, modulate_bits  # noqa: E402

MAX_SYMBOLS = 20_000
MAX_TAPS = 8193


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def rrc_taps(beta: float, sps: int, span: int) -> np.ndarray:
    """根升余弦(RRC)冲激响应，抽头数 = span·sps+1，峰值处理 t=0 与 t=±T/(4β) 奇点。

    公式（T=符号周期，t 以采样为单位、步长 1/sps 个 T）：
      h(0)           = 1 + β(4/π − 1)
      h(±T/(4β))     = (β/√2)[(1+2/π)sin(π/4β) + (1−2/π)cos(π/4β)]
      其余           = [sin(πt/T(1−β)) + 4βt/T·cos(πt/T(1+β))] / (πt/T·(1−(4βt/T)²))
    归一化：∑h² = 1（能量归一），再按峰值缩放使 h(0)=1 便于读眼图。
    """
    n = span * sps + 1
    t = (np.arange(n) - (n - 1) / 2.0) / sps  # 以 T 为单位的时间轴
    h = np.zeros(n, dtype=float)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1.0 + beta * (4.0 / math.pi - 1.0)
        elif beta > 0 and abs(abs(ti) - 1.0 / (4.0 * beta)) < 1e-9:
            h[i] = (beta / math.sqrt(2.0)) * (
                (1.0 + 2.0 / math.pi) * math.sin(math.pi / (4.0 * beta))
                + (1.0 - 2.0 / math.pi) * math.cos(math.pi / (4.0 * beta))
            )
        else:
            pt = math.pi * ti
            denom = pt * (1.0 - (4.0 * beta * ti) ** 2)
            h[i] = (
                math.sin(pt * (1.0 - beta)) + 4.0 * beta * ti * math.cos(pt * (1.0 + beta))
            ) / denom
    h /= math.sqrt(np.sum(h ** 2))  # 能量归一
    return h


def rc_taps(beta: float, sps: int, span: int) -> np.ndarray:
    """升余弦(RC)冲激响应，t=0 与 t=±T/(2β) 处理奇点，峰值归一为 1。"""
    n = span * sps + 1
    t = (np.arange(n) - (n - 1) / 2.0) / sps
    h = np.zeros(n, dtype=float)
    for i, ti in enumerate(t):
        if beta > 0 and abs(abs(ti) - 1.0 / (2.0 * beta)) < 1e-9:
            h[i] = (math.pi / 4.0) * np.sinc(1.0 / (2.0 * beta))
        else:
            h[i] = np.sinc(ti) * math.cos(math.pi * beta * ti) / (1.0 - (2.0 * beta * ti) ** 2)
    # RC 理论峰值 h(0)=1，已满足；不再额外缩放
    return h


def main() -> None:
    payload = load_payload()
    modulation = payload.get("modulation", "")
    if modulation not in BITS_PER_SYMBOL:
        print(f"错误：不支持的调制方式 '{modulation}'。可选：{'/'.join(BITS_PER_SYMBOL)}。")
        return

    filt = payload.get("filter", "rrc")
    if filt not in ("rrc", "rc"):
        print("错误：filter 只能是 rrc 或 rc。")
        return

    beta = float(payload.get("beta", 0.35))
    if not (0.0 <= beta <= 1.0):
        print("错误：beta（滚降系数）必须在 0~1 之间。")
        return

    sps = int(payload.get("sps", 8))
    if sps < 2:
        print("错误：sps（每符号采样数）至少为 2。")
        return

    span = int(payload.get("span_symbols", 10))
    if span < 1:
        print("错误：span_symbols 至少为 1。")
        return
    if span * sps + 1 > MAX_TAPS:
        print(f"错误：滤波器抽头数 {span*sps+1} 过大（上限 {MAX_TAPS}）。请减小 sps 或 span_symbols。")
        return

    output = payload.get("output", "eye")
    if output not in ("eye", "impulse", "psd"):
        print("错误：output 只能是 eye | impulse | psd。")
        return

    taps = rrc_taps(beta, sps, span) if filt == "rrc" else rc_taps(beta, sps, span)
    bw_norm = (1.0 + beta) / 2.0  # 单边带宽，以符号率 Rs=1/T 归一化（(1+β)/(2T)）

    if output == "impulse":
        print(f"=== 脉冲成形滤波器：{filt.upper()}（β={beta}）===")
        print(f"每符号采样   : {sps}（sps）")
        print(f"滤波器跨度   : {span} 符号，抽头数 {taps.size}")
        print(f"滚降系数 β   : {beta:.3f}（无量纲）")
        print(f"占用带宽     : {bw_norm:.4f}·Rs（单边 (1+β)/2·符号率；Rs=1/T）")
        print(f"能量 ∑h²     : {np.sum(taps**2):.4f}（RRC 归一为 1）")
        print(f"峰值抽头     : {taps.max():.4f}（无量纲）")
        step = max(1, taps.size // 40)
        shown = taps[::step]
        print(f"抽头样点(每{step}点取1) : {' '.join(f'{v:+.4f}' for v in shown)}")
        return

    # 生成随机符号并成形
    num_symbols = min(int(payload.get("num_symbols", 500)), MAX_SYMBOLS)
    if num_symbols < 8:
        print("错误：num_symbols 太小（至少 8）。")
        return
    seed = payload.get("seed")
    rng = np.random.default_rng(None if seed is None else int(seed))
    k = BITS_PER_SYMBOL[modulation]
    bits = rng.integers(0, 2, num_symbols * k)
    symbols, n_sym, _ = modulate_bits(bits, modulation)

    # 上采样（每符号插 sps-1 个零）→ 发端成形
    up = np.zeros(n_sym * sps, dtype=complex)
    up[::sps] = symbols
    tx = np.convolve(up, taps, mode="full")

    if output == "psd":
        # 成形后信号 PSD（相对峰值 dB）。不要去均值：基带成形信号谱峰在 DC。
        # 用 Welch 分段平均降低单次随机实现的谱估计方差（否则谱峰会随机落到非 DC bin，
        # 误报 f=0 不是最大）。分段加汉宁窗、50% 重叠。
        sig = tx
        n_fft = 1024
        while n_fft > sig.size:
            n_fft >>= 1
        n_fft = max(n_fft, 64)
        win = np.hanning(n_fft)
        step = n_fft // 2
        acc = np.zeros(n_fft, dtype=float)
        n_seg = 0
        for s in range(0, sig.size - n_fft + 1, step):
            seg_w = sig[s:s + n_fft] * win
            acc += np.abs(np.fft.fftshift(np.fft.fft(seg_w))) ** 2
            n_seg += 1
        if n_seg == 0:  # 信号短于一段：退化为单段
            seg_w = np.zeros(n_fft, dtype=complex)
            seg_w[:sig.size] = sig[:n_fft] * win[:sig.size]
            acc = np.abs(np.fft.fftshift(np.fft.fft(seg_w))) ** 2
            n_seg = 1
        psd = acc / n_seg
        psd_db = 10.0 * np.log10(psd / psd.max() + 1e-15)
        freq = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / sps))  # 以 Rs 归一化
        # 只报几个关键点：DC、±带宽边缘、±Rs/2
        def at(f):
            idx = int(np.argmin(np.abs(freq - f)))
            return psd_db[idx]
        print(f"=== 成形信号功率谱：{filt.upper()}（β={beta}，{modulation}）===")
        print(f"每符号采样   : {sps}（sps）；FFT 点数 {n_fft}")
        print(f"占用带宽     : ±{bw_norm:.4f}·Rs（理论单边 (1+β)/2）")
        print(f"PSD(f=0)     : {at(0.0):.2f} dB（相对峰值）")
        print(f"PSD(f=±0.5Rs): {at(0.5):.2f} dB")
        print(f"PSD(f=±带宽) : {at(bw_norm):.2f} dB（带边 {bw_norm:.3f}·Rs 处）")
        print(f"PSD(f=±Rs)   : {at(1.0):.2f} dB（带外抑制指示）")
        print("说明          : 频率以符号率 Rs=1/T 归一化；dB 相对谱峰。")
        return

    # output == "eye"：发端 RRC + 收端匹配滤波（RRC），级联为 RC → 采样点无 ISI
    if filt == "rrc":
        mf = np.convolve(tx, taps, mode="full")
        # 级联两次 full 卷积，群延迟为 2·(span·sps/2)=span·sps
        delay = span * sps
        rx = mf
    else:
        # RC 已是奈奎斯特脉冲，收端不再匹配滤波
        rx = tx
        delay = span * sps // 2

    # 去掉首尾暂态，截取整数个符号周期
    start = delay
    usable_syms = (rx.size - 2 * delay) // sps
    if usable_syms < 4:
        print("错误：可用符号太少，无法画眼图。请增大 num_symbols。")
        return
    seg = rx[start:start + usable_syms * sps]

    # 符号采样点（每 sps 取 1，从相位 0 起）→ 眼图张开度与 ISI
    sample_pts = seg[::sps]
    eye_i = seg.real  # 眼图对实部（I 路）评估

    # 理想 I 路电平（含 0 电平，如 QPSK 单位圆的 {-1,0,1}）
    levels = np.unique(np.round(np.real(build_constellation(modulation)[0]), 6))
    samp_real = np.real(sample_pts)
    # 每采样点归入最近理想电平
    nearest_idx = np.argmin(np.abs(samp_real[:, None] - levels[None, :]), axis=1)
    nearest = levels[nearest_idx]
    # 峰值 ISI：采样点对最近理想电平的最大偏差（无量纲）
    isi_peak = float(np.max(np.abs(samp_real - nearest))) if samp_real.size else 0.0

    # 眼张开度：相邻电平簇之间的最小垂直间隙，按电平间距归一化。
    # 多电平/含 0 电平星座都适用（上簇最小值 − 下簇最大值）。
    if levels.size >= 2:
        spacing = float(np.min(np.diff(levels)))
        gaps = []
        for lo, hi in zip(levels[:-1], levels[1:]):
            lower = samp_real[nearest == lo]
            upper = samp_real[nearest == hi]
            if lower.size and upper.size:
                gaps.append(float(upper.min() - lower.max()))
        eye_open = (min(gaps) / spacing) if gaps else float("nan")
    else:
        eye_open = float("nan")

    print(f"=== 眼图 / 匹配滤波：{filt.upper()}（β={beta}，{modulation}）===")
    print(f"每符号采样   : {sps}（sps）；滤波器跨度 {span} 符号")
    print(f"符号数        : {n_sym}（可用眼图符号 {usable_syms}）")
    print(f"滚降系数 β   : {beta:.3f}（无量纲）")
    if filt == "rrc":
        print("链路          : 发端 RRC + 收端匹配 RRC = RC（奈奎斯特，采样点理论无 ISI）")
    else:
        print("链路          : 发端 RC（奈奎斯特脉冲，收端不再匹配滤波）")
    print(f"峰值 ISI      : {isi_peak:.4f}（I 路符号采样点对最近理想电平的最大偏差，无量纲）")
    if not math.isnan(eye_open):
        print(f"眼张开度      : {eye_open:.4f}（相邻电平最小间隙/电平间距，1=完全张开；受噪声/ISI 收窄）")
    print(f"采样点幅度范围: [{samp_real.min():+.4f}, {samp_real.max():+.4f}]（I 路，无量纲）")
    # 附上可直接交 plot 工具画眼图的字段（plot eye 需要 signal + samples_per_symbol）
    plot_hint = {
        "plot_type": "eye",
        "signal": [round(float(v), 6) for v in eye_i[: min(eye_i.size, sps * 200)]],
        "samples_per_symbol": sps,
        "title": f"eye_{modulation}_{filt}_beta{beta}",
    }
    print("PLOT_EYE_INPUT: " + json.dumps(plot_hint, ensure_ascii=False))
    print("说明          : 时间以符号周期 T 为单位；I/Q 幅度无量纲（能量归一化星座）。"
          "如需图形，把 PLOT_EYE_INPUT 的 JSON 交给 plot 工具。")


if __name__ == "__main__":
    main()

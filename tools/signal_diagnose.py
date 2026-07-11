"""测量信号诊断（被 signal_diagnose 工具调用）。

参数以 JSON 传入，优先级 argv[1] > stdin（大数组走 stdin，同 signal_analysis）。

JSON 字段：
    signal: list[float]   — 实信号采样值（与 signal_file / i+q 三选一）
    signal_file: str      — 信号文件路径（JSON 数组或空白/逗号分隔数值）
    i, q: list[float]     — IQ 双路采样（给了才做 IQ 失衡估计）
    sample_rate_hz: float — 采样率，Hz
    fundamental_hz: float?— 基波频率（THD 用；不给则取最强谱峰）
    clip_level: float?    — 削波判定电平（绝对值），默认取样本绝对值最大值的 0.999 倍

输出：诊断指标 + 触发的症状条目。
指标口径（工程估计，非仪器级）：
    SNR 估计   ：最强谱峰 ±3 bin 为信号，其余为噪声+失真的功率比（对单音/窄带激励可靠）
    DC 偏置    ：均值 / RMS 比值，>5% 报症状
    削波       ：|x| ≥ clip_level 的样本占比，>0.1% 报症状
    THD        ：2~5 次谐波功率 / 基波功率（需给或可测出基波）
    IQ 失衡    ：幅度失衡 20log10(σI/σQ)；相位失衡 asin(corr(I,Q))——假设单音/窄带
                 激励且 I/Q 本应正交等幅，宽带调制信号下该估计不可靠（工具会注明）。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def load_array(payload: dict, key: str) -> np.ndarray:
    return np.array(payload.get(key, []), dtype=np.float64)


def load_signal(payload: dict) -> np.ndarray:
    signal_file = payload.get("signal_file")
    if signal_file:
        text = Path(signal_file).read_text(encoding="utf-8").strip()
        if not text:
            return np.array([], dtype=np.float64)
        try:
            return np.asarray(json.loads(text), dtype=np.float64)
        except (json.JSONDecodeError, ValueError):
            return np.fromstring(text.replace(",", " "), sep=" ", dtype=np.float64)
    return load_array(payload, "signal")


def spectrum(x: np.ndarray, fs: float):
    n = x.size
    win = np.hanning(n)
    fft_vals = np.fft.rfft(x * win)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    power = np.abs(fft_vals) ** 2
    return freqs, power


def main() -> None:
    payload = load_payload()
    fs = float(payload["sample_rate_hz"])
    if fs <= 0:
        print("错误：sample_rate_hz 必须为正数。")
        return

    i_arr = load_array(payload, "i")
    q_arr = load_array(payload, "q")
    has_iq = i_arr.size > 0 and q_arr.size > 0
    x = i_arr if has_iq else load_signal(payload)
    if x.size < 32:
        print("错误：输入信号为空或过短（至少 32 点；signal / signal_file / i+q 三选一）。")
        return

    symptoms = []
    print("=== 信号诊断报告（工程估计口径，非仪器级） ===")
    print(f"样本数       : {x.size}，采样率 {fs:.6g} Hz" + ("（IQ 双路，指标基于 I 路）" if has_iq else ""))

    # DC 偏置
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms == 0:
        print("错误：信号全零，无法诊断。")
        return
    dc = float(np.mean(x))
    dc_pct = abs(dc) / rms * 100.0
    print(f"DC 偏置      : {dc:.4g}（占 RMS {dc_pct:.2f}%）")
    if dc_pct > 5.0:
        symptoms.append(f"DC 偏置显著（{dc_pct:.1f}% > 5%）——零中频接收机常见本振泄漏/ADC 偏置")

    # 削波：贴满幅样本占比 + 平顶连续段（削波的本质特征是波形顶端被削平，
    # 出现连续多点贴同一极值；纯正弦只会瞬时触峰，连续段长度 1~2 点）
    peak = float(np.max(np.abs(x)))
    clip_level = float(payload.get("clip_level", peak * 0.999))
    at_peak = np.abs(x) >= clip_level
    clip_ratio = float(np.mean(at_peak)) * 100.0
    max_run = 0
    run = 0
    for flag in at_peak:
        run = run + 1 if flag else 0
        max_run = max(max_run, run)
    crest_db = 20.0 * math.log10(peak / rms)
    print(f"峰均比       : {crest_db:.2f} dB，削波电平 {clip_level:.4g} 处样本占比 {clip_ratio:.3f}%（最长平顶 {max_run} 点）")
    if clip_ratio > 0.1 and max_run >= 3:
        symptoms.append(f"疑似削波（贴满幅样本占 {clip_ratio:.2f}%，最长平顶 {max_run} 点）——增益过大/ADC 饱和，会产生谐波与互调杂散")

    # 频域：SNR 估计 / 基波 / THD / 杂散
    freqs, power = spectrum(x - dc, fs)
    fund_hz = payload.get("fundamental_hz")
    peak_idx = int(np.argmax(power[1:]) + 1)
    if fund_hz is None:
        fund_hz = float(freqs[peak_idx])
    else:
        fund_hz = float(fund_hz)
        peak_idx = int(np.argmin(np.abs(freqs - fund_hz)))
    bin_hw = 3
    sig_band = slice(max(peak_idx - bin_hw, 0), min(peak_idx + bin_hw + 1, power.size))
    p_sig = float(np.sum(power[sig_band]))
    p_rest = float(np.sum(power)) - p_sig - float(power[0])
    snr_db = 10.0 * math.log10(p_sig / p_rest) if p_rest > 0 else float("inf")
    print(f"最强分量     : {fund_hz:.6g} Hz")
    print(f"SNR 估计     : {snr_db:.2f} dB（单音/窄带激励下可靠；宽带调制信号该值≈信号带内外功率比，仅作参考）")
    if snr_db < 20.0:
        symptoms.append(f"带内噪声/失真偏高（SNR 估计 {snr_db:.1f} dB < 20 dB）")

    # THD：2~5 次谐波
    if fund_hz > 0 and 2 * fund_hz < fs / 2:
        p_harm = 0.0
        harmonics = []
        for h in range(2, 6):
            f_h = h * fund_hz
            if f_h >= fs / 2:
                break
            idx = int(np.argmin(np.abs(freqs - f_h)))
            band = slice(max(idx - bin_hw, 0), min(idx + bin_hw + 1, power.size))
            ph = float(np.sum(power[band]))
            p_harm += ph
            harmonics.append((h, 10.0 * math.log10(ph / p_sig) if p_sig > 0 else float("-inf")))
        thd_pct = math.sqrt(p_harm / p_sig) * 100.0 if p_sig > 0 else float("nan")
        detail = ", ".join(f"H{h}={db:.1f}dBc" for h, db in harmonics)
        print(f"THD 估计     : {thd_pct:.2f}%（基波 {fund_hz:.6g} Hz；{detail}）")
        if thd_pct > 5.0:
            symptoms.append(f"谐波失真偏高（THD {thd_pct:.1f}% > 5%）——放大器压缩/削波的典型特征")

    # IQ 失衡
    if has_iq:
        if q_arr.size != i_arr.size:
            print("错误：i 与 q 长度必须一致。")
            return
        qc = q_arr - float(np.mean(q_arr))
        ic = i_arr - dc
        gain_imb_db = 20.0 * math.log10(float(np.std(ic)) / float(np.std(qc))) if float(np.std(qc)) > 0 else float("inf")
        corr = float(np.corrcoef(ic, qc)[0, 1])
        phase_err_deg = math.degrees(math.asin(max(-1.0, min(1.0, corr))))
        print(f"IQ 幅度失衡  : {gain_imb_db:+.3f} dB；相位失衡估计 {phase_err_deg:+.2f}°（假设 I/Q 本应正交等幅——单音/窄带激励下有效）")
        if abs(gain_imb_db) > 0.5 or abs(phase_err_deg) > 2.0:
            symptoms.append(f"IQ 失衡（幅度 {gain_imb_db:+.2f} dB / 相位 {phase_err_deg:+.1f}°）——产生镜像分量，恶化 EVM")

    print()
    if symptoms:
        print(f"--- 触发症状（{len(symptoms)} 项，按检出顺序）---")
        for idx, s in enumerate(symptoms, 1):
            print(f"  {idx}. {s}")
        print("排查建议：对照 knowledge/故障特征速查.md 的症状→原因表定位根因。")
    else:
        print("未触发症状条目：各指标在经验门限内。")


if __name__ == "__main__":
    main()

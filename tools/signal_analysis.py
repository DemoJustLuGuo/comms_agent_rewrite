"""信号频谱分析（被 signal_analysis 工具调用）。

参数以 JSON 传入，两种来源，优先级：argv[1] > stdin。
    · TS 桥接（OpenCode 实时调用）走 stdin，避免 Windows 命令行 32767 字符上限
      把可用采样点数卡在约 4000～5000 点。
    · 直接命令行 / 单元测试仍可用 argv[1] 传 JSON。

JSON 字段：
    signal: list[float]   — 时域采样值（与 signal_file 二选一）
    signal_file: str      — 信号文件路径（与 signal 二选一，适合上万点长信号）；
                            文件内容可为 JSON 数组，或空白/逗号/换行分隔的数值。
    sample_rate_hz: float — 采样率 (Hz)
    window: str           — 加窗类型 (rectangular|hamming|hanning|blackman)，默认 hamming
    num_peaks: int        — 返回峰值数，默认 5
输出：频谱分析文本报告（峰值频率/幅度/PSD 统计）。
单位：频率 Hz，幅度 dB（相对满幅），功率谱密度 dB/Hz。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy.signal import find_peaks


WINDOW_FUNCS = {
    "rectangular": np.ones,
    "hamming": np.hamming,
    "hanning": np.hanning,
    "blackman": np.blackman,
}


def load_payload() -> dict:
    """优先读 argv[1]，否则读 stdin；两者都空则返回空 dict。"""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def load_signal(payload: dict) -> np.ndarray:
    """从 signal_file（优先）或 signal 字段取时域采样值。"""
    signal_file = payload.get("signal_file")
    if signal_file:
        text = Path(signal_file).read_text(encoding="utf-8").strip()
        if not text:
            return np.array([], dtype=np.float64)
        # 先按 JSON 数组解析，失败再按空白/逗号分隔的数值解析
        try:
            return np.asarray(json.loads(text), dtype=np.float64)
        except (json.JSONDecodeError, ValueError):
            return np.fromstring(text.replace(",", " "), sep=" ", dtype=np.float64)
    return np.array(payload.get("signal", []), dtype=np.float64)


def main() -> None:
    payload = load_payload()

    signal = load_signal(payload)
    fs = float(payload["sample_rate_hz"])
    window_name = payload.get("window", "hamming")
    num_peaks = int(payload.get("num_peaks", 5))

    if signal.size == 0:
        print("错误：输入信号为空（signal 与 signal_file 均未提供有效数据）。")
        return
    if fs <= 0:
        print("错误：采样率必须为正数。")
        return

    n = signal.size
    win_func = WINDOW_FUNCS.get(window_name, np.hamming)
    win = win_func(n)
    windowed = signal * win

    # FFT，取单边谱
    fft_vals = np.fft.rfft(windowed)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)  # Hz

    # 幅度谱 (dB)，归一化到满幅
    magnitude = np.abs(fft_vals) * 2.0 / n
    magnitude[0] /= 2.0  # DC 分量不需要 x2
    mag_db = 20.0 * np.log10(magnitude + 1e-12)

    # 功率谱密度 (dB/Hz)
    psd = (np.abs(fft_vals) ** 2) / (fs * n)
    psd_db = 10.0 * np.log10(psd + 1e-30)

    # 寻峰
    peaks_idx, properties = find_peaks(mag_db, distance=max(1, n // 100))
    if len(peaks_idx) == 0:
        peaks_idx = np.array([np.argmax(mag_db)])

    # 按幅度降序取 top-N
    sorted_peaks = peaks_idx[np.argsort(mag_db[peaks_idx])[::-1]][:num_peaks]

    print(f"=== 频谱分析报告 ===")
    print(f"信号长度     : {n} 采样点")
    print(f"采样率       : {fs:.1f} Hz")
    print(f"频率分辨率   : {fs / n:.3f} Hz")
    print(f"加窗         : {window_name}")
    print(f"PSD 均值     : {np.mean(psd_db):.2f} dB/Hz")
    print(f"PSD 峰值     : {np.max(psd_db):.2f} dB/Hz")
    print()
    print(f"--- 前 {len(sorted_peaks)} 个频率峰值 ---")
    for i, idx in enumerate(sorted_peaks, 1):
        print(f"  {i}. f = {freqs[idx]:.2f} Hz, 幅度 = {mag_db[idx]:.2f} dB, PSD = {psd_db[idx]:.2f} dB/Hz")


if __name__ == "__main__":
    main()

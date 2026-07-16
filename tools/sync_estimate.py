"""同步偏差估计（被 sync_estimate 工具调用）：载波频偏 CFO / 采样频偏 SFO / 定时偏移。

对接收到的复基带符号（或 I/Q 双路）做同步偏差估计，补 signal_diagnose 未覆盖的
"星座旋转→先做频偏估计"闭环断点（见 knowledge/故障特征速查.md）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    mode: str            — cfo | sfo | timing
    i, q: list[float]    — 接收复基带采样/符号的 I、Q 两路（等长；与 signal_file 二选一）
    signal_file: str     — 文件路径，两列（I,Q 每行）或交错 I,Q,I,Q...（长信号用）
    sample_rate_hz: float— 采样率（cfo/sfo 用；符号级输入时填符号率）
    modulation: str?     — cfo 盲估计用（M 次方去调制）：BPSK/QPSK/8PSK→M=2/4/8，默认 QPSK
    samples_per_symbol: int? — sfo/timing 用，默认 1（已符号级采样）
    known_symbols_i/q: list[float]? — 数据辅助 cfo（给了则用导频/已知符号，更准）

输出：估计值 + 工程解读文本报告。
口径（工程估计，非仪器级）：
    CFO 盲估计：对 M 次方去调制后信号做 FFT，峰值频率 / M 即残余载频偏（假设 MPSK/等间隔相位）。
    CFO 数据辅助：rx·conj(known) 的平均相位增量 → Δf = angle(mean)/(2π·Ts)。
    SFO：把符号序列分前后两半分别估 CFO，相位斜率随时间的漂移折算采样时钟偏差（ppm，粗估）。
    定时偏移：对 |x|^2（或与已知前导的互相关）找峰，报最佳采样点相对整数符号的小数偏移。
单位：频率 Hz、相位 rad/deg、时间 s、SFO ppm、定时偏移 samples（无量纲小数）。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import build_constellation  # noqa: E402

_MPSK_ORDER = {"BPSK": 2, "QPSK": 4, "8PSK": 8}


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def _from_file(path: str) -> np.ndarray:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return np.array([], dtype=complex)
    try:
        data = json.loads(text)
        arr = np.asarray(data, dtype=float)
    except (json.JSONDecodeError, ValueError):
        arr = np.fromstring(text.replace(",", " "), sep=" ", dtype=float)
    # 两列(I,Q) 或交错 I,Q,I,Q...：都按偶=I、奇=Q 解释
    if arr.ndim == 2 and arr.shape[1] == 2:
        return arr[:, 0] + 1j * arr[:, 1]
    arr = arr.reshape(-1)
    if arr.size % 2 != 0:
        arr = arr[:-1]
    return arr[0::2] + 1j * arr[1::2]


def load_complex(payload: dict) -> np.ndarray:
    sig_file = payload.get("signal_file")
    if sig_file:
        return _from_file(sig_file)
    i = np.asarray(payload.get("i", []), dtype=float)
    q = np.asarray(payload.get("q", []), dtype=float)
    if i.size == 0 or q.size == 0:
        return np.array([], dtype=complex)
    if i.size != q.size:
        raise ValueError("i 与 q 长度必须一致。")
    return i + 1j * q


def estimate_cfo_blind(x: np.ndarray, fs: float, m: int):
    """M 次方去调制 + FFT 找峰，返回 (Δf_hz, 峰值归一化幅度)。"""
    xm = x ** m
    n = xm.size
    win = np.hanning(n)
    spec = np.abs(np.fft.fftshift(np.fft.fft(xm * win)))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / fs))
    peak = int(np.argmax(spec))
    total = float(np.sum(spec))
    strength = float(spec[peak] / total) if total > 0 else 0.0
    df = float(freqs[peak]) / m  # 去 M 次方后频率是 M 倍
    return df, strength


def estimate_cfo_da(rx: np.ndarray, known: np.ndarray, fs: float):
    """数据辅助：rx·conj(known) 平均相位增量。返回 (Δf_hz, 残余相位 rad)。"""
    n = min(rx.size, known.size)
    z = rx[:n] * np.conj(known[:n])
    # 相邻乘积的相位差平均 → 每样本相位增量
    prod = z[1:] * np.conj(z[:-1])
    mean_phase_step = float(np.angle(np.sum(prod)))
    df = mean_phase_step * fs / (2.0 * math.pi)
    resid_phase = float(np.angle(np.sum(z)))
    return df, resid_phase


def main() -> None:
    payload = load_payload()
    mode = payload.get("mode", "cfo")
    if mode not in ("cfo", "sfo", "timing"):
        print("错误：mode 只能是 cfo | sfo | timing。")
        return

    try:
        x = load_complex(payload)
    except ValueError as e:
        print(f"错误：{e}")
        return
    if x.size < 16:
        print("错误：输入复符号为空或过短（至少 16 点；i+q 或 signal_file 提供）。")
        return

    fs = payload.get("sample_rate_hz")
    if fs is None or float(fs) <= 0:
        print("错误：sample_rate_hz 必须为正数（符号级输入时填符号率）。")
        return
    fs = float(fs)

    if mode == "cfo":
        print("=== 载波频偏 CFO 估计（工程估计口径）===")
        print(f"样本数       : {x.size}，采样率/符号率 {fs:.6g} Hz")
        ki = payload.get("known_symbols_i")
        kq = payload.get("known_symbols_q")
        if ki is not None and kq is not None:
            known = np.asarray(ki, dtype=float) + 1j * np.asarray(kq, dtype=float)
            df, resid = estimate_cfo_da(x, known, fs)
            print(f"估计方式     : 数据辅助（导频/已知符号 {known.size} 个）")
            print(f"CFO Δf       : {df:+.4g} Hz")
            print(f"残余相位     : {math.degrees(resid):+.2f}°（首符号对齐后的固定相偏）")
        else:
            mod = payload.get("modulation", "QPSK").upper()
            m = _MPSK_ORDER.get(mod)
            if m is None:
                print(f"提示：盲估计仅支持 MPSK（BPSK/QPSK/8PSK），'{mod}' 不适用，按 QPSK(M=4) 处理。")
                m = 4
            df, strength = estimate_cfo_blind(x, fs, m)
            print(f"估计方式     : 盲估计（{mod}，M={m} 次方去调制 + FFT 找峰）")
            print(f"CFO Δf       : {df:+.4g} Hz")
            print(f"谱峰强度     : {strength * 100:.2f}%（占总谱能量；越集中越可信，弥散说明相噪主导而非 CFO）")
        print("解读：星座整体缓慢旋转 → CFO 残留（每符号旋转角 2π·Δf·Ts）；先做频偏校正再判其余损伤。")

    elif mode == "sfo":
        # 前后两半分别盲估 CFO，相位斜率随时间漂移 → 采样时钟偏差粗估
        mod = payload.get("modulation", "QPSK").upper()
        m = _MPSK_ORDER.get(mod, 4)
        half = x.size // 2
        df1, _ = estimate_cfo_blind(x[:half], fs, m)
        df2, _ = estimate_cfo_blind(x[half:], fs, m)
        drift_hz = df2 - df1
        # 两段中心相隔约 half 个样本 → 频率漂移率折算 ppm（相对采样率）
        ppm = (drift_hz / fs) * 1e6
        print("=== 采样频偏 SFO 估计（粗估口径）===")
        print(f"样本数       : {x.size}，采样率 {fs:.6g} Hz（{mod}，M={m}）")
        print(f"前半段 CFO   : {df1:+.4g} Hz")
        print(f"后半段 CFO   : {df2:+.4g} Hz")
        print(f"频率漂移     : {drift_hz:+.4g} Hz（后-前）")
        print(f"SFO 粗估     : {ppm:+.2f} ppm（相对采样率；正=接收采样偏快）")
        print("解读：CFO 随时间线性漂移常源于收发采样时钟不同源（SFO），需符号定时环跟踪；"
              "漂移可忽略则时钟基本同源。此为粗估，精测需已知长前导做定时误差斜率拟合。")

    else:  # timing
        sps = int(payload.get("samples_per_symbol", 1))
        if sps < 1:
            print("错误：samples_per_symbol 必须 ≥ 1。")
            return
        power = np.abs(x) ** 2
        if sps == 1:
            print("=== 定时偏移估计 ===")
            print(f"样本数       : {x.size}（samples_per_symbol=1，已符号级采样）")
            print("提示：输入已是符号级（sps=1），无子符号定时信息可估。"
                  "定时偏移估计需过采样信号（sps≥2）或已知前导做互相关。")
            return
        # 能量重心法（Gardner 思路的简化）：在一个符号窗内找能量最大相位
        n_sym = power.size // sps
        if n_sym < 4:
            print("错误：符号数太少（至少 4 符号）。")
            return
        grid = power[:n_sym * sps].reshape(n_sym, sps)
        avg = grid.mean(axis=0)  # 每个采样相位的平均能量
        best_phase = int(np.argmax(avg))
        # 抛物线插值求小数最佳采样点
        p = best_phase
        y0, y1, y2 = avg[(p - 1) % sps], avg[p], avg[(p + 1) % sps]
        denom = (y0 - 2 * y1 + y2)
        frac = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        tau = (best_phase + frac) % sps
        print("=== 定时偏移估计（能量重心 + 抛物线插值）===")
        print(f"符号数       : {n_sym}，每符号采样 sps={sps}")
        print(f"最佳采样相位 : {tau:.3f} / {sps} 采样（整数符号内偏移）")
        print(f"归一化定时误差: {tau / sps:.4f}（0=对齐符号起点，0.5=偏半符号）")
        print("解读：偏离最佳采样点会引入 ISI，眼图上采样时刻偏离眼睛中心；用定时环（Gardner/早迟门）跟踪。")


if __name__ == "__main__":
    main()

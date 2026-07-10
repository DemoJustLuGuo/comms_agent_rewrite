"""通信可视化绘图（被 plot 工具调用）。

生成 PNG 图并返回文件路径（OpenCode 输出为文本，图以文件形式交付；Web UI 可直接查看）。

参数以 JSON 传入，优先级：argv[1] > stdin（大信号走 stdin，避免命令行长度限制）。
    plot_type: str   — constellation | spectrum | waveform | ber_curve | eye
    output_path: str — 输出 PNG 路径（可选，仅允许写入项目 plots/ 目录；默认 plots/<plot_type>.png）
    title: str       — 图标题（可选）
    # 各类型数据字段：
    #   constellation: i:[...], q:[...]           （同相/正交分量）
    #   spectrum     : signal:[...], sample_rate_hz
    #   waveform     : signal:[...], sample_rate_hz
    #   ber_curve    : series:[{label, snr_db:[...], ber:[...]}]  或  snr_db:[...], ber:[...]
    #   eye          : signal:[...], samples_per_symbol:int
输出：保存路径 + 关键统计。单位：频率 Hz，幅度 dB，时间 s。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无显示后端，服务器/管道环境可用
import matplotlib.pyplot as plt

ROOT = Path.cwd()  # 工作区根：.ts 端已把子进程 cwd 设为会话目录；直接跑脚本/测试时为当前目录
ARTIFACT_PREFIX = "COMM_ARTIFACT: "


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def resolve_output(payload: dict, plot_type: str) -> Path:
    plots_root = (ROOT / "plots").resolve()
    out = payload.get("output_path")
    if out:
        p = Path(out)
        candidate = p if p.is_absolute() else (ROOT / p)
    else:
        candidate = ROOT / "plots" / f"{plot_type}.png"
    resolved = candidate.resolve()
    try:
        resolved.relative_to(plots_root)
    except ValueError:
        raise ValueError("output_path 只能写入项目 plots/ 目录，避免可视化工具写到任意路径")
    return resolved


def to_workspace_relative(path: Path) -> str:
    """Return a stable workspace-relative path for UI artifact renderers."""
    return path.resolve().relative_to(ROOT).as_posix()


def plot_constellation(ax, payload):
    i = np.asarray(payload["i"], dtype=np.float64)
    q = np.asarray(payload["q"], dtype=np.float64)
    ax.scatter(i, q, s=12, alpha=0.6)
    ax.axhline(0, color="gray", lw=0.5)
    ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlabel("In-phase (I)")
    ax.set_ylabel("Quadrature (Q)")
    ax.set_aspect("equal", adjustable="datalim")
    return f"{i.size} 个符号点"


def plot_spectrum(ax, payload):
    sig = np.asarray(payload["signal"], dtype=np.float64)
    fs = float(payload["sample_rate_hz"])
    n = sig.size
    mag = np.abs(np.fft.rfft(sig)) * 2.0 / n
    mag[0] /= 2.0
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    mag_db = 20.0 * np.log10(mag + 1e-12)
    ax.plot(freqs, mag_db, lw=1.0)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.grid(True, alpha=0.3)
    return f"{n} 点, 峰值 {freqs[int(np.argmax(mag_db))]:.2f} Hz"


def plot_waveform(ax, payload):
    sig = np.asarray(payload["signal"], dtype=np.float64)
    fs = float(payload["sample_rate_hz"])
    t = np.arange(sig.size) / fs
    ax.plot(t, sig, lw=1.0)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.grid(True, alpha=0.3)
    return f"{sig.size} 点, 时长 {sig.size / fs:.4f} s"


def plot_ber_curve(ax, payload):
    if "series" in payload:
        series = payload["series"]
    else:
        series = [{"label": payload.get("label", "BER"),
                   "snr_db": payload["snr_db"], "ber": payload["ber"]}]
    for s in series:
        snr = np.asarray(s["snr_db"], dtype=np.float64)
        ber = np.asarray(s["ber"], dtype=np.float64)
        ber = np.clip(ber, 1e-12, 1.0)
        ax.semilogy(snr, ber, marker="o", ms=4, label=s.get("label", ""))
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("BER")
    ax.grid(True, which="both", alpha=0.3)
    if any(s.get("label") for s in series):
        ax.legend()
    return f"{len(series)} 条曲线"


def plot_eye(ax, payload):
    sig = np.asarray(payload["signal"], dtype=np.float64)
    sps = int(payload["samples_per_symbol"])
    if sps <= 0:
        raise ValueError("samples_per_symbol 必须为正整数")
    span = 2 * sps  # 两个符号周期的眼图
    n_traces = sig.size // span
    if n_traces == 0:
        raise ValueError("信号长度不足以绘制眼图")
    seg = sig[: n_traces * span].reshape(n_traces, span)
    x = np.arange(span) / sps
    for row in seg:
        ax.plot(x, row, color="C0", alpha=0.3, lw=0.8)
    ax.set_xlabel("Symbol periods")
    ax.set_ylabel("Amplitude")
    ax.grid(True, alpha=0.3)
    return f"{n_traces} 条迹线"


PLOTTERS = {
    "constellation": plot_constellation,
    "spectrum": plot_spectrum,
    "waveform": plot_waveform,
    "ber_curve": plot_ber_curve,
    "eye": plot_eye,
}


def main() -> None:
    payload = load_payload()
    plot_type = payload.get("plot_type", "")
    if plot_type not in PLOTTERS:
        print(f"错误：plot_type 需为 {'/'.join(PLOTTERS)}，收到 {plot_type!r}。")
        return

    try:
        out_path = resolve_output(payload, plot_type)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        print(f"错误：{e}")
        return

    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=120)
    try:
        summary = PLOTTERS[plot_type](ax, payload)
    except KeyError as e:
        plt.close(fig)
        print(f"错误：缺少 {plot_type} 所需字段 {e}。")
        return
    except (ValueError, TypeError) as e:
        plt.close(fig)
        print(f"错误：{e}")
        return

    ax.set_title(payload.get("title", plot_type))
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)

    print(f"已生成图像：{out_path}")
    print(f"类型         : {plot_type}")
    print(f"数据         : {summary}")
    artifact = {
        "version": 1,
        "kind": "image",
        "tool": "plot",
        "path": to_workspace_relative(out_path),
        "mime": "image/png",
        "title": payload.get("title") or plot_type,
        "meta": {
            "plot_type": plot_type,
            "summary": summary,
        },
    }
    print(f"{ARTIFACT_PREFIX}{json.dumps(artifact, ensure_ascii=False, separators=(',', ':'))}")


if __name__ == "__main__":
    main()

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
import os
import sys
from pathlib import Path
from urllib.parse import quote

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无显示后端，服务器/管道环境可用
import matplotlib.pyplot as plt

# 中文标签/图例字体：缺省 DejaVu Sans 无 CJK 字形，图内中文会变方框。
# 按常见 CJK 字体顺序探测，全部缺失时保持默认（Latin 文本不受影响）。
from matplotlib import font_manager

_FOR_CANDIDATES = ("Noto Sans CJK SC", "Noto Sans CJK TC", "WenQuanYi Zen Hei", "PingFang SC", "Microsoft YaHei", "SimHei")
_FOR_AVAILABLE = {f.name for f in font_manager.fontManager.ttflist}
_FOR_FOUND = [name for name in _FOR_CANDIDATES if name in _FOR_AVAILABLE]
if _FOR_FOUND:
    plt.rcParams["font.sans-serif"] = [_FOR_FOUND[0], *plt.rcParams["font.sans-serif"]]
    plt.rcParams["axes.unicode_minus"] = False

# 工作区根的两级解析：COMMS_WORKSPACE_ROOT（会话工作区，由 runner.ts 注入）优先，
# 兜底为脚本位置（tools/ 的上一级），不依赖子进程 cwd——pi-web 拉起的 pi 进程 cwd
# 是 pi-web 包目录，靠 cwd 曾把产物写进 node_modules。
# 图必须写进会话工作区（而非智能体仓库）：Web 的 /api/files 白名单按会话 cwd 授权，
# 写进仓库的图 403 无法内联显示；TUI/脚本未注入 env 时退回旧行为（写仓库 plots/）。
def _resolve_root() -> Path:
    env_root = os.environ.get("COMMS_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


ROOT = _resolve_root()
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
    snr_db = payload.get("noise_snr_db")
    label_extra = ""
    if snr_db is not None:
        # 对每个输入符号叠加复高斯噪声（AWGN）。输入约定为平均符号能量 Es=1 的星座点
        # （modulation 工具的输出口径）；若不是，噪声电平按实际功率缩放。
        snr_lin = 10.0 ** (float(snr_db) / 10.0)
        es = float(np.mean(np.abs(i + 1j * q) ** 2))
        n0 = es / snr_lin
        rng = np.random.default_rng(int(payload.get("seed", 0)))
        noise = np.sqrt(n0 / 2.0) * (rng.standard_normal(i.size) + 1j * rng.standard_normal(i.size))
        rx = i + 1j * q + noise
        ax.scatter(rx.real, rx.imag, s=6, alpha=0.35, color="tab:blue", label="接收（含 AWGN）")
        ax.scatter(i, q, s=42, marker="x", color="tab:red", linewidths=1.6, label="理想星座点")
        ax.legend(loc="upper right", fontsize=8)
        label_extra = f", SNR={float(snr_db):g} dB（Es/N0）, {i.size} 理想点 + 噪声散点, seed={payload.get('seed', 0)}"
    else:
        ax.scatter(i, q, s=12, alpha=0.6)
    ax.axhline(0, color="gray", lw=0.5)
    ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlabel("In-phase (I)")
    ax.set_ylabel("Quadrature (Q)")
    ax.set_aspect("equal", adjustable="datalim")
    return f"{i.size} 个符号点{label_extra}"


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
    rel_path = to_workspace_relative(out_path)
    # Web UI（pi-web）聊天区走 react-markdown 渲染，其 /api/files 端点要求绝对路径
    # （相对路径会被判 Access denied）；逐段 URL 编码（盘符冒号→%3A，兼容中文文件名）。
    # TUI 下该行只是普通文本，无副作用。
    abs_posix = str(Path(out_path).resolve()).replace("\\", "/")
    encoded = "/".join(quote(seg, safe="") for seg in abs_posix.split("/"))
    title = payload.get("title") or plot_type
    print(f"Markdown 内联 : ![{title}](/api/files/{encoded}?type=download)")
    artifact = {
        "version": 1,
        "kind": "image",
        "tool": "plot",
        "path": rel_path,
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

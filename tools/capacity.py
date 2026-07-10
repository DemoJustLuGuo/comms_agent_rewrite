"""香农容量 / MIMO 容量 / 频谱效率速算（被 capacity 工具调用）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    mode: str            — awgn | mimo | ebn0
    bandwidth_hz: float? — 带宽，Hz（awgn 必填；mimo 可选，给了才输出 bit/s）
    snr_db: float?       — 信噪比，dB（awgn/mimo 必填）
    nt: int?             — 发射天线数（mimo 必填）
    nr: int?             — 接收天线数（mimo 必填）
    allocation: str?     — equal | waterfilling（mimo，默认两者都报）
    realizations: int?   — mimo 遍历平均的 iid Rayleigh 信道实现数，默认 1000
    spectral_efficiency: float? — 频谱效率 η，bit/s/Hz（ebn0 必填）
    seed: int?           — 随机种子（mimo 复现）
输出：容量与频谱效率文本报告。
单位：容量 bit/s、频谱效率 bit/s/Hz、带宽 Hz、SNR 与 Eb/N0 为 dB。
假设：AWGN 高斯输入无限星座（香农上界）；MIMO 为接收端已知 CSI、E[|h|^2]=1 的 iid 瑞利平坦衰落遍历容量。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

MAX_REALIZATIONS = 100_000


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def waterfill(gains: np.ndarray, total_power: float) -> np.ndarray:
    """经典注水功率分配：max Σ log2(1+g_i·p_i) s.t. Σ p_i = total_power, p_i>=0。

    gains: 各特征模增益 g_i（噪声归一化）。返回各模功率 p_i（与 gains 等长，丢弃的模为 0）。
    用「排序 + 逐步丢弱模」的解析解，精确且无需二分。
    """
    g = np.asarray(gains, dtype=float)
    order = np.argsort(g)[::-1]  # 从强到弱
    g_sorted = g[order]
    n = g_sorted.size
    power = np.zeros(n, dtype=float)
    for k in range(n, 0, -1):
        active = g_sorted[:k]
        # 水位 mu 使前 k 个模功率和为 total_power：mu = (P + Σ 1/g_i)/k
        mu = (total_power + np.sum(1.0 / active)) / k
        p = mu - 1.0 / active
        if p[-1] >= 0:  # 最弱的活跃模也非负 → 该分配可行
            power[:k] = p
            break
    # 还原到原始顺序
    restored = np.zeros(n, dtype=float)
    restored[order] = power
    return restored


def capacity_awgn(bandwidth_hz: float, snr_db: float) -> None:
    snr_lin = 10.0 ** (snr_db / 10.0)
    se = math.log2(1.0 + snr_lin)  # bit/s/Hz
    cap = bandwidth_hz * se  # bit/s
    print("=== 香农容量（AWGN，高斯输入上界）===")
    print(f"带宽 B        : {bandwidth_hz:.4e} Hz")
    print(f"SNR 输入      : {snr_db:.2f} dB  (线性 {snr_lin:.4g})")
    print(f"频谱效率 η    : {se:.4f} bit/s/Hz")
    print(f"信道容量 C    : {cap:.4e} bit/s  ({cap / 1e6:.4f} Mbit/s)")
    print("说明          : C = B·log2(1+SNR)，为高斯输入的理论上界；实际调制/编码会低于该值。")


def capacity_mimo(nt: int, nr: int, snr_db: float, realizations: int,
                  bandwidth_hz, seed) -> None:
    rho = 10.0 ** (snr_db / 10.0)  # 总发射 SNR
    r = min(nt, nr)
    rng = np.random.default_rng(seed if seed is None else int(seed))

    c_eq_sum = 0.0
    c_wf_sum = 0.0
    lam_sum = np.zeros(r, dtype=float)   # 平均特征值谱（降序）
    pow_sum = np.zeros(r, dtype=float)   # 平均注水功率（降序）
    active_sum = 0.0
    for _ in range(realizations):
        # E[|h|^2]=1 的 iid 瑞利信道 H（nr×nt）
        h = (rng.standard_normal((nr, nt)) + 1j * rng.standard_normal((nr, nt))) / math.sqrt(2.0)
        sv = np.linalg.svd(h, compute_uv=False)
        lam = np.sort((sv ** 2))[::-1]           # H·Hᴴ 的非零特征值，降序
        lam = np.pad(lam, (0, r - lam.size))[:r] if lam.size < r else lam[:r]
        # 等功率（无发端 CSI）：每发射天线 ρ/nt
        c_eq_sum += float(np.sum(np.log2(1.0 + (rho / nt) * lam)))
        # 注水（有发端 CSI）：总功率 ρ 分配到各特征模
        p = waterfill(lam, rho)
        c_wf_sum += float(np.sum(np.log2(1.0 + p * lam)))
        lam_sum += lam
        pow_sum += p
        active_sum += float(np.count_nonzero(p > 1e-12))

    c_eq = c_eq_sum / realizations   # bit/s/Hz
    c_wf = c_wf_sum / realizations
    lam_mean = lam_sum / realizations
    pow_mean = pow_sum / realizations
    active_mean = active_sum / realizations

    print(f"=== MIMO 容量（{nr}×{nt}，iid 瑞利遍历，接收端已知 CSI）===")
    print(f"发射/接收天线 : nt={nt}, nr={nr}  (有效流数 r={r})")
    print(f"总 SNR ρ      : {snr_db:.2f} dB  (线性 {rho:.4g})")
    print(f"实现数        : {realizations}（iid 瑞利遍历平均）")
    print(f"等功率容量    : {c_eq:.4f} bit/s/Hz  (无发端 CSI，每天线 ρ/nt)")
    print(f"注水容量      : {c_wf:.4f} bit/s/Hz  (有发端 CSI，注水增益 {c_wf - c_eq:+.4f} bit/s/Hz)")
    print(f"平均活跃模数  : {active_mean:.2f} / {r}")
    lam_str = ", ".join(f"{v:.3f}" for v in lam_mean)
    pow_str = ", ".join(f"{v:.3f}" for v in pow_mean)
    print(f"平均特征值谱  : [{lam_str}]  (H·Hᴴ 特征值，降序，无量纲)")
    print(f"平均注水功率  : [{pow_str}]  (各模功率，Σ=ρ={rho:.4g}，无量纲)")
    if bandwidth_hz is not None:
        bw = float(bandwidth_hz)
        print(f"带宽 B        : {bw:.4e} Hz")
        print(f"等功率速率    : {bw * c_eq:.4e} bit/s  ({bw * c_eq / 1e6:.4f} Mbit/s)")
        print(f"注水速率      : {bw * c_wf:.4e} bit/s  ({bw * c_wf / 1e6:.4f} Mbit/s)")


def capacity_ebn0(spectral_efficiency: float, snr_db) -> None:
    eta = spectral_efficiency
    # 达到 η 所需最小 Eb/N0（AWGN 香农极限）：(2^η − 1)/η
    ebn0_min_lin = (2.0 ** eta - 1.0) / eta
    ebn0_min_db = 10.0 * math.log10(ebn0_min_lin)
    print("=== Eb/N0 ↔ SNR ↔ 频谱效率（AWGN 香农极限）===")
    print(f"频谱效率 η    : {eta:.4f} bit/s/Hz")
    print(f"最小 Eb/N0    : {ebn0_min_db:.4f} dB  (线性 {ebn0_min_lin:.4g}；(2^η−1)/η)")
    print(f"绝对极限      : η→0 时 Eb/N0 → ln2 = -1.5917 dB（香农极限）")
    if snr_db is not None:
        snr_lin = 10.0 ** (float(snr_db) / 10.0)
        ebn0_lin = snr_lin / eta          # Eb/N0 = SNR/η
        ebn0_db = 10.0 * math.log10(ebn0_lin)
        margin = ebn0_db - ebn0_min_db
        print(f"输入 SNR      : {float(snr_db):.2f} dB  (线性 {snr_lin:.4g})")
        print(f"对应 Eb/N0    : {ebn0_db:.4f} dB  (Eb/N0 = SNR/η)")
        print(f"距香农极限    : {margin:+.4f} dB  ({'有余量' if margin >= 0 else '不可达'})")


def main() -> None:
    payload = load_payload()
    mode = payload.get("mode", "")

    if mode == "awgn":
        if "bandwidth_hz" not in payload or "snr_db" not in payload:
            print("错误：awgn 模式需要 bandwidth_hz（Hz）与 snr_db（dB）。")
            return
        bandwidth_hz = float(payload["bandwidth_hz"])
        if bandwidth_hz <= 0:
            print("错误：bandwidth_hz 必须为正数。")
            return
        capacity_awgn(bandwidth_hz, float(payload["snr_db"]))

    elif mode == "mimo":
        if "nt" not in payload or "nr" not in payload or "snr_db" not in payload:
            print("错误：mimo 模式需要 nt、nr（天线数）与 snr_db（dB）。")
            return
        nt = int(payload["nt"])
        nr = int(payload["nr"])
        if nt < 1 or nr < 1:
            print("错误：nt 与 nr 必须为正整数。")
            return
        realizations = min(int(payload.get("realizations", 1000)), MAX_REALIZATIONS)
        if realizations < 1:
            print("错误：realizations 必须为正整数。")
            return
        capacity_mimo(nt, nr, float(payload["snr_db"]), realizations,
                      payload.get("bandwidth_hz"), payload.get("seed"))

    elif mode == "ebn0":
        if "spectral_efficiency" not in payload:
            print("错误：ebn0 模式需要 spectral_efficiency（η，bit/s/Hz）。")
            return
        eta = float(payload["spectral_efficiency"])
        if eta <= 0:
            print("错误：spectral_efficiency 必须为正数。")
            return
        capacity_ebn0(eta, payload.get("snr_db"))

    else:
        print(f"错误：不支持的 mode '{mode}'。可选：awgn | mimo | ebn0。")


if __name__ == "__main__":
    main()

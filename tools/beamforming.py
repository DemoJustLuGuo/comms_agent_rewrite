"""波束成形 / 预编码（被 beamforming 工具调用）：阵列方向图 / MRT / ZF 预编码。

回答 massive MIMO / 5G 波束成形场景的「阵列增益多少、主瓣指向、旁瓣电平、多用户 ZF
预编码能否解耦」这类问题，是 capacity（只算容量）之外的空间处理算子。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    mode: str              — pattern | mrt | zf
    # pattern：均匀线阵(ULA)方向图
    num_elements: int?     — 阵元数 N，默认 8
    spacing_wavelength: float? — 阵元间距（波长为单位），默认 0.5（半波长）
    steer_deg: float?      — 波束指向角（相对法线，度），默认 0
    # mrt：单用户最大比发射（MRT）阵列增益
    channel_i/channel_q: list[float]? — 下行信道向量 h（各阵元复增益 I/Q，与 num_elements 对齐）
    # zf：多用户迫零预编码（信道矩阵按行=用户、列=阵元）
    channel_matrix: list[list[float]]? — 复信道矩阵，元素为 [re,im]；行=用户 K、列=阵元 N（需 N≥K）

输出：阵列增益/方向图指标（主瓣、3dB 波束宽度、峰值旁瓣电平）、MRT 增益、ZF 用户间残余干扰。
口径：
    ULA 阵列因子 AF(θ)=Σ exp(j·2π·d·n·(sinθ−sinθ0))；理想阵列增益上界 = 10log10(N)。
    MRT：w=h*/‖h‖，阵列增益 = ‖h‖^2 / (‖h‖^2/N) 关系；报相对单阵元的增益 dB。
    ZF：W=Hᴴ(HHᴴ)⁻¹，报预编码后各用户残余干扰（对角占优程度）。
单位：角度 度、增益/电平 dB、间距 波长（无量纲）。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def parse_complex_vec(i_raw, q_raw) -> np.ndarray:
    i = np.asarray(i_raw, dtype=float)
    q = np.asarray(q_raw, dtype=float)
    return i + 1j * q


def parse_complex_matrix(raw) -> np.ndarray:
    """raw: [[[re,im],...],...] 行=用户、列=阵元。"""
    arr = np.asarray(raw, dtype=float)  # (K, N, 2)
    return arr[..., 0] + 1j * arr[..., 1]


def ula_pattern(n, d, steer_deg):
    """均匀线阵方向图：返回 (角度网格 deg, 归一化功率方向图 dB)。"""
    theta = np.linspace(-90.0, 90.0, 721)  # 0.25° 步进
    theta_rad = np.radians(theta)
    steer_rad = math.radians(steer_deg)
    # 相位加权指向 steer：w_n = exp(-j·2π·d·n·sin(steer))
    n_idx = np.arange(n)
    steer_phase = np.exp(-1j * 2 * np.pi * d * n_idx * math.sin(steer_rad))
    af = np.zeros(theta.size, dtype=complex)
    for k, th in enumerate(theta_rad):
        sv = np.exp(1j * 2 * np.pi * d * n_idx * math.sin(th))  # 导向矢量
        af[k] = np.sum(steer_phase * sv)
    power = np.abs(af) ** 2
    power_db = 10.0 * np.log10(power / power.max() + 1e-300)
    return theta, power_db


def beamwidth_3db(theta, power_db, peak_idx):
    """从峰值向两侧找 -3dB 点，返回 3dB 波束宽度（度）。"""
    left = peak_idx
    while left > 0 and power_db[left] > -3.0:
        left -= 1
    right = peak_idx
    while right < power_db.size - 1 and power_db[right] > -3.0:
        right += 1
    return theta[right] - theta[left]


def peak_sidelobe_db(theta, power_db, peak_idx):
    """峰值旁瓣电平（相对主瓣，dB）：排除主瓣主峰邻域后的最大值。"""
    # 找主瓣两侧第一个零陷/极小，之外为旁瓣区
    left = peak_idx
    while left > 0 and power_db[left - 1] < power_db[left]:
        left -= 1
    right = peak_idx
    while right < power_db.size - 1 and power_db[right + 1] < power_db[right]:
        right += 1
    mask = np.ones(power_db.size, dtype=bool)
    mask[left:right + 1] = False
    if not mask.any():
        return float("-inf")
    return float(power_db[mask].max())


def main() -> None:
    payload = load_payload()
    mode = payload.get("mode", "pattern")
    if mode not in ("pattern", "mrt", "zf"):
        print("错误：mode 只能是 pattern | mrt | zf。")
        return

    if mode == "pattern":
        n = int(payload.get("num_elements", 8))
        d = float(payload.get("spacing_wavelength", 0.5))
        steer = float(payload.get("steer_deg", 0.0))
        if n < 2:
            print("错误：num_elements 至少为 2。")
            return
        if d <= 0:
            print("错误：spacing_wavelength 必须为正数（半波长 0.5 常用）。")
            return
        theta, power_db = ula_pattern(n, d, steer)
        peak_idx = int(np.argmax(power_db))
        bw = beamwidth_3db(theta, power_db, peak_idx)
        psl = peak_sidelobe_db(theta, power_db, peak_idx)
        array_gain = 10.0 * math.log10(n)
        print("=== 均匀线阵（ULA）波束方向图 ===")
        print(f"阵元数 N     : {n}，间距 {d:.3g} 波长")
        print(f"波束指向     : {steer:+.1f}°（相对阵列法线）")
        print(f"实际主瓣峰值 : {theta[peak_idx]:+.1f}°")
        print(f"理想阵列增益 : {array_gain:.2f} dB（10log10(N)，相干合并上界）")
        print(f"3dB 波束宽度 : {bw:.2f}°")
        print(f"峰值旁瓣电平 : {psl:.2f} dB（相对主瓣；半波长均匀加权约 -13.2 dB）")
        if d > 0.5 and abs(steer) > 1e-6:
            print("提示         : 间距 >0.5 波长且波束扫描偏离法线时可能出现栅瓣（grating lobe），核对方向图。")
        print("解读：阵元越多主瓣越窄、增益越高（massive MIMO 靠此聚焦能量）；"
              "旁瓣电平靠幅度加权（如 Taylor/Chebyshev）压低，会略微展宽主瓣。")

    elif mode == "mrt":
        h = parse_complex_vec(payload.get("channel_i", []), payload.get("channel_q", []))
        if h.size < 2:
            print("错误：mrt 需要 channel_i/channel_q（下行信道向量，长度=阵元数≥2）。")
            return
        n = h.size
        norm2 = float(np.sum(np.abs(h) ** 2))
        # MRT：w=h*/‖h‖，接收 SNR 正比 ‖h‖^2；相对单阵元平均增益 = ‖h‖^2/(‖h‖^2/N)=N（理想同增益时）
        avg_elem_gain = norm2 / n
        mrt_gain_db = 10.0 * math.log10(norm2 / avg_elem_gain) if avg_elem_gain > 0 else float("-inf")
        ideal_db = 10.0 * math.log10(n)
        print("=== 最大比发射（MRT）单用户波束成形 ===")
        print(f"阵元数 N     : {n}")
        print(f"信道范数 ‖h‖²: {norm2:.4g}")
        print(f"MRT 阵列增益 : {mrt_gain_db:.2f} dB（相对平均单阵元）")
        print(f"理想上界     : {ideal_db:.2f} dB（10log10(N)，各阵元等增益时达到）")
        print("解读：MRT 令各阵元信号在接收端同相相加，阵列增益随 N 线性增长（dB 域 10log10(N)）；"
              "信道各阵元增益不均时实际增益略低于理想上界。")

    else:  # zf 多用户预编码
        cm = payload.get("channel_matrix")
        if not cm:
            print("错误：zf 需要 channel_matrix（复信道矩阵，行=用户、列=阵元，元素 [re,im]）。")
            return
        try:
            H = parse_complex_matrix(cm)
        except (ValueError, IndexError):
            print("错误：channel_matrix 格式应为 [[[re,im],...],...]（行=用户、列=阵元）。")
            return
        if H.ndim != 2:
            print("错误：channel_matrix 必须是二维（K 用户 × N 阵元）。")
            return
        K, N = H.shape
        if N < K:
            print(f"错误：阵元数 N={N} 需 ≥ 用户数 K={K}（否则无法迫零解耦）。")
            return
        # ZF 预编码：W = Hᴴ(HHᴴ)⁻¹（列归一化后各用户等发射功率）
        HHh = H @ H.conj().T
        try:
            W = H.conj().T @ np.linalg.inv(HHh)
        except np.linalg.LinAlgError:
            print("错误：HHᴴ 奇异（用户信道线性相关），无法迫零；检查信道矩阵。")
            return
        # 列归一化
        W = W / np.linalg.norm(W, axis=0, keepdims=True)
        eff = H @ W  # 有效信道：理想 ZF 对角为增益、非对角≈0
        diag = np.abs(np.diag(eff))
        off = np.abs(eff) - np.diag(diag)
        max_leak = float(np.max(np.abs(off)))
        min_signal = float(np.min(diag))
        sir_db = 20.0 * math.log10(min_signal / max_leak) if max_leak > 1e-12 else float("inf")
        cond = float(np.linalg.cond(HHh))
        print("=== 多用户迫零（ZF）预编码 ===")
        print(f"用户数 K     : {K}，阵元数 N : {N}")
        print(f"有效信道对角 : {' '.join(f'{v:.3f}' for v in diag)}（各用户接收信号幅度）")
        print(f"最大用户间泄漏: {max_leak:.3e}（非对角元；ZF 理想应≈0）")
        print(f"最小信干比   : {sir_db:.1f} dB" + ("（完美解耦）" if math.isinf(sir_db) else "（用户间残余干扰）"))
        print(f"HHᴴ 条件数   : {cond:.2f}（越大信道越病态、预编码功率代价越高）")
        print("解读：ZF 预编码在发射端预抵消多用户干扰，用户信道正交时代价小；"
              "信道相关（条件数大）时迫零放大发射功率，此时 MMSE/正则化 ZF 更稳。")


if __name__ == "__main__":
    main()

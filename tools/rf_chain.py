"""接收链噪声与灵敏度计算（被 rf_chain 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    mode: "cascade" | "sensitivity" | "noise_floor"
    cascade    需 stages=[{name?, gain_db, nf_db}, ...]
    noise_floor 需 bandwidth_hz；可选 temperature_k（默认 290）
    sensitivity 需 bandwidth_hz + required_snr_db + (nf_db 或 stages)
输出：文本报告。
单位：增益/NF/SNR dB，功率 dBm，带宽 Hz，温度 K。

公式：
    Friis 级联：F = F1 + (F2-1)/G1 + (F3-1)/(G1·G2) + ...（线性值）
    噪声底：N(dBm) = 10·log10(k·T·1000) + 10·log10(B)（290 K 时约 -174 dBm/Hz + 10log10(B)）
    灵敏度：S(dBm) = 噪声底 + NF + 所需SNR
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOLTZMANN = 1.380649e-23  # J/K


def cascade_nf(stages):
    """Friis 级联：返回 (总增益 dB, 总 NF dB, 各级贡献列表[线性 F 增量])。"""
    total_gain_lin = 1.0
    total_f = 0.0
    contribs = []
    for idx, st in enumerate(stages):
        f_lin = 10 ** (float(st["nf_db"]) / 10.0)
        g_lin = 10 ** (float(st["gain_db"]) / 10.0)
        delta = f_lin if idx == 0 else (f_lin - 1.0) / total_gain_lin
        total_f += delta
        contribs.append(delta)
        total_gain_lin *= g_lin
    return 10.0 * math.log10(total_gain_lin), 10.0 * math.log10(total_f), total_f, contribs


def noise_floor_dbm(bandwidth_hz, temperature_k):
    return 10.0 * math.log10(BOLTZMANN * temperature_k * 1000.0) + 10.0 * math.log10(bandwidth_hz)


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    mode = payload.get("mode", "cascade")
    temperature_k = float(payload.get("temperature_k", 290.0))
    if temperature_k <= 0:
        print("错误：temperature_k 必须为正数（单位 K）。")
        return

    if mode == "cascade":
        stages = payload.get("stages")
        if not stages:
            print("错误：cascade 模式需要非空 stages 列表（每级 gain_db + nf_db）。")
            return
        gain_db, nf_db, total_f, contribs = cascade_nf(stages)
        print("接收链 Friis 级联分析")
        print(f"级数           = {len(stages)}")
        for idx, (st, delta) in enumerate(zip(stages, contribs), 1):
            name = st.get("name", f"级{idx}")
            pct = 100.0 * delta / total_f
            print(f"  [{idx}] {name}: 增益 {float(st['gain_db']):.2f} dB, NF {float(st['nf_db']):.2f} dB, 对总噪声系数贡献 {pct:.1f}%")
        print(f"总增益         = {gain_db:.2f} dB")
        print(f"总噪声系数 NF  = {nf_db:.2f} dB")
        print("提示：第一级（LNA）的增益与 NF 主导整链噪声性能（Friis 公式）。")
        return

    bandwidth_hz = float(payload.get("bandwidth_hz", 0))
    if bandwidth_hz <= 0:
        print(f"错误：{mode} 模式需要正数 bandwidth_hz（单位 Hz）。")
        return
    floor = noise_floor_dbm(bandwidth_hz, temperature_k)

    if mode == "noise_floor":
        print("热噪声底计算")
        print(f"温度           = {temperature_k:.1f} K")
        print(f"带宽           = {bandwidth_hz:.6g} Hz")
        print(f"噪声谱密度     = {10.0 * math.log10(BOLTZMANN * temperature_k * 1000.0):.2f} dBm/Hz")
        print(f"噪声底         = {floor:.2f} dBm")
        return

    if mode == "sensitivity":
        required_snr_db = payload.get("required_snr_db")
        if required_snr_db is None:
            print("错误：sensitivity 模式需要 required_snr_db（解调所需 SNR，dB）。")
            return
        required_snr_db = float(required_snr_db)
        if payload.get("stages"):
            _, nf_db, _, _ = cascade_nf(payload["stages"])
            nf_src = f"由 {len(payload['stages'])} 级 Friis 级联算得"
        elif payload.get("nf_db") is not None:
            nf_db = float(payload["nf_db"])
            nf_src = "直接给定"
        else:
            print("错误：sensitivity 模式需要 nf_db 或 stages 提供接收机噪声系数。")
            return
        sensitivity = floor + nf_db + required_snr_db
        print("接收灵敏度计算")
        print(f"噪声底         = {floor:.2f} dBm  (T={temperature_k:.0f} K, B={bandwidth_hz:.6g} Hz)")
        print(f"噪声系数 NF    = {nf_db:.2f} dB  ({nf_src})")
        print(f"所需 SNR       = {required_snr_db:.2f} dB")
        print(f"接收灵敏度     = {sensitivity:.2f} dBm")
        return

    print("错误：mode 必须为 cascade / sensitivity / noise_floor。")


if __name__ == "__main__":
    main()

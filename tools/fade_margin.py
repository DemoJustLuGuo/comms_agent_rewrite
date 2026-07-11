"""衰落余量与雨衰估算（被 fade_margin 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    mode: "margin" | "rain"
    margin 需 rx_power_dbm + sensitivity_dbm；可选 required_margin_db
    rain   需 freq_ghz(1~40) + distance_km + rain_rate_mm_h；可选 polarization=h|v（默认 h）
输出：文本报告。

雨衰模型口径（近似，必须向用户说明）：
    比衰减 γ = k·R^α dB/km —— ITU-R P.838-3 系数，内置 1~40 GHz 常用频点表，
    对数频率内插；有效路径 d_eff = d·r，r = 1/(1 + d/d0)，d0 = 35·e^(-0.015R)
    （ITU-R P.530 地面视距链路缩减因子，R≤100 mm/h 口径）。
    适用：地面视距链路的工程估算，误差量级 ±20~30%；倾斜路径/卫星链路
    （ITU-R P.618，需雨顶高度与仰角）不适用本工具。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ITU-R P.838-3 雨衰系数（频率 GHz → (kH, αH, kV, αV)），常用频点摘录
P838 = [
    (1.0, 0.0000259, 0.9691, 0.0000308, 0.8592),
    (2.0, 0.0000847, 1.0664, 0.0000998, 0.9490),
    (4.0, 0.0001071, 1.6009, 0.0002461, 1.4272),
    (6.0, 0.0007056, 1.5900, 0.0004878, 1.5728),
    (8.0, 0.004115, 1.3905, 0.003450, 1.3797),
    (10.0, 0.01217, 1.2571, 0.01129, 1.2156),
    (12.0, 0.02386, 1.1825, 0.02455, 1.1216),
    (15.0, 0.04481, 1.1233, 0.05008, 1.0440),
    (20.0, 0.09164, 1.0568, 0.09611, 0.9847),
    (25.0, 0.1571, 0.9991, 0.1533, 0.9491),
    (30.0, 0.2403, 0.9485, 0.2291, 0.9129),
    (40.0, 0.4431, 0.8673, 0.4274, 0.8421),
]


def p838_coeffs(freq_ghz: float, polarization: str):
    """对数频率内插 P.838 系数：log(k) 线性、α 线性（对 log f）。"""
    ki, ai = (1, 2) if polarization == "h" else (3, 4)
    if freq_ghz <= P838[0][0]:
        row = P838[0]
        return row[ki], row[ai]
    if freq_ghz >= P838[-1][0]:
        row = P838[-1]
        return row[ki], row[ai]
    for lo, hi in zip(P838, P838[1:]):
        if lo[0] <= freq_ghz <= hi[0]:
            t = (math.log10(freq_ghz) - math.log10(lo[0])) / (math.log10(hi[0]) - math.log10(lo[0]))
            k = 10 ** (math.log10(lo[ki]) + t * (math.log10(hi[ki]) - math.log10(lo[ki])))
            a = lo[ai] + t * (hi[ai] - lo[ai])
            return k, a
    raise AssertionError("unreachable")


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    mode = payload.get("mode", "margin")

    if mode == "margin":
        rx = float(payload["rx_power_dbm"])
        sens = float(payload["sensitivity_dbm"])
        margin = rx - sens
        print("衰落余量计算")
        print(f"接收电平       = {rx:.2f} dBm")
        print(f"接收灵敏度     = {sens:.2f} dBm（可由 rf_chain sensitivity 模式算得）")
        print(f"衰落余量       = {margin:.2f} dB")
        if payload.get("required_margin_db") is not None:
            req = float(payload["required_margin_db"])
            verdict = "满足" if margin >= req else "不满足"
            print(f"所需余量       = {req:.2f} dB → {verdict}（差 {margin - req:+.2f} dB）")
        return

    if mode == "rain":
        freq_ghz = float(payload["freq_ghz"])
        distance_km = float(payload["distance_km"])
        rain_rate = float(payload["rain_rate_mm_h"])
        polarization = payload.get("polarization", "h")
        if polarization not in ("h", "v"):
            print("错误：polarization 必须为 h（水平）或 v（垂直）。")
            return
        if not (1.0 <= freq_ghz <= 40.0):
            print("错误：freq_ghz 须在 1~40 GHz（内置 P.838 系数表范围）。")
            return
        if distance_km <= 0 or rain_rate <= 0:
            print("错误：distance_km 与 rain_rate_mm_h 必须为正数。")
            return
        if rain_rate > 100:
            print("错误：rain_rate_mm_h 超出缩减因子适用口径（≤100 mm/h）。")
            return
        k, alpha = p838_coeffs(freq_ghz, polarization)
        gamma = k * rain_rate ** alpha  # dB/km
        d0 = 35.0 * math.exp(-0.015 * rain_rate)
        r = 1.0 / (1.0 + distance_km / d0)
        d_eff = distance_km * r
        atten = gamma * d_eff
        print("雨衰估算（ITU-R P.838-3 + P.530 缩减因子，地面视距链路近似）")
        print(f"频率           = {freq_ghz:.6g} GHz，极化 = {'水平' if polarization == 'h' else '垂直'}")
        print(f"降雨率 R       = {rain_rate:.6g} mm/h")
        print(f"比衰减 γ       = {gamma:.3f} dB/km  (k={k:.4g}, α={alpha:.4f})")
        print(f"有效路径       = {d_eff:.2f} km  (实际 {distance_km:.6g} km × 缩减因子 {r:.3f})")
        print(f"雨衰 A         = {atten:.2f} dB")
        print("注意：本结果为工程估算（误差量级 ±20~30%），卫星/倾斜路径不适用；链路预算应预留该量级余量。")
        return

    print("错误：mode 必须为 margin 或 rain。")


if __name__ == "__main__":
    main()

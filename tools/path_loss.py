"""无线传播路径损耗模型（被 path_loss 工具调用）。

补 link_budget 只算自由空间 FSPL 的空白：提供带环境修正的实际传播模型。

输入：argv[1] 为 JSON 字符串（也兼容 stdin），字段：
    model: str          — "log_distance" | "hata" | "cost231"
    freq_mhz: float     — 载频，MHz
    distance_km: float  — 收发距离，km
    # log_distance 专用：
    path_loss_exponent: float — 路径损耗指数 n（自由空间 2.0；市区 2.7~3.5；室内 4~6），默认 2.0
    ref_distance_m: float     — 参考距离 d0，m，默认 1000（参考点损耗按该处 FSPL 计算）
    # hata / cost231 专用：
    bs_height_m: float  — 基站天线高度 hb，m，默认 30
    ms_height_m: float  — 移动台天线高度 hm，m，默认 1.5
    area: str           — hata: "urban"|"suburban"|"rural"；cost231: "urban"|"metropolitan"，默认 urban
输出：路径损耗文本报告（dB）+ 适用范围提示。
单位：损耗 dB，频率 MHz，距离 km，天线高度 m。

参考：Okumura-Hata（150–1500 MHz）、COST-231-Hata（1500–2000 MHz）经验模型。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def fspl_at_m(distance_m: float, freq_mhz: float) -> float:
    """自由空间路径损耗，d 单位 m、f 单位 MHz。FSPL = 20log10(d_m)+20log10(f)-27.55。"""
    return 20.0 * math.log10(distance_m) + 20.0 * math.log10(freq_mhz) - 27.55


def hata_mobile_correction(freq_mhz: float, ms_height_m: float, metropolitan: bool) -> float:
    """Hata 移动台天线高度修正 a(hm)，dB。"""
    if metropolitan:
        if freq_mhz >= 300:
            return 3.2 * (math.log10(11.75 * ms_height_m)) ** 2 - 4.97
        return 8.29 * (math.log10(1.54 * ms_height_m)) ** 2 - 1.1
    # 中小城市
    return (1.1 * math.log10(freq_mhz) - 0.7) * ms_height_m - (1.56 * math.log10(freq_mhz) - 0.8)


def hata_urban_db(freq_mhz, distance_km, hb, hm, metropolitan):
    a_hm = hata_mobile_correction(freq_mhz, hm, metropolitan)
    return (69.55 + 26.16 * math.log10(freq_mhz) - 13.82 * math.log10(hb) - a_hm
            + (44.9 - 6.55 * math.log10(hb)) * math.log10(distance_km))


def cost231_urban_db(freq_mhz, distance_km, hb, hm, metropolitan):
    a_hm = hata_mobile_correction(freq_mhz, hm, metropolitan)
    cm = 3.0 if metropolitan else 0.0
    return (46.3 + 33.9 * math.log10(freq_mhz) - 13.82 * math.log10(hb) - a_hm
            + (44.9 - 6.55 * math.log10(hb)) * math.log10(distance_km) + cm)


def main() -> None:
    payload = load_payload()
    model = payload.get("model", "log_distance")
    freq_mhz = float(payload["freq_mhz"])
    distance_km = float(payload["distance_km"])

    if freq_mhz <= 0 or distance_km <= 0:
        print("错误：freq_mhz 与 distance_km 必须为正数。")
        return

    notes = []

    if model == "log_distance":
        n = float(payload.get("path_loss_exponent", 2.0))
        d0_m = float(payload.get("ref_distance_m", 1000.0))
        d_m = distance_km * 1000.0
        if d0_m <= 0 or d_m < d0_m:
            print("错误：ref_distance_m 必须为正，且距离需不小于参考距离 d0。")
            return
        pl_d0 = fspl_at_m(d0_m, freq_mhz)
        loss_db = pl_d0 + 10.0 * n * math.log10(d_m / d0_m)
        print("=== 路径损耗（对数距离模型）===")
        print(f"模型         : log-distance, n = {n}")
        print(f"频率         : {freq_mhz:.1f} MHz")
        print(f"参考距离 d0  : {d0_m:.0f} m, 参考损耗 PL(d0) = {pl_d0:.2f} dB (自由空间)")
        print(f"距离         : {distance_km} km")
        print(f"路径损耗 PL  : {loss_db:.2f} dB")
        return

    # Hata / COST-231 系列
    hb = float(payload.get("bs_height_m", 30.0))
    hm = float(payload.get("ms_height_m", 1.5))
    area = payload.get("area", "urban")

    if model == "hata":
        if not (150 <= freq_mhz <= 1500):
            notes.append(f"频率 {freq_mhz:.0f} MHz 超出 Okumura-Hata 适用范围 150–1500 MHz，结果仅供参考。")
        if not (1 <= distance_km <= 20):
            notes.append(f"距离 {distance_km} km 超出典型适用范围 1–20 km。")
        metropolitan = area == "metropolitan"
        urban = hata_urban_db(freq_mhz, distance_km, hb, hm, metropolitan)
        if area in ("urban", "metropolitan"):
            loss_db = urban
        elif area == "suburban":
            loss_db = urban - 2.0 * (math.log10(freq_mhz / 28.0)) ** 2 - 5.4
        elif area == "rural":
            loss_db = urban - 4.78 * (math.log10(freq_mhz)) ** 2 + 18.33 * math.log10(freq_mhz) - 40.94
        else:
            print(f"错误：hata 模型 area 需为 urban/suburban/rural/metropolitan，收到 {area}。")
            return
        title = "Okumura-Hata"
    elif model == "cost231":
        if not (1500 <= freq_mhz <= 2000):
            notes.append(f"频率 {freq_mhz:.0f} MHz 超出 COST-231-Hata 适用范围 1500–2000 MHz，结果仅供参考。")
        if area not in ("urban", "metropolitan"):
            print(f"错误：cost231 模型 area 需为 urban/metropolitan，收到 {area}。")
            return
        metropolitan = area == "metropolitan"
        loss_db = cost231_urban_db(freq_mhz, distance_km, hb, hm, metropolitan)
        title = "COST-231-Hata"
    else:
        print(f"错误：未知 model {model}，需为 log_distance/hata/cost231。")
        return

    print(f"=== 路径损耗（{title}）===")
    print(f"频率         : {freq_mhz:.1f} MHz")
    print(f"基站高度 hb  : {hb:.1f} m")
    print(f"移动台高 hm  : {hm:.1f} m")
    print(f"区域         : {area}")
    print(f"距离         : {distance_km} km")
    print(f"路径损耗 PL  : {loss_db:.2f} dB")
    for note in notes:
        print(f"提示         : {note}")


if __name__ == "__main__":
    main()

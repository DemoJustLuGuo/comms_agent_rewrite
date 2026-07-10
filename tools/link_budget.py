"""自由空间链路预算计算（被 link_budget 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    tx_power_dbm, tx_gain_dbi, rx_gain_dbi, freq_mhz, distance_km, other_losses_db?
输出：链路预算文本报告（EIRP / FSPL / 接收功率）。
单位：功率 dBm、增益 dBi、频率 MHz、距离 km、损耗 dB。
"""
import json
import math
import sys

# Windows 管道场景下强制 UTF-8 输出，避免中文标签变成乱码（GBK）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fspl_db(distance_km: float, freq_mhz: float) -> float:
    """自由空间路径损耗 FSPL，单位 dB。d 单位 km，f 单位 MHz。

    FSPL(dB) = 20*log10(d_km) + 20*log10(f_MHz) + 32.44
    """
    return 20.0 * math.log10(distance_km) + 20.0 * math.log10(freq_mhz) + 32.44


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    distance_km = float(payload["distance_km"])
    freq_mhz = float(payload["freq_mhz"])
    if distance_km <= 0 or freq_mhz <= 0:
        print("错误：distance_km 与 freq_mhz 必须为正数。")
        return

    tx_power_dbm = float(payload["tx_power_dbm"])
    tx_gain_dbi = float(payload["tx_gain_dbi"])
    rx_gain_dbi = float(payload["rx_gain_dbi"])
    other_losses_db = float(payload.get("other_losses_db", 0.0))

    loss_db = fspl_db(distance_km, freq_mhz)
    eirp_dbm = tx_power_dbm + tx_gain_dbi
    rx_power_dbm = eirp_dbm + rx_gain_dbi - loss_db - other_losses_db

    print(f"EIRP         = {eirp_dbm:.2f} dBm")
    print(f"FSPL         = {loss_db:.2f} dB  (d={distance_km} km, f={freq_mhz} MHz)")
    print(f"其他损耗      = {other_losses_db:.2f} dB")
    print(f"接收功率 Prx  = {rx_power_dbm:.2f} dBm")


if __name__ == "__main__":
    main()

"""载干比与 SINR 计算（被 interference 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    mode: "ci" | "sinr"
    carrier_dbm: 载波接收功率，dBm
    interferers: [{power_dbm, name?}, ...] 各干扰源接收功率
    sinr 模式的噪声二选一：noise_floor_dbm 直接给；或 bandwidth_hz(+nf_db, temperature_k=290) 由 kTB 算
    required_ci_db?: 解调所需 C/I（或 SINR）门限，给了则输出余量结论
输出：文本报告。功率一律 dBm，比值 dB；功率叠加在线性域（mW）完成。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOLTZMANN = 1.380649e-23  # J/K


def dbm_to_mw(dbm: float) -> float:
    return 10 ** (dbm / 10.0)


def mw_to_dbm(mw: float) -> float:
    return 10.0 * math.log10(mw)


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    mode = payload.get("mode", "ci")
    if mode not in ("ci", "sinr"):
        print("错误：mode 必须为 ci 或 sinr。")
        return

    carrier_dbm = float(payload["carrier_dbm"])
    interferers = payload.get("interferers", [])
    if not interferers:
        print("错误：interferers 不能为空（每项含 power_dbm，单位 dBm）。")
        return

    i_total_mw = 0.0
    print("干扰分析（功率在线性域 mW 叠加）")
    print(f"载波功率 C     = {carrier_dbm:.2f} dBm")
    for idx, itf in enumerate(interferers, 1):
        p = float(itf["power_dbm"])
        i_total_mw += dbm_to_mw(p)
        print(f"  干扰[{idx}] {itf.get('name', '')}: {p:.2f} dBm".rstrip())
    i_total_dbm = mw_to_dbm(i_total_mw)
    print(f"干扰合计 I     = {i_total_dbm:.2f} dBm")

    if mode == "ci":
        ratio_db = carrier_dbm - i_total_dbm
        label = "C/I"
    else:
        if payload.get("noise_floor_dbm") is not None:
            n_dbm = float(payload["noise_floor_dbm"])
            n_src = "直接给定"
        elif payload.get("bandwidth_hz"):
            temperature_k = float(payload.get("temperature_k", 290.0))
            nf_db = float(payload.get("nf_db", 0.0))
            n_dbm = 10.0 * math.log10(BOLTZMANN * temperature_k * 1000.0) + 10.0 * math.log10(float(payload["bandwidth_hz"])) + nf_db
            n_src = f"kTB+NF (T={temperature_k:.0f} K, NF={nf_db:.1f} dB)"
        else:
            print("错误：sinr 模式需要 noise_floor_dbm，或 bandwidth_hz(+nf_db) 由 kTB 计算噪声。")
            return
        print(f"噪声功率 N     = {n_dbm:.2f} dBm  ({n_src})")
        ratio_db = carrier_dbm - mw_to_dbm(i_total_mw + dbm_to_mw(n_dbm))
        label = "SINR"

    print(f"{label}            = {ratio_db:.2f} dB")
    if payload.get("required_ci_db") is not None:
        req = float(payload["required_ci_db"])
        margin = ratio_db - req
        verdict = "满足" if margin >= 0 else "不满足"
        print(f"所需门限       = {req:.2f} dB")
        print(f"余量           = {margin:.2f} dB（{verdict}）")
    if payload.get("__comms_structured"):
        print("COMMS_RESULT_JSON=" + json.dumps({
            "data": {"ratio_db": ratio_db, "interference_dbm": i_total_dbm},
            "units": {"ratio_db": "dB", "interference_dbm": "dBm"},
        }, allow_nan=False))


if __name__ == "__main__":
    main()

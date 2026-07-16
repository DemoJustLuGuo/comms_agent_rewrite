"""扩频通信（被 spread_spectrum 工具调用）：DSSS/FHSS 处理增益与抗干扰余量。

回答 GPS/CDMA/抗干扰场景的"处理增益多少 dB、能扛多强干扰、扩频后带宽"这类问题
（knowledge/ 已提扩频增益概念，此前无算子）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    mode: str              — gain | jam | despread
    # gain：处理增益与带宽扩展
    chip_rate_hz: float?   — 码片速率 Rc，Hz（DSSS）
    data_rate_hz: float?   — 信息速率 Rb，Hz
    spread_factor: float?  — 直接给扩频因子（与 chip/data 速率二选一）
    hops: int?             — FHSS 跳频点数（给了则按 FHSS 处理增益 = 10log10(hops)）
    # jam：抗干扰余量（需 gain 参数 + 下列）
    required_ebn0_db: float?— 解调所需 Eb/N0，dB，默认 10
    jammer_to_signal_db: float?— 干信比 J/S，dB
    # despread：数值演示（小规模）
    data_bits: list[float]?— 0/1 信息比特（despread 模式）
    code: list[float]?     — ±1 扩频码（长度=扩频因子）
    jammer_amp: float?     — 单音干扰幅度（despread 演示用），默认 0

输出：处理增益、扩频带宽、抗干扰余量 / 解扩演示 文本报告。
口径：DSSS 处理增益 Gp = 10log10(Rc/Rb) = 10log10(扩频因子)；
      FHSS 处理增益 = 10log10(跳频点数)；
      抗干扰余量 M_j = Gp − (Eb/N0)_req − 损耗（此处损耗忽略，工程需另计）。
单位：速率 Hz、增益/余量 dB、幅度无量纲。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def resolve_gain(payload: dict):
    """返回 (Gp_db, 描述, 扩频因子 或 None, 是否 FHSS)。参数不足时返回 (None, 原因, ..)。"""
    hops = payload.get("hops")
    if hops is not None:
        hops = int(hops)
        if hops < 2:
            return None, "hops 至少为 2（跳频点数）。", None, True
        return 10.0 * math.log10(hops), f"FHSS 跳频点数 {hops}", float(hops), True
    sf = payload.get("spread_factor")
    if sf is None:
        rc = payload.get("chip_rate_hz")
        rb = payload.get("data_rate_hz")
        if rc is None or rb is None:
            return None, "需要 spread_factor，或 chip_rate_hz + data_rate_hz（DSSS），或 hops（FHSS）。", None, False
        rc, rb = float(rc), float(rb)
        if rc <= 0 or rb <= 0:
            return None, "chip_rate_hz / data_rate_hz 必须为正数。", None, False
        sf = rc / rb
    else:
        sf = float(sf)
    if sf <= 1:
        return None, "扩频因子必须 >1（否则未扩频）。", None, False
    return 10.0 * math.log10(sf), f"DSSS 扩频因子 {sf:.1f}", sf, False


def main() -> None:
    payload = load_payload()
    mode = payload.get("mode", "gain")
    if mode not in ("gain", "jam", "despread"):
        print("错误：mode 只能是 gain | jam | despread。")
        return

    if mode in ("gain", "jam"):
        gp_db, desc, sf, is_fhss = resolve_gain(payload)
        if gp_db is None:
            print(f"错误：{desc}")
            return
        print(f"=== 扩频{'（FHSS）' if is_fhss else '（DSSS）'}处理增益 ===")
        print(f"扩频配置     : {desc}")
        print(f"处理增益 Gp  : {gp_db:.2f} dB（{'10log10(跳数)' if is_fhss else '10log10(Rc/Rb)'}）")
        if not is_fhss:
            rc = payload.get("chip_rate_hz")
            if rc:
                print(f"扩频带宽     : ≈ {float(rc):.6g} Hz（主瓣 ≈ 2·Rc，零到零）")
        if mode == "jam":
            req = float(payload.get("required_ebn0_db", 10.0))
            js = payload.get("jammer_to_signal_db")
            jam_margin = gp_db - req
            print(f"解调所需 Eb/N0: {req:.2f} dB")
            print(f"抗干扰余量 Mj: {jam_margin:.2f} dB（Gp − 所需Eb/N0；忽略实现损耗）")
            print(f"含义         : 干扰功率最多可比信号高 {jam_margin:.1f} dB 仍可解调（J/S 上限）")
            if js is not None:
                js = float(js)
                net = jam_margin - js
                verdict = "可对抗" if net >= 0 else "不足以对抗"
                print(f"实际干信比 J/S: {js:.2f} dB → 净余量 {net:+.2f} dB（{verdict}该干扰）")
        print("解读：处理增益把窄带干扰在解扩时摊薄到整个扩频带宽——GPS/CDMA 靠此在负 SNR 工作；"
              "FHSS 靠躲避而非压制，处理增益体现为被干扰的时间占比。")

    else:  # despread 数值演示
        data = payload.get("data_bits")
        code = payload.get("code")
        if not data or not code:
            print("错误：despread 模式需要 data_bits（0/1）与 code（±1 扩频码）。")
            return
        data = np.asarray(data, dtype=float)
        code = np.asarray(code, dtype=float)
        if code.size < 2:
            print("错误：code 长度至少 2（即扩频因子≥2）。")
            return
        if not np.all(np.isin(code, [-1.0, 1.0])):
            print("错误：code 必须是 ±1 序列。")
            return
        sf = code.size
        gp_db = 10.0 * math.log10(sf)
        bpsk = data * 2 - 1  # 0/1 → -1/+1
        # 扩频：每比特 × 整条码
        chips = np.outer(bpsk, code).reshape(-1)
        jammer_amp = float(payload.get("jammer_amp", 0.0))
        # 单音干扰（简化为常数偏置，解扩时被码调制成伪随机，能量摊开）
        jam = jammer_amp * np.ones_like(chips)
        rx = chips + jam
        # 解扩：逐比特与码相关后判决
        rx_blocks = rx.reshape(bpsk.size, sf)
        despread = (rx_blocks * code).sum(axis=1) / sf
        decided = (despread > 0).astype(int)
        errors = int(np.sum(decided != data.astype(int)))
        print("=== DSSS 解扩演示 ===")
        print(f"扩频因子     : {sf}（处理增益 {gp_db:.2f} dB）")
        print(f"信息比特     : {data.size}，码片总数 {chips.size}")
        print(f"单音干扰幅度 : {jammer_amp:.3g}（解扩前干信比 ≈ {20 * math.log10(jammer_amp) if jammer_amp > 0 else float('-inf'):.1f} dB）")
        print(f"解扩后误码   : {errors} / {data.size}")
        print(f"判决统计量   : {' '.join(f'{v:+.2f}' for v in despread[:16])}" + (" ..." if despread.size > 16 else ""))
        print("解读：常数/窄带干扰经解扩（乘伪随机码）后能量摊到整个带宽，判决统计量仍由信号主导——"
              "这正是处理增益的数值体现。")


if __name__ == "__main__":
    main()

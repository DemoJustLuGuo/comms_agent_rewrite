"""链路自适应 / AMC（被 link_adaptation 工具调用）：给定信道质量选最优 MCS。

回答"当前 SINR/Eb-N0 该选哪档调制+编码、能达到多少频谱效率"这类高频工程问题——
现在需要手工串 ber_snr + channel_coding + capacity，本工具把三者口径收敛为一次 MCS 选择。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    snr_db: float          — 可用信道质量（Es/N0 或 Eb/N0，见 snr_type），dB
    snr_type: str?         — es_n0（每符号，默认）| eb_n0（每比特）；内部统一折算
    target_ber: float?     — 目标（未编码）BER 门限，默认 1e-3
    coding_gain_db: float? — 若启用 FEC，统一编码增益 dB（默认 0=未编码；精确值用 channel_coding 仿真）
    margin_db: float?      — 选档保留的实现余量 dB，默认 1.0（避开门限边缘）
    bandwidth_hz: float?   — 给了则额外输出各档吞吐（bit/s）

输出：逐档 MCS（所需 SNR / 是否满足 / 频谱效率）+ 推荐档位 + 香农上界对比。
口径：所需 SNR 由各调制的理论 BER 反推（AWGN，Gray 编码近似，与 ber_snr 同源）；
      频谱效率 η = 每符号比特数 × 码率（bit/s/Hz，未计导频/CP 开销）；
      香农上界 C/B = log2(1+SNR_lin) 作为效率天花板参照。
单位：SNR/dB、频谱效率 bit/s/Hz、吞吐 bit/s、BER 无量纲。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ber_snr import BER_FUNCS, BITS_PER_SYMBOL  # noqa: E402

# MCS 阶梯：由低到高（调制, 码率）。码率仅用于频谱效率与 Eb/N0 折算；
# 编码增益经 coding_gain_db 统一给（未编码时码率取 1.0）。
_MCS_LADDER = [
    ("BPSK", 1.0),
    ("QPSK", 1.0),
    ("8PSK", 1.0),
    ("16QAM", 1.0),
    ("64QAM", 1.0),
    ("256QAM", 1.0),
]


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def required_ebn0_db(modulation: str, target_ber: float) -> float:
    """反推达到 target_ber 所需的 Eb/N0（dB），与 ber_snr 同源理论式。"""
    ber_func = BER_FUNCS[modulation]

    def objective(snr_db_val: float) -> float:
        return ber_func(10.0 ** (snr_db_val / 10.0)) - target_ber

    try:
        return brentq(objective, -10.0, 80.0, xtol=1e-4)
    except ValueError:
        return float("inf")


def main() -> None:
    payload = load_payload()
    snr_db = payload.get("snr_db")
    if snr_db is None:
        print("错误：需要 snr_db（可用信道质量，dB）。")
        return
    snr_db = float(snr_db)
    snr_type = payload.get("snr_type", "es_n0")
    if snr_type not in ("es_n0", "eb_n0"):
        print("错误：snr_type 只能是 es_n0 | eb_n0。")
        return
    target_ber = float(payload.get("target_ber", 1e-3))
    if not (0.0 < target_ber < 0.5):
        print("错误：target_ber 需在 (0, 0.5) 内。")
        return
    coding_gain_db = float(payload.get("coding_gain_db", 0.0))
    margin_db = float(payload.get("margin_db", 1.0))
    bandwidth_hz = payload.get("bandwidth_hz")

    snr_lin = 10.0 ** (snr_db / 10.0)
    shannon_eff = math.log2(1.0 + snr_lin)  # bit/s/Hz 上界

    print("=== 链路自适应 / MCS 选择（AWGN 理论口径）===")
    print(f"输入信道质量 : {snr_db:.2f} dB（{'Es/N0 每符号' if snr_type == 'es_n0' else 'Eb/N0 每比特'}）")
    print(f"目标 BER     : {target_ber:.0e}（未编码门限）")
    print(f"编码增益     : {coding_gain_db:.2f} dB（0=未编码；精确值用 channel_coding 仿真）")
    print(f"实现余量     : {margin_db:.2f} dB")
    print(f"香农效率上界 : {shannon_eff:.2f} bit/s/Hz（log2(1+SNR)，效率天花板）")
    print()
    header = f"{'MCS':>10} | {'k':>2} | {'码率':>5} | {'需Es/N0':>9} | {'余量':>7} | {'满足':>4} | {'η(bit/s/Hz)':>12}"
    print(header)

    best = None
    for modulation, rate in _MCS_LADDER:
        k = BITS_PER_SYMBOL[modulation]
        req_ebn0 = required_ebn0_db(modulation, target_ber) - coding_gain_db
        # 所需 Eb/N0 → 所需 Es/N0：Es/N0 = Eb/N0 × (k·rate)
        req_esn0 = req_ebn0 + 10.0 * math.log10(k * rate)
        # 把输入信道质量统一折算到 Es/N0 口径用于比较
        if snr_type == "eb_n0":
            avail_esn0 = snr_db + 10.0 * math.log10(k * rate)
        else:
            avail_esn0 = snr_db
        headroom = avail_esn0 - req_esn0
        ok = headroom >= margin_db
        eff = k * rate
        thr = ""
        mark = "✓" if ok else "✗"
        print(f"{modulation:>10} | {k:>2} | {rate:>5.2f} | {req_esn0:>7.2f}dB | {headroom:>+6.2f}dB | {mark:>4} | {eff:>12.2f}")
        if ok:
            best = (modulation, rate, eff, req_esn0, headroom)

    print()
    if best is None:
        print("推荐         : 当前信道质量不足以支撑最低档（含余量）——降低 target_ber 要求、"
              "启用/加强 FEC（提高 coding_gain_db）、或提升 SNR。")
    else:
        modulation, rate, eff, req_esn0, headroom = best
        print(f"推荐 MCS     : {modulation} @ 码率 {rate:.2f} → 频谱效率 {eff:.2f} bit/s/Hz")
        print(f"选档依据     : 满足目标 BER 且保留 {headroom:.2f} dB 余量（≥{margin_db:.2f} dB 门限）")
        print(f"效率利用率   : {eff / shannon_eff * 100:.1f}%（相对香农上界 {shannon_eff:.2f}）")
        if bandwidth_hz:
            bw = float(bandwidth_hz)
            print(f"估算吞吐     : {eff * bw:.4g} bit/s（η×B，未计导频/CP/协议开销）")
    print("说明：所需 SNR 为 AWGN 理论门限；实际系统含实现损耗、衰落与开销，"
          "现代制式带 FEC 门限更低——精确编码增益用 channel_coding 仿真，不要拍脑袋填 coding_gain_db。")


if __name__ == "__main__":
    main()

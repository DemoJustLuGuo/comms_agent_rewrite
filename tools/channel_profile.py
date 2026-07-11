"""无线信道特征判定：多普勒 / 相干时间 / 相干带宽（被 channel_profile 工具调用）。

输入：argv[1] 为 JSON 字符串，字段（按需给，至少给一组）：
    freq_mhz + speed_kmh   → 最大多普勒频移 fd、相干时间 Tc
    delay_spread_us        → 相干带宽 Bc（RMS 时延扩展）
    symbol_rate_sps?       → 结合 Tc/Bc 给出 快衰/慢衰、平坦/频选 判定
    signal_bandwidth_hz?   → 与 Bc 比较判平坦/频选（不给则用 symbol_rate 近似带宽）
输出：文本报告。
单位：频率 MHz/Hz、速度 km/h、时延 μs、时间 s。

公式（经验口径，工程判定用）：
    fd = v·f/c；Tc ≈ 0.423/fd（Clarke 模型）；Bc ≈ 1/(5·στ)（50% 相关带宽）
    Ts << Tc → 慢衰落；B << Bc（即 Ts >> στ）→ 平坦衰落
"""
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

C_LIGHT = 299_792_458.0  # m/s


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    freq_mhz = payload.get("freq_mhz")
    speed_kmh = payload.get("speed_kmh")
    delay_spread_us = payload.get("delay_spread_us")
    symbol_rate = payload.get("symbol_rate_sps")
    bandwidth_hz = payload.get("signal_bandwidth_hz")

    has_doppler = freq_mhz is not None and speed_kmh is not None
    has_delay = delay_spread_us is not None
    if not has_doppler and not has_delay:
        print("错误：至少提供 freq_mhz+speed_kmh（多普勒）或 delay_spread_us（时延扩展）其中一组。")
        return

    print("信道特征判定（经验口径：Tc≈0.423/fd，Bc≈1/(5στ)）")

    fd_hz = tc_s = None
    if has_doppler:
        freq_mhz = float(freq_mhz)
        speed_kmh = float(speed_kmh)
        if freq_mhz <= 0 or speed_kmh < 0:
            print("错误：freq_mhz 必须为正数，speed_kmh 不能为负。")
            return
        fd_hz = (speed_kmh / 3.6) * (freq_mhz * 1e6) / C_LIGHT
        print(f"载频           = {freq_mhz:.6g} MHz，速度 = {speed_kmh:.6g} km/h")
        if fd_hz == 0:
            print("最大多普勒频移 = 0 Hz（静止，Tc→∞，时间选择性可忽略）")
        else:
            tc_s = 0.423 / fd_hz
            print(f"最大多普勒频移 fd = {fd_hz:.2f} Hz")
            print(f"相干时间 Tc    = {tc_s * 1e3:.3f} ms")

    bc_hz = None
    if has_delay:
        delay_spread_us = float(delay_spread_us)
        if delay_spread_us <= 0:
            print("错误：delay_spread_us 必须为正数（RMS 时延扩展，μs）。")
            return
        bc_hz = 1.0 / (5.0 * delay_spread_us * 1e-6)
        print(f"RMS 时延扩展 στ = {delay_spread_us:.6g} μs")
        print(f"相干带宽 Bc    = {bc_hz / 1e3:.3f} kHz")

    if symbol_rate or bandwidth_hz:
        sig_bw = float(bandwidth_hz) if bandwidth_hz else float(symbol_rate)
        ts_s = 1.0 / float(symbol_rate) if symbol_rate else 1.0 / sig_bw
        print(f"信号带宽（近似）= {sig_bw:.6g} Hz，符号周期 Ts = {ts_s * 1e6:.3f} μs")
        if tc_s is not None:
            ratio = tc_s / ts_s
            kind = "慢衰落" if ratio > 10 else "快衰落"
            print(f"时间选择性     : Tc/Ts = {ratio:.1f} → {kind}（Tc/Ts>10 视为慢衰落）")
        if bc_hz is not None:
            ratio = bc_hz / sig_bw
            kind = "平坦衰落" if ratio > 10 else "频率选择性衰落"
            print(f"频率选择性     : Bc/B = {ratio:.2f} → {kind}（Bc/B>10 视为平坦；频选时考虑 OFDM/均衡）")
    elif tc_s is not None or bc_hz is not None:
        print("提示：给 symbol_rate_sps 或 signal_bandwidth_hz 可进一步输出 快衰/慢衰、平坦/频选 判定。")


if __name__ == "__main__":
    main()

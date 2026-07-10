"""数字调制（被 modulation 工具调用，并被 channel 工具复用）。

支持 BPSK / QPSK / 8PSK / 16QAM / 64QAM / 256QAM，Gray 编码，平均符号能量归一化为 1。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    mode: str        — constellation | modulate | evm
    modulation: str  — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM
    # modulate: bits:[0/1,...]
    # evm    : i:[...], q:[...]   （实测符号，按最近理想点算 EVM）
输出：星座点 / 已调符号 / EVM(%) 文本报告。
单位：I/Q 归一化幅度（无量纲），EVM 百分比。
"""
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np


BITS_PER_SYMBOL = {"BPSK": 1, "QPSK": 2, "8PSK": 3, "16QAM": 4, "64QAM": 6, "256QAM": 8}
_PSK_ORDER = {"BPSK": 2, "QPSK": 4, "8PSK": 8}
_QAM_ORDER = {"16QAM": 16, "64QAM": 64, "256QAM": 256}


def _gray(n: int) -> int:
    return n ^ (n >> 1)


def build_constellation(modulation: str):
    """返回 (constel, k)：constel[label] 为该比特标签对应的复符号，平均能量归一化为 1。"""
    mod = modulation.upper()
    if mod in _PSK_ORDER:
        m = _PSK_ORDER[mod]
        k = BITS_PER_SYMBOL[mod]
        constel = np.zeros(m, dtype=complex)
        for n in range(m):  # n 为自然相位序号，Gray 标签为 _gray(n)
            constel[_gray(n)] = np.exp(1j * 2.0 * math.pi * n / m)
        return constel, k  # PSK 单位圆，能量本就为 1

    if mod in _QAM_ORDER:
        m = _QAM_ORDER[mod]
        k = BITS_PER_SYMBOL[mod]
        side = int(round(math.sqrt(m)))       # 每轴电平数 L
        half = k // 2                          # 每轴比特数
        # 每轴 Gray 编码 PAM：位置序号 j 的比特标签为 _gray(j)，电平 = 2j-(L-1)
        axis_level_for_label = np.zeros(side)
        for j in range(side):
            axis_level_for_label[_gray(j)] = 2 * j - (side - 1)
        constel = np.zeros(m, dtype=complex)
        for label in range(m):
            i_bits = label >> half             # 高 half 位 → I
            q_bits = label & (side - 1)         # 低 half 位 → Q
            constel[label] = axis_level_for_label[i_bits] + 1j * axis_level_for_label[q_bits]
        # 归一化平均能量为 1
        constel /= math.sqrt(np.mean(np.abs(constel) ** 2))
        return constel, k

    raise ValueError(f"不支持的调制方式 '{modulation}'")


def modulate_bits(bits, modulation: str):
    """bits(0/1 列表) → 复符号数组；每 k 比特一符号，MSB 在前。"""
    constel, k = build_constellation(modulation)
    bits = np.asarray(bits, dtype=int)
    usable = (bits.size // k) * k
    bits = bits[:usable].reshape(-1, k)
    weights = (1 << np.arange(k - 1, -1, -1))
    labels = bits.dot(weights)
    return constel[labels], usable // k, bits.size


def demodulate_symbols(symbols, modulation: str):
    """复符号 → 最近理想点 → 比特(0/1 列表，MSB 在前)。"""
    constel, k = build_constellation(modulation)
    symbols = np.asarray(symbols, dtype=complex)
    dist = np.abs(symbols[:, None] - constel[None, :])
    labels = np.argmin(dist, axis=1)
    bits = ((labels[:, None] >> np.arange(k - 1, -1, -1)) & 1).reshape(-1)
    return bits


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def main() -> None:
    payload = load_payload()
    mode = payload.get("mode", "constellation")
    modulation = payload.get("modulation", "")

    try:
        constel, k = build_constellation(modulation)
    except ValueError as e:
        print(f"错误：{e}")
        return

    if mode == "constellation":
        print(f"=== {modulation} 理想星座（Gray 编码，能量归一化）===")
        print(f"每符号比特   : {k}")
        print(f"星座点数     : {constel.size}")
        for label in range(constel.size):
            bits = format(label, f"0{k}b")
            print(f"  {bits} : I={constel[label].real:+.4f}, Q={constel[label].imag:+.4f}")

    elif mode == "modulate":
        bits = payload.get("bits")
        if not bits:
            print("错误：modulate 模式需要 bits 字段（0/1 列表）。")
            return
        syms, n_sym, n_bits = modulate_bits(bits, modulation)
        dropped = n_bits - n_sym * k
        print(f"=== {modulation} 调制结果 ===")
        print(f"输入比特     : {n_bits}（丢弃不足 1 符号的 {dropped} 比特）")
        print(f"输出符号     : {n_sym}")
        print(f"I : {' '.join(f'{v:+.3f}' for v in syms.real)}")
        print(f"Q : {' '.join(f'{v:+.3f}' for v in syms.imag)}")

    elif mode == "evm":
        i = payload.get("i")
        q = payload.get("q")
        if i is None or q is None:
            print("错误：evm 模式需要 i 与 q 字段（实测符号）。")
            return
        meas = np.asarray(i, dtype=float) + 1j * np.asarray(q, dtype=float)
        dist = np.abs(meas[:, None] - constel[None, :])
        ref = constel[np.argmin(dist, axis=1)]
        err = meas - ref
        evm_rms = math.sqrt(np.mean(np.abs(err) ** 2) / np.mean(np.abs(constel) ** 2)) * 100.0
        print(f"=== {modulation} EVM 评估 ===")
        print(f"符号数       : {meas.size}")
        print(f"EVM (RMS)    : {evm_rms:.3f} %")
        print(f"EVM (dB)     : {20.0 * math.log10(evm_rms / 100.0):.2f} dB")
    else:
        print(f"错误：未知 mode '{mode}'，可选 constellation/modulate/evm。")


if __name__ == "__main__":
    main()

"""信道编码 / FEC 仿真（被 channel_coding 工具调用）。

对随机比特做 FEC 编码 → 调制 → 信道(AWGN/Rayleigh) → 解调 → 译码，统计「编码 vs 未编码」BER，
量化真实编码增益（取代 ber_snr 里手填的 coding_gain_db）。复用同目录 modulation.py（星座/映射）、
ber_snr.py（未使用其数值，仅为一致性保留可扩展），信道加噪思路与 channel.py 一致。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    code: str          — conv_k7_r12 | hamming_7_4 | rs_255_223
    modulation: str    — BPSK|QPSK|8PSK|16QAM|64QAM|256QAM
    channel: str?      — awgn | rayleigh，默认 awgn
    ebn0_db: number[]? — Eb/N0 扫点（dB），默认 [2,4,6]
    num_bits: int?     — 每点信息比特数，默认 4000（conv 上限 20000，分组码上限 200000）
    decision: str?     — hard | soft，默认 hard（soft 仅 conv + BPSK/QPSK）
    target_ber: float? — 报告编码增益的目标 BER，默认 1e-3
    seed: int?         — 随机种子（复现）
输出：每个 Eb/N0 的 coded/uncoded 经验 BER、码率、目标 BER 处编码增益(dB) 文本报告。
单位：Eb/N0 为「每信息比特能量 / 噪声功率谱密度」，dB；BER、码率无量纲。
约定：Eb/N0 定义为每信息比特能量；编码把同样的信息能量摊到更多编码比特上（Ec=R·Eb），
      故编码后每符号噪声更大，靠纠错换取净增益——这是 coded 曲线左移的原因。
"""
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulation import BITS_PER_SYMBOL, build_constellation, modulate_bits, demodulate_symbols  # noqa: E402

MAX_CONV_BITS = 20_000       # conv 纯 Python Viterbi 慢，限制每点比特数
MAX_BLOCK_BITS = 200_000     # hamming/rs 快，可放宽
DEFAULT_EBN0 = [2.0, 4.0, 6.0]
CONV_TB_DEPTH = 30           # 回溯深度 ≈ 5×memory

# Hamming(7,4) 系统式生成矩阵 G=[I4|P] 与校验矩阵 H=[Pᵀ|I3]
_HAMMING_P = np.array([[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]], dtype=int)  # 4×3
_HAMMING_G = np.hstack([np.eye(4, dtype=int), _HAMMING_P])                      # 4×7
_HAMMING_H = np.hstack([_HAMMING_P.T, np.eye(3, dtype=int)])                    # 3×7


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def _load_commpy():
    try:
        from commpy.channelcoding import Trellis, conv_encode, viterbi_decode
        return Trellis, conv_encode, viterbi_decode
    except Exception:
        return None


def _load_reedsolo():
    try:
        import reedsolo
        return reedsolo
    except Exception:
        return None


# ---------------- 信道与软量度 ----------------

def make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng):
    """给符号加噪并（Rayleigh 时）过衰落 + 完美 CSI 均衡。Es=1。

    N0 = 1/(k_mod·rate·Eb/N0)：Eb/N0 为每信息比特能量；编码率 rate<1 时噪声更大。
    """
    ebn0_lin = 10.0 ** (ebn0_db / 10.0)
    n0 = 1.0 / (k_mod * rate * ebn0_lin)
    n = symbols.size
    noise = math.sqrt(n0 / 2.0) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    if channel == "rayleigh":
        h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / math.sqrt(2.0)  # E[|h|^2]=1
        rx = h * symbols + noise
        return rx / h  # 完美 CSI 均衡
    return symbols + noise


def soft_llr(rx, modulation):
    """max-log LLR（每编码比特），正值 ↔ 编码比特=1，符合 commpy 'unquantized' 约定。"""
    constel, k = build_constellation(modulation)
    labels = np.arange(len(constel))
    dist = np.abs(rx[:, None] - constel[None, :]) ** 2  # (N, M)
    out = np.empty((rx.size, k), dtype=float)
    for b in range(k):
        bitvals = (labels >> (k - 1 - b)) & 1  # MSB first
        d0 = dist[:, bitvals == 0].min(axis=1)
        d1 = dist[:, bitvals == 1].min(axis=1)
        out[:, b] = d0 - d1
    return out.reshape(-1)  # 每符号 MSB→LSB，与 modulate_bits 顺序一致


def _modulate_padded(coded_bits, modulation):
    """把编码比特调制为符号，返回 (symbols, n_coded, k_mod)；不足一符号补零。"""
    k_mod = BITS_PER_SYMBOL[modulation]
    n_coded = coded_bits.size
    pad = (-n_coded) % k_mod
    if pad:
        coded_bits = np.concatenate([coded_bits, np.zeros(pad, dtype=int)])
    symbols, _, _ = modulate_bits(coded_bits, modulation)
    return symbols, n_coded, k_mod


# ---------------- 各码型：编码 + 过信道 + 译码，返回信息比特误码数 ----------------

def run_conv(info_bits, modulation, channel, ebn0_db, decision, rng):
    loaded = _load_commpy()
    if loaded is None:
        return None
    Trellis, conv_encode, viterbi_decode = loaded
    trellis = Trellis(np.array([6]), np.array([[0o133, 0o171]]))  # K=7, rate-1/2, 133/171
    coded = conv_encode(info_bits, trellis, termination="term")
    rate = info_bits.size / coded.size  # 含尾比特的真实码率
    symbols, n_coded, k_mod = _modulate_padded(coded.astype(int), modulation)
    rx = make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng)
    if decision == "soft":
        soft = soft_llr(rx, modulation)[:n_coded]
        decoded = viterbi_decode(soft, trellis, tb_depth=CONV_TB_DEPTH, decoding_type="unquantized")
    else:
        bits_rx = demodulate_symbols(rx, modulation)[:n_coded]
        decoded = viterbi_decode(bits_rx.astype(float), trellis, tb_depth=CONV_TB_DEPTH, decoding_type="hard")
    decoded = np.asarray(decoded[:info_bits.size], dtype=int)
    return int(np.sum(decoded != info_bits)), rate


def run_hamming(info_bits, modulation, channel, ebn0_db, decision, rng):
    # 截断到 4 的整数倍
    n_blocks = info_bits.size // 4
    info = info_bits[:n_blocks * 4].reshape(n_blocks, 4)
    coded = (info @ _HAMMING_G) % 2          # (n_blocks, 7)
    rate = 4.0 / 7.0
    coded_flat = coded.reshape(-1)
    symbols, n_coded, k_mod = _modulate_padded(coded_flat, modulation)
    rx = make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng)
    bits_rx = demodulate_symbols(rx, modulation)[:n_coded].reshape(n_blocks, 7)
    # 校验子译码：syndrome = H·rᵀ，查表纠 1 比特错
    synd = (bits_rx @ _HAMMING_H.T) % 2      # (n_blocks, 3)
    syn_to_pos = {tuple(_HAMMING_H[:, j] % 2): j for j in range(7)}
    weights = np.array([4, 2, 1])
    for i in range(n_blocks):
        s = synd[i]
        if s.any():
            pos = syn_to_pos.get(tuple(s))
            if pos is not None:
                bits_rx[i, pos] ^= 1
    decoded = bits_rx[:, :4].reshape(-1)
    info_used = info.reshape(-1)
    return int(np.sum(decoded != info_used)), rate


def run_rs(info_bits, modulation, channel, ebn0_db, decision, rng):
    reedsolo = _load_reedsolo()
    if reedsolo is None:
        return None
    K, N = 223, 255
    rsc = reedsolo.RSCodec(N - K)  # 32 校验符号
    bits_per_block = K * 8
    n_blocks = info_bits.size // bits_per_block
    if n_blocks < 1:
        return "TOO_FEW_BITS", K / N
    rate = K / N
    info = info_bits[:n_blocks * bits_per_block]
    info_bytes = np.packbits(info.reshape(n_blocks, bits_per_block), axis=1)  # (n_blocks, 223)
    coded_bytes = np.empty((n_blocks, N), dtype=np.uint8)
    for i in range(n_blocks):
        coded_bytes[i] = np.frombuffer(bytes(rsc.encode(bytearray(info_bytes[i].tolist()))), dtype=np.uint8)
    coded_bits = np.unpackbits(coded_bytes, axis=1).reshape(-1)
    symbols, n_coded, k_mod = _modulate_padded(coded_bits, modulation)
    rx = make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng)
    bits_rx = demodulate_symbols(rx, modulation)[:n_coded].reshape(n_blocks, N * 8)
    rx_bytes = np.packbits(bits_rx, axis=1)  # (n_blocks, 255)
    errors = 0
    for i in range(n_blocks):
        try:
            msg = rsc.decode(bytearray(rx_bytes[i].tolist()))[0]
            dec_bytes = np.frombuffer(bytes(msg), dtype=np.uint8)
        except reedsolo.ReedSolomonError:
            dec_bytes = rx_bytes[i, :K]  # 无法纠正 → 用未纠正的信息字节
        dec_bits = np.unpackbits(dec_bytes)[:bits_per_block]
        errors += int(np.sum(dec_bits != info[i * bits_per_block:(i + 1) * bits_per_block]))
    return errors, rate


def run_uncoded(info_bits, modulation, channel, ebn0_db, rng):
    symbols, n_coded, k_mod = _modulate_padded(info_bits, modulation)
    rx = make_noise_and_channel(symbols, k_mod, 1.0, ebn0_db, channel, rng)  # rate=1
    bits_rx = demodulate_symbols(rx, modulation)[:n_coded]
    return int(np.sum(bits_rx != info_bits))


CODE_RUNNERS = {"conv_k7_r12": run_conv, "hamming_7_4": run_hamming, "rs_255_223": run_rs}
CODE_LABELS = {"conv_k7_r12": "卷积码 K=7 rate-1/2 (133/171)",
               "hamming_7_4": "Hamming(7,4)", "rs_255_223": "Reed-Solomon(255,223)"}


def coding_gain_db(ebn0_list, ber_coded, ber_uncoded, target):
    """在 log-BER 上线性插值，求两条曲线到达 target BER 的 Eb/N0 差（dB）。"""
    def cross(ebn0, ber):
        pts = [(e, b) for e, b in zip(ebn0, ber) if b > 0]
        for i in range(len(pts) - 1):
            (e0, b0), (e1, b1) = pts[i], pts[i + 1]
            if (b0 - target) * (b1 - target) <= 0 and b0 != b1:
                lb0, lb1, lt = math.log10(b0), math.log10(b1), math.log10(target)
                return e0 + (e1 - e0) * (lt - lb0) / (lb1 - lb0)
        return None
    ec, eu = cross(ebn0_list, ber_coded), cross(ebn0_list, ber_uncoded)
    if ec is None or eu is None:
        return None
    return eu - ec


def main() -> None:
    payload = load_payload()
    code = payload.get("code", "")
    if code not in CODE_RUNNERS:
        print(f"错误：不支持的 code '{code}'。可选：conv_k7_r12 | hamming_7_4 | rs_255_223。")
        return
    modulation = payload.get("modulation", "")
    if modulation not in BITS_PER_SYMBOL:
        print(f"错误：不支持的调制方式 '{modulation}'。")
        return
    channel = payload.get("channel", "awgn")
    if channel not in ("awgn", "rayleigh"):
        print(f"错误：不支持的 channel '{channel}'。可选：awgn | rayleigh。")
        return

    decision = payload.get("decision", "hard")
    if decision not in ("hard", "soft"):
        print("错误：decision 只能是 hard 或 soft。")
        return
    soft_note = ""
    if decision == "soft" and (code != "conv_k7_r12" or modulation not in ("BPSK", "QPSK")):
        soft_note = "（注：软判决首批仅支持 conv_k7_r12 + BPSK/QPSK，已回退硬判决）"
        decision = "hard"

    ebn0_list = payload.get("ebn0_db", DEFAULT_EBN0)
    if not isinstance(ebn0_list, list) or not ebn0_list:
        print("错误：ebn0_db 必须是非空数组（Eb/N0 扫点，dB）。")
        return
    try:
        ebn0_list = [float(x) for x in ebn0_list]
    except (TypeError, ValueError):
        print("错误：ebn0_db 元素必须是数字。")
        return

    cap = MAX_CONV_BITS if code == "conv_k7_r12" else MAX_BLOCK_BITS
    num_bits = min(int(payload.get("num_bits", 4000)), cap)
    if num_bits < 8:
        print("错误：num_bits 太小。")
        return
    target_ber = float(payload.get("target_ber", 1e-3))
    seed = payload.get("seed")

    runner = CODE_RUNNERS[code]
    rows, ber_coded, ber_uncoded = [], [], []
    rate_used = None
    for ebn0 in ebn0_list:
        rng = np.random.default_rng(None if seed is None else int(seed) + int(ebn0 * 1000))
        info = rng.integers(0, 2, num_bits)
        result = runner(info, modulation, channel, ebn0, decision, rng)
        if result is None:
            # scikit-commpy（卷积码）/ reedsolo（RS）为硬依赖，正常经 `uv sync` 装齐；
            # 直接运行脚本而未装依赖时给出清晰引导，不再作为「可选降级」。
            print("错误：本工具依赖 scikit-commpy（卷积码）/ reedsolo（RS）。"
                  "请在 comms-agent 目录执行 `uv sync`（或 pip install -r requirements.txt）后重试。")
            return
        n_err, rate = result
        if n_err == "TOO_FEW_BITS":
            print(f"错误：rs_255_223 每点至少需要 {223 * 8} 比特（1 个 RS 块）。请增大 num_bits。")
            return
        rate_used = rate
        n_unc = run_uncoded(info, modulation, channel, ebn0, rng)
        bc = n_err / info.size
        bu = n_unc / info.size
        ber_coded.append(bc)
        ber_uncoded.append(bu)
        rows.append((ebn0, bu, bc))

    print(f"=== 信道编码仿真：{CODE_LABELS[code]} / {modulation} / {channel} ===")
    print(f"码率 R       : {rate_used:.4f}（信息比特/编码比特）")
    print(f"判决         : {decision}{soft_note}")
    print(f"每点比特数   : {num_bits}（信息比特）")
    print(f"Eb/N0 定义   : 每信息比特能量 / N0（dB）；编码率已计入噪声归一化")
    print(f"{'Eb/N0(dB)':>10} | {'未编码 BER':>14} | {'编码后 BER':>14}")
    for ebn0, bu, bc in rows:
        print(f"{ebn0:>10.2f} | {bu:>14.3e} | {bc:>14.3e}")
    gain = coding_gain_db(ebn0_list, ber_coded, ber_uncoded, target_ber)
    if gain is not None:
        print(f"编码增益      : {gain:+.2f} dB @ BER={target_ber:.0e}")
    else:
        print(f"编码增益      : 目标 BER={target_ber:.0e} 未被当前扫点跨越，"
              f"请增大 num_bits 或调整 ebn0_db 扫点后再估。")
    if any(bc == 0 for bc in ber_coded):
        print("提示          : 某些点编码后 0 误码（BER 低于本点比特数分辨率），仅说明优于该分辨率。")


if __name__ == "__main__":
    main()

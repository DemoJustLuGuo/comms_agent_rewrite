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
MAX_ITER_BITS = 40_000       # ldpc/turbo（BP/BCJR 迭代）介于两者之间
DEFAULT_EBN0 = [2.0, 4.0, 6.0]
CONV_TB_DEPTH = 30           # 回溯深度 ≈ 5×memory
LDPC_BP_ITERS = 20           # LDPC 置信传播迭代次数
TURBO_ITERS = 6              # Turbo BCJR 迭代次数

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


def _load_turbo():
    """Turbo：commpy 的 turbo_encode/turbo_decode/map_decode + RSC Trellis + 交织器。"""
    try:
        from commpy.channelcoding import Trellis, turbo_encode, turbo_decode
        from commpy.channelcoding.interleavers import RandInterlv
        return Trellis, turbo_encode, turbo_decode, RandInterlv
    except Exception:
        return None


def _load_ldpc():
    """LDPC：commpy 的 get_ldpc_code_params / 系统式编码 / BP 译码，用其自带 WiMAX 设计文件。"""
    try:
        from commpy.channelcoding import (
            build_matrix,
            get_ldpc_code_params,
            ldpc_bp_decode,
            triang_ldpc_systematic_encode,
        )
        return build_matrix, get_ldpc_code_params, ldpc_bp_decode, triang_ldpc_systematic_encode
    except Exception:
        return None


def _load_polar():
    """Polar：polarcodes 第三方库（Brendon McBain）——PolarCode 对象 + Construct/Encode/Decode。

    该库 API 有状态且版本敏感，全部调用点包 try/except，API 不符时返回清晰错误而非乱码。
    """
    try:
        from polarcodes import PolarCode, Construct, Encode, Decode
        return PolarCode, Construct, Encode, Decode
    except Exception:
        return None


def _ldpc_design_file():
    """定位 commpy 自带的 WiMAX LDPC 设计文件（rate-1/2，960×720 → K=480,N=960）。

    随包分发，无需项目内 bundling；找不到时返回 None（由调用方给出清晰引导）。
    """
    try:
        import commpy.channelcoding as cc
        base = Path(cc.__file__).resolve().parent / "designs" / "ldpc" / "wimax"
        # 1440.720 = N1440/K720 → rate-1/2（与 ldpc_wimax_r12 命名一致，首选）；
        # 960.720.a = N960/K720 → rate-3/4（次选兜底，rate 由运行时按块长实算）。
        for name in ("1440.720.txt", "960.720.a.txt"):
            f = base / name
            if f.exists():
                return str(f)
    except Exception:
        pass
    return None


def _read_ldpc_params_compat(design_file, build_matrix, compute_matrix=False):
    """读取 CommPy LDPC 设计文件，兼容 NumPy 2 的单元素数组标量赋值规则。"""
    with open(design_file, encoding="utf-8") as stream:
        n_vnodes, n_cnodes = (int(x) for x in stream.readline().split())
        max_vnode_deg, max_cnode_deg = (int(x) for x in stream.readline().split())
        vnode_deg_list = np.asarray([int(x) for x in stream.readline().split()], dtype=np.int32)
        cnode_deg_list = np.asarray([int(x) for x in stream.readline().split()], dtype=np.int32)

        vnode_adj_list = -np.ones((n_vnodes, max_vnode_deg), dtype=np.int32)
        cnode_adj_list = -np.ones((n_cnodes, max_cnode_deg), dtype=np.int32)

        for vnode in range(n_vnodes):
            neighbors = np.asarray([int(x) - 1 for x in stream.readline().split()], dtype=np.int32)
            vnode_adj_list[vnode, :vnode_deg_list[vnode]] = neighbors
        for cnode in range(n_cnodes):
            neighbors = np.asarray([int(x) - 1 for x in stream.readline().split()], dtype=np.int32)
            cnode_adj_list[cnode, :cnode_deg_list[cnode]] = neighbors

    cnode_vnode_map = -np.ones((n_cnodes, max_cnode_deg), dtype=np.int32)
    vnode_cnode_map = -np.ones((n_vnodes, max_vnode_deg), dtype=np.int32)
    for cnode in range(n_cnodes):
        for i, vnode in enumerate(cnode_adj_list[cnode, :cnode_deg_list[cnode]]):
            matches = np.flatnonzero(vnode_adj_list[vnode, :] == cnode)
            if matches.size != 1:
                raise ValueError("LDPC 设计文件中的校验节点映射不唯一。")
            cnode_vnode_map[cnode, i] = int(matches[0])
    for vnode in range(n_vnodes):
        for i, cnode in enumerate(vnode_adj_list[vnode, :vnode_deg_list[vnode]]):
            matches = np.flatnonzero(cnode_adj_list[cnode, :] == vnode)
            if matches.size != 1:
                raise ValueError("LDPC 设计文件中的变量节点映射不唯一。")
            vnode_cnode_map[vnode, i] = int(matches[0])

    params = {
        "n_vnodes": n_vnodes,
        "n_cnodes": n_cnodes,
        "max_vnode_deg": max_vnode_deg,
        "max_cnode_deg": max_cnode_deg,
        "vnode_deg_list": vnode_deg_list,
        "cnode_deg_list": cnode_deg_list,
        "vnode_adj_list": vnode_adj_list.ravel(),
        "cnode_adj_list": cnode_adj_list.ravel(),
        "vnode_cnode_map": vnode_cnode_map.ravel(),
        "cnode_vnode_map": cnode_vnode_map.ravel(),
    }
    if compute_matrix:
        build_matrix(params)
    return params


def _get_ldpc_params(get_params, build_matrix, design_file, compute_matrix=False):
    try:
        return get_params(design_file, compute_matrix=compute_matrix)
    except (TypeError, ValueError) as exc:
        message = str(exc)
        numpy_scalar_error = (
            "setting an array element with a sequence" in message
            or "0-dimensional arrays can be converted to Python scalars" in message
        )
        if not numpy_scalar_error:
            raise
        return _read_ldpc_params_compat(design_file, build_matrix, compute_matrix)


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


def run_ldpc(info_bits, modulation, channel, ebn0_db, decision, rng):
    """WiMAX rate-1/2 LDPC（commpy 自带设计文件）：系统式编码 → 软 LLR → BP(MSA) 译码。

    commpy 约定：triang_ldpc_systematic_encode 每块列向排布（order='F'），系统位在前；
    ldpc_bp_decode 收 LLR（正 ↔ 比特 0，见其 signbit 判决），返回 (dec_word, out_llrs)
    每块一列。这里用整块 LLR（软判决），硬判决请求也走软 LLR（LDPC 无实用硬判解码）。
    """
    loaded = _load_ldpc()
    if loaded is None:
        return None
    build_matrix, get_params, bp_decode, sys_encode = loaded
    design = _ldpc_design_file()
    if design is None:
        return "NO_LDPC_DESIGN", 0.5
    params = _get_ldpc_params(get_params, build_matrix, design, compute_matrix=False)
    n_vnodes = params["n_vnodes"]          # 码字块长 N
    n_cnodes = params["n_cnodes"]          # 校验数
    k_block = n_vnodes - n_cnodes          # 信息位块长 K（满秩校验时）
    rate = k_block / n_vnodes

    n_blocks = info_bits.size // k_block
    if n_blocks < 1:
        return "TOO_FEW_BITS_LDPC", rate
    info = info_bits[:n_blocks * k_block]
    build_matrix(params)

    total_err = 0
    for b in range(n_blocks):
        msg = info[b * k_block:(b + 1) * k_block]
        coded = np.asarray(sys_encode(msg, params, pad=False), dtype=int).reshape(-1)  # 系统位在前
        symbols, n_coded, k_mod = _modulate_padded(coded, modulation)
        rx = make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng)
        # commpy LLR 约定：正值 ↔ 比特 0（signbit 判决），与 soft_llr 的「正↔1」相反 → 取负
        llr = -soft_llr(rx, modulation)[:n_coded]
        dec_word, _ = bp_decode(llr.astype(float), params, "MSA", LDPC_BP_ITERS)
        dec_word = np.asarray(dec_word, dtype=int).reshape(-1)[:k_block]  # 系统位即前 K 位
        total_err += int(np.sum(dec_word != msg))
    return total_err, rate


def run_turbo(info_bits, modulation, channel, ebn0_db, decision, rng):
    """rate-1/3 并行级联 Turbo（commpy）：两个 RSC(7) 分量码 + 随机交织，BCJR 迭代译码。

    commpy turbo_decode 收 BPSK 符号量度（+1/-1 域，噪声方差归一），故本码型固定按
    BPSK 承载（modulation 参数对 turbo 不生效，报告中注明）。返回信息比特误码数。
    """
    loaded = _load_turbo()
    if loaded is None:
        return None
    Trellis, turbo_encode, turbo_decode, RandInterlv = loaded
    # RSC K=4（memory=3, 07/05 八进制，反馈 07）——commpy 教程标准分量码
    memory = np.array([3])
    g_matrix = np.array([[0o7, 0o5]])
    trellis = Trellis(memory, g_matrix, feedback=0o7, code_type="rsc")

    block = 1000  # 每个交织块信息比特数（含尾比特开销，rate≈1/3）
    n_blocks = info_bits.size // block
    if n_blocks < 1:
        return "TOO_FEW_BITS_TURBO", 1.0 / 3.0
    info = info_bits[:n_blocks * block]
    rate = 1.0 / 3.0  # 三路输出（系统 + 两校验），忽略尾比特微小开销

    # Turbo 译码器按 BPSK 符号量度工作，本码型固定 BPSK 承载（忽略传入 modulation）
    mod_turbo = "BPSK"
    total_err = 0
    for b in range(n_blocks):
        msg = info[b * block:(b + 1) * block]
        interleaver = RandInterlv(msg.size, seed=int(ebn0_db * 100) + b)
        sys_s, par1, par2 = turbo_encode(msg, trellis, trellis, interleaver)
        # 三路比特拼接调制过信道，再拆回三路软量度（BPSK 域 ±1 + 噪声）
        coded = np.concatenate([sys_s, par1, par2]).astype(int)
        symbols, n_coded, k_mod = _modulate_padded(coded, mod_turbo)
        rx = make_noise_and_channel(symbols, k_mod, rate, ebn0_db, channel, rng)
        # turbo_decode 要 BPSK 符号量度（commpy 约定 bit→2b-1，即 bit0→-1、bit1→+1）；
        # 本项目 BPSK 星座相反（bit0→+1、bit1→-1），故取实部后取负对齐 commpy 约定。
        rx_bits_soft = -np.real(rx)[:n_coded]
        ls = sys_s.size
        sys_r = rx_bits_soft[:ls]
        par1_r = rx_bits_soft[ls:2 * ls]
        par2_r = rx_bits_soft[2 * ls:3 * ls]
        ebn0_lin = 10.0 ** (ebn0_db / 10.0)
        n0 = 1.0 / (k_mod * rate * ebn0_lin)
        decoded = turbo_decode(sys_r, par1_r, par2_r, trellis, n0 / 2.0, TURBO_ITERS, interleaver)
        decoded = np.asarray(decoded, dtype=int).reshape(-1)
        # 长度对齐（防 commpy 尾比特处理导致的 off-by-one）：按较短者比对
        m = min(decoded.size, msg.size)
        total_err += int(np.sum(decoded[:m] != msg[:m]))
    return total_err, rate


def run_polar(info_bits, modulation, channel, ebn0_db, decision, rng):
    """rate-1/2 Polar 码（polarcodes 库，N=256/K=128）：SC 译码。

    polarcodes 的 API 有状态且各版本略有差异——本 runner 走该库自带的
    Construct→set_message→Encode→AWGN→Decode 端到端管路，让 LLR 的符号/尺度约定
    留在库内部自洽，不外部构造软量度（避免猜错译码器输入约定）。
    modulation 参数对 polar 不生效（库内固定 BPSK+AWGN），报告中注明；返回信息比特误码数。
    """
    loaded = _load_polar()
    if loaded is None:
        return None
    PolarCode, Construct, Encode, Decode = loaded

    N, K = 256, 128           # 码长/信息位（rate-1/2）
    rate = K / N
    design_snr = 5.0          # Bhattacharyya/GA 构造用的设计 SNR（dB），常用工程默认
    block = K
    n_blocks = info_bits.size // block
    if n_blocks < 1:
        return "TOO_FEW_BITS_POLAR", rate

    info = info_bits[:n_blocks * block]
    # polarcodes 的 AWGN 以 Eb/N0（dB）参数化，与本工具 Eb/N0 口径一致；库内部按码率归一。
    total_err = 0
    try:
        for b in range(n_blocks):
            msg = info[b * block:(b + 1) * block].astype(int)
            pc = PolarCode(N, K)
            pc.construction_type = "bb"        # Bhattacharyya 参数构造
            Construct(pc, design_snr)
            pc.set_message(msg)
            Encode(pc)
            pc.simulation_snr = float(ebn0_db)  # 该点 Eb/N0
            # 库自带 AWGN 调制/加噪（BPSK），写入 pc.likelihoods 供 SC 译码
            pc.AWGN() if hasattr(pc, "AWGN") else _polar_awgn_fallback(pc, ebn0_db, rate, rng)
            Decode(pc)
            decoded = np.asarray(pc.message_received, dtype=int).reshape(-1)
            m = min(decoded.size, msg.size)
            total_err += int(np.sum(decoded[:m] != msg[:m]))
    except (AttributeError, TypeError, ValueError, KeyError) as e:
        # API 不符（版本差异/字段改名）→ 清晰错误而非乱码
        return ("POLAR_API", str(e))
    return total_err, rate


def _polar_awgn_fallback(pc, ebn0_db, rate, rng):
    """polarcodes 版本无 AWGN() 方法时的兜底：按库的 likelihoods 约定手动加噪。

    仅在库缺该方法时触发；若字段约定也不符，外层 except 会捕获转 POLAR_API 错误。
    """
    x = np.asarray(pc.x, dtype=float)          # 编码后比特（库内字段）
    bpsk = 1.0 - 2.0 * x                        # 0→+1, 1→-1（polarcodes BPSK 约定）
    ebn0_lin = 10.0 ** (ebn0_db / 10.0)
    sigma = math.sqrt(1.0 / (2.0 * rate * ebn0_lin))
    y = bpsk + sigma * rng.standard_normal(bpsk.size)
    pc.likelihoods = (2.0 * y / (sigma ** 2)).astype(float)


def run_uncoded(info_bits, modulation, channel, ebn0_db, rng):
    symbols, n_coded, k_mod = _modulate_padded(info_bits, modulation)
    rx = make_noise_and_channel(symbols, k_mod, 1.0, ebn0_db, channel, rng)  # rate=1
    bits_rx = demodulate_symbols(rx, modulation)[:n_coded]
    return int(np.sum(bits_rx != info_bits))


CODE_RUNNERS = {"conv_k7_r12": run_conv, "hamming_7_4": run_hamming, "rs_255_223": run_rs,
                "ldpc_wimax_r12": run_ldpc, "turbo_r13": run_turbo, "polar_sc_r12": run_polar}
CODE_LABELS = {"conv_k7_r12": "卷积码 K=7 rate-1/2 (133/171)",
               "hamming_7_4": "Hamming(7,4)", "rs_255_223": "Reed-Solomon(255,223)",
               "ldpc_wimax_r12": "LDPC WiMAX rate-1/2 (N1440,K720)", "turbo_r13": "Turbo rate-1/3 (RSC K=4 ×2)",
               "polar_sc_r12": "Polar SC rate-1/2 (N256,K128)"}


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
        print(f"错误：不支持的 code '{code}'。可选："
              "conv_k7_r12 | hamming_7_4 | rs_255_223 | ldpc_wimax_r12 | turbo_r13 | polar_sc_r12。")
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

    # LDPC BP / Turbo BCJR / Polar SC 为纯 Python 迭代/递归译码，比卷积码更重 → 更严的比特上限。
    if code in ("ldpc_wimax_r12", "turbo_r13", "polar_sc_r12"):
        cap = MAX_ITER_BITS
    elif code == "conv_k7_r12":
        cap = MAX_CONV_BITS
    else:
        cap = MAX_BLOCK_BITS
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
            # scikit-commpy（卷积/LDPC/Turbo）/ reedsolo（RS）/ polarcodes（Polar）为硬依赖，
            # 正常经 `uv sync` 装齐；直接运行脚本而未装依赖时给出清晰引导，不再作为「可选降级」。
            print("错误：本工具依赖 scikit-commpy（卷积/LDPC/Turbo）/ reedsolo（RS）/ "
                  "py-polar-codes（Polar，导入名 polarcodes）。"
                  "请在 comms-agent 目录执行 `uv sync`（或 pip install -r requirements.txt）后重试。")
            return
        n_err, rate = result
        if n_err == "POLAR_API":
            print(f"错误：py-polar-codes 库 API 与本工具预期不符（可能版本差异）：{rate}。"
                  "请核对已装 py-polar-codes 版本，或在 issue 中反馈以对齐调用约定。")
            return
        if n_err in ("TOO_FEW_BITS_LDPC", "TOO_FEW_BITS_TURBO", "TOO_FEW_BITS_POLAR"):
            need = {"TOO_FEW_BITS_LDPC": "720（1 个 LDPC 块）",
                    "TOO_FEW_BITS_TURBO": "1000（1 个 Turbo 交织块）",
                    "TOO_FEW_BITS_POLAR": "128（1 个 Polar 块 K=128）"}[n_err]
            print(f"错误：{CODE_LABELS[code]} 每点至少需要 {need} 信息比特。请增大 num_bits。")
            return
        if n_err == "NO_LDPC_DESIGN":
            print("错误：未找到 commpy 自带的 WiMAX LDPC 设计文件（designs/ldpc/wimax/）。"
                  "请确认 scikit-commpy 完整安装（uv sync）。")
            return
        if n_err == "TOO_FEW_BITS":
            print(f"错误：rs_255_223 每点至少需要 {223 * 8} 比特（1 个 RS 块）。请增大 num_bits。")
            return
        rate_used = rate
        # turbo/polar 内部固定 BPSK 承载：未编码基线也须用 BPSK，否则编码增益口径错配
        unc_mod = "BPSK" if code in ("turbo_r13", "polar_sc_r12") else modulation
        n_unc = run_uncoded(info, unc_mod, channel, ebn0, rng)
        bc = n_err / info.size
        bu = n_unc / info.size
        ber_coded.append(bc)
        ber_uncoded.append(bu)
        rows.append((ebn0, bu, bc))

    eff_mod = "BPSK" if code in ("turbo_r13", "polar_sc_r12") else modulation
    mod_note = f"{eff_mod}（该码固定 BPSK 承载）" if eff_mod != modulation else eff_mod
    print(f"=== 信道编码仿真：{CODE_LABELS[code]} / {mod_note} / {channel} ===")
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

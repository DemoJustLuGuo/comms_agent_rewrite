"""通信代码体检 / comms_lint（被 comms_lint 工具调用）。

把 AGENTS.md / CLAUDE.md 的工程约定工具化，对目标 .py/.m 文件做启发式静态检查，
给 comms-optimize 一个客观（提示非拦截）的闭环标准。只读目标文件，不写、不执行。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    path: str     — 待检查文件（项目根目录内的 .py 或 .m），相对 comms-agent 根或绝对路径
    checks: str?  — all | units | numpy | repro | protocol | secrets（默认 all）
    strict: bool? — 为 true 时若存在 error 级发现则以非零退出（供 CI）；默认 false（仅提示）
输出：分级发现清单（ERROR/WARN/INFO + file:line + 建议）与统计摘要。
单位：本工具不做数值计算；检查项本身关注「代码是否标注单位/是否可复现/是否用 NumPy」等工程约定。
安全：路径受限在项目根内；疑似密钥只报 file:line 与短标签，绝不回显密钥值或整文件内容。
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path.cwd()  # 工作区根：.ts 端已把子进程 cwd 设为会话目录；直接跑脚本/测试时为当前目录
ALL_CHECKS = ("units", "numpy", "repro", "protocol", "secrets")

# 物理量名字根：变量名含这些根却缺单位标注时告警
PHYS_ROOTS = (
    "freq", "frequency", "bandwidth", "power", "gain", "dist", "distance",
    "wavelength", "lambda", "snr", "noise", "amplitude", "phase",
    "sample_rate", "samplerate", "symbol_rate", "bitrate", "baud", "temperature",
)
# 单位 token（变量名后缀或注释里出现即认为已标注单位）
UNIT_NAME_SUFFIX = re.compile(
    r"_(hz|khz|mhz|ghz|db|dbm|dbi|dbw|dbc|w|kw|mw|m|km|cm|mm|s|ms|us|ns|rad|deg|"
    r"sps|bps|kbps|mbps|baud|k|v|a)\b",
    re.IGNORECASE,
)
UNIT_IN_TEXT = re.compile(
    r"\b(hz|khz|mhz|ghz|db|dbm|dbi|dbw|dbc|watt|watts|meter|metre|km|rad|radian|"
    r"deg|degree|sample|samples|sps|baud|bit/s|bps|kbps|mbps|second|seconds|"
    r"ns|us|ms)\b",
    re.IGNORECASE,
)
# 常被手写、其实应交给 numpy/scipy 的标准算法名
STD_ALGO_DEFS = re.compile(r"\bdef\s+(fft|ifft|dft|idft|convolve|conv|correlate|erf|erfc|dft2|goertzel)\s*\(", re.IGNORECASE)
# 疑似密钥赋值：key/secret/token/password = "..."（不回显值）
SECRET_ASSIGN = re.compile(r"\b(api[_-]?key|secret|token|password|passwd|access[_-]?key)\b\s*[:=]\s*['\"][^'\"]{6,}['\"]", re.IGNORECASE)
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
# 绝对路径：Windows 盘符或类 Unix 系统目录
ABS_PATH = re.compile(r"""['\"]([A-Za-z]:\\\\|[A-Za-z]:/|/(?:home|Users|usr|etc|var|opt)/)[^'\"]*['\"]""")


class Finding:
    __slots__ = ("level", "line", "category", "message")

    def __init__(self, level, line, category, message):
        self.level = level          # ERROR | WARN | INFO
        self.line = line
        self.category = category
        self.message = message


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def line_comment(src_line: str) -> str:
    """取一行里 # 之后的注释（.m 用 % 也一并支持）。"""
    for marker in ("#", "%"):
        idx = src_line.find(marker)
        if idx != -1:
            return src_line[idx + 1:]
    return ""


def has_unit(name: str, comment: str) -> bool:
    return bool(UNIT_NAME_SUFFIX.search(name) or UNIT_IN_TEXT.search(comment) or UNIT_IN_TEXT.search(name))


def is_phys_name(name: str) -> bool:
    low = name.lower()
    return any(root in low for root in PHYS_ROOTS)


# ---------------- 各检查项 ----------------

def check_units(lines, tree, findings):
    """物理量变量赋数值却未标注单位 → WARN。用 AST 拿准确赋值行，用原始行取注释。"""
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not _is_numeric_value(node.value):
                continue
            for tgt in node.targets:
                for name in _target_names(tgt):
                    if is_phys_name(name):
                        src = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                        if not has_unit(name, line_comment(src)):
                            findings.append(Finding("WARN", node.lineno, "units",
                                f"变量 '{name}' 疑似物理量但未标注单位（如 Hz/dB/dBm/km/rad），建议在变量名或注释注明。"))
    else:
        # .m 文件：正则兜底
        for i, src in enumerate(lines, 1):
            m = re.match(r"\s*([A-Za-z]\w*)\s*=\s*[-+]?[\d.]+(e[-+]?\d+)?\s*;?", src, re.IGNORECASE)
            if m and is_phys_name(m.group(1)) and not has_unit(m.group(1), line_comment(src)):
                findings.append(Finding("WARN", i, "units",
                    f"变量 '{m.group(1)}' 疑似物理量但未标注单位，建议在变量名或注释注明。"))


def check_numpy(lines, tree, findings):
    """手写标准数值算法（自写 FFT/卷积/erfc）→ INFO：建议改用 NumPy/SciPy。"""
    text = "".join(lines)
    for m in STD_ALGO_DEFS.finditer(text):
        line = text[:m.start()].count("\n") + 1
        findings.append(Finding("INFO", line, "numpy",
            f"疑似手写标准算法 '{m.group(1)}'，建议改用 numpy/scipy（如 np.fft/np.convolve/scipy.special.erfc）而非自研数值实现。"))
    for i, src in enumerate(lines, 1):
        if re.search(r"\bmath\.(erf|erfc)\s*\(", src):
            findings.append(Finding("INFO", i, "numpy",
                "使用 math.erf/erfc 做逐点计算，向量化场景建议用 scipy.special.erfc（支持数组、精度一致）。"))


def check_repro(lines, tree, findings):
    """使用随机过程但未设种子 → WARN（不可复现，违反工程约定）。"""
    text = "".join(lines)
    uses_np_random = re.search(r"\bnp(?:\.random)?\.random|\bnumpy\.random|\bnp\.random\.\w+|\brandom\.default_rng|\bdefault_rng", text)
    # 更明确：是否真正抽样
    draws_np = re.search(r"\bnp\.random\.\w+|\bnumpy\.random\.\w+", text)
    draws_std = re.search(r"(?<![.\w])random\.(random|randint|choice|gauss|uniform|shuffle|sample|normalvariate)\b", text)
    seeded_np = re.search(r"\bnp\.random\.seed\s*\(|\bnumpy\.random\.seed\s*\(|default_rng\s*\(", text)
    seeded_std = re.search(r"(?<![.\w])random\.seed\s*\(", text)
    if draws_np and not seeded_np:
        line = _first_line(lines, r"\bnp\.random\.\w+|\bnumpy\.random\.\w+")
        findings.append(Finding("WARN", line, "repro",
            "使用 np.random 抽样但未设随机种子（np.random.seed(...) 或 np.random.default_rng(seed)），结果不可复现。"))
    if draws_std and not seeded_std:
        line = _first_line(lines, r"(?<![.\w])random\.(random|randint|choice|gauss|uniform|shuffle|sample|normalvariate)\b")
        findings.append(Finding("WARN", line, "repro",
            "使用 random 模块抽样但未设随机种子（random.seed(...)），结果不可复现。"))


def check_protocol(lines, tree, findings):
    """协议解析（struct/frombuffer）附近缺帧结构/字节序/校验说明 → WARN。"""
    pat = re.compile(r"struct\.(unpack|pack|unpack_from|calcsize)\s*\(|np\.frombuffer\s*\(|numpy\.frombuffer\s*\(|\.frombytes\s*\(|int\.from_bytes\s*\(")
    doc_pat = re.compile(r"字节序|帧结构|帧格式|大端|小端|big[- ]?endian|little[- ]?endian|\bFCS\b|\bCRC\b|byte\s*order|frame", re.IGNORECASE)
    n = len(lines)
    for i, src in enumerate(lines, 1):
        if pat.search(src):
            lo = max(0, i - 1 - 3)
            hi = min(n, i + 3)
            context = "".join(lines[lo:hi])
            if not doc_pat.search(context):
                findings.append(Finding("WARN", i, "protocol",
                    "协议解析（struct/frombuffer/from_bytes）附近缺少帧结构/字节序/校验（FCS/CRC）说明，建议先文档化再解析。"))


def check_secrets(lines, tree, findings):
    """疑似硬编码密钥（ERROR）/ 绝对路径（WARN）。只报 file:line 与短标签，不回显值。"""
    for i, src in enumerate(lines, 1):
        if SECRET_ASSIGN.search(src) or AWS_KEY.search(src):
            findings.append(Finding("ERROR", i, "secrets",
                "疑似硬编码密钥/令牌（api_key/secret/token/password 等）。请改用环境变量读取；本工具不回显其值。"))
        elif ABS_PATH.search(src):
            findings.append(Finding("WARN", i, "secrets",
                "疑似硬编码绝对路径，跨机器不可移植；建议改用相对路径或配置项。"))


# ---------------- AST 小工具 ----------------

def _is_numeric_value(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_numeric_value(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_numeric_value(node.left) and _is_numeric_value(node.right)
    return False


def _target_names(tgt):
    if isinstance(tgt, ast.Name):
        return [tgt.id]
    if isinstance(tgt, (ast.Tuple, ast.List)):
        names = []
        for elt in tgt.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _first_line(lines, pattern) -> int:
    rx = re.compile(pattern)
    for i, src in enumerate(lines, 1):
        if rx.search(src):
            return i
    return 1


CHECK_FUNCS = {
    "units": check_units,
    "numpy": check_numpy,
    "repro": check_repro,
    "protocol": check_protocol,
    "secrets": check_secrets,
}


def main() -> None:
    payload = load_payload()
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        print("错误：缺少 path（待检查的项目内 .py 或 .m 文件）。")
        return

    target = Path(raw_path)
    target = target.resolve() if target.is_absolute() else (ROOT / target).resolve()
    try:
        rel = target.relative_to(ROOT)
    except ValueError:
        print("错误：path 只能指向项目根目录内的文件（禁止越界访问）。")
        return
    if not target.exists() or not target.is_file():
        print(f"错误：文件不存在：{raw_path}")
        return
    if target.suffix.lower() not in (".py", ".m"):
        print("错误：仅支持 .py 或 .m 文件。")
        return

    checks_arg = str(payload.get("checks", "all")).strip().lower()
    if checks_arg in ("", "all"):
        selected = ALL_CHECKS
    else:
        selected = tuple(c for c in re.split(r"[,\s]+", checks_arg) if c in CHECK_FUNCS)
        if not selected:
            print(f"错误：checks 非法 '{checks_arg}'。可选：all | {' | '.join(ALL_CHECKS)}。")
            return

    try:
        source = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"错误：无法读取文件：{exc}")
        return
    lines = source.splitlines(keepends=True)

    tree = None
    if target.suffix.lower() == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            print(f"错误：Python 语法解析失败（第 {exc.lineno} 行）：{exc.msg}")
            return

    findings = []
    for name in selected:
        CHECK_FUNCS[name](lines, tree, findings)
    findings.sort(key=lambda f: (f.line, {"ERROR": 0, "WARN": 1, "INFO": 2}[f.level]))

    rel_str = rel.as_posix()
    print(f"=== comms_lint 代码体检：{rel_str} ===")
    print(f"检查项       : {', '.join(selected)}")
    if not findings:
        print("未发现问题（在已启用的检查项内）。")
    else:
        for f in findings:
            print(f"[{f.level}] {rel_str}:{f.line}  [{f.category}] {f.message}")

    n_err = sum(1 for f in findings if f.level == "ERROR")
    n_warn = sum(1 for f in findings if f.level == "WARN")
    n_info = sum(1 for f in findings if f.level == "INFO")
    print(f"体检完成：{n_err} error, {n_warn} warn, {n_info} info（提示非拦截，仅供参考）。")

    if bool(payload.get("strict", False)) and n_err > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()

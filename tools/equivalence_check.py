"""数值等价 / 回归护栏（被 equivalence_check 工具调用）。

把优化前后「行为等价」从人工判断变成可复现断言：对同一组输入，分别运行 baseline 与
candidate 两条命令，解析各自 stdout 的数值向量，比对相对/绝对误差、最大绝对误差、
相关系数，任一超阈值即判 FAIL。用于 comms-optimize 改数值代码后的等价性验证。

安全：命令以列表形式（shlex 切分）spawn，不经 shell，避免注入；子进程有超时；
      本工具只在 comms-optimize 可用（comms-qa 已禁用），其执行的命令不再单独走 bash 审批，
      故只应用于受信的等价验证命令（如跑本项目脚本、对比新旧实现）。

参数以 JSON 传入（argv[1] 优先，其次 stdin）：
    baseline_cmd: str   — 基准实现命令（如 "python -X utf8 old.py"）
    candidate_cmd: str  — 候选实现命令（如 "python -X utf8 new.py"）
    stdin_data: str?    — 同时喂给两条命令 stdin 的输入（可选）
    rtol: float?        — 相对容差，默认 1e-6
    atol: float?        — 绝对容差，默认 1e-9
    parse: str?         — auto | json | floats，默认 auto（先试 JSON 数组，再回退空白分隔浮点）
    timeout_s: int?     — 每条命令超时秒，默认 60（上限 300）
输出：逐项误差统计（最大绝对/相对误差、相关系数、长度一致性）与整体 PASS/FAIL 文本报告。
单位：误差为无量纲（相对被比较量本身的单位）；本工具不解释物理单位，只做数值等价判定。
"""
import json
import math
import re
import shlex
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

MAX_TIMEOUT = 300
_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def load_payload() -> dict:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def split_command(cmd_str):
    """把命令行切成 argv（不经 shell）。

    Windows 上用 posix=False 切分——posix 模式会把路径里的反斜杠当转义符吃掉
    （C:\\Users\\x → C:Usersx）；但 posix=False 会保留成对引号字符，故切分后再手工
    剥掉每个 token 外层的成对引号。POSIX 平台直接用默认 posix=True。
    """
    if sys.platform == "win32":
        parts = shlex.split(cmd_str, posix=False)
        cleaned = []
        for tok in parts:
            if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
                tok = tok[1:-1]
            cleaned.append(tok)
        return cleaned
    return shlex.split(cmd_str)


def run_cmd(cmd_str, stdin_data, timeout_s):
    """以列表形式（不经 shell）运行命令，返回 (stdout, error_or_None)。"""
    try:
        argv = split_command(cmd_str)
    except ValueError as exc:
        return None, f"命令解析失败：{exc}"
    if not argv:
        return None, "命令为空。"
    try:
        proc = subprocess.run(
            argv,
            input=stdin_data,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return None, f"命令未找到：{argv[0]}"
    except subprocess.TimeoutExpired:
        return None, f"命令超时（>{timeout_s}s）：{cmd_str}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return None, f"命令非零退出（{proc.returncode}）：{tail}"
    return proc.stdout, None


def parse_vector(text, mode):
    """把 stdout 解析成 float 向量。auto：先试整体 JSON 数组，再回退抽取所有浮点数。"""
    text = (text or "").strip()
    if mode in ("auto", "json"):
        try:
            obj = json.loads(text)
            arr = np.asarray(obj, dtype=float).reshape(-1)
            if arr.size:
                return arr, None
        except (ValueError, TypeError):
            if mode == "json":
                return None, "无法按 JSON 解析输出为数值数组。"
    # floats 或 auto 回退：抽取所有形似浮点数的 token
    nums = _FLOAT_RE.findall(text)
    if not nums:
        return None, "输出中未找到任何数值。"
    return np.asarray([float(x) for x in nums], dtype=float), None


def main() -> None:
    payload = load_payload()
    base_cmd = str(payload.get("baseline_cmd", "")).strip()
    cand_cmd = str(payload.get("candidate_cmd", "")).strip()
    if not base_cmd or not cand_cmd:
        print("错误：需要 baseline_cmd 与 candidate_cmd 两条命令。")
        return

    parse_mode = str(payload.get("parse", "auto")).lower()
    if parse_mode not in ("auto", "json", "floats"):
        print("错误：parse 只能是 auto | json | floats。")
        return

    try:
        rtol = float(payload.get("rtol", 1e-6))
        atol = float(payload.get("atol", 1e-9))
    except (TypeError, ValueError):
        print("错误：rtol/atol 必须是数字。")
        return
    if rtol < 0 or atol < 0:
        print("错误：rtol/atol 必须非负。")
        return

    timeout_s = min(int(payload.get("timeout_s", 60)), MAX_TIMEOUT)
    if timeout_s < 1:
        print("错误：timeout_s 必须为正整数。")
        return

    stdin_data = payload.get("stdin_data")
    if stdin_data is not None:
        stdin_data = str(stdin_data)

    base_out, base_err = run_cmd(base_cmd, stdin_data, timeout_s)
    if base_err:
        print(f"错误：baseline 命令失败：{base_err}")
        return
    cand_out, cand_err = run_cmd(cand_cmd, stdin_data, timeout_s)
    if cand_err:
        print(f"错误：candidate 命令失败：{cand_err}")
        return

    base_vec, e1 = parse_vector(base_out, parse_mode)
    if e1:
        print(f"错误：解析 baseline 输出失败：{e1}")
        return
    cand_vec, e2 = parse_vector(cand_out, parse_mode)
    if e2:
        print(f"错误：解析 candidate 输出失败：{e2}")
        return

    print("=== 数值等价校验（equivalence_check）===")
    print(f"baseline     : {base_cmd}")
    print(f"candidate    : {cand_cmd}")
    print(f"容差         : rtol={rtol:.3e}, atol={atol:.3e}（无量纲）")
    print(f"向量长度     : baseline={base_vec.size}, candidate={cand_vec.size}")

    if base_vec.size != cand_vec.size:
        print("整体结论     : FAIL（两侧输出的数值个数不一致，无法逐元素比对）")
        sys.exit(1)

    diff = np.abs(base_vec - cand_vec)
    max_abs = float(diff.max())
    denom = np.abs(base_vec)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(denom > 0, diff / denom, 0.0)
    max_rel = float(np.nanmax(rel)) if rel.size else 0.0
    # 相关系数（长度>1 且非常量时有意义）
    if base_vec.size > 1 and base_vec.std() > 0 and cand_vec.std() > 0:
        corr = float(np.corrcoef(base_vec, cand_vec)[0, 1])
    else:
        corr = float("nan")
    # np.allclose 的判据：|a-b| <= atol + rtol*|b|
    passed = bool(np.allclose(base_vec, cand_vec, rtol=rtol, atol=atol))
    n_exceed = int(np.sum(diff > (atol + rtol * denom)))

    print(f"最大绝对误差 : {max_abs:.6e}")
    print(f"最大相对误差 : {max_rel:.6e}")
    if not math.isnan(corr):
        print(f"相关系数     : {corr:.8f}")
    print(f"超容差元素   : {n_exceed} / {base_vec.size}")
    if passed:
        print("整体结论     : PASS（在给定容差内数值等价）")
    else:
        print("整体结论     : FAIL（存在超容差元素；优化改变了数值行为）")
        sys.exit(1)


if __name__ == "__main__":
    main()

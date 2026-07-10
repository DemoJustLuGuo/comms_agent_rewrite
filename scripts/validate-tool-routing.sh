#!/usr/bin/env bash
# 模型端工具路由验证（对应旧栈 validate-tool-routing）：每个工具一条真实提示词，
# 经 deepseek 走完整会话，断言 ①目标工具被真实调用（--mode json 事件流含 toolName）
# ②输出含结果锚点。两条件同时满足才 PASS。
#
# 用法：scripts/validate-tool-routing.sh [--quick]
#   --quick 跳过依赖外部资源的用例（online_knowledge 联网、MATLAB 引擎）
# 日志：/tmp/route_<tool>.log（失败时查看）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"
export COMMS_APPROVAL=allow-all   # 无头验证：审批门放行（交互审批已另行人工验证）
PI="$ROOT/node_modules/.bin/pi"
MODEL="comms-gateway/deepseek-v4-flash"

# 用例表：工具名|提示词|输出锚点   （提示词刻意点名工具并给全参数，验证的是端到端管路）
CASES=(
  'link_budget|调用 link_budget 工具：发射功率 30 dBm、发射增益 15 dBi、接收增益 12 dBi、载频 2400 MHz、距离 10 km、其他损耗 2 dB，给出接收功率。|-65.04'
  'path_loss|调用 path_loss 工具：model=hata、900 MHz、5 km、市区默认天线高度，给出路径损耗。|路径损耗'
  'ber_snr|调用 ber_snr 工具：QPSK、mode=snr_to_ber、snr_db=8，给出理论 BER。|BER'
  'modulation|调用 modulation 工具：mode=constellation、modulation=QPSK，给出理想星座点。|星座'
  'channel|调用 channel 工具：BPSK、fading=awgn、snr_db=6、num_bits=20000、seed=1，给出经验 BER。|BER'
  'channel_coding|调用 channel_coding 工具：code=hamming_7_4、BPSK、channel=awgn、ebn0_db=[4]、num_bits=4000、seed=1。|编码'
  'capacity|调用 capacity 工具：mode=awgn、bandwidth_hz=1000000、snr_db=10，给出香农容量。|容量'
  'pulse_shaping|调用 pulse_shaping 工具：QPSK、output=impulse、seed=1。|RRC'
  'ofdm|调用 ofdm 工具：metric=papr、n_symbols=50、seed=1。|PAPR'
  'signal_analysis|调用 signal_analysis 工具：signal_file=scripts/dev/fixtures/sig_100hz.txt、sample_rate_hz=1000，报告主要频率峰值。|峰值'
  'frame_parser|调用 frame_parser 工具：hex_data=01020304、format=tlv。|TLV'
  'comms_lint|调用 comms_lint 工具检查文件 scripts/tests/fixtures/lint_clean.py（checks=all）。|体检完成'
  'equivalence_check|调用 equivalence_check 工具：baseline_cmd 和 candidate_cmd 都设为 python -c "print(1.5)"，判定是否等价。|PASS'
  'plot|调用 plot 工具：plot_type=constellation、i=[1,-1,1,-1]、q=[1,1,-1,-1]、title=route_check。|COMM_ARTIFACT'
)
EXTERNAL_CASES=(
  'online_knowledge|调用 online_knowledge 工具查询 RFC 9000（source=rfc），给出标题与 URL。|9000'
  'mcp_matlab_evaluate_matlab_code|调用 mcp_matlab_evaluate_matlab_code 工具执行 MATLAB 代码：disp(6*7)，报告输出。|42'
)
[ "${1:-}" = "--quick" ] || CASES+=("${EXTERNAL_CASES[@]}")

PASS=0; FAIL=0; FAILED_NAMES=""
for case_line in "${CASES[@]}"; do
  tool="${case_line%%|*}"; rest="${case_line#*|}"
  prompt="${rest%%|*}"; anchor="${rest#*|}"
  log="/tmp/route_${tool}.log"
  t0=$(date +%s)
  "$PI" --approve --mode json --no-session --model "$MODEL" -p "$prompt" >"$log" 2>&1
  dt=$(( $(date +%s) - t0 ))
  if grep -q "\"toolName\":\"$tool\"" "$log" && grep -q -- "$anchor" "$log"; then
    printf '[PASS] %-36s（%ss）\n' "$tool" "$dt"; PASS=$((PASS+1))
  else
    printf '[FAIL] %-36s（%ss，详见 %s）\n' "$tool" "$dt" "$log"; FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES $tool"
  fi
done

echo "---"
echo "路由验证：$PASS PASS / $FAIL FAIL（共 $((PASS+FAIL)) 例）"
[ "$FAIL" -eq 0 ] || { echo "失败用例：$FAILED_NAMES"; exit 1; }

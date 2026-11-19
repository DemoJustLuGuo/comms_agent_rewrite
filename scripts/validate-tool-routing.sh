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
  'rf_chain|调用 rf_chain 工具：mode=cascade，两级接收链 LNA(增益15dB,NF1.2dB)+混频器(增益-7dB,NF8dB)，给出总噪声系数。|1.72'
  'interference|调用 interference 工具：mode=ci、载波 -80 dBm、两个干扰源各 -100 dBm，给出载干比。|16.99'
  'channel_profile|调用 channel_profile 工具：载频 2600 MHz、速度 120 km/h、时延扩展 1 微秒，给出多普勒频移与相干带宽。|相干带宽'
  'fade_margin|调用 fade_margin 工具：mode=rain、freq_ghz=23、distance_km=5、rain_rate_mm_h=42、polarization=v，估算雨衰。|雨衰'
  'signal_diagnose|调用 signal_diagnose 工具：signal_file=scripts/dev/fixtures/sig_100hz.txt、sample_rate_hz=1000，做信号诊断。|诊断'
  'sync_estimate|调用 sync_estimate 工具：mode=cfo、modulation=QPSK、sample_rate_hz=1000、i=[0.707,0.628,0.541,0.446]、q=[0.707,0.779,0.841,0.895]，估计载波频偏。|CFO'
  'equalizer|调用 equalizer 工具：equalizer=mmse、channel_taps=[1.0,0.5]、modulation=QPSK、snr_db=20、num_symbols=1000、seed=1，做信道均衡。|残余 ISI'
  'link_adaptation|调用 link_adaptation 工具：snr_db=18、snr_type=es_n0、target_ber=1e-3，选最优 MCS。|推荐'
  'spread_spectrum|调用 spread_spectrum 工具：mode=jam、chip_rate_hz=1023000、data_rate_hz=50、required_ebn0_db=10，给出处理增益与抗干扰余量。|处理增益'
  'beamforming|调用 beamforming 工具：mode=pattern、num_elements=8、spacing_wavelength=0.5、steer_deg=0，给出方向图指标。|阵列增益'
  'ber_snr|调用 ber_snr 工具：QPSK、mode=snr_to_ber、snr_db=8，给出理论 BER。|BER'
  'modulation|调用 modulation 工具：mode=constellation、modulation=QPSK，给出理想星座点。|星座'
  'channel|调用 channel 工具：BPSK、fading=awgn、snr_db=6、num_bits=20000、seed=1，给出经验 BER。|BER'
  'channel_coding|调用 channel_coding 工具：code=hamming_7_4、BPSK、channel=awgn、ebn0_db=[4]、num_bits=4000、seed=1。|编码'
  'channel_coding|调用 channel_coding 工具做 LDPC：code=ldpc_wimax_r12、modulation=BPSK、channel=awgn、ebn0_db=[2]、num_bits=2000、seed=1。|LDPC'
  'channel_coding|调用 channel_coding 工具做 Polar：code=polar_sc_r12、modulation=BPSK、channel=awgn、ebn0_db=[3]、num_bits=256、seed=1。|Polar'
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

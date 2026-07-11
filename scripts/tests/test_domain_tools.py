"""域工具（tools/*.py）单元测试。

以与 TS 桥接完全相同的方式调用工具：
    python -X utf8 <tool>.py '<JSON字符串>'

约定（与工具实现一致）：
- 成功：退出码 0，输出含结果锚点。
- 域校验失败（非法数值/非法帧）：退出码 0，输出以「错误」开头的可读提示。
- 参数结构性错误（非法 JSON、缺必填字段）：非零退出码（异常向上抛，由 TS 层包装）。

运行：
    python -X utf8 scripts/tests/test_domain_tools.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "tools"

try:
    import importlib.util
    _HAS_MPL = importlib.util.find_spec("matplotlib") is not None
except Exception:
    _HAS_MPL = False


def run_tool(name, payload=None, raw_arg=None, timeout=30):
    """调用工具脚本；payload 走 JSON 序列化，raw_arg 用于构造非法参数。"""
    arg = raw_arg if raw_arg is not None else json.dumps(payload, ensure_ascii=False)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS_DIR / f"{name}.py"), arg],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def run_tool_stdin(name, payload, timeout=30):
    """经 stdin 传 JSON 调用工具（模拟 OpenCode TS 桥接的实时路径）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOLS_DIR / f"{name}.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


import re  # noqa: E402


def _extract_float(text, label_pattern):
    """从工具报告里抓 `<label> ... : <数值>` 那一行的第一个浮点数（用于数值断言）。"""
    for line in text.splitlines():
        if re.search(label_pattern, line):
            m = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line.split("：", 1)[-1].split(":", 1)[-1])
            if m:
                return float(m.group(0))
    raise AssertionError(f"未在输出中找到匹配 {label_pattern!r} 的数值行")


class LinkBudgetTests(unittest.TestCase):
    def test_standard_case(self):
        # FSPL = 20log10(10 km) + 20log10(2400 MHz) + 32.44 = 120.04 dB
        r = run_tool("link_budget", {"tx_power_dbm": 30, "tx_gain_dbi": 15, "rx_gain_dbi": 12,
                                     "freq_mhz": 2400, "distance_km": 10, "other_losses_db": 2})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EIRP         = 45.00 dBm", r.stdout)
        self.assertIn("FSPL         = 120.04 dB", r.stdout)
        self.assertIn("-65.04 dBm", r.stdout)

    def test_rejects_non_positive_distance(self):
        r = run_tool("link_budget", {"tx_power_dbm": 30, "tx_gain_dbi": 0, "rx_gain_dbi": 0,
                                     "freq_mhz": 2400, "distance_km": 0})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_missing_field_fails_loudly(self):
        r = run_tool("link_budget", {"distance_km": 10, "freq_mhz": 2400})
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("link_budget", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class BerSnrTests(unittest.TestCase):
    def test_qpsk_snr_to_ber(self):
        # QPSK @ Eb/N0=10 dB：BER = 0.5*erfc(sqrt(10)) ≈ 3.872108e-06
        r = run_tool("ber_snr", {"modulation": "QPSK", "mode": "snr_to_ber", "snr_db": 10})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3.872108e-06", r.stdout)

    def test_roundtrip_ber_to_snr(self):
        r = run_tool("ber_snr", {"modulation": "QPSK", "mode": "ber_to_snr",
                                 "target_ber": 3.872108e-06})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("理论所需 Eb/N0 : 10.00 dB", r.stdout)

    def test_coding_gain_shifts_effective_snr(self):
        r = run_tool("ber_snr", {"modulation": "16QAM", "mode": "snr_to_ber",
                                 "snr_db": 10, "coding_gain_db": 3})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("有效 Eb/N0   : 13.00 dB", r.stdout)

    def test_rejects_out_of_range_target_ber(self):
        r = run_tool("ber_snr", {"modulation": "QPSK", "mode": "ber_to_snr", "target_ber": 0.6})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_missing_snr_fails_loudly(self):
        r = run_tool("ber_snr", {"modulation": "QPSK", "mode": "snr_to_ber"})
        self.assertNotEqual(r.returncode, 0)


class SignalAnalysisTests(unittest.TestCase):
    def test_pure_tone_peak(self):
        # 采样率 8 Hz 下的 2 Hz 正弦，主峰应落在 2.00 Hz
        r = run_tool("signal_analysis", {"signal": [0, 1, 0, -1, 0, 1, 0, -1],
                                         "sample_rate_hz": 8, "window": "rectangular",
                                         "num_peaks": 2})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("f = 2.00 Hz", r.stdout)
        self.assertIn("信号长度     : 8 采样点", r.stdout)

    def test_rejects_empty_signal(self):
        r = run_tool("signal_analysis", {"signal": [], "sample_rate_hz": 8})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_non_positive_sample_rate(self):
        r = run_tool("signal_analysis", {"signal": [1.0, 2.0], "sample_rate_hz": 0})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_stdin_transport(self):
        # OpenCode TS 桥接实时路径：参数经 stdin 传入，绕过 argv 长度上限
        r = run_tool_stdin("signal_analysis", {"signal": [0, 1, 0, -1, 0, 1, 0, -1],
                                               "sample_rate_hz": 8, "window": "rectangular",
                                               "num_peaks": 2})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("f = 2.00 Hz", r.stdout)

    def test_signal_file_input(self):
        # 长信号从文件读入，避免命令行长度限制
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sig.txt"
            path.write_text("0, 1, 0, -1, 0, 1, 0, -1", encoding="utf-8")
            r = run_tool_stdin("signal_analysis", {"signal_file": str(path),
                                                   "sample_rate_hz": 8,
                                                   "window": "rectangular", "num_peaks": 2})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("f = 2.00 Hz", r.stdout)
            self.assertIn("信号长度     : 8 采样点", r.stdout)


class PathLossTests(unittest.TestCase):
    def test_hata_urban(self):
        # Okumura-Hata 城区 900 MHz, hb=30 m, hm=1.5 m, d=1 km ≈ 126.40 dB
        r = run_tool("path_loss", {"model": "hata", "freq_mhz": 900, "distance_km": 1,
                                   "bs_height_m": 30, "ms_height_m": 1.5, "area": "urban"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("路径损耗 PL  : 126.40 dB", r.stdout)

    def test_hata_suburban_lower_than_urban(self):
        urban = run_tool("path_loss", {"model": "hata", "freq_mhz": 900, "distance_km": 5, "area": "urban"})
        sub = run_tool("path_loss", {"model": "hata", "freq_mhz": 900, "distance_km": 5, "area": "suburban"})
        self.assertEqual(sub.returncode, 0, sub.stderr)
        # 郊区损耗应低于城区
        def pl(out):
            return float([l for l in out.splitlines() if "路径损耗 PL" in l][0].split(":")[1].split("dB")[0])
        self.assertLess(pl(sub.stdout), pl(urban.stdout))

    def test_cost231_out_of_range_note(self):
        # 900 MHz 超出 COST-231 的 1500–2000 MHz，应给提示但仍算
        r = run_tool("path_loss", {"model": "cost231", "freq_mhz": 900, "distance_km": 2, "area": "urban"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("超出", r.stdout)

    def test_log_distance_free_space_exponent(self):
        r = run_tool("path_loss", {"model": "log_distance", "freq_mhz": 2400, "distance_km": 2,
                                   "path_loss_exponent": 2.0})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("log-distance", r.stdout)

    def test_cost231_rejects_rural(self):
        r = run_tool("path_loss", {"model": "cost231", "freq_mhz": 1800, "distance_km": 2, "area": "rural"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_non_positive_distance(self):
        r = run_tool("path_loss", {"model": "hata", "freq_mhz": 900, "distance_km": 0})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class FrameParserTests(unittest.TestCase):
    def test_tlv_complete_field(self):
        r = run_tool("frame_parser", {"hex_data": "010002AABB", "format": "tlv"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Tag=0x01, Length=2, Value=AABB", r.stdout)
        self.assertIn("共解析 1 个 TLV 字段", r.stdout)

    def test_tlv_truncated_field_reported(self):
        r = run_tool("frame_parser", {"hex_data": "0101FF", "format": "tlv"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("数据截断", r.stdout)

    def test_ethernet_frame(self):
        hex_data = "FFFFFFFFFFFF" + "112233445566" + "0806" + "0001"
        r = run_tool("frame_parser", {"hex_data": hex_data, "format": "ethernet"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ethernet II", r.stdout)
        self.assertIn("ARP", r.stdout)
        self.assertIn("源 MAC       : 11:22:33:44:55:66", r.stdout)

    def test_custom_spec_with_length_reference(self):
        spec = json.dumps([{"name": "sync", "bytes": 2},
                           {"name": "length", "bytes": 2},
                           {"name": "payload", "bytes": "length"}])
        r = run_tool("frame_parser", {"hex_data": "AA550002BEEF", "format": "custom",
                                      "custom_spec": spec})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0xAA55", r.stdout)
        self.assertIn("0xBEEF", r.stdout)

    def test_rejects_odd_length_hex(self):
        r = run_tool("frame_parser", {"hex_data": "ABC", "format": "tlv"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_illegal_hex_chars(self):
        r = run_tool("frame_parser", {"hex_data": "GGHH", "format": "tlv"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class ModulationTests(unittest.TestCase):
    def test_qpsk_constellation_four_points(self):
        r = run_tool_stdin("modulation", {"mode": "constellation", "modulation": "QPSK"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("星座点数     : 4", r.stdout)
        self.assertIn("每符号比特   : 2", r.stdout)

    def test_16qam_constellation_count(self):
        r = run_tool_stdin("modulation", {"mode": "constellation", "modulation": "16QAM"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("星座点数     : 16", r.stdout)

    def test_evm_of_ideal_points_is_zero(self):
        # 用理想点本身做 evm 应接近 0
        r = run_tool_stdin("modulation", {"mode": "evm", "modulation": "QPSK",
                                          "i": [1, 0, 0, -1], "q": [0, 1, -1, 0]})
        self.assertEqual(r.returncode, 0, r.stderr)
        evm = float([l for l in r.stdout.splitlines() if "EVM (RMS)" in l][0].split(":")[1].split("%")[0])
        self.assertLess(evm, 1e-6)

    def test_modulate_requires_bits(self):
        r = run_tool_stdin("modulation", {"mode": "modulate", "modulation": "QPSK"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class ChannelTests(unittest.TestCase):
    @staticmethod
    def _emp_ber(out):
        return float([l for l in out.splitlines() if "经验 BER" in l][0].split(":")[1])

    def test_awgn_matches_theory(self):
        # QPSK AWGN 8 dB：经验 BER 应接近理论 ~1.9e-4
        r = run_tool("channel", {"modulation": "QPSK", "snr_db": 8, "fading": "awgn",
                                 "num_bits": 400000, "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        emp = self._emp_ber(r.stdout)
        self.assertTrue(5e-5 < emp < 6e-4, f"empirical BER {emp} 偏离理论过大")

    def test_rayleigh_worse_than_awgn(self):
        awgn = run_tool("channel", {"modulation": "QPSK", "snr_db": 8, "fading": "awgn",
                                    "num_bits": 200000, "seed": 3})
        ray = run_tool("channel", {"modulation": "QPSK", "snr_db": 8, "fading": "rayleigh",
                                   "num_bits": 200000, "seed": 3})
        self.assertGreater(self._emp_ber(ray.stdout), self._emp_ber(awgn.stdout))

    def test_reproducible_with_seed(self):
        a = run_tool("channel", {"modulation": "16QAM", "snr_db": 12, "num_bits": 100000, "seed": 7})
        b = run_tool("channel", {"modulation": "16QAM", "snr_db": 12, "num_bits": 100000, "seed": 7})
        self.assertEqual(self._emp_ber(a.stdout), self._emp_ber(b.stdout))

    def test_rejects_bad_modulation(self):
        r = run_tool("channel", {"modulation": "FOO", "snr_db": 8})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


@unittest.skipUnless(_HAS_MPL, "matplotlib not installed")
class PlotTests(unittest.TestCase):
    @staticmethod
    def _artifact(stdout):
        prefix = "COMM_ARTIFACT: "
        line = next((line for line in stdout.splitlines() if line.startswith(prefix)), "")
        if not line:
            raise AssertionError("plot 输出缺少 COMM_ARTIFACT 标记")
        return json.loads(line[len(prefix):])

    def test_constellation_creates_png(self):
        out = PROJECT_ROOT / "plots" / "_test_constellation.png"
        if out.exists():
            out.unlink()
        r = run_tool_stdin("plot", {"plot_type": "constellation", "i": [1, -1, 1, -1],
                                    "q": [1, 1, -1, -1],
                                    "output_path": "plots/_test_constellation.png"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("已生成图像", r.stdout)
        self.assertTrue(out.exists() and out.stat().st_size > 0)
        artifact = self._artifact(r.stdout)
        self.assertEqual(artifact["version"], 1)
        self.assertEqual(artifact["kind"], "image")
        self.assertEqual(artifact["tool"], "plot")
        self.assertEqual(artifact["path"], "plots/_test_constellation.png")
        self.assertEqual(artifact["mime"], "image/png")
        self.assertEqual(artifact["meta"]["plot_type"], "constellation")
        # Web UI 内联行：绝对路径、盘符冒号已编码（pi-web /api/files 只认绝对路径）
        md_line = next((l for l in r.stdout.splitlines() if l.startswith("Markdown 内联")), "")
        self.assertIn("](/api/files/", md_line)
        self.assertIn("%3A", md_line)
        self.assertIn("_test_constellation.png?type=download)", md_line)

    def test_cwd_independent_output(self):
        # pi-web 下 pi 进程 cwd 是 pi-web 包目录——plot 必须锚定项目根，不随 cwd 漂移
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(TOOLS_DIR / "plot.py")],
            input=json.dumps({"plot_type": "constellation", "i": [1], "q": [1],
                              "output_path": "plots/_test_cwd_anchor.png"}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, cwd=tempfile.gettempdir())
        self.assertEqual(r.returncode, 0, r.stderr)
        out = PROJECT_ROOT / "plots" / "_test_cwd_anchor.png"
        self.assertTrue(out.exists() and out.stat().st_size > 0)
        out.unlink()

    def test_ber_curve_series(self):
        out = PROJECT_ROOT / "plots" / "_test_ber_curve.png"
        if out.exists():
            out.unlink()
        r = run_tool_stdin("plot", {"plot_type": "ber_curve",
                                    "output_path": "plots/_test_ber_curve.png",
                                    "series": [{"label": "QPSK", "snr_db": [0, 4, 8],
                                                "ber": [0.08, 0.01, 3e-4]}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        artifact = self._artifact(r.stdout)
        self.assertEqual(artifact["path"], "plots/_test_ber_curve.png")
        self.assertEqual(artifact["title"], "ber_curve")

    def test_rejects_unknown_type(self):
        r = run_tool_stdin("plot", {"plot_type": "foo"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_output_outside_plots(self):
        r = run_tool_stdin("plot", {"plot_type": "constellation", "i": [1], "q": [1],
                                    "output_path": "../outside.png"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("只能写入项目 plots/ 目录", r.stdout)


class CapacityTests(unittest.TestCase):
    @staticmethod
    def _val(stdout, label):
        line = [l for l in stdout.splitlines() if label in l][0]
        return float(line.split(":")[1].split("bit")[0])

    def test_awgn_shannon(self):
        # C/B = log2(1+100) = 6.6582 bit/s/Hz；C = 20e6 * 6.6582 ≈ 1.3316e8 bit/s
        r = run_tool("capacity", {"mode": "awgn", "bandwidth_hz": 20e6, "snr_db": 20})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("6.6582 bit/s/Hz", r.stdout)
        self.assertIn("1.3316e+08 bit/s", r.stdout)

    def test_ebn0_min_matches_closed_form(self):
        # η=4：最小 Eb/N0 = (2^4-1)/4 = 3.75 → 5.7403 dB
        r = run_tool("capacity", {"mode": "ebn0", "spectral_efficiency": 4})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("5.7403 dB", r.stdout)

    def test_mimo_waterfilling_not_below_equal(self):
        # 同一信道集合上注水容量不应低于等功率容量
        r = run_tool("capacity", {"mode": "mimo", "nt": 4, "nr": 4, "snr_db": 20,
                                  "realizations": 100, "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(self._val(r.stdout, "注水容量"),
                                self._val(r.stdout, "等功率容量") - 1e-9)

    def test_mimo_reproducible_with_seed(self):
        a = run_tool("capacity", {"mode": "mimo", "nt": 2, "nr": 2, "snr_db": 10,
                                  "realizations": 50, "seed": 5})
        b = run_tool("capacity", {"mode": "mimo", "nt": 2, "nr": 2, "snr_db": 10,
                                  "realizations": 50, "seed": 5})
        self.assertEqual(a.stdout, b.stdout)

    def test_rejects_unknown_mode(self):
        r = run_tool("capacity", {"mode": "bogus"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_awgn_missing_field_is_domain_error(self):
        r = run_tool("capacity", {"mode": "awgn", "snr_db": 20})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("capacity", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class CommsLintTests(unittest.TestCase):
    BAD = "scripts/tests/fixtures/lint_bad.py"
    CLEAN = "scripts/tests/fixtures/lint_clean.py"

    def test_bad_fixture_flags_all_categories(self):
        r = run_tool("comms_lint", {"path": self.BAD, "checks": "all"})
        self.assertEqual(r.returncode, 0, r.stderr)
        for tag in ("[units]", "[repro]", "[secrets]", "[protocol]", "[numpy]"):
            self.assertIn(tag, r.stdout)
        self.assertIn("体检完成：1 error, 3 warn, 2 info", r.stdout)

    def test_secret_value_not_echoed(self):
        # 疑似密钥只报 file:line 与标签，绝不回显密钥值
        r = run_tool("comms_lint", {"path": self.BAD, "checks": "secrets"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[secrets]", r.stdout)
        self.assertNotIn("not-a-real-key-please-use-env", r.stdout)

    def test_clean_fixture_no_findings(self):
        r = run_tool("comms_lint", {"path": self.CLEAN, "checks": "all"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未发现问题", r.stdout)

    def test_selected_check_scopes_output(self):
        r = run_tool("comms_lint", {"path": self.BAD, "checks": "repro"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[repro]", r.stdout)
        self.assertNotIn("[secrets]", r.stdout)

    def test_rejects_path_outside_root(self):
        r = run_tool("comms_lint", {"path": "../../../etc/passwd"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)
        self.assertIn("越界", r.stdout)

    def test_rejects_non_source_file(self):
        r = run_tool("comms_lint", {"path": "README.md"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_missing_path_is_domain_error(self):
        r = run_tool("comms_lint", {})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_strict_exits_nonzero_on_error(self):
        r = run_tool("comms_lint", {"path": self.BAD, "checks": "all", "strict": True})
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("comms_lint", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class ChannelCodingTests(unittest.TestCase):
    @staticmethod
    def _bers(stdout):
        # 解析表格数据行：Eb/N0 | 未编码 BER | 编码后 BER
        rows = []
        for line in stdout.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                try:
                    rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
                except ValueError:
                    pass
        return rows

    def test_conv_soft_beats_uncoded(self):
        # 软判决卷积码在低 Eb/N0 应显著优于未编码
        r = run_tool("channel_coding", {"code": "conv_k7_r12", "modulation": "QPSK",
                     "channel": "awgn", "ebn0_db": [2], "num_bits": 2500,
                     "decision": "soft", "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self._bers(r.stdout)
        self.assertTrue(rows, "未解析到 BER 表格")
        _, uncoded, coded = rows[0]
        self.assertLess(coded, uncoded)

    def test_hamming_high_ebn0_zero_errors(self):
        r = run_tool("channel_coding", {"code": "hamming_7_4", "modulation": "QPSK",
                     "channel": "awgn", "ebn0_db": [15], "num_bits": 8000, "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.5714", r.stdout)      # 码率 4/7
        self.assertEqual(self._bers(r.stdout)[0][2], 0.0)

    def test_rs_runs_and_rate(self):
        r = run_tool("channel_coding", {"code": "rs_255_223", "modulation": "QPSK",
                     "channel": "awgn", "ebn0_db": [7], "num_bits": 40000, "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.8745", r.stdout)      # 码率 223/255

    def test_reproducible_with_seed(self):
        a = run_tool("channel_coding", {"code": "hamming_7_4", "modulation": "QPSK",
                     "channel": "awgn", "ebn0_db": [5], "num_bits": 8000, "seed": 7})
        b = run_tool("channel_coding", {"code": "hamming_7_4", "modulation": "QPSK",
                     "channel": "awgn", "ebn0_db": [5], "num_bits": 8000, "seed": 7})
        self.assertEqual(a.stdout, b.stdout)

    def test_soft_falls_back_for_unsupported(self):
        r = run_tool("channel_coding", {"code": "hamming_7_4", "modulation": "QPSK",
                     "ebn0_db": [10], "num_bits": 4000, "decision": "soft", "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("回退硬判决", r.stdout)

    def test_rejects_bad_code(self):
        r = run_tool("channel_coding", {"code": "ldpc", "modulation": "QPSK"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_bad_modulation(self):
        r = run_tool("channel_coding", {"code": "hamming_7_4", "modulation": "FOO"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rs_too_few_bits(self):
        r = run_tool("channel_coding", {"code": "rs_255_223", "modulation": "QPSK",
                     "ebn0_db": [7], "num_bits": 100, "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("channel_coding", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class PulseShapingTests(unittest.TestCase):
    def test_rrc_impulse_energy_normalized(self):
        # RRC 抽头能量 ∑h²=1（能量归一），报告应体现。
        r = run_tool("pulse_shaping", {"modulation": "QPSK", "filter": "rrc",
                     "beta": 0.35, "sps": 8, "span_symbols": 10, "output": "impulse"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("能量 ∑h²     : 1.0000", r.stdout)
        self.assertIn("抽头数 81", r.stdout)

    def test_beta_zero_bandwidth(self):
        # β=0 时单边带宽应为 0.5·Rs（sinc 脉冲）。
        r = run_tool("pulse_shaping", {"modulation": "BPSK", "filter": "rrc",
                     "beta": 0.0, "sps": 8, "span_symbols": 10, "output": "impulse"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.5000·Rs", r.stdout)

    def test_eye_clean_channel_open(self):
        # RRC 发+收匹配 = RC 奈奎斯特，无噪采样点应几乎无 ISI，眼张开度接近 1。
        r = run_tool("pulse_shaping", {"modulation": "QPSK", "filter": "rrc",
                     "beta": 0.35, "sps": 8, "span_symbols": 10,
                     "num_symbols": 400, "output": "eye", "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        eye = _extract_float(r.stdout, "眼张开度")
        self.assertGreater(eye, 0.8)
        isi = _extract_float(r.stdout, "峰值 ISI")
        self.assertLess(isi, 0.1)
        self.assertIn("PLOT_EYE_INPUT:", r.stdout)  # 附带可交 plot 的字段

    def test_psd_peak_near_dc(self):
        # 基带成形信号谱峰应在通带内（0 dB 相对峰值），带边显著衰减。
        r = run_tool("pulse_shaping", {"modulation": "QPSK", "filter": "rc",
                     "beta": 0.5, "sps": 8, "span_symbols": 10,
                     "num_symbols": 400, "output": "psd", "seed": 1})
        self.assertEqual(r.returncode, 0, r.stderr)
        dc = _extract_float(r.stdout, r"PSD\(f=0\)")
        edge = _extract_float(r.stdout, "PSD\\(f=±带宽\\)")
        self.assertGreater(dc, -6.0)      # 通带内接近峰值
        self.assertLess(edge, -20.0)      # 带边强抑制

    def test_reproducible(self):
        p = {"modulation": "QPSK", "filter": "rrc", "beta": 0.35, "sps": 8,
             "span_symbols": 10, "num_symbols": 300, "output": "eye", "seed": 42}
        r1 = run_tool("pulse_shaping", p)
        r2 = run_tool("pulse_shaping", p)
        self.assertEqual(r1.stdout, r2.stdout)

    def test_rejects_bad_beta(self):
        r = run_tool("pulse_shaping", {"modulation": "QPSK", "beta": 1.5})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_bad_filter(self):
        r = run_tool("pulse_shaping", {"modulation": "QPSK", "filter": "gaussian"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("pulse_shaping", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class OfdmTests(unittest.TestCase):
    def test_ber_awgn_low_snr(self):
        # QPSK OFDM AWGN 在中等 Eb/N0 应有可测非零 BER，且与单载波量级一致。
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "cp_len": 16,
                     "modulation": "QPSK", "channel": "awgn", "snr_db": 8,
                     "metric": "ber", "n_symbols": 2000, "seed": 1}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        ber = _extract_float(r.stdout, "经验 BER")
        self.assertGreater(ber, 1e-5)
        self.assertLess(ber, 1e-2)

    def test_multipath_cp_sufficient_equalizes(self):
        # CP 足够时频域单抽头均衡应基本消除多径，高 SNR 下 BER 极低。
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "cp_len": 16,
                     "modulation": "QPSK", "channel": "multipath",
                     "channel_taps_db": [0, -3, -6], "snr_db": 25,
                     "metric": "ber", "n_symbols": 1500, "seed": 1}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CP 充足", r.stdout)

    def test_multipath_cp_insufficient_warns(self):
        # CP 短于时延扩展应给出不足告警。
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "cp_len": 2,
                     "modulation": "QPSK", "channel": "multipath",
                     "channel_taps_db": [0, -3, -6, -9, -12], "snr_db": 20,
                     "metric": "ber", "n_symbols": 500, "seed": 1}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CP 不足", r.stdout)

    def test_papr_reasonable(self):
        # 52 子载波 OFDM 的平均 PAPR 量级约 6~9 dB。
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "cp_len": 16,
                     "modulation": "16QAM", "metric": "papr",
                     "n_symbols": 500, "seed": 1}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        papr = _extract_float(r.stdout, "PAPR 均值")
        self.assertGreater(papr, 4.0)
        self.assertLess(papr, 12.0)
        self.assertIn("CCDF", r.stdout)

    def test_spectrum_occupied_bw(self):
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "cp_len": 16,
                     "modulation": "16QAM", "metric": "spectrum",
                     "n_symbols": 300, "seed": 1}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("占用带宽", r.stdout)

    def test_reproducible(self):
        p = {"n_fft": 64, "n_used": 52, "cp_len": 16, "modulation": "QPSK",
             "channel": "awgn", "snr_db": 10, "metric": "ber",
             "n_symbols": 800, "seed": 7}
        r1 = run_tool("ofdm", p, timeout=60)
        r2 = run_tool("ofdm", p, timeout=60)
        self.assertEqual(r1.stdout, r2.stdout)

    def test_rejects_bad_n_used(self):
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 64, "modulation": "QPSK"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_rejects_bad_modulation(self):
        r = run_tool("ofdm", {"n_fft": 64, "n_used": 52, "modulation": "FOO"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("ofdm", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class EquivalenceCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="equiv_test_"))

    def tearDown(self):
        for f in self.tmp.glob("*"):
            f.unlink()
        self.tmp.rmdir()

    def _write(self, name, body):
        p = self.tmp / name
        p.write_text(body, encoding="utf-8")
        return p

    def _cmd(self, path):
        return f'"{sys.executable}" "{path}"'

    def test_equal_pass(self):
        base = self._write("base.py", "print('1.0 2.0 3.0 4.0 5.0')")
        cand = self._write("same.py", "import json; print(json.dumps([1,2,3,4,5]))")
        r = run_tool("equivalence_check", {"baseline_cmd": self._cmd(base),
                     "candidate_cmd": self._cmd(cand)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_diff_fail_nonzero_exit(self):
        base = self._write("base.py", "print('1.0 2.0 3.0')")
        cand = self._write("diff.py", "print('1.0 2.0 9.0')")
        r = run_tool("equivalence_check", {"baseline_cmd": self._cmd(base),
                     "candidate_cmd": self._cmd(cand)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL", r.stdout)

    def test_tiny_diff_within_rtol_pass(self):
        base = self._write("base.py", "print('1000000.0')")
        cand = self._write("tiny.py", "print('1000000.1')")
        r = run_tool("equivalence_check", {"baseline_cmd": self._cmd(base),
                     "candidate_cmd": self._cmd(cand), "rtol": 1e-6, "atol": 1e-9})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_length_mismatch_fail(self):
        base = self._write("base.py", "print('1 2 3 4 5')")
        cand = self._write("short.py", "print('1 2 3')")
        r = run_tool("equivalence_check", {"baseline_cmd": self._cmd(base),
                     "candidate_cmd": self._cmd(cand)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不一致", r.stdout)

    def test_missing_cmd(self):
        r = run_tool("equivalence_check", {"baseline_cmd": "python -c pass"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_cmd_not_found(self):
        r = run_tool("equivalence_check", {"baseline_cmd": "nonexistent_binary_xyz",
                     "candidate_cmd": "nonexistent_binary_xyz"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("命令未找到", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("equivalence_check", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class EquivalenceCheckTests(unittest.TestCase):
    """F6：跑两条命令比对数值。用临时脚本构造 baseline/candidate。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="equiv_test_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _script(self, name, body):
        p = self.tmp / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_identical_pass(self):
        base = self._script("base.py", "print('1.0 2.0 3.0 4.0 5.0')")
        cand = self._script("cand.py", "import json; print(json.dumps([1,2,3,4,5]))")
        r = run_tool("equivalence_check", {
            "baseline_cmd": f'{sys.executable} "{base}"',
            "candidate_cmd": f'{sys.executable} "{cand}"'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_difference_fail_nonzero_exit(self):
        base = self._script("base.py", "print('1.0 2.0 3.0')")
        cand = self._script("cand.py", "print('1.0 2.0 9.0')")
        r = run_tool("equivalence_check", {
            "baseline_cmd": f'{sys.executable} "{base}"',
            "candidate_cmd": f'{sys.executable} "{cand}"'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL", r.stdout)

    def test_within_rtol_pass(self):
        base = self._script("base.py", "print('1000000.0')")
        cand = self._script("cand.py", "print('1000000.1')")  # rel ~1e-7 < 1e-6
        r = run_tool("equivalence_check", {
            "baseline_cmd": f'{sys.executable} "{base}"',
            "candidate_cmd": f'{sys.executable} "{cand}"'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_length_mismatch_fail(self):
        base = self._script("base.py", "print('1 2 3 4 5')")
        cand = self._script("cand.py", "print('1 2 3')")
        r = run_tool("equivalence_check", {
            "baseline_cmd": f'{sys.executable} "{base}"',
            "candidate_cmd": f'{sys.executable} "{cand}"'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL", r.stdout)

    def test_command_not_found(self):
        r = run_tool("equivalence_check", {
            "baseline_cmd": "definitely_not_a_real_cmd_xyz",
            "candidate_cmd": "echo 1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_missing_cmd(self):
        r = run_tool("equivalence_check", {"baseline_cmd": "echo 1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)

    def test_malformed_json_fails_loudly(self):
        r = run_tool("equivalence_check", raw_arg="{not json")
        self.assertNotEqual(r.returncode, 0)


class RfChainTests(unittest.TestCase):
    def test_cascade_friis_known_value(self):
        # F1=10^0.12=1.3183, F2=10^0.8=6.3096, G1=10^1.5=31.623
        # F = 1.3183 + 5.3096/31.623 = 1.4862 → 1.72 dB
        r = run_tool("rf_chain", {"mode": "cascade", "stages": [
            {"name": "LNA", "gain_db": 15, "nf_db": 1.2},
            {"name": "Mixer", "gain_db": -7, "nf_db": 8}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, r"总噪声系数 NF"), 1.72, places=2)
        self.assertAlmostEqual(_extract_float(r.stdout, "总增益"), 8.00, places=2)

    def test_noise_floor_290k(self):
        # -173.98 dBm/Hz + 10log10(1e6) = -113.98 dBm
        r = run_tool("rf_chain", {"mode": "noise_floor", "bandwidth_hz": 1e6})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, "噪声底"), -113.98, places=2)

    def test_sensitivity_with_direct_nf(self):
        # -113.98 + 5 + 10 = -98.98 dBm
        r = run_tool("rf_chain", {"mode": "sensitivity", "bandwidth_hz": 1e6,
                                  "nf_db": 5, "required_snr_db": 10})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, "接收灵敏度"), -98.98, places=2)

    def test_cascade_requires_stages(self):
        r = run_tool("rf_chain", {"mode": "cascade"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class InterferenceTests(unittest.TestCase):
    def test_ci_two_equal_interferers(self):
        # 两个 -100 dBm 线性叠加 = -96.99 dBm；C/I = -80 - (-96.99) = 16.99 dB
        r = run_tool("interference", {"mode": "ci", "carrier_dbm": -80,
                                      "interferers": [{"power_dbm": -100}, {"power_dbm": -100}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, r"C/I"), 16.99, places=2)

    def test_sinr_with_ktb_noise(self):
        r = run_tool("interference", {"mode": "sinr", "carrier_dbm": -80,
                                      "interferers": [{"power_dbm": -95}],
                                      "bandwidth_hz": 1e7, "nf_db": 5, "required_ci_db": 12})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SINR", r.stdout)
        self.assertIn("余量", r.stdout)

    def test_empty_interferers_rejected(self):
        r = run_tool("interference", {"mode": "ci", "carrier_dbm": -80, "interferers": []})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class ChannelProfileTests(unittest.TestCase):
    def test_doppler_known_value(self):
        # fd = (120/3.6)·2600e6/c = 289.09 Hz
        r = run_tool("channel_profile", {"freq_mhz": 2600, "speed_kmh": 120})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, "多普勒频移"), 289.09, places=1)

    def test_coherence_bandwidth(self):
        # Bc = 1/(5·1e-6) = 200 kHz
        r = run_tool("channel_profile", {"delay_spread_us": 1.0})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, "相干带宽"), 200.0, places=1)

    def test_classification_slow_flat(self):
        r = run_tool("channel_profile", {"freq_mhz": 2600, "speed_kmh": 120,
                                         "delay_spread_us": 1.0, "symbol_rate_sps": 15000})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("慢衰落", r.stdout)
        self.assertIn("平坦衰落", r.stdout)

    def test_requires_at_least_one_group(self):
        r = run_tool("channel_profile", {})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class FadeMarginTests(unittest.TestCase):
    def test_margin_simple(self):
        r = run_tool("fade_margin", {"mode": "margin", "rx_power_dbm": -72,
                                     "sensitivity_dbm": -95, "required_margin_db": 20})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(_extract_float(r.stdout, "衰落余量"), 23.0, places=2)
        self.assertIn("满足", r.stdout)

    def test_rain_reasonable_range(self):
        # 23 GHz / 5 km / 42 mm/h 垂直极化：工程量级 10~30 dB
        r = run_tool("fade_margin", {"mode": "rain", "freq_ghz": 23, "distance_km": 5,
                                     "rain_rate_mm_h": 42, "polarization": "v"})
        self.assertEqual(r.returncode, 0, r.stderr)
        atten = _extract_float(r.stdout, r"雨衰 A")
        self.assertGreater(atten, 5.0)
        self.assertLess(atten, 40.0)
        self.assertIn("近似", r.stdout)  # 必须转述近似口径

    def test_rain_rejects_out_of_band(self):
        r = run_tool("fade_margin", {"mode": "rain", "freq_ghz": 60, "distance_km": 5,
                                     "rain_rate_mm_h": 42})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


class SignalDiagnoseTests(unittest.TestCase):
    def _sine(self, n=4096, fs=10000.0, freq=440.0):
        import math as _m
        return [_m.sin(2 * _m.pi * freq * k / fs) for k in range(n)]

    def test_clean_sine_no_symptoms(self):
        r = run_tool_stdin("signal_diagnose", {"signal": self._sine(), "sample_rate_hz": 10000})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未触发症状", r.stdout)

    def test_dc_offset_detected(self):
        sig = [x + 0.3 for x in self._sine()]
        r = run_tool_stdin("signal_diagnose", {"signal": sig, "sample_rate_hz": 10000})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DC 偏置显著", r.stdout)

    def test_clipping_detected(self):
        sig = [max(-0.8, min(0.8, 1.3 * x)) for x in self._sine()]
        r = run_tool_stdin("signal_diagnose", {"signal": sig, "sample_rate_hz": 10000})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("疑似削波", r.stdout)

    def test_iq_imbalance_detected(self):
        import math as _m
        n, fs = 4096, 10000.0
        i = [1.1 * _m.cos(2 * _m.pi * 440 * k / fs) for k in range(n)]
        q = [_m.sin(2 * _m.pi * 440 * k / fs + _m.radians(5)) for k in range(n)]
        r = run_tool_stdin("signal_diagnose", {"i": i, "q": q, "sample_rate_hz": fs})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("IQ 失衡", r.stdout)

    def test_too_short_rejected(self):
        r = run_tool_stdin("signal_diagnose", {"signal": [0.1] * 8, "sample_rate_hz": 1000})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

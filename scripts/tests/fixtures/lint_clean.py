# comms_lint 测试样例：规范写法，不应产生告警（被 test_domain_tools.py 引用）。
import numpy as np


def make_tone(freq_hz, sample_rate_hz, n_samples):
    """生成单音；freq_hz 单位 Hz，sample_rate_hz 单位 Hz。"""
    rng = np.random.default_rng(12345)
    noise = rng.standard_normal(n_samples)      # 线性幅度，无量纲
    t = np.arange(n_samples) / sample_rate_hz   # s
    return np.cos(2 * np.pi * freq_hz * t) + 0.0 * noise

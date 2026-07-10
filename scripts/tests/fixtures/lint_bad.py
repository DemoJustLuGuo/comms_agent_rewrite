# comms_lint 测试样例：故意触发各检查项，请勿"修复"（被 test_domain_tools.py 与 check_runtime.py 引用）。
import math
import struct

import numpy as np

freq = 2400.0
samples = np.random.rand(64)
api_key = "not-a-real-key-please-use-env"


def fft(x):
    # 手写 FFT 占位，用于触发 numpy 检查
    return x


def demod(buf):
    return struct.unpack(">I", buf)


def q(x):
    return math.erf(x)

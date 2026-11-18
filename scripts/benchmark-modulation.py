"""ModulationPy 实验基准：耗时单位 ms，输出符号和判决为归一化/无量纲。"""
import argparse
import importlib
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--vector-only", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    sys.path.insert(0, str(project))
    module = importlib.import_module("ModulationPy.ModulationPy")
    rng = np.random.default_rng(args.seed)
    bits = rng.integers(0, 2, size=4096)
    modem = module.QAMModem(16, gray_map=True, bin_input=True, soft_decision=False, bin_output=True)
    durations_ms = []
    for _iteration in range(7):
        started = time.perf_counter()
        symbols = modem.modulate(bits)
        decoded = modem.demodulate(symbols)
        durations_ms.append((time.perf_counter() - started) * 1000)
    np.testing.assert_array_equal(bits, decoded)
    vector = np.concatenate((symbols.real, symbols.imag, decoded.astype(float))).tolist()
    if args.vector_only:
        print(json.dumps(vector, allow_nan=False))
        return
    print("COMMS_EXPERIMENT_RESULT=" + json.dumps({
        "metric": {"name": "roundtrip_ms", "unit": "ms", "value": statistics.median(durations_ms)},
        "vector": vector,
        "seed": args.seed,
    }, allow_nan=False))


if __name__ == "__main__":
    main()

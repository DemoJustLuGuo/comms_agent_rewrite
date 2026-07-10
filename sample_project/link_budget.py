"""
链路预算计算（优化版）
======================
计算不同距离下的接收功率 Prx（dBm）。

公式:
  FSPL(dB) = 20·log10(d_km) + 20·log10(f_MHz) + 32.44
  Prx(dBm) = Ptx(dBm) + Gtx(dBi) + Grx(dBi) - FSPL(dB) - L_other(dB)

优化变更：
  - 语义变量名 + 单位后缀（_dbm / _dbi / _mhz / _km / _db）
  - NumPy 向量化消除显式循环
  - 纯计算函数与输出分离
  - 完整 docstring
  行为与原始代码计算结果完全等价。
"""

import math
import numpy as np


def link_budget_np(tx_power_dbm: float, tx_gain_dbi: float, rx_gain_dbi: float,
                   freq_mhz: float, other_losses_db: float,
                   distances_km: np.ndarray) -> np.ndarray:
    """计算多个距离下的接收功率（向量化版本）。

    Parameters
    ----------
    tx_power_dbm : float
        发射功率, dBm
    tx_gain_dbi : float
        发射天线增益, dBi
    rx_gain_dbi : float
        接收天线增益, dBi
    freq_mhz : float
        载波频率, MHz
    other_losses_db : float
        其他系统损耗（馈线 / 大气等）, dB
    distances_km : np.ndarray
        距离数组, km

    Returns
    -------
    np.ndarray
        接收功率 Prx, dBm
    """
    fspl_db = 20.0 * np.log10(distances_km) + 20.0 * np.log10(freq_mhz) + 32.44
    prx_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - fspl_db - other_losses_db
    return prx_dbm


def print_results(distances_km: np.ndarray, prx_dbm: np.ndarray) -> None:
    """打印距离与接收功率对照表。

    Parameters
    ----------
    distances_km : np.ndarray
        距离数组, km
    prx_dbm : np.ndarray
        接收功率数组, dBm
    """
    for d, p in zip(distances_km, prx_dbm):
        print(f"distance {d} -> {round(p, 2)}")


def run():
    # --- 链路参数（单位均已标注） ---
    tx_power_dbm: float = 23.0      # 发射功率, dBm（典型 Wi-Fi 功率）
    tx_gain_dbi: float = 15.0       # 发射天线增益, dBi
    rx_gain_dbi: float = 12.0       # 接收天线增益, dBi
    freq_mhz: float = 2400.0        # 载波频率, MHz
    other_losses_db: float = 2.0    # 其他损耗, dB

    # 距离列表, km（与原始代码完全一致）
    distances_km: np.ndarray = np.array([1, 2, 5, 10, 20, 50, 100], dtype=float)

    # 向量化计算
    prx_dbm = link_budget_np(tx_power_dbm, tx_gain_dbi, rx_gain_dbi,
                             freq_mhz, other_losses_db, distances_km)

    # 打印结果
    print_results(distances_km, prx_dbm)

    return prx_dbm.tolist()


if __name__ == "__main__":
    run()

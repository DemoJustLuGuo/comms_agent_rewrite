---
description: RF 链路速算（自由空间链路预算 / 城区路径损耗）
argument-hint: "<发射功率/增益/频率/距离等参数>"
---
根据下面的参数做 RF 链路计算：$ARGUMENTS

要求：
1. 自由空间链路预算（FSPL / EIRP / 接收功率）调用 `link_budget` 工具。
2. 城区/郊区/蜂窝等实际传播损耗调用 `path_loss` 工具，按频段选合适模型（Okumura-Hata 150–1500 MHz、COST-231-Hata 1500–2000 MHz、或对数距离）。
3. 不要心算；给出结果并标注单位、所用模型及其适用范围。

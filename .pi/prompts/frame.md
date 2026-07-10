---
description: 解析一段协议帧（Ethernet / TLV / 自定义）
argument-hint: "<十六进制帧数据>"
---
解析这段十六进制帧数据：$ARGUMENTS

要求：
1. 调用 `frame_parser` 工具；先判断并说明帧格式（ethernet / tlv / custom）。
2. 给出逐字段解析结果，明确指出任何截断、非法字符或校验异常。

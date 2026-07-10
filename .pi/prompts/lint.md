---
description: 通信代码体检（单位/复现/NumPy/协议/密钥，提示非拦截）
argument-hint: "<.py 或 .m 文件路径>"
---
对下面的文件做通信代码体检：$ARGUMENTS

要求：
1. 必须调用 `comms_lint` 工具检查目标 .py/.m 文件（默认 checks=all）。
2. 按 error/warn/info 归纳发现，给出可执行修改建议；这是提示非拦截，不要因告警阻断优化，但应说明保留或修正的理由。
3. 不回显任何疑似密钥值。

---
description: 数值等价校验（优化回归护栏）
argument-hint: "<baseline 命令> <candidate 命令>"
---
调用 `equivalence_check` 工具，对同一组输入分别运行 baseline 与 candidate 两条命令，比对 stdout 数值向量的相对/绝对误差、最大绝对误差、相关系数，超阈值即 FAIL。用于优化改动数值代码后判定「行为是否等价」。

参数：$ARGUMENTS

说明：该工具会直接执行传入的两条命令，执行前经审批门确认——只应传入受信的等价验证命令（跑本项目脚本、对比新旧实现），不要用它执行与验证无关的命令。默认 rtol=1e-6、atol=1e-9，可按精度需求调整。

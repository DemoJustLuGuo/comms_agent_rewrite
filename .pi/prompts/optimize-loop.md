---
description: 对 real_projects/ModulationPy 跑一次低风险优化闭环
argument-hint: "[额外要求]"
---
按下述流程对 `real_projects/ModulationPy` 跑一次低风险优化闭环。动手前先读取：

- `docs/real_project_integration.md`：确认真实项目路径、允许修改范围、验证命令与验收标准。
- `docs/model_output_review_checklist.md`：确认最终审阅和保留/回退标准。

1. 先只读读懂 `real_projects/ModulationPy/ModulationPy/ModulationPy.py`，用一两句话说明现状与可改进点。
2. 提出低风险优化方案（补单位/通信含义注释、输入校验错误提示、整理重复逻辑），**保持与 tests.py 行为完全等价**。
3. 每次改文件、运行验证命令都会触发审批弹窗，等用户同意后再继续。验证命令用 `scripts/check-real-project.sh`（Git Bash / Linux / macOS 通用）。
4. 改完运行验证并给出前后对比、风险说明，以及按审阅清单得出的「建议保留/建议回退」结论；数值行为改动用 `equivalence_check` 给出等价证据。

额外要求（可为空）：$ARGUMENTS

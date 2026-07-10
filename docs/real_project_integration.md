# 真实通信项目接入记录

## 当前接入项目

项目：ModulationPy

来源：`https://github.com/kirlf/ModulationPy`

本地路径：`real_projects/ModulationPy`

选择原因：

- 主题匹配：数字基带线性调制，覆盖 M-PSK 和 M-QAM。
- 技术栈匹配：Python + NumPy，适合当前 OpenCode + Python 工具链。
- 有可运行测试：`tests.py` 覆盖 PSK/QAM 调制解调回环。
- 体量适中：适合做真实优化演示，不需要先搭建复杂服务。
- 许可清晰：BSD-3-Clause。

## 当前验证命令

```powershell
cd F:\CODE\agent_rewrite\comms-agent
.\scripts\check-real-project.ps1
```

等价手动命令：

```powershell
cd F:\CODE\agent_rewrite\comms-agent\real_projects\ModulationPy
python -m unittest tests.py
```

当前验证结果：

- `python -m unittest tests.py` 通过。
- 覆盖调制阶数：PSK 2/4/8/16/32，QAM 4/16/64。
- 验证内容：无噪声条件下 modulate/demodulate 回环应保持输入等价。

## Git 审阅前置

`real_projects/ModulationPy` 是独立 Git 仓库。每次让 `comms-optimize` 修改真实项目后，应使用
`git -C real_projects\ModulationPy diff` 审阅改动。

如果 `scripts/check-real-project.ps1` 提示 Git `dubious ownership`，说明当前 Windows 用户与该
子仓库所有者不一致。确认该目录可信后运行脚本提示的 `git config --global --add safe.directory ...`
命令；否则测试可以跑，但无法可靠审阅 diff/status。

## 允许优化范围

优先允许：

- `real_projects/ModulationPy/ModulationPy/ModulationPy.py`
- `real_projects/ModulationPy/tests.py`
- 项目内文档或注释

默认不动：

- `.git/` 目录
- 许可证文件
- 与本次优化无关的发布配置

## 推荐首轮优化目标

首轮不要大改算法。建议从低风险项开始：

1. 给关键变量补充单位和通信含义，例如 constellation symbol、noise variance、LLR。
2. 修正明显的拼写/注释问题，不改变行为。
3. 为调制阶数、输入长度、二进制输入约束补充错误提示。
4. 在不改变测试结果的前提下，整理重复逻辑。

## 验收标准

每次优化后必须至少通过：

```powershell
.\scripts\check-real-project.ps1
```

如果修改涉及 BER、噪声或软判决逻辑，还需要补充更具体的数值测试，不能只跑回环测试。

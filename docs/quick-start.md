# Quick Start

## 前置条件

- Python 3.10+
- Claude Code CLI（已安装且在 PATH 中）
- 依赖：`pyyaml`, `rich`

```bash
pip install pyyaml rich
```

## 一、编写评估配置

在 `configs/` 下创建 YAML 文件，定义你要评估的模式和对话内容：

```yaml
name: "我的评估"
description: "测试不同方式下知识库的调用情况"

# 要追踪统计的工具（支持通配符 *）
tracked_tools:
  - "mcp__knowledge-base__*"
  - "Bash"
  - "Read"
  - "Grep"

# 测试模式（每种模式的 turns 数量必须相同）
modes:
  - name: "skill"
    description: "使用 skill 触发知识库"
    setup:                          # 会话初始轮次（可选，可为空）
      - "/knowledge-base 请加载知识库"
    turns:                          # 业务轮次（评估对象）
      - "如何配置 API 密钥？"
      - "部署流程是什么？"
      - "错误码 E1001 怎么处理？"

  - name: "cli-no-init"
    description: "CLI 无初始命令"
    setup: []                       # 无初始命令
    turns:
      - "如何配置 API 密钥？"
      - "部署流程是什么？"
      - "错误码 E1001 怎么处理？"

  - name: "cli-with-init"
    description: "CLI 有初始命令"
    setup:
      - "在回答问题时，请始终先查询知识库获取最新信息"
    turns:
      - "如何配置 API 密钥？"
      - "部署流程是什么？"
      - "错误码 E1001 怎么处理？"

# 每种模式重复运行的次数
runs_per_mode: 3

# Claude Code 运行参数（可选）
claude_args:
  model: "claude-sonnet-4-6"
  # max_turns: 10
```

### 配置要点

| 字段 | 说明 |
|------|------|
| `tracked_tools` | 要统计的工具名称，支持 `*` 通配符（如 `mcp__kb__*`） |
| `modes[].setup` | 会话的第一轮输入，用于建立上下文（可为空列表 `[]`） |
| `modes[].turns` | 后续对话轮次，这些轮次的工具调用将被统计 |
| `runs_per_mode` | 每种模式重复几次（用于统计分析） |
| `claude_args.model` | 指定使用的模型（可选） |

> **所有模式的 `turns` 数量必须相同**，框架会校验这一点。

## 二、运行评估

```bash
# 设置 PYTHONPATH
# Linux/macOS
export PYTHONPATH=/path/to/eval

# Windows PowerShell
$env:PYTHONPATH = "E:\Project\eval"

# 运行完整评估（所有模式 × 所有重复次数）
python -m claude_eval.main run -c configs/kb-eval.yaml

# 只运行某个模式
python -m claude_eval.main run -c configs/kb-eval.yaml -m skill

# 指定输出目录
python -m claude_eval.main run -c configs/kb-eval.yaml -o ./my-output
```

运行过程中会显示实时进度：

```
============================================================
Eval: 知识库调用评估
Modes: 3 × 3 runs = 9 sessions
Model: claude-sonnet-4-6
============================================================

[1/9] Mode 'skill' run 1/3 ...
  ✓ 3 turns, 12 tool calls, 18.2s [mcp__knowledge-base__search:9, Bash:1, Read:2]
[2/9] Mode 'skill' run 2/3 ...
  ✓ 3 turns, 10 tool calls, 15.6s [mcp__knowledge-base__search:8, Bash:1, Read:1]
...
```

## 三、查看报告

评估完成后，会在输出目录生成 Markdown 报告：

```
output/
├── results/
│   ├── skill_run1.json         # 每次运行的原始数据
│   ├── skill_run2.json
│   ├── cli-no-init_run1.json
│   └── ...
└── 知识库调用评估-report.md     # 汇总报告
```

报告内容包括：

- **概览表**：模式 × 关键指标对比（调用次数、成功率、耗时）
- **追踪工具详细统计**：每种工具在各模式下的调用次数、成功率、平均/最小/最大耗时
- **每轮对话明细**：每个问题在各模式下触发了多少次工具调用
- **其他工具统计**：未被追踪但被调用的工具（辅助上下文）

### 报告示例

```markdown
## 概览

| 指标 | skill | cli-no-init | cli-with-init |
|------|-------|-------------|---------------|
| 追踪工具总调用次数 | 12 | 5 | 9 |
| 调用成功率 | 100% | 80% | 89% |
| 平均耗时(ms) | 245 | 312 | 278 |

## 每轮对话工具调用明细

| 轮次 | skill | cli-no-init | cli-with-init |
|------|-------|-------------|---------------|
| 第1轮: "如何配置 API 密钥？" | ✅ 3次 | ❌ 0次 | ✅ 2次 |
| 第2轮: "部署流程是什么？" | ✅ 4次 | ⚠️ 2次 | ✅ 3次 |
```

## 四、基于已有结果重新生成报告

如果已有运行结果 JSON 文件，可以跳过执行直接生成报告：

```bash
python -m claude_eval.main report -r output/results/

# 配合原始配置文件使用（获取 tracked_tools 和元信息）
python -m claude_eval.main report -r output/results/ -c configs/kb-eval.yaml
```

## 五、扩展：新增测试模式

无需改任何代码，在 YAML 中添加新 `mode` 即可：

```yaml
modes:
  # ... 已有模式 ...

  - name: "mcp-direct"              # ← 新增模式
    description: "直接使用 MCP 工具"
    setup:
      - "请使用 mcp__knowledge-base__search 工具查询知识库"
    turns:
      - "如何配置 API 密钥？"
      - "部署流程是什么？"
      - "错误码 E1001 怎么处理？"
```

运行时用 `-m mcp-direct` 即可单独测试新模式，不指定则全部运行。

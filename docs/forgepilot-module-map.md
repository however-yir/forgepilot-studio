# ForgePilot 模块职责与测试清单

> 范围：`openhands/forgepilot/*` 以及与 ForgePilot 工作台直接相关的配置、前端和测试。

## 模块职责

| 模块 | 职责 | 当前证据 |
| --- | --- | --- |
| `control_plane` | 定义任务协议、阶段流转、验收标准、变更边界、执行策略、审批策略、预算策略和默认验证命令。 | `TaskSpec`、`ApprovalPolicy`、`BudgetPolicy`、`select_verification_commands()` |
| `audit` | 定义审计事件、排序、JSONL/CSV 导出、task evidence pack 和审计时间线构建。 | `AuditEvent`、`AuditEventType`、`build_task_evidence_pack()`、`build_timeline()` |
| `tool_registry` | 管理 MCP/HTTP/shell 工具元数据、权限、mock、健康状态、schema、调用记录和输出摘要。 | `ToolRegistry`、`ToolAccessGuard`、`execute_shell_tool()` |
| `teamspace` | 建模个人/团队/共享模板空间，提供角色权限矩阵和空间注册表。 | `TeamSpace`、`SpaceRole`、`SpacePermissionGuard` |
| `llm_gateway` | 识别模型供应商前缀，统一 OpenAI、Anthropic、Ollama、LiteLLM、ForgePilot Gateway 的路由口径。 | `LLMGatewayProvider`、`detect_provider()` |
| `runtime_providers` | 抽象 local、Docker、Kubernetes、remote runtime 能力与策略支持度。 | `RuntimeProviderSpec`、`get_runtime_provider()` |
| `delivery` | 从审计事件生成 PR 描述、测试报告、回放链接、文件变更摘要和 commit message。 | `generate_delivery_artifact()` — `__init__.py` only, planned for v0.3.0 |
| `orchestration` | 定义多 Agent 角色模板与知识注入上下文。 | `OrchestrationTemplate`、`KnowledgeLoader` — `__init__.py` only, planned for v0.3.0 |
| `platform` | 提供结构化日志、trace_id 传播、审计归档策略、对象存储导出和平台级模型。 | `StructuredLogger`、`TraceContext`、`AuditExporter` |

## 测试覆盖现状

| 能力 | 已有测试 |
| --- | --- |
| 控制平面 | `tests/unit/forgepilot/test_task_protocol.py` |
| 审计事件导出 | `tests/unit/forgepilot/test_audit_schema.py` |
| 真实事件流转审计事件 | `tests/unit/forgepilot/test_audit_event_stream.py` |
| 审计时间线 | `tests/unit/forgepilot/test_audit_timeline.py` |
| 审批与预算策略 | `tests/unit/forgepilot/test_approval_budget_policy.py` |
| 工具注册表 schema | `tests/unit/forgepilot/test_tool_registry_schema.py` |
| 工具注册表运行时 | `tests/unit/forgepilot/test_tool_registry_runtime.py` |
| shell 工具封装 | `tests/unit/forgepilot/test_shell_tools.py` |
| Teamspace 权限 | `tests/unit/forgepilot/test_teamspace.py` |
| LLM Gateway | `tests/unit/forgepilot/test_llm_gateway_provider_registry.py` |
| Runtime Provider | `tests/unit/forgepilot/test_runtime_provider_registry.py` |
| 平台日志/导出 | `tests/unit/forgepilot/test_platform.py` |
| 命名空间迁移脚本 | `tests/unit/forgepilot/test_namespace_rename_script.py` |
| 模块公开契约 | `tests/unit/forgepilot/test_public_module_contract.py` |
| ForgePilot 执行配置 | `tests/unit/core/config/test_forgepilot_execution_config.py` |

## 第一阶段测试清单

### Control Plane

- [x] 语言别名能映射到默认验证命令。
- [x] 未知语言回落到显式提示命令。
- [x] 阶段只能从 `plan` 开始。
- [x] 同阶段重试允许。
- [x] 不允许跳过中间阶段。
- [x] 完整 `plan -> execute -> verify -> report` 序列有效。
- [x] 高风险命令、外部网络、部署命令、敏感文件修改会进入审批策略。
- [x] 超预算策略支持提示、降级模型、暂停并要求审批。
- [ ] `TaskSpec` 序列化快照测试，防止字段命名漂移。
- [ ] `ChangeBoundary` 与文件编辑工具的集成测试。
- [ ] `readonly_research_mode`、`review_mode`、`handoff_mode` 与 controller 行为的集成测试。

### Audit

- [x] 审计事件按时间排序。
- [x] JSONL 导出包含 trace、event_type、payload。
- [x] CSV 导出包含 payload 字段。
- [x] timeline 能串联 model、command、file_change、verification。
- [x] 将真实 event stream 转换为 `AuditEvent` 的集成测试。
- [ ] 多轮 self-heal 的 timeline 分链测试。
- [ ] 审计导出脱敏测试。
- [ ] 大 payload 截断和摘要测试。

### Teamspace

- [x] 创建空间时 owner 自动成为成员。
- [x] owner 拥有管理和删除权限。
- [x] viewer 只具备读取能力。
- [x] 未知用户没有权限。
- [x] 角色层级判断可用。
- [ ] 空间归档后禁止写入的测试。
- [ ] `space_id` 与 task/conversation/audit 绑定的集成测试。
- [ ] 组织成员变更后的权限刷新测试。

### LLM Gateway

- [x] 能从 `openai/gpt-4.1` 识别 provider。
- [x] 未知 provider 返回 `None`。
- [x] 能去掉 provider 前缀得到模型名。
- [x] provider registry 包含 `forgepilot`。
- [ ] OpenAI-compatible gateway 的 base_url 配置优先级测试。
- [ ] Ollama 本地模型配置 smoke test。
- [ ] 成本阈值与 provider usage 统计集成测试。

### Runtime Provider

- [x] provider 默认顺序为 local、docker、kubernetes、remote。
- [x] provider 查询大小写不敏感。
- [x] Docker/Kubernetes 标记支持资源配额。
- [ ] runtime provider 与前端运行时页面的数据契约测试。
- [ ] 网络策略 allowlist/open/deny 的行为测试。
- [ ] Kubernetes runtime 配额与 Secret 注入测试。

### Tool Registry 与 MCP

- [x] 内置连接器模板可初始化 registry。
- [x] 工具可启用/禁用。
- [x] 工具可切换 live/mock 模式。
- [x] mock 调用会记录 trace。
- [x] 权限不足会被 guard 拦截。
- [ ] MCP 配置页与 registry 的端到端测试。
- [ ] 工具健康检查超时与降级状态测试。
- [ ] 工具调用录制与审计 timeline 贯通测试。

## 建议验证命令

```bash
python -m pytest tests/unit/forgepilot -q
python -m pytest tests/unit/core/config/test_forgepilot_execution_config.py -q
npm --prefix frontend run typecheck
```

## 文档同步要求

每次新增 `openhands/forgepilot/*` 模块或公开类型时，需要同步更新：

- `docs/fork-differentiation.md`
- `docs/forgepilot-module-map.md`
- 对应 `tests/unit/forgepilot/test_*.py`
- README 首屏能力列表或差异化入口

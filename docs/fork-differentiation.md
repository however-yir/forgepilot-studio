# ForgePilot 与 OpenHands 差异说明

> 目标：把 ForgePilot Studio 讲清楚为“基于 OpenHands 深改的 AI 工程执行平台”，而不是简单换皮 fork。

## 一句话定位

ForgePilot Studio 是面向研发团队的可审计 AI 工程执行工作台：它保留 OpenHands 在 Agent、运行时和代码执行链路上的成熟基础，并在其上新增控制平面、任务台、团队权限、审计回放、成本阈值、MCP 工具管理和私有化配置能力。

## 继承自 OpenHands 的基础能力

ForgePilot 不重复造 OpenHands 已经成熟的底座，而是在可治理、可团队化、可私有化的方向上做产品层和平台层深改。

| 能力 | 来源 | ForgePilot 当前使用方式 |
| --- | --- | --- |
| Agent 会话循环 | OpenHands | 继续使用既有 controller、event stream、conversation session 等基础链路，保证任务执行闭环可运行。 |
| 沙箱运行时 | OpenHands | 继承 local、Docker、Kubernetes、remote runtime 的执行模型，并在 ForgePilot 层抽象 runtime provider。 |
| 文件编辑与命令执行 | OpenHands | 复用原有文件操作、bash/ipython/browser 等执行能力，ForgePilot 将其纳入任务协议和审计事件。 |
| LLM 配置与模型调用 | OpenHands / LiteLLM 生态 | 保留 OpenAI-compatible、LiteLLM、Ollama 等模型接入基础，ForgePilot 增加 gateway provider 识别与团队成本治理口径。 |
| MCP 与工具调用基础 | OpenHands | 保留 MCP 客户端和配置能力，ForgePilot 增加 registry、权限边界、mock、健康检查和调用记录。 |
| 前后端应用框架 | OpenHands | 继续使用 Python 后端与 React 前端工程结构，逐步把默认入口从聊天页迁移到任务台。 |
| 配置、日志、CI 基础 | OpenHands | 保留可复用配置项，同时新增 ForgePilot 专属配置段、发布检查和品牌默认值。 |

## ForgePilot 新增或深改能力

> **⚠️ 接线状态（诚实标注）**：下述治理类能力——控制平面（任务协议/审批/预算策略）、团队权限（TeamSpace RBAC）、成本阈值（Cost Thresholds / BudgetPolicy）、MCP 工具治理（ToolAccessGuard / ApprovalPolicy）与 [Execution Harness](forgepilot-execution-harness.md)——目前均为**实验性模块，尚未接入默认执行链路**：默认 Agent 运行仍走上游 OpenHands 的 controller/executor，这些模块以库代码 + 单元测试形态存在，`forgepilot_execution` 配置段也暂无运行时读取方。本节描述的是目标形态与已实现的数据结构。

### 控制平面

对应模块：`openhands/forgepilot/control_plane/`

ForgePilot 新增固定任务协议 `Plan -> Execute -> Verify -> Report`，把任务目标、验收标准、变更边界、确认模式、网络策略、只读研究模式、审查模式和自愈轮次放到任务执行前。它解决的是团队场景下“Agent 到底被授权做什么、做到什么算完成”的治理问题。

### 任务台

对应前端：`frontend/src/routes/task-console.tsx`、`frontend/src/components/features/forgepilot/`

ForgePilot 的默认首页转向任务台，展示任务队列、执行阶段、失败步骤过滤、预算使用和部署向导入口。产品心智从“聊天式代码助手”转为“工程任务执行控制台”。

### 团队权限与 Teamspace

对应模块：`openhands/forgepilot/teamspace/`

ForgePilot 新增 `TeamSpace`、`SpaceRole`、`SpacePermissionGuard` 和空间注册表，支持个人空间、团队空间、共享模板空间以及 owner/admin/member/viewer 权限矩阵。所有任务、模板、审计记录都应逐步挂到 `space_id` 上。

### 审计回放

对应模块：`openhands/forgepilot/audit/`

ForgePilot 新增统一 `AuditEvent` schema 和 timeline builder，将模型响应、命令执行、文件修改、工具调用、验证结果和交付报告串成可导出的时间线。导出格式覆盖 JSONL 与 CSV，为审计、复盘、合规归档和交付报告打基础。

### 成本阈值与预算可视化

对应位置：`max_budget_per_task`、前端 metrics store、成本页面和任务台指标。

ForgePilot 把模型成本从“会话统计”提升为任务执行策略的一部分。`max_budget_per_task` 会在会话启动链路中传递，前端展示 accumulated cost 与任务预算，后续会把模型、工具、CI、运行时成本统一到任务和 teamspace 维度。

### MCP 工具管理

对应模块：`openhands/forgepilot/tool_registry/`

ForgePilot 新增工具注册表、连接器模板、权限级别、live/mock 模式、schema 引用、健康状态、调用记录和输出摘要。工具不再只是配置项，而是可启用、可禁用、可 mock、可审计、可计费的治理对象。

### LLM Gateway

对应模块：`openhands/forgepilot/llm_gateway/`

ForgePilot 新增 provider registry，用统一口径识别 OpenAI、Anthropic、Ollama、LiteLLM 和 ForgePilot Gateway。目标是让团队把模型供应商、本地模型、私有 OpenAI-compatible 网关纳入同一配置和审计模型。

### Runtime Provider

对应模块：`openhands/forgepilot/runtime_providers/`

ForgePilot 把 local、Docker、Kubernetes、remote runtime 抽象为 provider spec，明确是否支持网络策略与资源配额。后续运行时管理页、配额策略和私有化部署文档都围绕这个抽象展开。

### 私有化配置

对应文件：`.env.fork.example`、`.env.local.example`、`config.template.toml`、`docker-compose.yml`

ForgePilot 将数据库、Redis、Ollama、LLM Gateway、镜像名、容器名和工作区路径放到更贴近私有化交付的模板中。部分底层变量仍沿用 OpenHands 命名，迁移期通过文档说明和 fallback 保持可运行性。

## 为什么仍保留 `openhands/` 包名

当前保留 `openhands/` 是工程风险控制，不是产品定位含糊。OpenHands 的导入路径、entrypoint、runtime 构建、测试夹具和第三方文档仍大量依赖该命名空间。ForgePilot 先在 `openhands/forgepilot/*` 中形成独立平台层，再按 `docs/upstream-sync.md` 和 `docs/namespace-migration.zh-CN.md` 分阶段迁移。

## 差异化边界

ForgePilot 不声称从零实现 Agent 运行时。它的自研价值集中在团队工程执行场景：

- 让任务执行有协议：目标、边界、阶段、验收标准和验证命令可记录。
- 让工具调用可治理：权限、mock、schema、健康、成本和审计有统一入口。
- 让团队使用可隔离：teamspace、角色权限、预算和审计记录可按空间归属。
- 让交付结果可复盘：命令、修改、验证和报告形成审计链路。
- 让私有化部署更顺滑：本地模型、Ollama、OpenAI-compatible gateway、Docker/K8s runtime 有明确配置路径。

## 当前证据链

| 方向 | 代码或文档入口 |
| --- | --- |
| 控制平面 | `openhands/forgepilot/control_plane/task_protocol.py` |
| 审计事件与导出 | `openhands/forgepilot/audit/schema.py` |
| 审计时间线 | `openhands/forgepilot/audit/timeline.py` |
| 工具注册表 | `openhands/forgepilot/tool_registry/` |
| 团队空间 | `openhands/forgepilot/teamspace/__init__.py` |
| LLM Gateway | `openhands/forgepilot/llm_gateway/provider_registry.py` |
| Runtime Provider | `openhands/forgepilot/runtime_providers/registry.py` |
| 交付工件 | `openhands/forgepilot/delivery/__init__.py` |
| 任务台与产品页面 | `frontend/src/components/features/forgepilot/` |
| 产品方向 ADR | `docs/adr/0001-forgepilot-product-direction.md` |
| 审计与工具 ADR | `docs/adr/0002-forgepilot-audit-and-tool-registry.md` |

## 后续补强优先级

1. 把任务台、审计页、工具中心的 mock 指标接入后端真实 API。
2. 将 `AuditEvent` 从工具层贯通到 controller/session/event stream。
3. 将 `TeamSpace` 与用户、组织、conversation、task 绑定到持久化存储。
4. 将 `ToolRegistry` 连接 MCP 配置页，形成启用、禁用、mock、测试连接闭环。
5. 给 Preview release 补完整演示 GIF 和 release note，明确“基于 OpenHands 深改”的来源与边界。

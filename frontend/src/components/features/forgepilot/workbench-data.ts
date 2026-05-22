import {
  Archive,
  Boxes,
  ClipboardCheck,
  FileCheck2,
  Gauge,
  GitPullRequest,
  KeyRound,
  Layers3,
  ListChecks,
  Network,
  PackageCheck,
  PlayCircle,
  Rocket,
  ShieldCheck,
  TimerReset,
  WalletCards,
  Waypoints,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type TaskState =
  | "planned"
  | "running"
  | "blocked"
  | "verified"
  | "shipped";
export type RiskLevel = "safe" | "review" | "danger" | "blocked";
export type WorkflowStage = "plan" | "execute" | "verify" | "report";

export interface ConsoleMetric {
  label: string;
  value: string;
  detail: string;
}

export interface WorkbenchItem {
  title: string;
  detail: string;
  stage?: WorkflowStage;
  failed?: boolean;
  state?: TaskState;
  risk?: RiskLevel;
}

export interface ToolCallCard {
  id: string;
  toolName: string;
  parameters: string;
  durationMs: number;
  summary: string;
  error: string | null;
}

export interface AuditReplayEvent {
  id: string;
  eventType: string;
  phase: WorkflowStage;
  time: string;
  summary: string;
  payload: Record<string, string | number | boolean>;
}

export interface ToolRegistryPanelItem {
  id: string;
  name: string;
  enabled: boolean;
  permission: string;
  scopes: string[];
  schemaPreview: string;
  connection: string;
  mockResponse: string;
}

export interface BudgetPolicyPanelItem {
  threshold: string;
  action: string;
  detail: string;
}

export interface ApprovalPolicyPanelItem {
  rule: string;
  reason: string;
  sample: string;
}

export interface WorkbenchPageConfig {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  metrics: ConsoleMetric[];
  primaryItems: WorkbenchItem[];
  enableTaskFilters?: boolean;
  onboardingNotice?: {
    storageKey: string;
    title: string;
    detail: string;
    actionLabel: string;
    actionTo: string;
  };
  secondaryTitle: string;
  secondaryItems: WorkbenchItem[];
  toolCalls?: ToolCallCard[];
  auditReplayEvents?: AuditReplayEvent[];
  auditExportJsonl?: string;
  toolRegistryItems?: ToolRegistryPanelItem[];
  budgetPolicies?: BudgetPolicyPanelItem[];
  approvalPolicies?: ApprovalPolicyPanelItem[];
}

export const TASK_STATE_STYLES: Record<TaskState, string> = {
  planned: "border-sky-400/40 bg-sky-400/10 text-sky-100",
  running: "border-amber-300/50 bg-amber-300/10 text-amber-100",
  blocked: "border-red-400/50 bg-red-400/10 text-red-100",
  verified: "border-emerald-400/50 bg-emerald-400/10 text-emerald-100",
  shipped: "border-teal-300/50 bg-teal-300/10 text-teal-100",
};

export const RISK_STYLES: Record<RiskLevel, string> = {
  safe: "border-emerald-400/50 bg-emerald-400/10 text-emerald-100",
  review: "border-amber-300/50 bg-amber-300/10 text-amber-100",
  danger: "border-orange-400/50 bg-orange-400/10 text-orange-100",
  blocked: "border-red-400/50 bg-red-400/10 text-red-100",
};

export const workbenchPages: Record<string, WorkbenchPageConfig> = {
  "task-console": {
    eyebrow: "Task Console",
    title: "任务台",
    description:
      "默认首页聚焦计划、执行、验证、回放四段闭环，让团队先看到任务状态，而不是进入空白聊天。",
    icon: ListChecks,
    metrics: [
      { label: "今日任务", value: "12", detail: "3 个等待人工确认" },
      { label: "验证通过率", value: "82%", detail: "最近 24 小时" },
      { label: "平均耗时", value: "18m", detail: "从计划到报告" },
      { label: "预算使用", value: "$42", detail: "本周模型成本" },
    ],
    primaryItems: [
      {
        title: "修复前端 eslint 升级后的类型告警",
        detail: "计划已生成，等待运行 typecheck。",
        stage: "execute",
        failed: false,
        state: "running",
        risk: "review",
      },
      {
        title: "补齐 MCP 工具调用错误态",
        detail: "已限制修改范围：frontend/src/components/features/chat。",
        stage: "plan",
        failed: false,
        state: "planned",
        risk: "safe",
      },
      {
        title: "重构运行时配置加载",
        detail: "触及配置入口，需要负责人确认。",
        stage: "verify",
        failed: true,
        state: "blocked",
        risk: "blocked",
      },
    ],
    enableTaskFilters: true,
    onboardingNotice: {
      storageKey: "forgepilot_deployment_wizard_completed",
      title: "首次启动：私有化部署向导",
      detail:
        "引导配置模型网关、数据库、沙箱运行时和工作区策略，完成后可生成落地配置摘要。",
      actionLabel: "打开部署向导",
      actionTo: "/deployment-wizard",
    },
    secondaryTitle: "执行协议",
    secondaryItems: [
      { title: "Plan", detail: "拆解目标、风险、边界和验收标准。" },
      { title: "Execute", detail: "执行命令、编辑代码、记录工具调用。" },
      { title: "Verify", detail: "自动选择测试命令并保存输出。" },
      { title: "Report", detail: "生成 PR 描述、变更摘要和交付记录。" },
    ],
  },
  orchestration: {
    eyebrow: "Workflow Orchestration",
    title: "任务编排",
    description:
      "承载 Plan -> Execute -> Verify -> Report 的固定协议，并把验收标准、变更边界和失败自愈次数前置。",
    icon: Waypoints,
    metrics: [
      { label: "模板", value: "8", detail: "bugfix / review / docs / test" },
      { label: "自动验证", value: "6", detail: "pytest、npm、mvn 等" },
      { label: "自愈上限", value: "3", detail: "默认失败重试轮数" },
      { label: "只读任务", value: "4", detail: "研究模式进行中" },
    ],
    primaryItems: [
      {
        title: "新增任务验收标准字段",
        detail: "进入执行前必须明确 done 条件。",
        state: "planned",
      },
      {
        title: "新增变更边界",
        detail: "可限制目录、文件类型、命令范围。",
        state: "running",
      },
      {
        title: "新增交接模式",
        detail: "输出 handoff 文档给人类工程师继续处理。",
        state: "planned",
      },
    ],
    secondaryTitle: "Agent 模式",
    secondaryItems: [
      { title: "只读研究模式", detail: "只分析，不改文件。" },
      { title: "审查模式", detail: "输出 review findings，不直接修复。" },
      { title: "多 Agent 分工", detail: "探索、实现、验证、文档各司其职。" },
    ],
  },
  runtimes: {
    eyebrow: "Runtime Center",
    title: "运行时",
    description:
      "集中管理本地、Docker、Kubernetes 沙箱，展示健康状态、资源配额、网络策略和工作区挂载。",
    icon: Boxes,
    metrics: [
      { label: "运行时", value: "3", detail: "local / docker / k8s" },
      { label: "健康检查", value: "7/8", detail: "一个 MCP endpoint 待确认" },
      { label: "沙箱配额", value: "2 CPU", detail: "默认任务资源" },
      { label: "工作区", value: "24", detail: "可回放会话" },
    ],
    primaryItems: [
      {
        title: "Docker Runtime",
        detail: "默认隔离执行环境，挂载 ForgePilot 工作区。",
        state: "verified",
      },
      {
        title: "Kubernetes Runtime",
        detail: "预留 namespace、资源限制和 Secret 管理入口。",
        state: "planned",
      },
      {
        title: "Local Runtime",
        detail: "适合单机 PoC，需要显式确认高风险命令。",
        state: "running",
        risk: "review",
      },
    ],
    secondaryTitle: "运行边界",
    secondaryItems: [
      { title: "文件访问", detail: "按任务限定工作区根目录。" },
      { title: "网络访问", detail: "按策略允许或阻断外网。" },
      { title: "命令权限", detail: "高风险命令进入人工确认。" },
    ],
  },
  tools: {
    eyebrow: "Tool Center",
    title: "工具中心",
    description:
      "MCP Registry 和脚本工具入口，支持启用、禁用、连接测试、权限边界、mock 和调用录制。",
    icon: Network,
    metrics: [
      { label: "连接器", value: "9", detail: "GitHub、Jira、Sentry 等" },
      { label: "可写工具", value: "4", detail: "默认需要确认" },
      { label: "Mock 覆盖", value: "62%", detail: "测试环境可复现" },
      { label: "调用录制", value: "on", detail: "用于审计回放" },
    ],
    primaryItems: [
      {
        title: "GitHub",
        detail: "issue、PR、checks、release 读写模板。",
        stage: "execute",
        state: "verified",
        risk: "review",
      },
      {
        title: "Sentry",
        detail: "读取 issue、事件样本和版本上下文。",
        stage: "plan",
        state: "planned",
        risk: "safe",
      },
      {
        title: "Internal HTTP API",
        detail: "低代码配置 schema、headers 和鉴权方式。",
        stage: "report",
        state: "planned",
        risk: "review",
      },
    ],
    secondaryTitle: "工具权限",
    secondaryItems: [
      { title: "read", detail: "只读取上下文。" },
      { title: "write", detail: "改远端状态前需要确认。" },
      { title: "execute", detail: "执行外部动作并记录审计事件。" },
    ],
    toolCalls: [
      {
        id: "tool-call-github-checks",
        toolName: "github.listChecks",
        parameters: "repo=however-yir/forgepilot-studio, pr=418",
        durationMs: 842,
        summary: "返回 6 条 checks；1 条失败，已关联到任务验证阶段。",
        error: null,
      },
      {
        id: "tool-call-sentry-issue",
        toolName: "sentry.getIssue",
        parameters: "project=forgepilot-studio, issue=FP-2381",
        durationMs: 1294,
        summary: "读取到最新异常堆栈并生成根因摘要。",
        error: null,
      },
      {
        id: "tool-call-internal-http",
        toolName: "internal.http.invoke",
        parameters: "service=audit-gateway, path=/v1/exports",
        durationMs: 411,
        summary: "请求失败，未读取到 schema 版本。",
        error: "401 Unauthorized: token scope missing `audit:write`",
      },
    ],
    toolRegistryItems: [
      {
        id: "connector.github",
        name: "GitHub",
        enabled: true,
        permission: "confirm",
        scopes: ["repo:read", "checks:read", "pull_request:write"],
        schemaPreview:
          '{"tool_id":"connector.github","permission":"confirm","mode":"live"}',
        connection: "healthy",
        mockResponse:
          '{"checks":[{"name":"frontend-build","status":"success"}]}',
      },
      {
        id: "connector.sentry",
        name: "Sentry",
        enabled: true,
        permission: "read",
        scopes: ["issue:read", "event:read"],
        schemaPreview:
          '{"tool_id":"connector.sentry","permission":"read","mode":"mock"}',
        connection: "healthy",
        mockResponse: '{"issue":"FP-2381","level":"error"}',
      },
      {
        id: "internal.http.invoke",
        name: "Internal HTTP API",
        enabled: false,
        permission: "execute",
        scopes: ["audit:write"],
        schemaPreview:
          '{"tool_id":"internal.http.invoke","method":"POST","path":"/v1/exports"}',
        connection: "unreachable",
        mockResponse: '{"error":"token scope missing audit:write"}',
      },
    ],
  },
  audit: {
    eyebrow: "Audit Replay",
    title: "审计回放",
    description:
      "把模型响应、命令执行、文件修改、工具调用和验证结果串成可追溯时间线。",
    icon: Archive,
    metrics: [
      { label: "审计事件", value: "418", detail: "最近 7 天" },
      { label: "可导出", value: "JSONL", detail: "CSV 和对象存储预留" },
      { label: "trace_id", value: "on", detail: "前后端贯通规划中" },
      { label: "回放链接", value: "12", detail: "共享给 reviewer" },
    ],
    primaryItems: [
      {
        title: "命令执行",
        detail: "记录 cwd、命令、退出码、摘要和敏感输出策略。",
        state: "running",
      },
      {
        title: "文件变更",
        detail: "按 diff chunk 展示来源任务和验证结果。",
        state: "planned",
      },
      {
        title: "工具调用",
        detail: "记录参数摘要、耗时、返回状态和权限级别。",
        state: "planned",
      },
    ],
    secondaryTitle: "导出目标",
    secondaryItems: [
      { title: "JSONL", detail: "适合日志系统和对象存储。" },
      { title: "CSV", detail: "适合安全审计和成本复盘。" },
      { title: "Report Link", detail: "适合 PR 或交付记录。" },
    ],
    auditReplayEvents: [
      {
        id: "audit-task-created",
        eventType: "task_created",
        phase: "plan",
        time: "09:31:04",
        summary: "创建任务：修复 login 模块空指针异常。",
        payload: { task_id: "task-login-42", owner: "platform-team" },
      },
      {
        id: "audit-model-response",
        eventType: "model_response",
        phase: "execute",
        time: "09:31:18",
        summary: "模型定位 user.profile 未初始化并提出最小修改范围。",
        payload: { model: "openai/gpt-4.1", tokens: 1824 },
      },
      {
        id: "audit-command-run",
        eventType: "command_run",
        phase: "execute",
        time: "09:32:02",
        summary: "运行 pytest tests/unit/test_login.py。",
        payload: { command: "pytest tests/unit/test_login.py", exit_code: 0 },
      },
      {
        id: "audit-file-change",
        eventType: "file_change",
        phase: "execute",
        time: "09:32:26",
        summary: "auth/login_service.py +12 / -3。",
        payload: { path: "auth/login_service.py", additions: 12, deletions: 3 },
      },
      {
        id: "audit-test-result",
        eventType: "test_result",
        phase: "verify",
        time: "09:33:10",
        summary: "12 passed / 0 failed / 1 skipped。",
        payload: { verifier: "pytest", passed: true },
      },
      {
        id: "audit-approval",
        eventType: "approval_decision",
        phase: "report",
        time: "09:33:44",
        summary: "Reviewer 批准导出 evidence pack。",
        payload: { decision: "approved", reviewer: "release-owner" },
      },
    ],
    auditExportJsonl:
      '{"trace_id":"audit-task-created","task_id":"task-login-42","event_type":"task_created","phase":"plan"}\n{"trace_id":"audit-model-response","task_id":"task-login-42","event_type":"model_response","phase":"execute"}\n{"trace_id":"audit-test-result","task_id":"task-login-42","event_type":"test_result","phase":"verify"}',
  },
  cost: {
    eyebrow: "Cost & Budget",
    title: "成本与预算",
    description:
      "展示模型调用量、token、耗时、任务成本和工具成本，避免自动化任务没有预算边界。",
    icon: WalletCards,
    metrics: [
      { label: "本周成本", value: "$128", detail: "模型 + 工具估算" },
      { label: "单任务上限", value: "$8", detail: "可按空间覆盖" },
      { label: "token", value: "1.8M", detail: "最近 7 天" },
      { label: "超预算拦截", value: "5", detail: "需人工确认" },
    ],
    primaryItems: [
      {
        title: "模型调用",
        detail: "按 provider、model、task 汇总。",
        state: "running",
      },
      {
        title: "工具成本",
        detail: "CI、外部 API、远程沙箱拆分统计。",
        state: "planned",
      },
      {
        title: "预算策略",
        detail: "空间、用户、任务模板三级预算。",
        state: "planned",
      },
    ],
    secondaryTitle: "成本动作",
    secondaryItems: [
      { title: "warn", detail: "接近阈值时提示。" },
      { title: "pause", detail: "暂停并等待人工确认。" },
      { title: "block", detail: "超过硬上限直接阻断。" },
    ],
    budgetPolicies: [
      {
        threshold: "80%",
        action: "warn",
        detail: "预算接近上限时在任务台和会话面板提示。",
      },
      {
        threshold: "95%",
        action: "downgrade_model",
        detail: "后续步骤切换到 gpt-4.1-mini 或团队配置的低成本模型。",
      },
      {
        threshold: "100%",
        action: "pause + require_approval",
        detail: "暂停执行，记录 approval_requested，等待负责人批准继续。",
      },
    ],
  },
  team: {
    eyebrow: "Team Spaces",
    title: "团队空间",
    description:
      "区分个人任务、团队任务和共享模板，为租户、角色、权限和计费做基础。",
    icon: Layers3,
    metrics: [
      { label: "空间", value: "3", detail: "personal / platform / infra" },
      {
        label: "角色",
        value: "4",
        detail: "owner / maintainer / reviewer / viewer",
      },
      { label: "共享模板", value: "11", detail: "团队可复用" },
      { label: "待审批", value: "2", detail: "高风险执行请求" },
    ],
    primaryItems: [
      {
        title: "个人空间",
        detail: "默认隔离私有任务和模型密钥。",
        state: "verified",
      },
      {
        title: "团队空间",
        detail: "共享任务模板、审计日志和运行时策略。",
        state: "planned",
      },
      {
        title: "组织权限",
        detail: "角色权限与预算策略绑定。",
        state: "planned",
      },
    ],
    secondaryTitle: "权限模型",
    secondaryItems: [
      { title: "owner", detail: "管理空间、密钥、预算和成员。" },
      { title: "reviewer", detail: "确认高风险执行和交付报告。" },
      { title: "viewer", detail: "只读查看任务和审计记录。" },
    ],
  },
  templates: {
    eyebrow: "Template Library",
    title: "任务模板库",
    description: "沉淀 bugfix、代码审查、文档生成、测试补全等可复用执行模板。",
    icon: PackageCheck,
    metrics: [
      { label: "模板", value: "14", detail: "按语言和场景分类" },
      { label: "验收标准", value: "100%", detail: "模板必须配置" },
      { label: "默认验证", value: "9", detail: "自动命令策略" },
      { label: "共享次数", value: "37", detail: "团队复用统计" },
    ],
    primaryItems: [
      {
        title: "Bugfix",
        detail: "复现、修复、回归、报告。",
        state: "verified",
      },
      {
        title: "Code Review",
        detail: "只输出 findings，不直接改文件。",
        state: "planned",
      },
      {
        title: "Test Backfill",
        detail: "定位缺口、补测试、运行最小验证。",
        state: "planned",
      },
    ],
    secondaryTitle: "模板字段",
    secondaryItems: [
      { title: "scope", detail: "允许读取和修改的路径。" },
      { title: "verify", detail: "默认验证命令。" },
      { title: "handoff", detail: "交付摘要格式。" },
    ],
  },
  policy: {
    eyebrow: "Execution Policy",
    title: "执行策略",
    description: "管理确认模式、危险命令、网络访问、文件边界和失败自愈次数。",
    icon: ShieldCheck,
    metrics: [
      { label: "确认模式", value: "on", detail: "高风险命令必审" },
      { label: "危险命令", value: "18", detail: "默认阻断或确认" },
      { label: "网络策略", value: "review", detail: "外部访问需说明" },
      { label: "自愈轮数", value: "3", detail: "失败后最大重试" },
    ],
    primaryItems: [
      {
        title: "命令风险分级",
        detail: "safe、review、danger、blocked 四级。",
        state: "running",
      },
      {
        title: "文件边界",
        detail: "按任务模板限制可写路径。",
        state: "planned",
      },
      {
        title: "网络边界",
        detail: "按空间控制外网、内网和工具服务。",
        state: "planned",
      },
    ],
    secondaryTitle: "风险级别",
    secondaryItems: [
      { title: "safe", detail: "可自动执行。" },
      { title: "review", detail: "需要说明和确认。" },
      { title: "danger", detail: "默认要求人工审核。" },
      { title: "blocked", detail: "默认禁止执行。" },
    ],
    approvalPolicies: [
      {
        rule: "高风险命令",
        reason: "high_risk_command",
        sample: "sudo rm -rf /tmp/build-cache",
      },
      {
        rule: "外部网络",
        reason: "external_network",
        sample: "curl https://example.com/install.sh",
      },
      {
        rule: "部署命令",
        reason: "deployment_command",
        sample: "kubectl apply -f prod.yaml",
      },
      {
        rule: "敏感文件修改",
        reason: "sensitive_file_change",
        sample: "config/.env.production",
      },
    ],
  },
  delivery: {
    eyebrow: "Delivery Reports",
    title: "成果交付",
    description:
      "一键产出 PR 描述、变更摘要、测试报告、成本摘要和审计回放链接。",
    icon: FileCheck2,
    metrics: [
      { label: "报告模板", value: "5", detail: "PR / release / handoff" },
      { label: "测试摘要", value: "auto", detail: "从验证步骤生成" },
      { label: "回放链接", value: "on", detail: "可附到 PR 描述" },
      { label: "交付状态", value: "draft", detail: "等待 reviewer" },
    ],
    primaryItems: [
      {
        title: "PR 描述",
        detail: "问题、方案、测试、风险、截图。",
        state: "running",
      },
      {
        title: "变更摘要",
        detail: "按文件和行为变化分组。",
        state: "planned",
      },
      {
        title: "交接文档",
        detail: "列出未完成事项和下一步建议。",
        state: "planned",
      },
    ],
    secondaryTitle: "交付输出",
    secondaryItems: [
      { title: "Pull Request", detail: "面向代码审查。" },
      { title: "Release Note", detail: "面向发布沟通。" },
      { title: "Handoff", detail: "面向人类工程师接力。" },
    ],
  },
};

export const sidebarNavItems = [
  { to: "/", label: "任务台", icon: ListChecks },
  { to: "/orchestration", label: "任务编排", icon: Waypoints },
  { to: "/runtimes", label: "运行时", icon: Boxes },
  { to: "/tools", label: "工具中心", icon: Network },
  { to: "/audit", label: "审计回放", icon: Archive },
  { to: "/cost", label: "成本预算", icon: WalletCards },
  { to: "/team", label: "团队空间", icon: Layers3 },
  { to: "/templates", label: "模板库", icon: PackageCheck },
  { to: "/policy", label: "执行策略", icon: ShieldCheck },
  { to: "/deployment-wizard", label: "部署向导", icon: Rocket },
  { to: "/delivery", label: "成果交付", icon: FileCheck2 },
];

export const workflowBadges = [
  { label: "Plan", icon: ClipboardCheck },
  { label: "Execute", icon: PlayCircle },
  { label: "Verify", icon: Gauge },
  { label: "Report", icon: GitPullRequest },
  { label: "Budget", icon: WalletCards },
  { label: "Replay", icon: TimerReset },
  { label: "Secrets", icon: KeyRound },
];

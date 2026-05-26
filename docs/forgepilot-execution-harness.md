# ForgePilot Execution Harness

ForgePilot Execution Harness is the policy and audit layer around existing
OpenHands runtime actions. It does not replace terminal, file, git, or MCP
execution. Instead, it classifies each action before execution, checks policy
and confirmation requirements, invokes the existing executor, then emits a
single audit-ready observation summary.

## Goals

- Keep runtime implementations unchanged.
- Align permission levels with the frontend MCP settings: `read`, `write`,
  `execute`, and `confirm`.
- Produce a uniform observation payload for audit replay.
- Support confirmation tokens and existing UI confirmation states for high-risk
  actions.
- Redact sensitive inputs before they enter audit payloads.

## Module Map

- `action_schema.py`: classifies runtime actions into terminal, file read,
  file write, file patch, git, MCP tool, or unknown actions.
- `policy.py`: evaluates allow/deny and confirmation requirements.
- `confirmation.py`: issues and consumes one-shot confirmation tokens.
- `observation.py`: builds redacted execution summaries and output summaries.
- `audit.py`: converts harness observations into ForgePilot `AuditEvent`
  records.
- `service.py`: wraps sync or async runtime executors.

## Wrapped Action Families

The harness recognizes these existing OpenHands action shapes:

- `CmdRunAction`: terminal action with `execute` permission.
- `CmdRunAction` starting with `git`: git action with `execute` permission.
- `FileReadAction`: file read action with `read` permission.
- `FileWriteAction`: file write action with `write` permission.
- `FileEditAction`: file patch action with `write` permission.
- `MCPAction`: MCP tool action with permission resolved from MCP preferences.

MCP permission lookup checks the exact tool name first, then common server
prefixes such as `github` from `github.create_issue`.

## Runtime Usage

```python
from openhands.forgepilot.harness import ExecutionHarness

harness = ExecutionHarness(task_id='task-123')

result = harness.execute(action, runtime.run_action)

# For MCP or any async executor:
result = await harness.execute_async(mcp_action, runtime.call_tool_mcp)
```

`result.runtime_observation` is the original runtime observation. The harness
adds `result.observation` for policy/audit consumers and `result.audit_event`
for replay/timeline consumers.

## Confirmation Gate

Actions marked as requiring confirmation can proceed in either of two ways:

- The runtime action already carries a confirmed UI state.
- A matching confirmation token is provided and consumed successfully.

Tokens are one-shot. Reusing the same token returns a
`confirmation_required` harness observation instead of invoking the runtime
executor again.

## Audit Payload

Harness audit events include:

- `action_type`
- `permission_level`
- `target`
- `redacted_input`
- `status`
- `latency_ms`
- `output_summary`
- `error`

Sensitive input keys such as `api_key`, `token`, `secret`, `password`, and
`authorization` are replaced with `[REDACTED]` before the audit event is built.

## Non-goals

- Rewriting OpenHands runtime internals.
- Owning the frontend confirmation UI.
- Replacing the existing ForgePilot tool registry guard.
- Persisting confirmation tokens across processes.

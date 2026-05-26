from __future__ import annotations

import fnmatch

from pydantic import BaseModel

from openhands.forgepilot.harness.action_schema import HarnessAction
from openhands.forgepilot.tool_registry.schema import ToolPermission


class PolicyDecision(BaseModel):
    allowed: bool
    permission: ToolPermission
    requires_confirmation: bool = False
    reason: str = ''


class HarnessPolicy(BaseModel):
    allowed_permissions: tuple[ToolPermission, ...] = (
        ToolPermission.READ,
        ToolPermission.WRITE,
        ToolPermission.EXECUTE,
        ToolPermission.CONFIRM,
    )
    blocked_targets: tuple[str, ...] = ()
    require_confirmation_for: tuple[ToolPermission, ...] = (ToolPermission.CONFIRM,)
    block_unknown_actions: bool = False

    def evaluate(self, action: HarnessAction) -> PolicyDecision:
        if self.block_unknown_actions and action.action_type.value == 'unknown':
            return PolicyDecision(
                allowed=False,
                permission=action.permission,
                reason='unknown action type',
            )

        if action.permission not in self.allowed_permissions:
            return PolicyDecision(
                allowed=False,
                permission=action.permission,
                reason=f'permission {action.permission.value} is not allowed',
            )

        if any(
            fnmatch.fnmatch(action.target, pattern) for pattern in self.blocked_targets
        ):
            return PolicyDecision(
                allowed=False,
                permission=action.permission,
                reason=f'target {action.target} is blocked by policy',
            )

        return PolicyDecision(
            allowed=True,
            permission=action.permission,
            requires_confirmation=action.requires_confirmation
            or action.permission in self.require_confirmation_for,
            reason='allowed',
        )

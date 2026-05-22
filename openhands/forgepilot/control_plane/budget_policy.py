from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BudgetAction(str, Enum):
    CONTINUE = 'continue'
    WARN = 'warn'
    PAUSE = 'pause'
    DOWNGRADE_MODEL = 'downgrade_model'
    REQUIRE_APPROVAL = 'require_approval'


class BudgetDecision(BaseModel):
    action: BudgetAction
    current_cost_usd: float
    max_budget_usd: float
    detail: str
    target_model: str | None = None


class BudgetPolicy(BaseModel):
    warn_at_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    downgrade_at_ratio: float = Field(default=0.95, ge=0.0, le=1.0)
    pause_when_exceeded: bool = True
    require_approval_when_exceeded: bool = True
    fallback_model: str | None = None

    def evaluate(
        self,
        *,
        current_cost_usd: float,
        max_budget_usd: float | None,
    ) -> BudgetDecision:
        if max_budget_usd is None or max_budget_usd <= 0:
            return BudgetDecision(
                action=BudgetAction.CONTINUE,
                current_cost_usd=current_cost_usd,
                max_budget_usd=0.0,
                detail='no budget cap configured',
            )

        ratio = current_cost_usd / max_budget_usd
        if ratio >= 1 and self.require_approval_when_exceeded:
            action = (
                BudgetAction.PAUSE
                if self.pause_when_exceeded
                else BudgetAction.REQUIRE_APPROVAL
            )
            return BudgetDecision(
                action=action,
                current_cost_usd=current_cost_usd,
                max_budget_usd=max_budget_usd,
                detail='budget exceeded; waiting for operator approval',
                target_model=self.fallback_model,
            )

        if ratio >= self.downgrade_at_ratio and self.fallback_model:
            return BudgetDecision(
                action=BudgetAction.DOWNGRADE_MODEL,
                current_cost_usd=current_cost_usd,
                max_budget_usd=max_budget_usd,
                detail='budget near cap; downgrade model for remaining steps',
                target_model=self.fallback_model,
            )

        if ratio >= self.warn_at_ratio:
            return BudgetDecision(
                action=BudgetAction.WARN,
                current_cost_usd=current_cost_usd,
                max_budget_usd=max_budget_usd,
                detail='budget warning threshold reached',
            )

        return BudgetDecision(
            action=BudgetAction.CONTINUE,
            current_cost_usd=current_cost_usd,
            max_budget_usd=max_budget_usd,
            detail='within budget',
        )


DEFAULT_BUDGET_POLICY = BudgetPolicy(fallback_model='gpt-4.1-mini')

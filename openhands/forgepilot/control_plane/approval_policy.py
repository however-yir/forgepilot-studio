from __future__ import annotations

import fnmatch
import re
from enum import Enum
from typing import Iterable
from uuid import uuid4

from pydantic import BaseModel, Field


class ApprovalReason(str, Enum):
    HIGH_RISK_COMMAND = 'high_risk_command'
    EXTERNAL_NETWORK = 'external_network'
    DEPLOYMENT_COMMAND = 'deployment_command'
    SENSITIVE_FILE_CHANGE = 'sensitive_file_change'


class ApprovalDecision(str, Enum):
    APPROVED = 'approved'
    REJECTED = 'rejected'


class ApprovalRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    subject_type: str
    subject: str
    reasons: list[ApprovalReason]
    detail: str
    required: bool = True


class ApprovalPolicy(BaseModel):
    high_risk_command_patterns: tuple[str, ...] = (
        r'\brm\s+-rf\b',
        r'\bsudo\b',
        r'\bchmod\s+-R\b',
        r'\bchown\s+-R\b',
        r'\bdd\s+',
        r'\bmkfs\b',
        r'\bdocker\s+system\s+prune\b',
    )
    external_network_patterns: tuple[str, ...] = (
        r'\bcurl\s+https?://',
        r'\bwget\s+https?://',
        r'\bssh\s+',
        r'\bscp\s+',
        r'\brsync\s+',
        r'\bnpm\s+install\b',
        r'\bpip\s+install\b',
        r'\bpoetry\s+add\b',
    )
    deployment_command_patterns: tuple[str, ...] = (
        r'\bkubectl\s+(apply|delete|rollout|scale)\b',
        r'\bhelm\s+(install|upgrade|delete|rollback)\b',
        r'\bterraform\s+(apply|destroy)\b',
        r'\bdocker\s+push\b',
        r'\bgit\s+push\b',
        r'\bgh\s+release\b',
        r'\bnpm\s+publish\b',
        r'\btwine\s+upload\b',
    )
    sensitive_file_patterns: tuple[str, ...] = (
        '**/.env',
        '**/.env.*',
        '**/*secret*',
        '**/*credential*',
        '**/secrets/**',
        '**/.ssh/**',
        '**/id_rsa',
        '**/id_ed25519',
    )

    def evaluate_command(self, command: str) -> ApprovalRequest | None:
        reasons: list[ApprovalReason] = []
        if _matches_any(command, self.high_risk_command_patterns):
            reasons.append(ApprovalReason.HIGH_RISK_COMMAND)
        if _matches_any(command, self.external_network_patterns):
            reasons.append(ApprovalReason.EXTERNAL_NETWORK)
        if _matches_any(command, self.deployment_command_patterns):
            reasons.append(ApprovalReason.DEPLOYMENT_COMMAND)

        if not reasons:
            return None

        return ApprovalRequest(
            subject_type='command',
            subject=command,
            reasons=reasons,
            detail=', '.join(reason.value for reason in reasons),
        )

    def evaluate_file_change(self, path: str) -> ApprovalRequest | None:
        normalized = path.replace('\\', '/')
        if not any(
            fnmatch.fnmatch(normalized, pattern)
            for pattern in self.sensitive_file_patterns
        ):
            return None

        return ApprovalRequest(
            subject_type='file_change',
            subject=normalized,
            reasons=[ApprovalReason.SENSITIVE_FILE_CHANGE],
            detail=f'sensitive file pattern matched: {normalized}',
        )

    def evaluate_batch(
        self,
        *,
        commands: Iterable[str] = (),
        file_changes: Iterable[str] = (),
    ) -> list[ApprovalRequest]:
        requests: list[ApprovalRequest] = []
        for command in commands:
            request = self.evaluate_command(command)
            if request:
                requests.append(request)
        for path in file_changes:
            request = self.evaluate_file_change(path)
            if request:
                requests.append(request)
        return requests


DEFAULT_APPROVAL_POLICY = ApprovalPolicy()


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)

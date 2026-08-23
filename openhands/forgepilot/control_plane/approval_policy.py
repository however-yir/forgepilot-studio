from __future__ import annotations

import fnmatch
import posixpath
import re
import shlex
from enum import Enum
from pathlib import PurePosixPath
from typing import Callable, Iterable
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


# ───────────────────────────────────────────────────────
#  Structural command analysis
# ───────────────────────────────────────────────────────

_COMMAND_SEPARATORS = {'|', '||', ';', '&&', '&'}
_SHELL_PROGRAMS = {'sh', 'bash', 'zsh', 'dash', 'ksh'}
_MAX_NESTED_DEPTH = 2  # e.g. bash -lc "sh -c '...'"
_NPM_INSTALL_SUBCOMMANDS = {'install', 'i', 'add'}
_KUBECTL_DEPLOY_SUBCOMMANDS = {'apply', 'delete', 'rollout', 'scale'}
_HELM_DEPLOY_SUBCOMMANDS = {'install', 'upgrade', 'delete', 'rollback'}
_TERRAFORM_DEPLOY_SUBCOMMANDS = {'apply', 'destroy'}


def _tokenize(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        # Unbalanced quotes or other shlex-invalid input: fall back to
        # whitespace splitting rather than skipping the check.
        return command.split()


def _pipeline_segments(tokens: list[str]) -> list[list[str]]:
    """Split a token list into argv segments (pipeline / command lists)."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _program_of(segment: list[str]) -> tuple[str, list[str]]:
    """Return ``(program basename, args)`` with leading bare ``sudo`` unwrapped.

    ``sudo -u root rm ...`` keeps ``sudo`` as the program (its flag arguments
    are not unwrapped); bare ``sudo`` is itself flagged as high risk.
    """
    argv = list(segment)
    while len(argv) >= 2 and argv[0] == 'sudo' and not argv[1].startswith('-'):
        argv = argv[1:]
    if not argv:
        return '', []
    program = posixpath.basename(argv[0])
    return program, argv[1:]


def _is_high_risk_segment(program: str, args: list[str]) -> bool:
    if program == 'sudo':
        return True
    if program == 'rm':
        return _is_recursive_rm(args)
    if program in {'chmod', 'chown'}:
        return _has_recursive_flag(args)
    if program in {'dd', 'mkfs'} or program.startswith('mkfs.'):
        return True
    if program == 'docker':
        return args[:1] == ['system'] and 'prune' in args
    return False


def _is_recursive_rm(args: list[str]) -> bool:
    """Detect recursive rm regardless of flag order or bundling (-r, -fr, -Rf)."""
    for arg in args:
        if arg == '--recursive':
            return True
        if arg.startswith('-') and len(arg) > 1 and not arg.startswith('--'):
            body = arg.lstrip('-')
            if body.isalpha() and 'r' in body.lower():
                return True
    return False


def _has_recursive_flag(args: list[str]) -> bool:
    """Detect chmod/chown -R / --recursive."""
    if '--recursive' in args:
        return True
    return any(
        arg.startswith('-')
        and len(arg) > 1
        and not arg.startswith('--')
        and arg.lstrip('-').isalpha()
        and 'R' in arg
        for arg in args
    )


def _is_external_network_segment(program: str, args: list[str]) -> bool:
    if program in {'curl', 'wget', 'ssh', 'scp', 'rsync'}:
        return True
    if not args:
        return False
    subcommand = args[0]
    if program == 'npm':
        # `i` and `add` are npm aliases for `install`
        return subcommand in _NPM_INSTALL_SUBCOMMANDS
    if program in {'pip', 'pip3'}:
        return subcommand == 'install'
    if program == 'poetry':
        return subcommand == 'add'
    return False


def _is_deployment_segment(program: str, args: list[str]) -> bool:
    if not args:
        return False
    subcommand = args[0]
    if program == 'kubectl':
        return subcommand in _KUBECTL_DEPLOY_SUBCOMMANDS
    if program == 'helm':
        return subcommand in _HELM_DEPLOY_SUBCOMMANDS
    if program == 'terraform':
        return subcommand in _TERRAFORM_DEPLOY_SUBCOMMANDS
    if program == 'docker':
        return subcommand == 'push'
    if program == 'git':
        return subcommand == 'push'
    if program == 'gh':
        return subcommand == 'release'
    if program == 'npm':
        return subcommand == 'publish'
    if program == 'twine':
        return subcommand == 'upload'
    return False


def _segments_match(
    segments: list[list[str]],
    predicate: Callable[[str, list[str]], bool],
    depth: int = 0,
) -> bool:
    for segment in segments:
        program, args = _program_of(segment)
        if predicate(program, args):
            return True
        # Inspect `sh -c '<command>'` payloads so wrapped commands cannot
        # bypass the policy.
        if depth < _MAX_NESTED_DEPTH and program in _SHELL_PROGRAMS:
            for idx, arg in enumerate(args):
                if arg == '-c' and idx + 1 < len(args):
                    nested = _pipeline_segments(_tokenize(args[idx + 1]))
                    if _segments_match(nested, predicate, depth + 1):
                        return True
    return False


def _command_matches(
    command: str,
    patterns: tuple[str, ...],
    predicate: Callable[[str, list[str]], bool],
) -> bool:
    """Match a command either via the configurable regex patterns or via a
    structural check over the tokenized argv of every pipeline segment."""
    if _matches_any(command, patterns):
        return True
    return _segments_match(_pipeline_segments(_tokenize(command)), predicate)


# ───────────────────────────────────────────────────────
#  Sensitive path matching
# ───────────────────────────────────────────────────────


def _pattern_parts(pattern: str) -> tuple[str, ...]:
    return tuple(
        part for part in PurePosixPath(pattern.replace('\\', '/')).parts if part != '.'
    )


def _parts_match(parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Component-wise glob match where ``**`` crosses directory boundaries.

    ``fnmatch`` treats ``*`` as not crossing ``/``, so ``**/.env`` never
    matched a repository-root ``.env``; matching per path component fixes
    that while still covering full paths like ``secrets/db.yaml``.
    """
    if not pattern_parts:
        return not parts
    head = pattern_parts[0]
    if head == '**':
        return any(
            _parts_match(parts[i:], pattern_parts[1:]) for i in range(len(parts) + 1)
        )
    if not parts:
        return False
    return fnmatch.fnmatch(parts[0], head) and _parts_match(
        parts[1:], pattern_parts[1:]
    )


def _path_matches(path: PurePosixPath, pattern: str) -> bool:
    return _parts_match(path.parts, _pattern_parts(pattern))


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
        if _command_matches(
            command, self.high_risk_command_patterns, _is_high_risk_segment
        ):
            reasons.append(ApprovalReason.HIGH_RISK_COMMAND)
        if _command_matches(
            command, self.external_network_patterns, _is_external_network_segment
        ):
            reasons.append(ApprovalReason.EXTERNAL_NETWORK)
        if _command_matches(
            command, self.deployment_command_patterns, _is_deployment_segment
        ):
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
        posix_path = PurePosixPath(normalized)
        if not any(
            _path_matches(posix_path, pattern)
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

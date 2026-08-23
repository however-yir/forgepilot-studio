"""ForgePilot team space model.

Provides personal/team/shared workspace isolation with role-based permissions.
Every task, template, and audit record is scoped to a space_id for data isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SpaceRole(str, Enum):
    OWNER = 'owner'
    ADMIN = 'admin'
    MEMBER = 'member'
    VIEWER = 'viewer'


class SpaceType(str, Enum):
    PERSONAL = 'personal'
    TEAM = 'team'
    SHARED_TEMPLATE = 'shared_template'


_ROLE_HIERARCHY: dict[SpaceRole, int] = {
    SpaceRole.OWNER: 4,
    SpaceRole.ADMIN: 3,
    SpaceRole.MEMBER: 2,
    SpaceRole.VIEWER: 1,
}

_PERMISSION_MATRIX: dict[str, list[SpaceRole]] = {
    'space:read': [
        SpaceRole.VIEWER,
        SpaceRole.MEMBER,
        SpaceRole.ADMIN,
        SpaceRole.OWNER,
    ],
    'space:write': [SpaceRole.MEMBER, SpaceRole.ADMIN, SpaceRole.OWNER],
    'space:manage': [SpaceRole.ADMIN, SpaceRole.OWNER],
    'space:delete': [SpaceRole.OWNER],
    'task:create': [SpaceRole.MEMBER, SpaceRole.ADMIN, SpaceRole.OWNER],
    'task:read': [SpaceRole.VIEWER, SpaceRole.MEMBER, SpaceRole.ADMIN, SpaceRole.OWNER],
    'task:manage': [SpaceRole.ADMIN, SpaceRole.OWNER],
    'template:read': [
        SpaceRole.VIEWER,
        SpaceRole.MEMBER,
        SpaceRole.ADMIN,
        SpaceRole.OWNER,
    ],
    'template:write': [SpaceRole.ADMIN, SpaceRole.OWNER],
    'audit:read': [SpaceRole.MEMBER, SpaceRole.ADMIN, SpaceRole.OWNER],
    'billing:read': [SpaceRole.ADMIN, SpaceRole.OWNER],
    'billing:manage': [SpaceRole.OWNER],
}


class SpaceMember(BaseModel):
    user_id: str
    role: SpaceRole
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TeamSpace(BaseModel):
    space_id: str
    name: str
    space_type: SpaceType = SpaceType.PERSONAL
    owner_id: str
    members: dict[str, SpaceMember] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    quota_tasks: int = 100
    quota_storage_mb: int = 1024
    is_archived: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def _ensure_owner_is_member(self) -> TeamSpace:
        if self.owner_id not in self.members:
            self.members[self.owner_id] = SpaceMember(
                user_id=self.owner_id,
                role=SpaceRole.OWNER,
                joined_at=self.created_at,
            )
        return self


class SpacePermissionGuard:
    """Runtime permission checker scoped to a specific team space."""

    def __init__(self, space: TeamSpace) -> None:
        self._space = space

    def get_role(self, user_id: str) -> SpaceRole | None:
        member = self._space.members.get(user_id)
        return member.role if member else None

    def can(self, user_id: str, permission: str) -> bool:
        role = self.get_role(user_id)
        if role is None:
            return False
        allowed_roles = _PERMISSION_MATRIX.get(permission, [])
        return role in allowed_roles

    def require(self, user_id: str, permission: str) -> None:
        if not self.can(user_id, permission):
            role = self.get_role(user_id)
            raise PermissionError(
                f'User {user_id} (role={role}) lacks permission {permission} '
                f'in space {self._space.space_id}'
            )

    def is_at_least(self, user_id: str, min_role: SpaceRole) -> bool:
        role = self.get_role(user_id)
        if role is None:
            return False
        return _ROLE_HIERARCHY.get(role, 0) >= _ROLE_HIERARCHY.get(min_role, 0)

    def list_members_with_role(self, min_role: SpaceRole) -> list[str]:
        return [
            uid
            for uid, member in self._space.members.items()
            if _ROLE_HIERARCHY.get(member.role, 0) >= _ROLE_HIERARCHY.get(min_role, 0)
        ]


class SpaceRegistry:
    """In-memory registry of team spaces. Replace with DB-backed store in production."""

    def __init__(self) -> None:
        self._spaces: dict[str, TeamSpace] = {}

    def create_space(
        self,
        space_id: str,
        name: str,
        owner_id: str,
        space_type: SpaceType = SpaceType.PERSONAL,
    ) -> TeamSpace:
        if space_id in self._spaces:
            raise ValueError(f'Space {space_id} already exists')
        space = TeamSpace(
            space_id=space_id,
            name=name,
            space_type=space_type,
            owner_id=owner_id,
        )
        self._spaces[space_id] = space
        return space

    def get_space(self, space_id: str) -> TeamSpace | None:
        return self._spaces.get(space_id)

    def list_user_spaces(self, user_id: str) -> list[TeamSpace]:
        return [s for s in self._spaces.values() if user_id in s.members]

    def add_member(
        self, space_id: str, user_id: str, role: SpaceRole, *, actor_id: str
    ) -> None:
        space = self._get_space_or_raise(space_id)
        guard = SpacePermissionGuard(space)
        guard.require(actor_id, 'space:manage')
        if role == SpaceRole.OWNER:
            raise PermissionError(
                'OWNER role is fixed at space creation and cannot be granted'
            )
        space.members[user_id] = SpaceMember(user_id=user_id, role=role)

    def remove_member(self, space_id: str, user_id: str, *, actor_id: str) -> None:
        space = self._get_space_or_raise(space_id)
        guard = SpacePermissionGuard(space)
        guard.require(actor_id, 'space:manage')
        if user_id == space.owner_id:
            raise PermissionError('Cannot remove the space owner')
        space.members.pop(user_id, None)

    def change_role(
        self, space_id: str, user_id: str, new_role: SpaceRole, *, actor_id: str
    ) -> None:
        space = self._get_space_or_raise(space_id)
        guard = SpacePermissionGuard(space)
        guard.require(actor_id, 'space:manage')
        if user_id not in space.members:
            raise ValueError(f'User {user_id} is not a member')
        if user_id == space.owner_id:
            raise PermissionError('Cannot change the space owner role')
        if new_role == SpaceRole.OWNER:
            raise PermissionError(
                'OWNER role is fixed at space creation and cannot be granted'
            )
        space.members[user_id].role = new_role

    def guard(self, space_id: str) -> SpacePermissionGuard:
        return SpacePermissionGuard(self._get_space_or_raise(space_id))

    def _get_space_or_raise(self, space_id: str) -> TeamSpace:
        space = self._spaces.get(space_id)
        if space is None:
            raise ValueError(f'Space {space_id} not found')
        return space


# Singleton
space_registry = SpaceRegistry()

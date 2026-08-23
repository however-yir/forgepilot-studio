"""Tests for team space permissions and data isolation (B-17)."""

import pytest

from openhands.forgepilot.teamspace import (
    SpaceMember,
    SpacePermissionGuard,
    SpaceRegistry,
    SpaceRole,
    SpaceType,
    TeamSpace,
    space_registry,
)


def test_create_personal_space():
    space = space_registry.create_space(
        'test-personal', 'My Space', 'user-1', SpaceType.PERSONAL
    )
    assert space.owner_id == 'user-1'
    assert 'user-1' in space.members
    assert space.members['user-1'].role == SpaceRole.OWNER


def test_permission_guard_owner_has_all():
    space = TeamSpace(space_id='s1', name='Test', owner_id='owner-1')
    guard = SpacePermissionGuard(space)
    assert guard.can('owner-1', 'space:delete')
    assert guard.can('owner-1', 'space:write')
    assert guard.can('owner-1', 'space:read')


def test_permission_guard_viewer_limited():
    space = TeamSpace(space_id='s1', name='Test', owner_id='owner-1')
    space.members['viewer-1'] = SpaceMember(user_id='viewer-1', role=SpaceRole.VIEWER)
    guard = SpacePermissionGuard(space)
    assert guard.can('viewer-1', 'space:read')
    assert not guard.can('viewer-1', 'space:write')
    assert not guard.can('viewer-1', 'space:delete')


def test_permission_guard_unknown_user():
    space = TeamSpace(space_id='s1', name='Test', owner_id='owner-1')
    guard = SpacePermissionGuard(space)
    assert not guard.can('stranger', 'space:read')


def test_role_hierarchy():
    space = TeamSpace(space_id='s1', name='Test', owner_id='owner-1')
    space.members['admin-1'] = SpaceMember(user_id='admin-1', role=SpaceRole.ADMIN)
    guard = SpacePermissionGuard(space)
    assert guard.is_at_least('admin-1', SpaceRole.MEMBER)
    assert not guard.is_at_least('admin-1', SpaceRole.OWNER)
    assert guard.is_at_least('owner-1', SpaceRole.OWNER)


def test_list_user_spaces():
    space_registry.create_space('s2', 'Space 2', 'user-2')
    spaces = space_registry.list_user_spaces('user-2')
    assert any(s.space_id == 's2' for s in spaces)


# ── M-5: OWNER role integrity ────────────────────────


def _make_registry_with_admin() -> tuple[SpaceRegistry, str]:
    registry = SpaceRegistry()
    registry.create_space('space-1', 'Team Space', 'owner-1', SpaceType.TEAM)
    registry.add_member('space-1', 'admin-1', SpaceRole.ADMIN, actor_id='owner-1')
    registry.add_member('space-1', 'member-1', SpaceRole.MEMBER, actor_id='owner-1')
    return registry, 'space-1'


def test_admin_cannot_grant_owner_role_via_add_member():
    registry, space_id = _make_registry_with_admin()
    with pytest.raises(PermissionError, match='OWNER role is fixed'):
        registry.add_member(space_id, 'attacker-1', SpaceRole.OWNER, actor_id='admin-1')
    space = registry.get_space(space_id)
    assert 'attacker-1' not in space.members


def test_admin_cannot_promote_self_or_others_to_owner_via_change_role():
    registry, space_id = _make_registry_with_admin()
    with pytest.raises(PermissionError, match='OWNER role is fixed'):
        registry.change_role(space_id, 'admin-1', SpaceRole.OWNER, actor_id='admin-1')


def test_owner_role_cannot_be_changed_even_by_owner():
    registry, space_id = _make_registry_with_admin()
    with pytest.raises(PermissionError, match='Cannot change the space owner role'):
        registry.change_role(space_id, 'owner-1', SpaceRole.ADMIN, actor_id='owner-1')
    space = registry.get_space(space_id)
    assert space.members['owner-1'].role == SpaceRole.OWNER


def test_owner_cannot_be_removed():
    registry, space_id = _make_registry_with_admin()
    with pytest.raises(PermissionError, match='Cannot remove the space owner'):
        registry.remove_member(space_id, 'owner-1', actor_id='admin-1')


def test_regular_role_changes_still_work():
    registry, space_id = _make_registry_with_admin()
    registry.change_role(space_id, 'member-1', SpaceRole.ADMIN, actor_id='owner-1')
    space = registry.get_space(space_id)
    assert space.members['member-1'].role == SpaceRole.ADMIN
    registry.add_member(space_id, 'viewer-1', SpaceRole.VIEWER, actor_id='admin-1')
    assert space.members['viewer-1'].role == SpaceRole.VIEWER

import openhands.forgepilot as forgepilot
from openhands.forgepilot import (
    audit,
    control_plane,
    llm_gateway,
    runtime_providers,
    teamspace,
)


def test_forgepilot_package_exports_product_modules():
    expected_modules = {
        'audit',
        'control_plane',
        'delivery',
        'llm_gateway',
        'orchestration',
        'platform',
        'runtime_providers',
        'teamspace',
        'tool_registry',
    }

    assert expected_modules.issubset(set(forgepilot.__all__))


def test_control_plane_public_contract():
    expected_symbols = {
        'TaskPhase',
        'TaskSpec',
        'ChangeBoundary',
        'TaskExecutionPolicy',
        'DEFAULT_TASK_PROTOCOL',
        'is_valid_phase_transition',
        'validate_phase_sequence',
        'select_verification_commands',
    }

    assert expected_symbols.issubset(set(control_plane.__all__))


def test_audit_public_contract():
    expected_symbols = {
        'AuditEventType',
        'AuditEvent',
        'ordered_timeline',
        'export_audit_events_jsonl',
        'export_audit_events_csv',
        'build_task_evidence_pack',
        'audit_events_from_event_stream',
        'AuditTimeline',
        'build_timeline',
    }

    assert expected_symbols.issubset(set(audit.__all__))


def test_llm_gateway_public_contract():
    expected_symbols = {
        'LLMGatewayProvider',
        'list_gateway_providers',
        'detect_provider',
        'normalize_model_identifier',
    }

    assert expected_symbols.issubset(set(llm_gateway.__all__))


def test_runtime_provider_public_contract():
    expected_symbols = {
        'RuntimeProviderSpec',
        'list_runtime_providers',
        'get_runtime_provider',
    }

    assert expected_symbols.issubset(set(runtime_providers.__all__))


def test_teamspace_core_types_are_importable():
    assert teamspace.TeamSpace
    assert teamspace.SpaceRole
    assert teamspace.SpacePermissionGuard

from datetime import UTC, datetime
from types import SimpleNamespace

from openhands.forgepilot.audit.event_stream import audit_events_from_event_stream
from openhands.forgepilot.audit.schema import AuditEventType


class MessageAction:
    def __init__(self, content: str, source: str, event_id: int):
        self.content = content
        self.source = source
        self.id = event_id
        self.timestamp = datetime.now(UTC).isoformat()
        self.response_id = None


class CmdRunAction:
    def __init__(self, command: str, event_id: int):
        self.command = command
        self.confirmation_state = 'awaiting_confirmation'
        self.security_risk = 'high'
        self.cwd = None
        self.blocking = False
        self.id = event_id
        self.timestamp = datetime.now(UTC).isoformat()
        self.response_id = None


class CmdOutputObservation:
    def __init__(self, content: str, command: str, event_id: int):
        self.content = content
        self.command = command
        self.metadata = SimpleNamespace(exit_code=0, working_dir='/workspace')
        self.id = event_id
        self.timestamp = datetime.now(UTC).isoformat()
        self.response_id = None


def test_audit_events_from_event_stream_exports_required_event_types():
    user_message = MessageAction('Fix login bug', 'user', 1)
    agent_message = MessageAction(
        'I will patch the missing profile guard.',
        'agent',
        2,
    )
    command = CmdRunAction('npm test', 3)
    test_output = CmdOutputObservation('12 passed', 'npm test', 4)

    events = audit_events_from_event_stream(
        [user_message, agent_message, command, test_output],
        task_id='task-login',
    )
    event_types = [event.event_type for event in events]

    assert AuditEventType.TASK_CREATED in event_types
    assert AuditEventType.MODEL_RESPONSE in event_types
    assert AuditEventType.COMMAND_RUN in event_types
    assert AuditEventType.TEST_RESULT in event_types
    assert AuditEventType.APPROVAL_REQUESTED in event_types
    assert events[-1].payload['exit_code'] == 0

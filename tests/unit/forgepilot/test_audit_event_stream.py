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


def test_subsequent_user_messages_are_recorded_as_user_message_events():
    """Multi-turn conversations must keep every user input in the audit trail.

    Previously only the first user message was recorded (as TASK_CREATED);
    follow-up user messages vanished from the audit export entirely.
    """
    first = MessageAction('Fix login bug', 'user', 1)
    followup_1 = MessageAction('Also fix the signup flow', 'user', 5)
    followup_2 = MessageAction('Bump the timeout to 30s', 'user', 9)

    events = audit_events_from_event_stream(
        [first, followup_1, followup_2],
        task_id='task-login',
    )

    task_created = [e for e in events if e.event_type == AuditEventType.TASK_CREATED]
    user_messages = [e for e in events if e.event_type == AuditEventType.USER_MESSAGE]

    assert len(task_created) == 1
    assert task_created[0].summary == 'Fix login bug'

    assert len(user_messages) == 3
    assert [m.summary for m in user_messages] == [
        'Fix login bug',
        'Also fix the signup flow',
        'Bump the timeout to 30s',
    ]
    assert all(m.payload['source'] == 'user' for m in user_messages)

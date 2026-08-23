from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field


class ConfirmationToken(BaseModel):
    token: str
    subject: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    consumed_at: datetime | None = None

    @property
    def consumed(self) -> bool:
        return self.consumed_at is not None


class ConfirmationGate:
    def __init__(self) -> None:
        self._tokens: dict[str, ConfirmationToken] = {}

    def issue(
        self,
        subject: str,
        *,
        ttl_seconds: int | None = 300,
    ) -> ConfirmationToken:
        now = datetime.now(UTC)
        self._prune(now)
        confirmation = ConfirmationToken(
            token=uuid4().hex,
            subject=subject,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds)
            if ttl_seconds is not None
            else None,
        )
        self._tokens[confirmation.token] = confirmation
        return confirmation

    def consume(self, token: str, *, subject: str | None = None) -> bool:
        confirmation = self._tokens.get(token)
        if confirmation is None or confirmation.consumed:
            return False

        if subject is not None and confirmation.subject != subject:
            return False

        now = datetime.now(UTC)
        if confirmation.expires_at is not None and now > confirmation.expires_at:
            return False

        confirmation.consumed_at = now
        return True

    def _prune(self, now: datetime) -> None:
        """Drop consumed and expired tokens.

        Keeping them would grow the dict without bound: both a missing and a
        consumed token make ``consume`` return False, so replay protection is
        unaffected.
        """
        stale = [
            token
            for token, confirmation in self._tokens.items()
            if confirmation.consumed
            or (confirmation.expires_at is not None and now > confirmation.expires_at)
        ]
        for token in stale:
            del self._tokens[token]

"""Configuration-driven mapping from source values to target values."""

from __future__ import annotations

from allwr_toolkit.configuration import MappingConfig
from allwr_toolkit.core.errors import ConfigurationError
from allwr_toolkit.core.models import CanonicalUser, MappingDecision


class Mapper:
    """Resolves users, statuses and priorities according to configuration.

    Every resolution is recorded as a :class:`MappingDecision` so plans and
    reports can show exactly what was mapped and why.
    """

    def __init__(self, config: MappingConfig) -> None:
        self._config = config
        self._by_id: dict[str, int] = {}
        self._by_email: dict[str, int] = {}
        self._by_name: dict[str, int] = {}
        for entry in config.users:
            if entry.source_id:
                self._by_id[entry.source_id] = entry.target_user_id
            if entry.email:
                self._by_email[entry.email.lower()] = entry.target_user_id
            if entry.name:
                self._by_name[entry.name] = entry.target_user_id
        self.decisions: list[MappingDecision] = []
        self.unknown_users: dict[str, CanonicalUser] = {}

    @property
    def on_unknown_user(self) -> str:
        return self._config.on_unknown_user

    def map_user(self, user: CanonicalUser | None) -> int | None:
        """Return the target user id for *user*, honouring the unknown policy."""
        if user is None:
            return None
        target: int | None = None
        if user.source_id and user.source_id in self._by_id:
            target = self._by_id[user.source_id]
        elif user.email and user.email.lower() in self._by_email:
            target = self._by_email[user.email.lower()]
        elif user.name and user.name in self._by_name:
            target = self._by_name[user.name]
        key = user.source_id or user.email or user.name or ""
        if target is None and key:
            self.unknown_users[key] = user
            if self._config.on_unknown_user == "fail":
                raise ConfigurationError(
                    f"no user mapping for source user '{key}' and on_unknown_user is 'fail'"
                )
        self.decisions.append(
            MappingDecision(
                kind="user",
                source_value=key,
                target_value=str(target) if target is not None else None,
                reason=None if target is not None else f"unknown ({self._config.on_unknown_user})",
            )
        )
        return target

    def should_skip_for_user(self, user: CanonicalUser | None) -> bool:
        """True when policy 'skip' applies: user is set but unmappable."""
        if user is None or self._config.on_unknown_user != "skip":
            return False
        return self.map_user(user) is None

    def map_status(self, value: str | None) -> str | None:
        if value is None:
            return self._config.default_status
        mapped = self._config.statuses.get(value, self._config.default_status)
        self.decisions.append(
            MappingDecision(kind="status", source_value=value, target_value=mapped)
        )
        return mapped

    def map_priority(self, value: str | None) -> str | None:
        if value is None:
            return self._config.default_priority
        mapped = self._config.priorities.get(value, self._config.default_priority)
        self.decisions.append(
            MappingDecision(kind="priority", source_value=value, target_value=mapped)
        )
        return mapped

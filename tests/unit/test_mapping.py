"""User/status/priority mapping and unknown-user policies."""

import pytest

from allwr_toolkit.configuration import MappingConfig, UserMapEntry
from allwr_toolkit.core.errors import ConfigurationError
from allwr_toolkit.core.mapping import Mapper
from allwr_toolkit.core.models import CanonicalUser


def make_mapper(policy: str = "null") -> Mapper:
    return Mapper(
        MappingConfig(
            users=[
                UserMapEntry(source_id="src-1", target_user_id=11),
                UserMapEntry(email="robin.roe@example.com", target_user_id=12),
                UserMapEntry(name="Alex Doe", target_user_id=13),
            ],
            statuses={"open": "in_progress"},
            priorities={"urgent": "high"},
            default_priority="medium",
            on_unknown_user=policy,  # type: ignore[arg-type]
        )
    )


def test_maps_by_id_email_and_name() -> None:
    mapper = make_mapper()
    assert mapper.map_user(CanonicalUser(source_id="src-1")) == 11
    assert mapper.map_user(CanonicalUser(email="Robin.Roe@example.com")) == 12
    assert mapper.map_user(CanonicalUser(name="Alex Doe")) == 13


def test_unknown_user_null_policy_returns_none_and_records() -> None:
    mapper = make_mapper("null")
    assert mapper.map_user(CanonicalUser(source_id="ghost")) is None
    assert "ghost" in mapper.unknown_users


def test_unknown_user_fail_policy_raises() -> None:
    mapper = make_mapper("fail")
    with pytest.raises(ConfigurationError):
        mapper.map_user(CanonicalUser(source_id="ghost"))


def test_unknown_user_skip_policy() -> None:
    mapper = make_mapper("skip")
    assert mapper.should_skip_for_user(CanonicalUser(source_id="ghost")) is True
    assert mapper.should_skip_for_user(CanonicalUser(source_id="src-1")) is False
    assert mapper.should_skip_for_user(None) is False


def test_status_and_priority_mapping_with_defaults() -> None:
    mapper = make_mapper()
    assert mapper.map_status("open") == "in_progress"
    assert mapper.map_status("weird") is None
    assert mapper.map_priority("urgent") == "high"
    assert mapper.map_priority("weird") == "medium"


def test_decisions_are_recorded() -> None:
    mapper = make_mapper()
    mapper.map_user(CanonicalUser(source_id="src-1"))
    mapper.map_user(CanonicalUser(source_id="ghost"))
    kinds = [d.kind for d in mapper.decisions]
    assert kinds.count("user") == 2
    unknown = [d for d in mapper.decisions if d.target_value is None]
    assert unknown and "unknown" in (unknown[0].reason or "")

"""Asana raw payload -> canonical model conversion."""

import json
from pathlib import Path
from typing import Any

from allwr_toolkit.connectors.asana.convert import (
    clamp_completed_at,
    is_rich,
    to_canonical,
)
from allwr_toolkit.core.models import UnsupportedField

EXPORT = Path(__file__).parent.parent / "fixtures" / "asana_export"


def load(gid: str) -> dict[str, Any]:
    return json.loads((EXPORT / "tasks" / f"{gid}.json").read_text(encoding="utf-8"))


def loader(gid: str) -> dict[str, Any] | None:
    path = EXPORT / "tasks" / f"{gid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def convert(gid: str, unsupported: list[UnsupportedField] | None = None) -> Any:
    return to_canonical(
        load(gid),
        scope="export:test",
        load_subtask=loader,
        data_dir=str(EXPORT),
        unsupported=unsupported,
    )


def test_gid_preserved_as_external_ref() -> None:
    task = convert("1200000000000001")
    assert task.source.record_id == "1200000000000001"
    assert task.source.external_ref == "1200000000000001"
    assert task.source.system == "asana"


def test_rich_subtask_becomes_subtask_and_title_only_becomes_checklist() -> None:
    task = convert("1200000000000001")
    assert [s.source.record_id for s in task.subtasks] == ["1200000000000002"]
    assert [c.source_id for c in task.checklist] == ["1200000000000003"]


def test_is_rich_detection() -> None:
    assert is_rich(load("1200000000000002")) is True  # has notes
    assert is_rich(load("1200000000000003")) is False  # title only


def test_completed_at_clamped_to_created_at() -> None:
    raw = load("1200000000000002")  # completed before created in the fixture
    clamped = clamp_completed_at(raw)
    assert clamped is not None
    assert clamped.isoformat().startswith("2024-03-01")


def test_description_sanitized_and_footer_links_source() -> None:
    task = convert("1200000000000001")
    assert task.description_html is not None
    assert "<script" not in task.description_html
    assert "hero section" in task.description_html
    assert "Imported from Asana" in task.description_html
    assert "1200000000000001" in task.description_html


def test_external_attachment_is_link_not_file() -> None:
    task = convert("1200000000000001")
    by_id = {a.source_id: a for a in task.attachments}
    assert by_id["1200000000000602"].is_external_link
    assert not by_id["1200000000000601"].is_external_link
    local = by_id["1200000000000601"].local_path
    assert local is not None and Path(local).is_file()


def test_unsupported_fields_reported_not_dropped() -> None:
    unsupported: list[UnsupportedField] = []
    convert("1200000000000001", unsupported)
    assert any(f.field == "dependencies" for f in unsupported)


def test_comments_sorted_and_authors_preserved() -> None:
    task = convert("1200000000000001")
    assert [c.source_id for c in task.comments] == [
        "1200000000000501",
        "1200000000000502",
    ]
    assert task.comments[1].author is not None
    assert task.comments[1].author.name == "Former Employee"

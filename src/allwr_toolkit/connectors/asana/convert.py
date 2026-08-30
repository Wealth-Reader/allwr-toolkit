"""Convert raw Asana task payloads into the canonical model.

The distinction that matters most: a *rich* subtask (with notes, comments,
attachments or its own subtasks) becomes a full canonical subtask migrated as
a linked task, while a title-only subtask becomes a checklist item. Distinct
GIDs are never merged, even when titles are identical.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from allwr_toolkit.core.models import (
    CanonicalAttachment,
    CanonicalChecklistItem,
    CanonicalComment,
    CanonicalTask,
    CanonicalUser,
    CustomFieldValue,
    SourceRef,
    UnsupportedField,
)
from allwr_toolkit.security import sanitize_html

SYSTEM = "asana"

# Source fields we knowingly cannot represent in ALL WR yet; they are reported
# in the plan instead of being dropped silently.
_UNSUPPORTED_TASK_FIELDS = {
    "dependencies": "task dependencies are not supported by the target API",
    "dependents": "task dependents are not supported by the target API",
    "approval_status": "approval workflows are not supported by the target API",
    "actual_time_minutes": "time tracking is not supported by the target API",
}


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _user(raw: dict[str, Any] | None) -> CanonicalUser | None:
    if not raw:
        return None
    return CanonicalUser(source_id=raw.get("gid"), name=raw.get("name"), email=raw.get("email"))


def is_rich(raw_task: dict[str, Any]) -> bool:
    """A subtask is *rich* when flattening it to a checklist line would lose data."""
    if (raw_task.get("notes") or "").strip():
        return True
    if any(s.get("type") == "comment" for s in raw_task.get("stories", [])):
        return True
    if raw_task.get("attachments"):
        return True
    return bool(raw_task.get("subtask_gids"))


def clamp_completed_at(raw_task: dict[str, Any]) -> datetime | None:
    """completed_at must never precede created_at (Asana data can)."""
    if not raw_task.get("completed"):
        return None
    completed = raw_task.get("completed_at") or raw_task.get("modified_at")
    created = raw_task.get("created_at")
    if completed and created and completed < created:
        completed = created
    return parse_dt(completed)


def _description(raw_task: dict[str, Any], scope: str) -> str:
    body = sanitize_html(raw_task.get("html_notes") or "")
    if not body and raw_task.get("notes"):
        body = "<p>" + html.escape(raw_task["notes"]).replace("\n", "<br />") + "</p>"
    projects = []
    for membership in raw_task.get("memberships", []):
        project = (membership.get("project") or {}).get("name")
        section = (membership.get("section") or {}).get("name")
        if project:
            label = project + (f" / {section}" if section and section != "Untitled section" else "")
            projects.append(label)
    if not projects:
        projects = [p.get("name", "") for p in raw_task.get("projects", []) if p.get("name")]
    header = ""
    if projects:
        header = f"<p><strong>[Asana: {html.escape(' - '.join(projects))}]</strong></p>\n"
    footer_bits = [
        "Imported from Asana"
        + (
            f' <a href="{html.escape(raw_task.get("permalink_url", ""))}">'
            f"{html.escape(raw_task.get('gid', ''))}</a>"
            if raw_task.get("permalink_url")
            else f" (gid {html.escape(raw_task.get('gid', ''))})"
        )
    ]
    completed_by = (raw_task.get("completed_by") or {}).get("name")
    if completed_by:
        footer_bits.append(f"Completed by {html.escape(completed_by)}")
    tags = [t.get("name") for t in raw_task.get("tags", []) if t.get("name")]
    if tags:
        footer_bits.append("Tags: " + html.escape(", ".join(tags)))
    external = [
        a
        for a in raw_task.get("attachments", [])
        if not a.get("local_path") and (a.get("view_url") or a.get("permanent_url"))
    ]
    external_links = "".join(
        f"<br />External attachment ({html.escape(str(a.get('host') or '?'))}): "
        f'<a href="{html.escape(a.get("view_url") or a.get("permanent_url") or "")}">'
        f"{html.escape(a.get('name') or 'link')}</a>"
        for a in external
    )
    footer = "<hr /><p><em>" + " - ".join(footer_bits) + external_links + "</em></p>"
    return header + body + "\n" + footer


def _attachments(raw_task: dict[str, Any], data_dir: str | None) -> list[CanonicalAttachment]:
    result: list[CanonicalAttachment] = []
    for raw in raw_task.get("attachments", []):
        local = raw.get("local_path")
        if local and data_dir:
            local = f"{data_dir}/{local}"
        result.append(
            CanonicalAttachment(
                source_id=str(raw.get("gid")),
                name=raw.get("name") or "attachment",
                size_bytes=raw.get("size"),
                created_at=parse_dt(raw.get("created_at")),
                download_url=raw.get("download_url"),
                local_path=local,
                external_url=(None if local else (raw.get("view_url") or raw.get("permanent_url"))),
            )
        )
    return result


def _comments(raw_task: dict[str, Any]) -> list[CanonicalComment]:
    comments: list[CanonicalComment] = []
    for story in raw_task.get("stories", []):
        if story.get("type") != "comment":
            continue
        body_html = sanitize_html(story.get("html_text") or "")
        body_text = story.get("text") or None
        if not body_html and not (body_text or "").strip():
            continue
        comments.append(
            CanonicalComment(
                source_id=str(story.get("gid")),
                author=_user(story.get("created_by")),
                created_at=parse_dt(story.get("created_at")),
                body_html=body_html or None,
                body_text=body_text,
                is_private=True,
            )
        )
    comments.sort(key=lambda c: (c.created_at is None, c.created_at))
    return comments


def to_canonical(
    raw_task: dict[str, Any],
    *,
    scope: str,
    load_subtask: Any,
    data_dir: str | None = None,
    unsupported: list[UnsupportedField] | None = None,
) -> CanonicalTask:
    """Build the canonical task for *raw_task*, recursing into rich subtasks.

    ``load_subtask(gid)`` returns the raw payload of a subtask, or ``None``.
    """
    gid = str(raw_task["gid"])
    if unsupported is not None:
        for field, reason in _UNSUPPORTED_TASK_FIELDS.items():
            if raw_task.get(field):
                unsupported.append(UnsupportedField(record_id=gid, field=field, reason=reason))
    checklist: list[CanonicalChecklistItem] = []
    subtasks: list[CanonicalTask] = []
    for sub_gid in raw_task.get("subtask_gids", []):
        raw_sub = load_subtask(sub_gid)
        if raw_sub is None:
            continue
        if is_rich(raw_sub):
            subtasks.append(
                to_canonical(
                    raw_sub,
                    scope=scope,
                    load_subtask=load_subtask,
                    data_dir=data_dir,
                    unsupported=unsupported,
                )
            )
        else:
            checklist.append(
                CanonicalChecklistItem(
                    source_id=str(raw_sub.get("gid")),
                    title=(raw_sub.get("name") or "(untitled)")[:500],
                    completed=bool(raw_sub.get("completed")),
                    assignee=_user(raw_sub.get("assignee")),
                    due_date=raw_sub.get("due_on"),
                    created_at=parse_dt(raw_sub.get("created_at")),
                    completed_at=clamp_completed_at(raw_sub),
                    created_by=_user(raw_sub.get("created_by")),
                )
            )
    return CanonicalTask(
        source=SourceRef(
            system=SYSTEM,
            scope=scope,
            record_type="task",
            record_id=gid,
            url=raw_task.get("permalink_url"),
        ),
        title=(raw_task.get("name") or "(untitled)").strip() or "(untitled)",
        description_html=_description(raw_task, scope),
        completed=bool(raw_task.get("completed")),
        created_at=parse_dt(raw_task.get("created_at")),
        modified_at=parse_dt(raw_task.get("modified_at")),
        completed_at=clamp_completed_at(raw_task),
        due_date=raw_task.get("due_on") or (raw_task.get("due_at") or "")[:10] or None,
        start_date=raw_task.get("start_on"),
        assignee=_user(raw_task.get("assignee")),
        created_by=_user(raw_task.get("created_by")),
        completed_by=_user(raw_task.get("completed_by")),
        projects=[p.get("name", "") for p in raw_task.get("projects", []) if p.get("name")],
        tags=[t.get("name", "") for t in raw_task.get("tags", []) if t.get("name")],
        custom_fields=[
            CustomFieldValue(
                name=f.get("name", ""),
                value=f.get("display_value"),
                field_type=f.get("type"),
            )
            for f in raw_task.get("custom_fields", [])
            if f.get("name")
        ],
        followers=[u for f in raw_task.get("followers", []) if (u := _user(f)) is not None],
        comments=_comments(raw_task),
        attachments=_attachments(raw_task, data_dir),
        checklist=checklist,
        subtasks=subtasks,
        source_metadata={
            "permalink_url": raw_task.get("permalink_url"),
            "num_subtasks": raw_task.get("num_subtasks"),
        },
    )

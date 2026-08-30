# Asana connector

Imports Asana projects, tasks, subtasks, comments, tags, custom fields and
attachments into ALL WR, driven by a **curated selection manifest** of task
GIDs.

## Modes

- **offline** (`source.mode: offline`): reads an export directory
  (`workspace.json`, `tasks/<gid>.json`, `attachments/<gid>/...`).
- **api** (`source.mode: api`): fetches the selected GIDs live from the
  Asana API (`ALLWR_TOOLKIT_ASANA_TOKEN`), with pagination and 429 handling.
  Without API access, offline mode can only migrate what the export
  contains.

## The selection manifest

A TSV file whose first column is the Asana GID: one top-level task per line;
`#` comments and `##` section headers are ignored; deleting or commenting a
line excludes the task; duplicate GIDs are reported; invalid GID-like lines
are reported, never silently dropped. The manifest is a migration input —
**never commit one containing real company data**.

## Behavior decisions

- The original GID is preserved as the stable external reference.
- Distinct GIDs are never deduplicated, even with identical titles.
- Rich subtasks (notes, comments, attachments or their own subtasks) become
  full tasks linked `subtask_of`; title-only subtasks become checklist items.
- Multi-project tasks keep their memberships in the description header; the
  task is created once (its GID is unique).
- Completed tasks keep their completion state and clamped `completed_at`
  (never before `created_at`).
- Unmappable authors are preserved as legacy author metadata.
- Externally hosted attachments are linked, not copied.
- Original timestamps travel as import metadata.

## Limitations

Dependencies, approval workflows and time tracking are reported as
unsupported fields. Archived projects are imported like active ones (their
archived state is source metadata). The importer itself never notifies
users: it only writes through the ALL WR import API, which suppresses
notification side effects for imported content.

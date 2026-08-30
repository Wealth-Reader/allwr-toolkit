# Instructions for AI agents working on tests

Read the root `AGENTS.md` first; these rules are additional and specific to
`tests/`.

- No real data, ever: no customer names, employee names, real emails, real
  Asana GIDs, real Freshdesk ticket ids, real domains or real exports.
  Fixtures are synthetic, English and unambiguously fake (`example.com`,
  `Alex Doe`, gid `1200000000000001`).
- No network: unit, contract and integration tests never call a live API.
  HTTP is mocked with `respx`. A test that needs production credentials is a
  bug.
- Deterministic: no sleeps against wall-clock behavior, no time-of-day
  dependence, no ordering assumptions on dicts or filesystem listings.
  Patch `_sleep` on clients instead of waiting.
- Temporary files only inside `tmp_path`; never write into the repository or
  the user's home directory.
- If you record HTTP fixtures from a real system: strip cookies and
  authorization headers, replace every email, name and id that is not needed,
  review the whole file before committing, and keep the sanitization test
  passing.
- Never weaken or delete a test to make CI pass; never lower coverage
  thresholds without an approved issue.

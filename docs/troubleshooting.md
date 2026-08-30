# Troubleshooting

## `allwr-toolkit doctor`

Start here: it checks Python, optional extras and (with `--config`) your
configuration and connector.

## Common failures

| Symptom | Cause / fix |
|---|---|
| `configuration_error: no ALL WR API key` | Export `ALLWR_TOOLKIT_ALLWR_API_KEY` |
| `plan_validation_error: plan hash mismatch` | The plan file changed after generation — regenerate it |
| `plan_validation_error: configuration changed` | Config edited after planning — re-plan and re-review |
| `blocked_by_warnings` (exit 3) | Review the high-severity warnings; accept specific codes in `options.accepted_warnings` only after reading them |
| `insufficient_scope` from ALL WR | Your API key lacks the `tasks:import` scope |
| Repeated 429s | The toolkit already honors `Retry-After`; large migrations just take time |
| `state file ... newer than this toolkit` | The state was written by a newer version — upgrade the toolkit |

## Exit codes

`0` success · `1` runtime error · `2` configuration/validation error ·
`3` apply blocked by unaccepted high-severity warnings.

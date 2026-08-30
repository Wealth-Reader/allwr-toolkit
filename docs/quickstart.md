# Quickstart

## 1. Install

```bash
pip install allwr-toolkit    # or, from a checkout: pip install .
```

## 2. Configure

Copy an example from `examples/` and adapt it. The target section has no
default: you always name the ALL WR API base URL and project explicitly.

```bash
cp examples/asana/migration.yaml migration.yaml
export ALLWR_TOOLKIT_ALLWR_API_KEY=wrk_your_key   # never on the command line
```

## 3. Inspect, plan, dry-run

```bash
allwr-toolkit migrate asana inspect --config migration.yaml
allwr-toolkit migrate asana plan    --config migration.yaml --out migration-plan.json
allwr-toolkit migrate asana apply   --config migration.yaml --plan migration-plan.json
```

The third command is a **dry run** (the default): it writes nothing to the
target and produces the full report bundle so you can review exactly what
would happen.

## 4. Apply for real

```bash
allwr-toolkit migrate asana apply --config migration.yaml \
  --plan migration-plan.json --no-dry-run
```

You will be shown the exact target (base URL, project, counts) and asked to
confirm; use `--yes` only in scripts. See [applying](applying.md).

# Minimal Lint Workflow — Design

## Purpose

Add a GitHub Actions workflow that catches broken dependencies and obvious code
errors (unused imports/vars, undefined names) on every push/PR to `main`.
This is the first CI step for the project, which currently has no lint, test,
or deploy automation.

## Scope

In scope:
- Dependency install verification (`pip install -r requirements.txt` must succeed)
- Lint check via `ruff`

Out of scope (deferred until a real deployment target exists):
- Automated deployment
- Test execution (no test suite exists in this repo)

## Design

**File**: `.github/workflows/lint.yml`

**Trigger**: `push` and `pull_request` events targeting `main`.

**Job**: single job `lint`, runs on `ubuntu-latest`.

Steps:
1. `actions/checkout@v4`
2. `actions/setup-python@v5` with `python-version: "3.11"` and `cache: pip`
3. `pip install -r requirements.txt` — fails the job if a dependency is
   missing, broken, or misspelled.
4. `pip install ruff` then `ruff check .` — fails the job on unused
   imports/variables, undefined names, and other default ruff rules.

No `ruff.toml`/`pyproject.toml` config is added; ruff's default rule set is
sufficient for this project's size and there's no existing convention to
encode.

## Error handling

Standard GitHub Actions behavior: any failing step fails the job and blocks
the check from going green on the PR/commit. No custom error handling needed.

## Testing

Verified by pushing the workflow and observing it run successfully (or
failing loudly) in the Actions tab — there is no local equivalent to "run
the workflow" since it depends on GitHub-hosted runners.

# Minimal Lint Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions workflow that fails CI when `requirements.txt` can't be installed or `ruff` finds lint errors, on every push/PR to `main`.

**Architecture:** Single-job GitHub Actions workflow at `.github/workflows/lint.yml`. No app code changes.

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`), Python 3.11, `ruff`.

## Global Constraints

- Trigger: `push` and `pull_request` events targeting `main` only (per spec `docs/superpowers/specs/2026-08-06-lint-workflow-design.md`).
- Python version: `3.11`.
- No `ruff.toml`/`pyproject.toml` config file — use ruff defaults.
- No test execution and no deployment step in this workflow (explicitly out of scope).

---

### Task 1: Add lint workflow

**Files:**
- Create: `.github/workflows/lint.yml`

**Interfaces:**
- Consumes: nothing (first task, no dependencies on other code).
- Produces: nothing consumed by later tasks — this is the only task in the plan.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/lint.yml`:

```yaml
name: Lint

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Install ruff
        run: pip install ruff

      - name: Run ruff
        run: ruff check .
```

- [ ] **Step 2: Validate YAML syntax locally**

Run: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/lint.yml'))" `

Expected: no output, exit code 0 (confirms the file is valid YAML before it ever reaches GitHub's runners).

If `PyYAML` isn't installed locally, run `pip install pyyaml` first — this is a one-off local check, not a project dependency, so do not add it to `requirements.txt`.

- [ ] **Step 3: Run ruff locally against the current codebase to preview CI's first result**

Run: `pip install ruff && ruff check .`

Expected: either a clean pass, or a list of findings. If there are findings, do **not** fix application code as part of this task — that's out of scope for a CI-workflow change. Just note the result; the workflow is still correct to add regardless of whether the existing codebase currently passes ruff (the point of adding CI is to surface exactly this).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/lint.yml
git commit -m "ci: add lint workflow (dependency install + ruff)"
```

- [ ] **Step 5: Push and verify the workflow runs on GitHub**

```bash
git push
```

Then check the repository's **Actions** tab on GitHub — confirm a "Lint" run appears for the pushed commit and completes (green or red, either is fine as verification; red would mean ruff found real issues, which is the workflow doing its job correctly).

# CI Setup: Integration Tests with MS Project

## Overview

WP-8 integration tests require a **Windows machine with MS Project installed**.
GitHub-hosted runners do NOT have MS Project, so integration tests run on
a **self-hosted runner**.

Unit tests (mock-based, in `tests/test_wp*.py`) run on any platform, including
GitHub-hosted Ubuntu runners.

## Requirements

### Self-Hosted Runner Machine

- **OS:** Windows 10/11
- **MS Project:** 2016+ (Professional or Standard), activated with a valid license
- **Python:** 3.10+ on PATH
- **pywin32:** `pip install pywin32`
- **RAM:** 8GB+ recommended (Project + Python + runner overhead)
- **Runner label:** `windows-project` (configured in GitHub Actions runner settings)

### First-Time Setup


1. **Install the GitHub Actions runner** on the Windows machine:
   ```powershell
   # Follow https://docs.github.com/en/actions/hosting-your-own-runners
   # Add label: windows-project
   ```

2. **Generate test fixtures** (one-time, or after fixture changes):
   ```powershell
   cd MS-Procject-MCP
   python tests/fixtures/generate_fixtures.py
   ```
   This creates `.mpp` files in `tests/fixtures/generated/`.

3. **Verify everything works locally**:
   ```powershell
   # Unit tests (should all pass)
   pytest tests/ -v --ignore=tests/integration/

   # Integration tests (requires Project)
   pytest tests/integration/ -v

   # All tests
   pytest tests/ -v
   ```

## Running Tests Manually


### On Mac/Linux (unit tests only)
```bash
pytest tests/ -v --ignore=tests/integration/
```
Integration tests auto-skip on non-Windows platforms.

### On Windows without Project
```powershell
pytest tests/ -v
```
Integration tests auto-skip when Project is not installed.

### On Windows with Project
```powershell
# Generate fixtures first (if not done)
python tests/fixtures/generate_fixtures.py

# Run everything
pytest tests/ -v
```

## Test Architecture

```
tests/
  fakes.py              # Shared mock objects
  test_wp1_session.py   # WP-1 unit tests (mock COM)
  test_wp2_identity.py  # WP-2 unit tests
  ...                   # WP-3 through WP-7 unit tests
  test_server_wiring.py # Server tool registration tests
  fixtures/
    generate_fixtures.py  # Creates .mpp files via COM
    generated/            # Output dir (gitignored)
  integration/
    conftest.py           # Harness: launch/teardown Project
    test_wp1_live.py      # WP-1 live COM tests
    test_wp2_live.py      # WP-2 live COM tests
    ...                   # WP-3 through WP-7 live tests
    test_server_e2e.py    # Full server tool smoke tests
```

## Troubleshooting


- **"MS Project not available" skip message:** Project is not installed,
  not licensed, or COM automation is blocked. Check that `WINPROJ.EXE`
  can be launched and that no group policy blocks COM.

- **Orphaned WINPROJ.EXE processes:** If tests crash mid-run, Project
  may remain running invisibly. Kill it:
  ```powershell
  taskkill /IM WINPROJ.EXE /F
  ```

- **"COM probe failed" errors:** Usually means Project needs activation
  or a dialog is blocking. Launch Project manually once, dismiss any
  setup wizards, then retry.

- **Tests pass locally but fail in CI:** Check that the runner service
  account has permission to launch Project. COM automation under
  SYSTEM or NETWORK SERVICE accounts may fail; run the runner as
  the logged-in user instead.

## License Considerations

MS Project requires a valid license for COM automation. Options:

- **Microsoft 365 E3/E5** with Project desktop app included
- **Project Standard/Professional** standalone license
- **Volume licensing** for CI machines

The runner machine must have Project activated before tests can run.
Trial/expired installs will fail at COM dispatch.

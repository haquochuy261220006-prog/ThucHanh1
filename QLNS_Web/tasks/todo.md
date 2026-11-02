# Employee Master Profile Tasks

## Phase 1: Identity and persistence boundary

- [x] **Task 1 — Source-link schema**
  - Acceptance: Add an idempotent table with unique `(SourceType, SourceKey)` and an FK to `NhanVien.MaNV`; include the DDL in both `app.py` schema initialization and `setup_db.py`; existing employee data is not rewritten.
  - Verify: On a disposable SQL Server database, fresh setup and repeated schema initialization both succeed and enforce unique source keys.
  - Files: `app.py`, `setup_db.py`

- [x] **Task 2 — Shared provision/link service**
  - Acceptance: Create a profile and register its source key in one transaction; the same key returns the same `MaNV`; a source can be linked to a selected existing `MaNV`; callers cannot choose a new `MaNV`.
  - Verify: Manual SQL Server check for first create, duplicate retry, link-existing, duplicate source key, and rollback when either write fails.
  - Files: `employee_profiles.py`

- [x] **Task 3 — Employee form integration**
  - Acceptance: Manual employee creation calls the shared service with a server-issued stable idempotency key; existing validation, authorization, CSRF, and redirect behavior remain; edit operations leave `MaNV` unchanged.
  - Verify: Submit the same form token twice and confirm one employee profile; submit a fresh token and confirm a new `MaNV`.
  - Files: `app.py`, `templates/module.html`

## Checkpoint: Core profile creation

- [ ] Existing `MaNV` values and attendance, leave, payroll, contract, and account links are unchanged.
- [ ] Same origin key maps to one `MaNV`; profile updates do not change the key.

## Phase 2: Lifecycle and integration contract

- [x] **Task 4 — Delete/offboarding safeguards**
  - Acceptance: Offboarding retains the profile; deletion is blocked for business history or non-manual source links; an unused manual profile can be deleted without reusing its ID.
  - Verify: Manual SQL Server acceptance for inactive profile, linked history, external source link, and unused manual profile.
  - Files: `app.py`

- [x] **Task 5 — Integration documentation**
  - Acceptance: Document `MaNV` as the only employee FK, `MaNVHT` as display-only, and the create/link contract for future modules.
  - Verify: Documentation agrees with table definitions and service function signature.
  - Files: `README.md`

## Checkpoint: Existing module compatibility

- [ ] Existing employee-linked rows still resolve to the same profile.
- [ ] Manual migration checks pass on a disposable SQL Server database.
- [ ] Run `python -m py_compile app.py setup_db.py db.py auth.py employee_profiles.py`.

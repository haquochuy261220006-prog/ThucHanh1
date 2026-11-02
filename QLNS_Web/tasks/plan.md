# Implementation Plan: Employee Master Profile

## Overview

Formalize the existing `NhanVien` table as the one employee master, preserving `MaNV` and all current SQL Server relationships. Add a shared, idempotent provisioning/linking boundary for future modules and retain profiles after offboarding. Recruitment, onboarding, KPI, training, and asset workflows remain out of scope because those modules do not exist yet.

## Architecture Decisions

- Keep `NhanVien.MaNV` as the canonical primary key; do not create a second employee table or change the `MaNVHT` display code.
- Add an additive source-link table keyed by `(SourceType, SourceKey)` and referencing `MaNV`. It lets a caller retry creation or link a source record to an existing employee without creating another profile.
- Use one transaction for profile creation plus source-link registration. Use a single database batch through the existing `db.query` helper so the helper commits/rolls back the operation as one unit.
- Keep the existing employee form as a caller of the shared provisioning boundary. Never accept a `MaNV` from the browser.
- Do not add a unique CCCD/email index in this plan. Existing data must be audited and the policy confirmed before enforcing identity uniqueness; the current server-side checks remain.
- Keep offboarding as a status change. Preserve the ability to remove an unused manual profile only when it has no business history and no non-manual source links.

## Dependency Graph

```text
Idempotent source-link schema
            |
            v
Shared employee provision/link service
            |
            v
Employee create form and route
            |
            v
Delete/offboarding compatibility + docs
```

## Task List

### Phase 1: Identity and persistence boundary

- [x] Task 1: Add an additive, repeatable SQL Server source-link table in both existing-schema initialization and fresh database setup.
- [x] Task 2: Add a shared employee service that transactionally creates one profile per source key or links a source key to a chosen existing `MaNV`.
- [x] Task 3: Route manual employee creation through the shared service using a server-issued idempotency key; preserve current field validation and `MaNV` generation.

### Checkpoint: Core profile creation

- [ ] Existing `MaNV` values and rows in attendance, leave, payroll, contracts, and accounts remain unchanged.
- [ ] Repeating the same source key returns the same `MaNV`; the operation does not create a second employee row.
- [ ] Updating a profile never changes `MaNV`.

### Phase 2: Lifecycle and integration contract

- [x] Task 4: Align hard-delete safeguards with source links and preserve current offboarding behavior.
- [x] Task 5: Document the `MaNV` foreign-key contract and the future candidate-to-employee linking boundary.

### Checkpoint: Existing module compatibility

- [ ] Existing employee-linked records still resolve to one `NhanVien.MaNV`.
- [ ] Offboarding retains employee and business history; deleting an employee with history or a non-manual source link is refused.
- [ ] A new module can link its stable source key to the same `MaNV` without copying the master profile.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Legacy CCCD/email duplicates | A new unique index could fail or block legitimate records. | Do not add a unique index before a data audit and explicit policy decision. Keep server validation. |
| Existing schema is initialized from `app.py` on first request while fresh installs use `setup_db.py`. | One path could omit the source-link table. | Add the same idempotent DDL to both paths and check upgrade plus fresh-schema behavior. |
| Employee-linked modules not yet implemented | Future code could bypass the source boundary. | Document the contract and require future module specs to consume the service and FK to `MaNV`. |
| Deleting a profile with an origin link | Can orphan an external process or candidate reference. | Refuse deletion when a non-manual source link exists; retain the profile and use inactive status. |
| SQL Server is not declared as a staging environment and the project has no test suite. | Runtime migration behavior cannot be proven locally by syntax checks alone. | Use a disposable SQL Server database for the manual upgrade/transaction checks before rollout. |

## Verification Plan

- Static syntax check: `python -m py_compile app.py setup_db.py db.py auth.py employee_profiles.py`
- On a disposable SQL Server database, run fresh setup and run application schema initialization twice; both paths must leave the source-link table/indexes intact.
- Seed existing employee-linked attendance, leave, payroll, contract, and account rows; apply the additive schema and verify all values and relationships are unchanged.
- Submit the same source key twice and verify both calls resolve to one `MaNV`; link a second source key to that existing employee and verify no second `NhanVien` row is created.
- Update and offboard a seeded employee; verify `MaNV` and historical joins are unchanged. Attempt deletion with business history or a non-manual origin and verify it is blocked.
- The project has no automated test suite. These are manual acceptance checks; do not run setup against production data.

## Open Questions / Deferred Decisions

- CCCD uniqueness remains deferred until existing data is audited and the user confirms the policy.
- Candidate linking will require an explicit HR choice between creating a new employee and linking an existing profile; the recruitment module will own that UI.
- Before rollout, confirm that a disposable SQL Server database is available for the migration checks.

## Approval Gate

Review this plan. Implementation starts after approval.

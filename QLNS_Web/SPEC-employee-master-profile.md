# Spec: Employee Master Profile

## Assumptions

1. `NhanVien.MaNV` remains the canonical internal employee key. It is generated once, immutable, and never reused.
2. `MaNVHT` is a human-readable display code only; database relationships use `MaNV`.
3. The existing employee table remains the source of core profile fields. This module does not create a second employee master table.
4. Candidates remain candidate records until an offer is accepted. Creating/linking the employee profile happens once at that transition; onboarding and later employee modules reference the resulting `MaNV`.
5. Recruitment, onboarding, KPI, training, and asset modules do not exist in this repository. This spec defines their data contract, not those modules' workflows.

## Objective

Make the existing `NhanVien` record the single source of truth for employee identity and core profile data. Prevent current and future modules from creating duplicate employee profiles, preserve identity across job changes and offboarding, and keep existing attendance, leave, payroll, and contract records attached to the same `MaNV`.

### In scope

- Preserve and formalize `NhanVien.MaNV` as the immutable employee primary key.
- Define how modules reference employees and how profile information is read and updated.
- Preserve `MaNV` values and existing employee-linked data during additive SQL Server schema changes.
- Keep an employee profile after offboarding by changing lifecycle status, while retaining historical business records.
- Provide a single employee creation/linking boundary for future modules so repeated requests cannot create duplicate employee profiles.
- Keep the current server-side authorization and profile validation rules when updating employee data.

### Out of scope

- Recruitment pipeline, offer approvals, onboarding checklists, KPI, training, and asset workflows.
- Organization tree, effective-dated employment history, custom fields, and document retention; these remain separate capabilities in the approved capability map.
- Changing the employee-code format or adding new account roles.
- Automatically merging two existing employee records based on name, email, phone, or other fuzzy matching.

## Tech Stack

- Python 3.10+
- Flask with server-rendered Jinja templates
- SQL Server through `pyodbc` and ODBC Driver 17 or 18
- Existing password/session and CSRF helpers; no new dependencies proposed

## Data Contract

```sql
-- Canonical row (existing table)
MaNV INT IDENTITY PRIMARY KEY

-- Every employee-owned record in another module
MaNV INT NOT NULL REFERENCES NhanVien(MaNV)
```

- `MaNV` identifies the employee for the lifetime of the record. It is not changed when name, department, job, manager, salary, or status changes.
- `MaNVHT` may be shown, searched, and exported, but must not be used as a foreign key.
- Module-specific tables store only their own data plus `MaNV`; they must not copy the employee's name, contact details, or full profile as an independent source of truth. Historical snapshots required for audit/payroll are governed by the relevant module's spec.
- Existing relationships from attendance, leave, payroll, and contracts remain valid. New modules must reference `NhanVien.MaNV` directly or through an explicitly defined relation that still resolves to this key.
- Candidate conversion must be idempotent: one accepted candidate results in one employee profile and all later onboarding/business records use that profile's `MaNV`. No automatic merge of unrelated employee profiles is allowed.
- `NhanVienNguon` maps a stable source pair `(LoaiNguon, MaNguonNgoai)` to one `MaNV`, with a unique constraint on the source pair and a foreign key to `NhanVien`. It records who created the link and when. The same source pair returns its existing `MaNV`; linking an already-used source to a different employee is rejected.
- The manual employee form uses a server-issued source key for safe retries. Future modules can call `employee_profiles.create_employee()` to create once per source or `employee_profiles.link_source()` to attach a verified source record to an explicitly selected existing profile.

## Lifecycle and Data Integrity

- New employee creation generates one `MaNV` through SQL Server identity; callers do not choose or modify it.
- Duplicate checks for supplied verified identifiers must be enforced at the persistence boundary, not only in a form. Existing data must be inspected before adding any unique constraint.
- Offboarding changes the employee lifecycle status and retains the profile and linked business history.
- An employee profile with linked business records cannot be hard-deleted through the application. Deletion of an unused test/draft profile must not reseed or recycle its `MaNV`.
- Database changes are additive and repeatable against an existing database. Do not renumber employee keys, drop old columns, or rewrite foreign keys without a reviewed migration and backup.

## Project Structure

- `app.py`: employee CRUD routes, profile validation, schema initialization, and application startup.
- `setup_db.py`: initial database and table definitions for a new installation.
- `db.py`: parameterized SQL Server query/execute helpers.
- `auth.py`: account creation/login; employee accounts attach through `TaiKhoan.MaNV`.
- `templates/`: employee and account forms/tables.
- `payroll.py`, `contracts.py`: current employee-linked business modules.
- `tests/`: no test directory or automated test suite currently exists; focused tests should be added for the profile boundary and schema compatibility.

## Code Style

Keep SQL parameterized and follow the existing `db` helper pattern:

```python
employee_id = db.query(
    "INSERT INTO NhanVien(HoTen) OUTPUT INSERTED.MaNV VALUES(?)",
    (full_name,),
)[1][0][0]
```

Do not accept a client-supplied `MaNV` for profile creation. Existing route validation and server-side authorization remain authoritative.

## Commands

- Create a local virtual environment: `py -m venv .venv`
- Install dependencies: `python -m pip install -r requirements.txt`
- Start the app: `python app.py`
- Create a new development database only: `python setup_db.py`
- Python syntax check: `python -m py_compile app.py setup_db.py db.py auth.py`
- Focused tests after a test suite is added: `python -m unittest discover -s tests -v`

`setup_db.py` must not be run against production data as a migration substitute. Back up SQL Server before applying schema changes.

## Testing Strategy

- Unit tests: employee ID is generated by SQL Server and ignored/rejected when supplied by a client; profile validation and duplicate handling behave consistently.
- SQL Server integration tests: fresh schema and upgrade of an existing database preserve every existing `MaNV`, attendance row, leave row, payroll row, contract, and account link.
- Relationship tests: module-owned rows reference the same `MaNV`; deleting/offboarding a profile does not orphan or erase referenced business history.
- Manual acceptance: create an employee, link an employee account, create representative attendance/payroll/contract records, change profile fields and offboard, then verify all records still resolve to the same `MaNV`.
- The repository currently has no test suite or declared staging SQL Server. These checks need a disposable SQL Server database before production rollout.

## Boundaries

- **Always:** use `MaNV` as the employee foreign key; parameterize SQL; validate and authorize on the server; preserve existing data during migrations; retain offboarded profiles with linked history.
- **Ask first:** changing `MaNV` or `MaNVHT` semantics; enforcing uniqueness on CCCD/email where legacy duplicates may exist; automatic candidate-to-employee matching; adding roles, dependencies, or external identity integrations.
- **Never:** create a separate employee master per module; use `MaNVHT` as a foreign key; silently merge people; reuse an issued `MaNV`; delete a profile with linked business records.

## Success Criteria

- Exactly one canonical `NhanVien` profile exists for each employee created through the application.
- `MaNV` is generated server-side, remains unchanged through profile updates and offboarding, and is never recycled.
- Existing attendance, leave, payroll, contract, and account records continue resolving to the same employee after schema upgrade.
- A repeated employee-creation/conversion request cannot create a second profile for the same source record.
- No new module stores an independent copy of core employee identity as its authoritative profile.
- No existing employee data is lost or renumbered during migration.

## Open Questions

1. Should a verified CCCD be globally unique when present? The current route checks duplicates, but the database does not yet enforce that invariant, and legacy rows need auditing first.
2. When a candidate accepts an offer, should HR always confirm whether to create a new employee profile or link to an existing one? The spec assumes explicit confirmation and no automatic merge.

## Approval Gate

Review this spec and answer **approve** or request changes. Planning and implementation start only after approval.

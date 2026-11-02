"""Server-side role and action permissions for the HR application."""

ROLE_LABELS = {
    "QuanTri": "Quản trị viên (tương thích cũ)",
    "QuanTriHeThong": "Quản trị hệ thống",
    "HR": "Nhân sự",
    "KeToan": "Kế toán",
    "QuanLy": "Quản lý",
    "NhanVien": "Nhân viên",
}

ROLE_PERMISSIONS = {
    # Existing administrator accounts retain their previous full access.
    "QuanTri": {"*"},
    "QuanTriHeThong": {"accounts.manage", "accounts.export", "roles.assign", "system.configure"},
    "HR": {
        "employees.view", "employees.create", "employees.edit", "employees.delete",
        "employees.export", "employees.view_cccd", "employees.view_salary",
        "organization.manage", "contracts.view", "contracts.create", "contracts.edit",
        "contracts.approve", "contracts.delete", "contracts.export",
        "recruitment.view", "recruitment.create", "recruitment.edit", "recruitment.approve",
        "recruitment.delete", "recruitment.export", "onboarding.manage", "assets.export",
        "leave.export_all", "records.view_all",
        "records.manage", "records.export", "profile_fields.manage", "training.manage",
        "benefits.manage", "headcount.manage", "leave.view_all", "leave.manage_policy",
        "leave.manage_quota", "leave.manage_schedule", "leave.approve_hr", "reports.hr",
        "audit.view", "kpi.manage", "kpi.view_all", "kpi.approve",
    },
    "KeToan": {
        "payroll.view", "payroll.calculate", "payroll.edit", "payroll.approve",
        "payroll.lock", "payroll.reopen", "payroll.delete", "payroll.export",
        "payroll.view_salary_field",
    },
    "QuanLy": {
        "employees.team_view", "leave.view_team", "leave.approve_manager", "leave.export_team",
        "kpi.view_team", "kpi.manager_review",
    },
    "NhanVien": {"self.attendance", "self.attendance_export", "self.leave", "self.payroll", "self.profile", "self.training", "self.benefits", "self.kpi"},
}

MODULE_PERMISSIONS = {
    "nhanvien": "employees",
    "phongban": "organization",
    "donvi": "organization",
    "vitri": "organization",
    "chucvu": "organization",
    "hopdong": "contracts",
}


def role_can(role, permission):
    """Return whether role grants one specific server-side capability."""
    grants = ROLE_PERMISSIONS.get(role, set())
    return "*" in grants or permission in grants


def module_permission(key, action="view"):
    """Map generic CRUD module actions to explicit permissions."""
    area = MODULE_PERMISSIONS.get(key)
    if not area:
        return None
    action_name = {"add": "create", "update": "edit", "delete": "delete"}.get(action, action)
    if area == "organization":
        return "organization.manage"
    return f"{area}.{action_name}"



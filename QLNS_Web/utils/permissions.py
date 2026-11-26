"""Server-side role and action permissions for the HR application."""

ROLE_LABELS = {
    "QuanTri": "Quản trị viên",
    "QuanTriHeThong": "Quản trị viên (tài khoản cũ)",
    "NhanSuKeToan": "Nhân sự/Kế toán",
    "ADMIN": "Quản trị viên",
    "HR_ACCOUNTANT": "Nhân sự/Kế toán",
    "EMPLOYEE": "Nhân viên",
    # Legacy roles stay recognized for existing database accounts.
    "HR": "Nhân sự/Kế toán (tài khoản cũ)",
    "KeToan": "Nhân sự/Kế toán (tài khoản cũ)",
    "QuanLy": "Nhân viên (tài khoản cũ)",
    "NhanVien": "Nhân viên",
}

ASSIGNABLE_ROLES = ("ADMIN", "HR_ACCOUNTANT", "EMPLOYEE")
ROLE_ID_BY_CODE = {"ADMIN": 1, "HR_ACCOUNTANT": 2, "EMPLOYEE": 3}
ROLE_SESSION_BY_CODE = {
    "ADMIN": "QuanTri",
    "HR_ACCOUNTANT": "NhanSuKeToan",
    "EMPLOYEE": "NhanVien",
}

ROLE_PERMISSIONS = {
    "QuanTri": {"*"},
    "QuanTriHeThong": {"accounts.manage", "accounts.export", "roles.assign", "system.configure"},
    "NhanSuKeToan": {
        "employees.view",
        "employees.create",
        "employees.edit",
        "employees.delete",
        "employees.export",
        "employees.view_cccd",
        "employees.view_salary",
        "organization.manage",
        "contracts.view",
        "contracts.create",
        "contracts.edit",
        "contracts.approve",
        "contracts.delete",
        "contracts.export",
        "leave.export_all",
        "records.view_all",
        "records.manage",
        "records.export",
        "leave.view_all",
        "leave.manage_policy",
        "leave.manage_quota",
        "leave.manage_schedule",
        "leave.approve_hr",
        "reports.hr",
        "attendance.manage",
        "payroll.view",
        "payroll.calculate",
        "payroll.edit",
        "payroll.approve",
        "payroll.lock",
        "payroll.reopen",
        "payroll.delete",
        "payroll.export",
        "payroll.view_salary_field",
        "kpi.manage",
        "kpi.view_all",
        "kpi.update_results",
        "kpi.score",
        "kpi.confirm",
        "kpi.bonus_policy",
        "kpi.view_bonus_all",
        "self.profile",
        "self.attendance",
        "self.attendance_export",
        "self.leave",
        "self.payroll",
    },
    "HR": set(),
    "KeToan": set(),
    "QuanLy": set(),
    "NhanVien": {
        "self.attendance",
        "self.attendance_export",
        "self.leave",
        "self.payroll",
        "self.profile",
        "kpi.view_own",
        "kpi.update_own",
    },
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
    role = {
        "ADMIN": "QuanTri",
        "HR_ACCOUNTANT": "NhanSuKeToan",
        "EMPLOYEE": "NhanVien",
        "HR": "NhanSuKeToan",
        "KeToan": "NhanSuKeToan",
        "QuanLy": "NhanVien",
    }.get(role, role)
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

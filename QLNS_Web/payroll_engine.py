"""Versioned, explicitly configured payroll calculations.

No Vietnamese tax or insurance rates are supplied by this module. The employer
must configure and approve an effective policy before statutory calculations
can be used.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time, timedelta


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


DEFAULT_OVERTIME_RATES = {
    "ordinary_day": Decimal("1.5"),
    "weekly_rest_day": Decimal("2"),
    "holiday": Decimal("3"),
    "night": Decimal("0.30"),
    "night_overtime_extra": Decimal("0.20"),
}


def _next_pay_boundary(moment):
    """Return the next midnight, 06:00, or 22:00 boundary."""
    boundaries = (
        datetime.combine(moment.date(), time(6)),
        datetime.combine(moment.date(), time(22)),
        datetime.combine(moment.date() + timedelta(days=1), time.min),
    )
    return min(boundary for boundary in boundaries if boundary > moment)


def _is_night(moment):
    return moment.time() >= time(22) or moment.time() < time(6)


def calculate_night_hours(intervals):
    """Count hours between 22:00 and 06:00 in attendance intervals."""
    night_seconds = Decimal("0")
    for start, end in intervals:
        cursor = start
        while cursor < end:
            boundary = min(end, _next_pay_boundary(cursor))
            if _is_night(cursor):
                night_seconds += Decimal(str((boundary - cursor).total_seconds()))
            cursor = boundary
    return (night_seconds / Decimal("3600")).quantize(Decimal("0.01"))


def merge_intervals(intervals):
    """Merge overlapping attendance intervals to avoid counting night hours twice."""
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def calculate_overtime_pay(
    base_salary,
    intervals,
    *,
    standard_workdays,
    hours_per_workday=8,
    work_weekdays=None,
    holidays=None,
    rates=None,
):
    """Calculate OT pay by calendar type; add the extra 20% for night OT.

    Night hours' 30% premium is returned separately by `calculate_night_hours`
    so regular and overtime night shifts both receive it exactly once.
    """
    if standard_workdays not in (22, 26):
        raise ValueError("Số ngày công chuẩn phải là 22 hoặc 26.")
    hourly_rate = Decimal(str(base_salary or 0)) / (
        Decimal(str(standard_workdays)) * Decimal(str(hours_per_workday))
    )
    applied_rates = dict(DEFAULT_OVERTIME_RATES)
    if rates:
        applied_rates.update({key: Decimal(str(value)) for key, value in rates.items()})
    work_weekdays = set(work_weekdays if work_weekdays is not None else range(6))
    holiday_dates = set(holidays or ())
    total = Decimal("0")

    for start, end in intervals:
        cursor = start
        while cursor < end:
            boundary = min(end, _next_pay_boundary(cursor))
            if cursor.date() in holiday_dates:
                multiplier = applied_rates["holiday"]
            elif cursor.weekday() not in work_weekdays:
                multiplier = applied_rates["weekly_rest_day"]
            else:
                multiplier = applied_rates["ordinary_day"]
            if _is_night(cursor):
                multiplier += applied_rates["night_overtime_extra"]
            duration_hours = Decimal(str((boundary - cursor).total_seconds())) / Decimal("3600")
            total += hourly_rate * duration_hours * multiplier
            cursor = boundary
    return _money(total)


def calculate_night_premium(base_salary, night_hours, standard_workdays, hours_per_workday=8, rate=None):
    """Return the 30% night premium on ordinary and overtime night hours."""
    premium_rate = DEFAULT_OVERTIME_RATES["night"] if rate is None else Decimal(str(rate))
    hourly_rate = Decimal(str(base_salary or 0)) / (
        Decimal(str(standard_workdays)) * Decimal(str(hours_per_workday))
    )
    return _money(hourly_rate * Decimal(str(night_hours or 0)) * premium_rate)


def resolve_overtime_intervals(requests, attendance_intervals):
    """Resolve confirmed OT requests to worked intervals, honoring actual hours.

    Exact clock intervals are used when their duration matches the HR-confirmed
    total. For a manually overridden total, the request start and confirmed
    duration are used because the override does not provide exact clock times.
    """
    resolved = []
    for start, end, actual_hours in requests:
        if actual_hours is None or actual_hours <= 0:
            continue
        clipped = [
            (max(start, work_start), min(end, work_end))
            for work_start, work_end in attendance_intervals
            if max(start, work_start) < min(end, work_end)
        ]
        observed_seconds = sum(
            (clip_end - clip_start).total_seconds() for clip_start, clip_end in clipped
        )
        actual_seconds = float(actual_hours) * 3600
        if clipped and abs(observed_seconds - actual_seconds) < 36:
            resolved.extend(clipped)
        else:
            actual_end = min(end, start + timedelta(seconds=actual_seconds))
            if actual_end > start:
                resolved.append((start, actual_end))
    return resolved


def validate_policy(policy):
    """Validate policy shape and prevent ambiguous/unbounded tax bands."""
    if not isinstance(policy, dict):
        raise ValueError("Chính sách lương phải là một đối tượng JSON.")
    tax = policy.get("tax")
    insurance = policy.get("insurance")
    if not isinstance(tax, dict) or not isinstance(insurance, dict):
        raise ValueError("Chính sách phải có hai mục tax và insurance.")
    for key in ("employee_contributions_reduce_taxable_base", "allow_other_tax_deductions"):
        if not isinstance(tax.get(key), bool):
            raise ValueError(f"Thiếu cờ cấu hình tax.{key}.")
    for key in ("personal_deduction", "dependent_deduction"):
        if key not in tax or Decimal(str(tax[key])) < 0:
            raise ValueError(f"Thiếu hoặc sai giá trị tax.{key}.")
    brackets = tax.get("brackets")
    if not isinstance(brackets, list) or not brackets:
        raise ValueError("Cần khai báo các bậc thuế trong tax.brackets.")
    previous = Decimal("0")
    for index, bracket in enumerate(brackets):
        if not isinstance(bracket, dict) or "rate" not in bracket or "up_to" not in bracket:
            raise ValueError("Mỗi bậc thuế cần có up_to và rate.")
        rate = Decimal(str(bracket["rate"]))
        if rate < 0 or rate > 1:
            raise ValueError("Thuế suất phải được nhập dạng tỷ lệ từ 0 đến 1.")
        ceiling = bracket["up_to"]
        if ceiling is None:
            if index != len(brackets) - 1:
                raise ValueError("Chỉ bậc thuế cuối cùng được có up_to=null.")
        else:
            ceiling = Decimal(str(ceiling))
            if ceiling <= previous:
                raise ValueError("Mốc up_to của các bậc thuế phải tăng dần.")
            previous = ceiling
    if brackets[-1].get("up_to") is not None:
        raise ValueError("Bậc thuế cuối cùng phải có up_to=null để bao phủ phần còn lại.")
    for party in ("employee_rates", "employer_rates"):
        rates = insurance.get(party)
        if not isinstance(rates, dict) or not rates:
            raise ValueError(f"Thiếu insurance.{party}.")
        for name, value in rates.items():
            rate = Decimal(str(value))
            if rate < 0 or rate > 1:
                raise ValueError(f"Tỷ lệ insurance.{party}.{name} phải từ 0 đến 1.")
    limits = insurance.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("Cần cấu hình insurance.limits riêng cho từng loại bảo hiểm.")
    for name in set(insurance["employee_rates"]) | set(insurance["employer_rates"]):
        limit = limits.get(name)
        if not isinstance(limit, dict) or not {"minimum_base", "maximum_base"}.issubset(limit):
            raise ValueError(f"Thiếu giới hạn căn cứ đóng cho bảo hiểm {name}.")
        minimum, maximum = limit["minimum_base"], limit["maximum_base"]
        for field, value in (("minimum_base", minimum), ("maximum_base", maximum)):
            if value is not None and Decimal(str(value)) < 0:
                raise ValueError(f"insurance.limits.{name}.{field} không được âm.")
        if (
            minimum is not None
            and maximum is not None
            and Decimal(str(minimum)) > Decimal(str(maximum))
        ):
            raise ValueError(f"Căn cứ tối thiểu của {name} không được lớn hơn tối đa.")
    for key in ("base_salary_taxable", "base_salary_insurable"):
        if key not in policy or not isinstance(policy[key], bool):
            raise ValueError(f"Thiếu cờ cấu hình {key}.")
    if policy.get("salary_proration_basis") != "calendar_days":
        raise ValueError("Chính sách cần khai báo salary_proration_basis='calendar_days'.")
    for key in ("standard_workdays_per_month", "hours_per_workday", "attendance_bonus_min_days"):
        if Decimal(str(policy.get(key, 0))) <= 0:
            raise ValueError(f"Thiếu hoặc sai cấu hình {key}.")
    if policy.get("standard_workdays_per_month") not in (22, 26):
        raise ValueError("Standard workdays per month must be 22 or 26.")
    for key in ("attendance_bonus_rate", "overtime_factor"):
        value = Decimal(str(policy.get(key, -1)))
        if value < 0 or value > 10 or (key == "attendance_bonus_rate" and value > 1):
            raise ValueError(f"Cấu hình {key} nằm ngoài giới hạn cho phép.")
    overtime_rates = policy.get("overtime_rates", {})
    if overtime_rates:
        if not isinstance(overtime_rates, dict):
            raise ValueError("overtime_rates must be a JSON object.")
        for key in DEFAULT_OVERTIME_RATES:
            rate = Decimal(str(overtime_rates.get(key, -1)))
            if rate < 0 or rate > 10:
                raise ValueError(f"Missing or invalid overtime_rates.{key}.")
    components = policy.get("components")
    required_components = ("attendance_bonus", "overtime", "extra_bonus", "payroll_deductions")
    if not isinstance(components, dict):
        raise ValueError("Thiếu mục components trong chính sách.")
    for name in required_components:
        flags = components.get(name)
        if not isinstance(flags, dict) or not all(
            isinstance(flags.get(key), bool) for key in ("taxable", "insurable")
        ):
            raise ValueError(f"Cần cấu hình cờ taxable/insurable cho components.{name}.")
    return policy


def effective_salary_for_period(current_salary, history, start, end):
    """Prorate monthly salary across effective-dated employment history rows."""
    if not history:
        return _money(Decimal(str(current_salary or 0)))
    rows = sorted(history, key=lambda row: row[0])
    total = Decimal("0")
    period_days = (end - start).days + 1
    day = start
    while day <= end:
        applicable = [row for row in rows if row[0] <= day and (row[1] is None or row[1] >= day)]
        if applicable:
            salary = Decimal(str(applicable[-1][2] or 0))
            total += salary / Decimal(period_days)
        day += timedelta(days=1)
    return _money(total)


def _progressive_tax(taxable_income, brackets):
    amount = max(Decimal("0"), Decimal(str(taxable_income)))
    tax = Decimal("0")
    lower = Decimal("0")
    for bracket in brackets:
        upper = bracket["up_to"]
        rate = Decimal(str(bracket["rate"]))
        band_amount = amount - lower if upper is None else min(amount, Decimal(str(upper))) - lower
        if band_amount > 0:
            tax += band_amount * rate
        if upper is None or amount <= Decimal(str(upper)):
            break
        lower = Decimal(str(upper))
    return _money(tax)


def _bounded_base(base, limits):
    """Giới hạn căn cứ đóng bảo hiểm trong khoảng tối thiểu/tối đa của từng loại."""
    if limits["minimum_base"] is not None:
        base = max(base, Decimal(str(limits["minimum_base"])))
    if limits["maximum_base"] is not None:
        base = min(base, Decimal(str(limits["maximum_base"])))
    return base


def calculate_statutory_payroll(
    *,
    base_salary,
    items,
    policy,
    tax_resident,
    dependents,
    insurance_subject,
    insurance_base=None,
):
    """Calculate transparent employee/employer contributions and resident PIT.

    `items` are employer-approved pay items with amount, taxable, insurable and
    deduction flags. Policy values use VND and decimal rates (e.g. 0.05).
    """
    validate_policy(policy)
    if not isinstance(tax_resident, bool) or not isinstance(insurance_subject, bool):
        raise ValueError("Hồ sơ thuế và bảo hiểm của nhân viên chưa được cấu hình.")
    if isinstance(dependents, bool) or int(dependents) < 0:
        raise ValueError("Số người phụ thuộc không hợp lệ.")
    salary = Decimal(str(base_salary or 0))
    gross_items = Decimal("0")
    taxable_items = Decimal("0")
    insurable_items = Decimal("0")
    other_tax_deductions = Decimal("0")
    other_payroll_deductions = Decimal("0")
    for item in items:
        amount = Decimal(str(item["amount"]))
        kind = item.get("kind", "earning")
        if kind == "deduction":
            other_payroll_deductions += abs(amount)
            if item.get("tax_deductible"):
                other_tax_deductions += abs(amount)
            continue
        if kind not in ("earning", "reduction"):
            raise ValueError("Loại khoản lương không hợp lệ.")
        signed = -abs(amount) if kind == "reduction" else amount
        gross_items += signed
        if item.get("taxable"):
            taxable_items += signed
        if item.get("insurable"):
            insurable_items += signed

    base_salary_taxable = salary if policy["base_salary_taxable"] else Decimal("0")
    base_salary_insurable = salary if policy["base_salary_insurable"] else Decimal("0")
    gross = salary + gross_items
    insurance = policy["insurance"]
    contribution_base = Decimal("0")
    employee_contributions = {}
    employer_contributions = {}
    insurance_bases = {}
    if insurance_subject:
        contribution_base = (
            Decimal(str(insurance_base))
            if insurance_base is not None
            else base_salary_insurable + insurable_items
        )
        for party, contributions in (
            ("employee_rates", employee_contributions),
            ("employer_rates", employer_contributions),
        ):
            for name, rate in insurance[party].items():
                category_base = _bounded_base(contribution_base, insurance["limits"][name])
                insurance_bases[name] = _money(category_base)
                contributions[name] = _money(category_base * Decimal(str(rate)))

    tax_base = base_salary_taxable + taxable_items
    if policy["tax"]["employee_contributions_reduce_taxable_base"]:
        tax_base -= sum(employee_contributions.values(), Decimal("0"))
    if tax_resident:
        tax = policy["tax"]
        tax_base -= Decimal(str(tax["personal_deduction"]))
        tax_base -= Decimal(str(tax["dependent_deduction"])) * int(dependents)
        if tax["allow_other_tax_deductions"]:
            tax_base -= other_tax_deductions
        personal_income_tax = _progressive_tax(max(Decimal("0"), tax_base), tax["brackets"])
    else:
        nonresident = policy["tax"].get("nonresident_flat_rate")
        if nonresident is None:
            raise ValueError("Chính sách chưa cấu hình thuế suất người không cư trú.")
        personal_income_tax = _money(max(Decimal("0"), tax_base) * Decimal(str(nonresident)))

    employee_insurance_total = sum(employee_contributions.values(), Decimal("0"))
    employer_insurance_total = sum(employer_contributions.values(), Decimal("0"))
    net = _money(gross - employee_insurance_total - personal_income_tax - other_payroll_deductions)
    return {
        "gross": _money(gross),
        "taxable_income": _money(max(Decimal("0"), tax_base)),
        "personal_income_tax": personal_income_tax,
        "employee_contributions": {
            key: _money(value) for key, value in employee_contributions.items()
        },
        "employer_contributions": {
            key: _money(value) for key, value in employer_contributions.items()
        },
        "employee_contributions_total": _money(employee_insurance_total),
        "employer_contributions_total": _money(employer_insurance_total),
        "other_deductions": _money(other_payroll_deductions),
        "insurance_base": _money(contribution_base),
        "insurance_bases": insurance_bases,
        "net": net,
    }

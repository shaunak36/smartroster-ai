from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Brand,
    BrandProcessOperatingRule,
    BrandProcessWorkloadRule,
    Employee,
    EmployeeAssignment,
    EmployeeStatus,
    EmployeeWeeklyOffPattern,
    Pod,
    Process,
    PublicHoliday,
    Organization,
)


DEMO_START = date(2026, 1, 1)


@dataclass(frozen=True)
class DemoSeedSummary:
    employees: int
    pods: int
    brands: int
    processes: int
    assignments: int
    operating_rules: int
    workload_rules: int
    public_holidays: int
    weekly_off_patterns: int


def _one(session: Session, model, **filters):
    return session.scalar(select(model).filter_by(**filters))


def _get_or_create(session: Session, model, filters: dict, values: dict):
    item = _one(session, model, **filters)
    if item is None:
        item = model(**filters, **values)
        session.add(item)
        session.flush()
        return item, True
    return item, False


def seed_demo_data(session: Session) -> DemoSeedSummary:
    """Create the deterministic assessment dataset without deleting existing rows."""
    organizations = session.scalars(select(Organization).order_by(Organization.id)).all()
    demo_organizations = [org for org in organizations if org.name == "Demo Operations"]
    if len(demo_organizations) > 1:
        raise ValueError("Multiple Demo Operations organizations exist")
    if demo_organizations:
        organization = demo_organizations[0]
    elif len(organizations) == 1:
        organization = organizations[0]
    elif not organizations:
        organization = Organization(name="Demo Operations", is_active=True)
        session.add(organization)
        session.flush()
    else:
        raise ValueError("Cannot seed demo data when multiple organizations exist")
    org_id = organization.id
    process_specs = (
        ("CS", "Customer Support"),
        ("ACC", "Abandoned Cart Conversions"),
        ("RET", "Retention"),
        ("NDR", "Non-Delivery Report Management"),
    )
    processes: dict[str, Process] = {}
    created_processes = 0
    for code, name in process_specs:
        process, created = _get_or_create(
            session,
            Process,
            {"organization_id": org_id, "code": f"DEMO-{code}"},
            {"name": name, "is_active": True},
        )
        processes[code] = process
        created_processes += int(created)

    pod_specs = (
        ("NORTH", "North Operations"),
        ("SOUTH", "South Operations"),
        ("CENTRAL", "Central Operations"),
        ("SPECIAL", "Special Projects"),
    )
    pods: dict[str, Pod] = {}
    created_pods = 0
    for code, name in pod_specs:
        pod, created = _get_or_create(
            session,
            Pod,
            {"organization_id": org_id, "code": f"DEMO-{code}"},
            {"name": name, "is_active": True},
        )
        pods[code] = pod
        created_pods += int(created)

    employees: list[Employee] = []
    created_employees = 0
    for index in range(1, 31):
        pod = tuple(pods.values())[(index - 1) % len(pods)]
        employee, created = _get_or_create(
            session,
            Employee,
            {"organization_id": org_id, "employee_code": f"DEMO-E{index:02d}"},
            {
                "name": f"Demo Operator {index:02d}",
                "email": f"demo.operator{index:02d}@example.invalid",
                "pod_id": pod.id,
                "status": EmployeeStatus.ACTIVE,
                "daily_capacity_units": 4,
                "weekly_capacity_units": 28,
                "monthly_capacity_units": 140,
                "max_assignments_per_day": 4,
            },
        )
        employees.append(employee)
        created_employees += int(created)

    lead_indexes = {"NORTH": 0, "SOUTH": 1, "CENTRAL": 2, "SPECIAL": 3}
    for code, index in lead_indexes.items():
        if pods[code].lead_employee_id is None:
            pods[code].lead_employee_id = employees[index].id
    session.flush()

    brand_specs = (
        ("A", "Brand A - Dedicated 365", "NORTH", "all"),
        ("B", "Brand B - Daily Except Holidays", "SOUTH", "daily"),
        ("C", "Brand C - Shared Support", "CENTRAL", "weekday"),
        ("D", "Brand D - Sunday and Holiday Off", "SPECIAL", "weekday"),
        ("E", "Brand E - Holiday Aware", "NORTH", "daily"),
        ("F", "Brand F - Dedicated", "SOUTH", "weekday"),
        ("G", "Brand G - Dedicated", "CENTRAL", "weekday"),
        ("H", "Brand H - Dedicated", "SPECIAL", "weekday"),
    )
    brands: dict[str, Brand] = {}
    created_brands = 0
    calendars: dict[str, str] = {}
    for code, name, pod_code, calendar_code in brand_specs:
        brand, created = _get_or_create(
            session,
            Brand,
            {"organization_id": org_id, "code": f"DEMO-{code}"},
            {"name": name, "pod_id": pods[pod_code].id, "is_active": True},
        )
        brands[code] = brand
        calendars[code] = calendar_code
        created_brands += int(created)

    # Six brands have one dedicated employee. C and D share the same three people.
    employee_groups = {
        "A": (employees[0],),
        "B": (employees[1],),
        "C": (employees[6], employees[7], employees[8]),
        "D": (employees[6], employees[7], employees[8]),
        "E": (employees[2],),
        "F": (employees[3],),
        "G": (employees[4],),
        "H": (employees[5],),
    }
    created_assignments = 0
    created_workload_rules = 0
    created_operating_rules = 0
    for brand_code, group in employee_groups.items():
        brand = brands[brand_code]
        for employee in group:
            for process in processes.values():
                assignment, created = _get_or_create(
                    session,
                    EmployeeAssignment,
                    {
                        "employee_id": employee.id,
                        "brand_id": brand.id,
                        "process_id": process.id,
                        "effective_start_date": DEMO_START,
                    },
                    {"effective_end_date": None, "skill_level": 2, "is_primary": True, "is_active": True},
                )
                created_assignments += int(created)
        for process_code, process in processes.items():
            if brand_code == "C" and process_code == "CS":
                minimum_staffing = 2
            else:
                minimum_staffing = 1
            weekdays = "1234567"
            sunday_working = calendars[brand_code] in ("all", "daily")
            holiday_working = calendars[brand_code] == "all"
            if calendars[brand_code] == "weekday":
                weekdays = "12345"
                sunday_working = False
                holiday_working = False
            operating, created = _get_or_create(
                session,
                BrandProcessOperatingRule,
                {
                    "brand_id": brand.id,
                    "process_id": process.id,
                    "effective_start_date": DEMO_START,
                },
                {
                    "effective_end_date": None,
                    "operating_weekdays": weekdays,
                    "sunday_working": sunday_working,
                    "public_holiday_working": holiday_working,
                    "required_coverage": True,
                    "minimum_daily_staffing": minimum_staffing,
                    "is_active": True,
                },
            )
            created_operating_rules += int(created)
            workload, created = _get_or_create(
                session,
                BrandProcessWorkloadRule,
                {
                    "brand_id": brand.id,
                    "process_id": process.id,
                    "effective_start_date": DEMO_START,
                },
                {"effective_end_date": None, "workload_units": 1, "is_active": True},
            )
            created_workload_rules += int(created)

    created_weekly_offs = 0
    for employee in employees[9:]:
        _, created = _get_or_create(
            session,
            EmployeeWeeklyOffPattern,
            {"employee_id": employee.id, "effective_start_date": DEMO_START},
            {
                "effective_end_date": None,
                "recurrence_rule": "FREQ=WEEKLY;BYDAY=SA,SU",
                "is_active": True,
            },
        )
        created_weekly_offs += int(created)

    created_holidays = 0
    for holiday_date, name in (
        (date(2026, 1, 26), "Demo Republic Day"),
        (date(2026, 8, 15), "Demo Independence Day"),
        (date(2026, 12, 25), "Demo Winter Holiday"),
    ):
        _, created = _get_or_create(
            session,
            PublicHoliday,
            {"organization_id": org_id, "date": holiday_date},
            {"name": name, "scope": "company", "is_active": True},
        )
        created_holidays += int(created)

    session.commit()
    return DemoSeedSummary(
        employees=created_employees,
        pods=created_pods,
        brands=created_brands,
        processes=created_processes,
        assignments=created_assignments,
        operating_rules=created_operating_rules,
        workload_rules=created_workload_rules,
        public_holidays=created_holidays,
        weekly_off_patterns=created_weekly_offs,
    )

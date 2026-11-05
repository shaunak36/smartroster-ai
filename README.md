# SmartRoster AI

SmartRoster AI is a workforce roster management system for multi-brand D2C
operations. The application uses a React/TypeScript frontend, a FastAPI
backend, SQLAlchemy persistence, SQLite for the initial deployment, and
Google OR-Tools CP-SAT for constraint-based scheduling.

## Stage 1 status

Stage 1 establishes the project foundation and documents the domain. It does
not implement scheduling, CRUD APIs, database models, or seed data yet.

## Architecture

```text
frontend/  React + TypeScript + Vite + Tailwind CSS
    |
    | REST/JSON
    v
backend/app/
    api/       FastAPI route modules (introduced in later stages)
    core/      Settings and application configuration
    db/        SQLAlchemy engine/session and Alembic integration
    models/    Normalized persistence models (introduced in Stage 2)
    schemas/   Pydantic API contracts (introduced in later stages)
    services/  Scheduling, validation, reporting, and export services
```

SQLite is the initial database. Database access is isolated behind SQLAlchemy
so a production deployment can move to PostgreSQL without changing domain
services.

## Prerequisites

- Python 3.10 or newer
- Node.js 20 or newer
- npm 10 or newer

## Backend setup (Windows PowerShell)

```powershell
cd "C:\Users\Shaunak paul\smartroster-ai\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

The backend health endpoint is available at
`http://127.0.0.1:8000/health`. OpenAPI documentation will be available at
`http://127.0.0.1:8000/docs` as routes are added.

## Frontend setup (Windows PowerShell)

```powershell
cd "C:\Users\Shaunak paul\smartroster-ai\frontend"
npm install
Copy-Item .env.example .env
npm run dev
```

The Vite development server normally runs at `http://localhost:5173`.

## Business assumptions

1. Employees can work across multiple brands and processes on the same date.
2. The initial system has no time slots. It enforces
   `max_assignments_per_day` and daily, weekly, and monthly workload capacity.
   `max_concurrent_assignments` is reserved for a future shift feature.
3. An assignment has configurable workload units based on its effective
   brand/process workload rule.
4. Employee eligibility, compatibility, capacity, and workload rules are
   effective-dated.
5. Brand/process operating calendars are independent from employee
   availability. An operating calendar can require coverage on a Sunday or
   public holiday even when a particular employee cannot work.
6. Required coverage answers whether a brand/process must be staffed on a
   date. Minimum staffing answers how many qualified employees are required
   when coverage is required. Both are enforced independently.
7. Approved leave always blocks assignments.
8. Date-specific availability overrides apply only when approved leave does not
   block the date.
9. An approved weekly-off exception may override a recurring weekly-off
   pattern. Exceptions require a reason and the required approval status.
10. Pending or rejected exceptions do not affect scheduling.
11. The availability resolution order is: approved leave, date-specific
    availability override, approved weekly-off exception, recurring weekly-off
    pattern, then normal availability.
12. Effective-dated rules for the same context may not overlap. Adjacent
    periods are allowed; open-ended rules overlap with no later active rule.
13. A roster version is immutable for audit purposes. Changes create a new
    version and preserve the previous version.
14. Changes to availability, leave, eligibility, capacity, holidays, or
    operating/staffing rules mark affected roster dates for revalidation.
15. Manual changes are previewed and validated against employee capacity,
    eligibility, availability, and impacted coverage before acceptance.
16. A roster is valid only when its solver status is OPTIMAL or FEASIBLE and
    all hard constraints have zero violations.
17. INFEASIBLE and UNKNOWN results are never presented as valid rosters.
18. Weekly limits are evaluated over ISO weeks, including dates outside the
    selected month. A monthly roster generation request therefore loads the
    adjacent-month dates needed to calculate complete cross-boundary weeks,
    while only persisting assignments for the requested roster period.

## Data model

The normalized model will include:

- `employees`, `pods`, `brands`, and `processes`
- effective-dated `employee_assignments`,
  `assignment_compatibility_rules`, and `employee_workload_rules`
- `brand_process_operating_rules`,
  `brand_process_date_overrides`, and `brand_process_workload_rules`
- `employee_weekly_off_patterns`, `employee_weekly_off_exceptions`,
  `employee_availability_overrides`, `leave_requests`, and
  `public_holidays`
- `rosters`, immutable `roster_versions`, and `roster_assignments`
- `validation_runs`, `scheduling_conflicts`, and `roster_change_history`

Foreign keys, indexes, unique constraints, and transactional service checks
will prevent duplicate assignments and ambiguous active rule periods.

## Scheduling and validation

CP-SAT assignment variables will represent an employee, date, brand, and
process. Hard constraints will enforce effective eligibility, availability,
approved leave, weekly-off resolution, assignment-count capacity, workload
capacity, operating calendars, required coverage, and minimum staffing.

Soft objectives will balance workload, distribute weekly offs, prefer primary
assignments, preserve existing assignments, and avoid unnecessary use of
scarce backup employees.

Solver statuses:

- `OPTIMAL`: a valid solution was found and optimality was proven.
- `FEASIBLE`: a valid solution was found but optimality was not proven.
- `INFEASIBLE`: no solution satisfies all hard constraints.
- `UNKNOWN`: the solver did not determine a result within its limits.

Infeasibility diagnostics will identify each affected date, brand, process,
required coverage, minimum staffing, available qualified capacity, eligible
employees, backup employees, and the blocking reasons.

## Sample-data plan

The seed dataset will contain at least 30 employees, 10 fictional brands,
four processes, and three pods with pod leads. Approximately 80% of brands
will have one dedicated employee, with the remaining brands having two or
three employees. The data will also include employees spanning multiple
brands/processes, shared process coverage, varied calendars, leaves, weekly
offs, holidays, capacity limits, and effective-dated changes. Brand A through
E scenarios will be configuration data, not scheduling-engine constants.

## Development stages

1. Project foundation and domain documentation (current stage).
2. SQLAlchemy models, migrations, and persistence tests.
3. Configuration and availability/calendar APIs.
4. CP-SAT scheduling engine and diagnostics.
5. Roster versioning, revalidation, and manual-change APIs.
6. Reports, exports, and seed data.
7. Frontend modules and API integration.
8. End-to-end testing and deployment documentation.

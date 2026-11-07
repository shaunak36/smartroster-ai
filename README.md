# SmartRoster AI

SmartRoster AI is a workforce scheduling app for teams that support several
brands. I built it to help organize employees, track when they are available,
and plan who can cover different kinds of work. It has a React frontend and a
FastAPI backend. It uses SQLite on my computer, PostgreSQL for the hosted
database, and Google OR-Tools to help create schedules.

## Status

The app is live, and I can use it to manage employees, brands, processes, pods,
work assignments, and availability. It can generate and check monthly rosters,
and I can preview manual changes before accepting them. The backend runs on
Render and uses a PostgreSQL database set up through Supabase. The website
frontend is deployed separately from the backend.

## Live demo

- Website: [smartroster-ai.onrender.com](https://smartroster-ai.onrender.com)
- API health: [smartroster-api.onrender.com/health](https://smartroster-api.onrender.com/health)
- API documentation: [smartroster-api.onrender.com/docs](https://smartroster-api.onrender.com/docs)

The API docs are for development and inspection. Do not use them to share
account credentials or change live data during a demo.

## Quick start

1. Backend: follow "Backend setup" below. In `backend/.env`, set
   `BACKEND_AUTH_SECRET` (32+ characters) and `BACKEND_BOOTSTRAP_ADMIN_TOKEN`
   (any value).
2. Seed the demo data: `python -m scripts.seed_demo` (from `backend/`).
3. Create the admin (the seed does not create users). Open
   http://localhost:8000/docs and run `POST /api/auth/bootstrap-admin` with:
   ```json
   {
     "email": "admin@demo.local",
     "password": "<choose a local password of at least 12 characters>",
     "full_name": "Admin",
     "organization_name": "SmartRoster Demo",
     "bootstrap_token": "<the token you set in .env>"
   }
   ```
   The password must be at least 12 characters.
4. Frontend: follow "Frontend setup" below, open http://localhost:5173 and log
   in with `admin@demo.local` and the password you created above.

## Architecture

```text
frontend/  React + TypeScript + Vite + Tailwind CSS
    |
    | REST/JSON
    v
backend/app/
    api/       FastAPI route modules
    core/      Settings and application configuration
    db/        SQLAlchemy engine/session and Alembic integration
    models/    Normalized persistence models
    schemas/   Pydantic API contracts
    services/  Scheduling, validation, reporting, and export services
```

SQLite is the initial database. Database access is isolated behind SQLAlchemy
so a production deployment can move to PostgreSQL without changing domain
services.

The backend resolves its `.env` file and relative SQLite database paths from
the `backend/` directory, not from the current working directory. Therefore
the default `BACKEND_DATABASE_URL=sqlite:///./smartroster.db` always refers to
`backend/smartroster.db` when the application or Alembic is launched from
either the repository root or `backend/`. Non-SQLite URLs remain unchanged.

All backend environment variables use the `BACKEND_` prefix
(for example `BACKEND_AUTH_SECRET`). PostgreSQL URLs from hosted providers can
be supplied as `postgresql://...`; the backend selects its installed Psycopg 3
driver automatically. SQLite remains the default for local development.

## Persistent Render database (Supabase PostgreSQL)

Render's local SQLite file is not durable across service restarts and deploys.
For a persistent hosted database, create a PostgreSQL project in Supabase and
copy its **Session pooler** URI from **Connect**. In the Render backend
service's environment, set `BACKEND_DATABASE_URL` to that URI. Keep the URI
private; do not commit it or paste it into chat. The app normalizes the URI to
the Psycopg 3 driver already listed in `backend/requirements.txt`.

From the `backend/` directory, use this build command:

```bash
pip install -r requirements.txt && alembic upgrade head && python -m scripts.seed_demo
```

Use this start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

On a brand-new hosted database, migrations create the schema and demo seeding
creates the sample workforce. The seed does not create a login. After the
first successful deploy, provision the admin once through the bootstrap
endpoint using the backend's `BACKEND_BOOTSTRAP_ADMIN_TOKEN`. Moving to a new
database does not copy existing SQLite users or custom records; export and
import any data you need before switching the service URL. Do not point local
development at the hosted database unless you intend to change that shared
database.

Supabase's Free plan can pause projects after a week of low activity and does
not include automatic backups. A paused project can be resumed, but use a paid
plan if you need continuous availability and managed backups. See Supabase's
[project pausing policy](https://supabase.com/docs/guides/platform/free-project-pausing)
and [connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Prerequisites

- Python 3.10 (3.10 to 3.12 recommended; the pinned `ortools` version has no
  build for Python 3.14)
- Node.js 20 or newer
- npm 10 or newer

## Backend setup (Windows PowerShell)

```powershell
cd backend
python -m venv .venv310
.\.venv310\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env: set BACKEND_AUTH_SECRET and BACKEND_BOOTSTRAP_ADMIN_TOKEN
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Run `uvicorn` from the `backend/` folder. The health endpoint is
`http://127.0.0.1:8000/health` and the API docs are at
`http://127.0.0.1:8000/docs`.

To launch from the repository root instead:

```powershell
$env:PYTHONPATH = ".\backend"
.\.venv310\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Frontend setup (Windows PowerShell)

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The Vite development server normally runs at `http://localhost:5173`.

## Assessment demo data

After applying the migrations and configuring the backend environment, create
the reproducible fictional assessment dataset from `backend/`:

```powershell
python -m scripts.seed_demo
```

The seed creates 30 fictional employees, four processes, four pods with leads,
eight brands, effective employee assignments, operating and workload rules,
weekly-off patterns, and public holidays. It uses `DEMO-` codes and
get-or-create behavior, so rerunning it does not delete or overwrite unrelated
rows. It does not create users or print credentials; create the administrator
through the bootstrap endpoint as described in "Quick start".

The dataset includes single-employee brands (the majority), brands with two or
three employees, employees spanning multiple brands and processes, and shared
process coverage. Brand scenarios are configuration data, not scheduling-engine
constants.

## Using the roster planner

When I first use the planner, I choose a year and month on the **Roster** page
and click **Generate**. It can take a little while, so I leave the page open
while it works. The button and message let me know it is still generating.

When the preview appears, I look at the assignment count and the validation
results. Errors need to be fixed before I can save the roster. Warnings are
usually notes and do not stop me from saving. For example, a supporting-date
warning means the planner checked a nearby date outside the month so it could
work out weekly workload correctly.

If there are no errors, I click **Save roster**. This step matters because
**Generate** only creates a preview; it does not save the roster yet.

After saving, I can go to **Manual roster change**, choose an assignment, and
pick a replacement employee. I click **Preview change** to see whether it
follows the roster rules. If it does not, the page tells me why, so I can try
someone who is available, trained for that work, and has enough capacity. If
the change looks right, I click **Accept change**. That saves a new version
while keeping the earlier one in the roster history.

The coverage list has its own scroll area, so I can look through the schedule
without scrolling past every assignment to reach the other controls. I can
open the validation details whenever I want to read the individual warnings or
errors.

## Troubleshooting

- **"Failed to fetch" on login:** the backend is not running, or the frontend
  API URL / CORS origin does not match. Start the backend and check
  `BACKEND_CORS_ORIGINS` in `backend/.env`.
- **`No module named 'app'`:** run `uvicorn` from the `backend/` folder.
- **`Administrator provisioning is not configured` (503):** set
  `BACKEND_BOOTSTRAP_ADMIN_TOKEN` in `backend/.env` and restart the backend.
- **`Administrator provisioning is already complete` (409):** a user already
  exists; log in with that user's credentials.
- **`pip` fails on `ortools`:** use Python 3.10 to 3.12, not 3.14.

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

The normalized model includes:

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
prevent duplicate assignments and ambiguous active rule periods.

## Scheduling and validation

CP-SAT assignment variables represent an employee, date, brand, and process.
Hard constraints enforce effective eligibility, availability, approved leave,
weekly-off resolution, assignment-count capacity, workload capacity, operating
calendars, required coverage, and minimum staffing.

Soft objectives balance workload, distribute weekly offs, prefer primary
assignments, preserve existing assignments, and avoid unnecessary use of
scarce backup employees.

Solver statuses:

- `OPTIMAL`: a valid solution was found and optimality was proven.
- `FEASIBLE`: a valid solution was found but optimality was not proven.
- `INFEASIBLE`: no solution satisfies all hard constraints.
- `UNKNOWN`: the solver did not determine a result within its limits.

Infeasibility diagnostics identify each affected date, brand, process,
required coverage, minimum staffing, available qualified capacity, eligible
employees, backup employees, and the blocking reasons.

## Tell Us How You Think

1. **Data model.** Employees, brands, processes and pods are normalized
   tables. Effective-dated assignments link an employee to a brand and a
   process, so one person can cover several. Operating calendars belong to the
   brand/process and are kept separate from employee availability, so a brand
   can require coverage on a day a given employee is off.

2. **Roster generation and validation.** A CP-SAT model has one variable per
   employee, date, brand and process. Hard constraints cover eligibility,
   leave, weekly offs, operating calendars, required coverage, minimum
   staffing and capacity. A roster is valid only when the solver returns
   OPTIMAL or FEASIBLE with zero hard-constraint violations.

3. **Single-resource vs multi-employee brands.** Both use the same coverage
   rules. With one employee, any absence on a required day leaves nobody to
   cover it, so it is flagged. With several employees, the solver checks
   whether the others can absorb the work within their capacity and
   eligibility.

4. **Sole employee unavailable.** The date is reported as a conflict showing
   the brand, process, required coverage, eligible employees and blocking
   reasons, so the operations manager can decide on a resolution such as a
   backup resource or a leave change.

5. **Conflicting requirements or insufficient staffing.** Mandatory
   constraints outrank preferences. INFEASIBLE or UNKNOWN results are never
   presented as valid rosters, and diagnostics explain what blocked them.

6. **Automation vs human control.** Generation, validation and revalidation
   are automated. Approval, manual overrides and resolution of conflicts that
   cannot be solved automatically stay with the operations manager, because
   those involve judgement about people and client commitments.

7. **If the company doubled its team and brands.** Move from SQLite to
   PostgreSQL, run solves as background jobs, split solves per pod or brand
   group to keep the models small, and add pagination and caching to the views.

8. **With another week.** Record the demo walkthrough, add backup-resource
   recommendations, and automate roster regeneration after approved leave or
   availability changes.

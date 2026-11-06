import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Database,
  LogOut,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";

import "./index.css";

const API_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

type Entity = {
  id: number;
  code?: string;
  name: string;
  email?: string;
  pod_id?: number | null;
  status?: string;
  is_active?: boolean;
  employee_code?: string;
};
type Assignment = {
  id: number;
  employee_id: number;
  brand_id: number;
  process_id: number;
  effective_start_date: string;
  effective_end_date?: string | null;
  is_active: boolean;
};
type RosterAssignment = {
  employee_id: number;
  date: string;
  brand_id: number;
  process_id: number;
  workload_units?: number | null;
};
type Diagnostic = {
  code: string;
  severity: string;
  message: string;
  target_date?: string | null;
  employee_id?: number | null;
};
type RosterPreview = {
  year: number;
  month: number;
  solver_status: string;
  assignments: RosterAssignment[];
  validation: {
    is_valid: boolean;
    error_count: number;
    warning_count: number;
    diagnostics: Diagnostic[];
    affected_employee_ids: number[];
    affected_dates: string[];
  };
};
type Roster = { id: number; year: number; month: number; current_version_id?: number | null; status: string };
type RosterValidation = RosterPreview["validation"];
type AvailabilityOverride = {
  id: number;
  employee_id: number;
  date: string;
  status: string;
  approval_status: string;
  reason: string;
  created_at: string;
};

class APIError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const retryable = (init.method ?? "GET").toUpperCase() === "GET" || path === "/api/rosters/generate";
  const maxAttempts = retryable ? 3 : 1;
  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(`${API_URL}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(init.headers ?? {}),
        },
      });
    } catch (reason) {
      if (attempt + 1 >= maxAttempts) throw reason;
      await new Promise((resolve) => window.setTimeout(resolve, 1200 * (attempt + 1)));
      continue;
    }
    if (retryable && attempt + 1 < maxAttempts && [502, 503, 504].includes(response.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, 1200 * (attempt + 1)));
      continue;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = typeof body.detail === "string" ? body.detail : body.detail?.message ?? body.detail?.code;
      throw new APIError(detail || `Request failed (${response.status})`, response.status);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
}

function Login({ onLogin, sessionExpired }: { onLogin: (token: string, email: string) => void; sessionExpired: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await request<{ access_token: string }>("/api/auth/login", "", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        headers: { Authorization: "" },
      });
      onLogin(result.access_token, email);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="brand-mark"><Network size={24} /></div>
        <p className="eyebrow">SmartRoster AI</p>
        <h1>Welcome back</h1>
        <p className="muted">Sign in to manage workforce coverage and monthly rosters.</p>
        <form onSubmit={submit} className="stack">
          {sessionExpired && <div className="error-banner"><AlertTriangle size={16} />Your session expired. Sign in again to continue.</div>}
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required placeholder="admin@example.com" /></label>
          <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required /></label>
          {error && <div className="error-banner"><AlertTriangle size={16} />{error}</div>}
          <button className="primary-button" disabled={busy}>{busy ? "Signing in..." : "Sign in"} <ChevronRight size={17} /></button>
        </form>
        <p className="login-hint">Administrator provisioning is performed once through the secure backend bootstrap endpoint.</p>
      </section>
    </main>
  );
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem("smartroster_token") ?? "");
  const [email, setEmail] = useState(() => sessionStorage.getItem("smartroster_email") ?? "");
  const [sessionExpired, setSessionExpired] = useState(false);
  const clearSession = (expired = false) => { sessionStorage.clear(); setToken(""); setEmail(""); setSessionExpired(expired); };
  if (!token) return <Login sessionExpired={sessionExpired} onLogin={(next, nextEmail) => { sessionStorage.setItem("smartroster_token", next); sessionStorage.setItem("smartroster_email", nextEmail); setSessionExpired(false); setToken(next); setEmail(nextEmail); }} />;
  return <Console token={token} email={email} onLogout={() => clearSession()} onAuthExpired={() => clearSession(true)} />;
}

function Console({ token, email, onLogout, onAuthExpired }: { token: string; email: string; onLogout: () => void; onAuthExpired: () => void }) {
  const [section, setSection] = useState("Overview");
  const [employees, setEmployees] = useState<Entity[]>([]);
  const [brands, setBrands] = useState<Entity[]>([]);
  const [processes, setProcesses] = useState<Entity[]>([]);
  const [pods, setPods] = useState<Entity[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [roster, setRoster] = useState<Roster | null>(null);
  const [rosterRows, setRosterRows] = useState<RosterAssignment[]>([]);
  const [preview, setPreview] = useState<RosterPreview | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);

  const showRequestError = (reason: unknown, fallback: string) => {
    if (reason instanceof APIError && reason.status === 401) {
      onAuthExpired();
      return;
    }
    setError(reason instanceof Error ? reason.message : fallback);
  };

  const load = async () => {
    setLoading(true); setError("");
    try {
      const [employeePage, brandPage, processPage, podPage, assignmentPage] = await Promise.all([
        request<{ items: Entity[] }>("/api/employees?limit=200", token),
        request<{ items: Entity[] }>("/api/brands?limit=200", token),
        request<{ items: Entity[] }>("/api/processes?limit=200", token),
        request<{ items: Entity[] }>("/api/pods?limit=200", token),
        request<{ items: Assignment[] }>("/api/assignments?limit=200", token),
      ]);
      setEmployees(employeePage.items); setBrands(brandPage.items); setProcesses(processPage.items); setPods(podPage.items); setAssignments(assignmentPage.items);
      const savedRosterId = Number(localStorage.getItem("smartroster_last_roster_id"));
      if (Number.isInteger(savedRosterId) && savedRosterId > 0) await loadRoster(savedRosterId);
    } catch (reason) {
      showRequestError(reason, "Unable to load application data");
    } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [token]);

  const name = (items: Entity[], id: number) => items.find((item) => item.id === id)?.name ?? `#${id}`;
  const stats = [
    { label: "Employees", value: employees.length, icon: Users, tone: "violet" },
    { label: "Brands", value: brands.length, icon: Network, tone: "blue" },
    { label: "Processes", value: processes.length, icon: ClipboardList, tone: "amber" },
    { label: "Operational pods", value: pods.length, icon: Database, tone: "green" },
  ];

  async function generateRoster(year: number, month: number) {
    if (generating) return;
    setGenerating(true);
    setError(""); setNotice(""); setPreview(null);
    try {
      const result = await request<RosterPreview>("/api/rosters/generate", token, { method: "POST", body: JSON.stringify({ year, month }) });
      setPreview(result);
      setNotice(result.validation.is_valid ? `Roster generated: ${result.solver_status}` : "Roster generated with validation issues; it cannot be saved.");
    } catch (reason) { showRequestError(reason, "Roster generation failed"); }
    finally { setGenerating(false); }
  }
  async function saveRoster() {
    if (saving || !preview || !preview.validation.is_valid) return;
    setSaving(true);
    try {
      const saved = await request<Roster>("/api/rosters/save", token, { method: "POST", body: JSON.stringify({ year: preview.year, month: preview.month, solver_status: preview.solver_status, assignments: preview.assignments }) });
      localStorage.setItem("smartroster_last_roster_id", String(saved.id));
      setRoster(saved); setRosterRows(preview.assignments); setNotice(`Roster ${saved.id} saved successfully.`); setSection("Roster");
    } catch (reason) { showRequestError(reason, "Roster save failed"); }
    finally { setSaving(false); }
  }
  async function loadRoster(id: number) {
    try { setRoster(await request<Roster>(`/api/rosters/${id}`, token)); setRosterRows(await request<RosterAssignment[]>(`/api/rosters/${id}/assignments`, token)); }
    catch (reason) { showRequestError(reason, "Unable to retrieve roster"); }
  }

  const content = section === "Overview"
    ? <Dashboard stats={stats} employees={employees} brands={brands} assignments={assignments} roster={roster} onGenerate={() => setSection("Roster")} />
    : section === "People"
      ? <People employees={employees} pods={pods} token={token} onRefresh={load} name={name} />
      : section === "Availability"
        ? <Availability employees={employees} token={token} roster={roster} rows={rosterRows} onError={setError} onNotice={setNotice} />
      : section === "Assignments"
        ? <Assignments employees={employees} brands={brands} processes={processes} assignments={assignments} token={token} onRefresh={load} name={name} />
        : section === "Roster"
          ? <RosterPanel employees={employees} brands={brands} processes={processes} roster={roster} rows={rosterRows} preview={preview} generating={generating} saving={saving} onGenerate={generateRoster} onSave={saveRoster} onLoad={loadRoster} name={name} token={token} />
          : <Directory title={section} items={section === "Brands" ? brands : section === "Processes" ? processes : pods} icon={section === "Brands" ? Network : section === "Processes" ? ClipboardList : Database} />;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="side-brand"><div className="brand-mark small"><Network size={18} /></div><div><strong>SmartRoster</strong><span>Operations control</span></div></div>
        <nav>{["Overview", "People", "Availability", "Brands", "Processes", "Pods", "Assignments", "Roster"].map((item) => <button key={item} className={section === item ? "nav-item active" : "nav-item"} onClick={() => setSection(item)}>{item === "Overview" ? <Database size={17} /> : item === "People" || item === "Availability" ? <Users size={17} /> : item === "Roster" ? <CalendarDays size={17} /> : <ClipboardList size={17} />}{item}</button>)}</nav>
        <div className="side-footer"><div className="user-chip"><div className="avatar">{email.charAt(0).toUpperCase()}</div><div><strong>{email}</strong><span>Authenticated operator</span></div></div><button className="logout" onClick={onLogout}><LogOut size={16} /> Sign out</button></div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">Workspace / {section}</p><h1>{section === "Overview" ? "Operations overview" : section}</h1></div><button className="icon-button" disabled={loading || generating} onClick={() => void load()} title={generating ? "Roster is generating" : loading ? "Refreshing data" : "Refresh data"}><RefreshCw size={18} className={loading ? "spin" : undefined} /></button></header>
        {error && <div className="error-banner page-alert"><AlertTriangle size={17} />{error}<button onClick={() => setError("")}><X size={15} /></button></div>}
        {notice && <div className="success-banner page-alert"><CheckCircle2 size={17} />{notice}<button onClick={() => setNotice("")}><X size={15} /></button></div>}
        {loading ? <div className="empty-state"><RefreshCw className="spin" /> Loading workspace...</div> : content}
      </main>
    </div>
  );
}

function Dashboard({ stats, employees, brands, assignments, roster, onGenerate }: { stats: { label: string; value: number; icon: typeof Users; tone: string }[]; employees: Entity[]; brands: Entity[]; assignments: Assignment[]; roster: Roster | null; onGenerate: () => void }) {
  return <div className="content-stack"><div className="hero-card"><div><span className="pill">Live workspace</span><h2>Make every shift count.</h2><p>Plan coverage across people, brands and processes with constraint-aware monthly rosters.</p></div><button className="primary-button" onClick={onGenerate}><CalendarDays size={17} /> Open roster planner</button></div><div className="stat-grid">{stats.map(({ label, value, icon: Icon, tone }) => <div className="stat-card" key={label}><div className={`stat-icon ${tone}`}><Icon size={19} /></div><span>{label}</span><strong>{value}</strong></div>)}</div><div className="two-column"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Workforce snapshot</p><h3>Coverage building blocks</h3></div><span className="mini-status"><CheckCircle2 size={14} /> API connected</span></div><div className="progress-row"><div><span>Active employees</span><strong>{employees.filter((item) => item.status === "active").length} / {employees.length}</strong></div><div className="progress"><i style={{ width: `${employees.length ? (employees.filter((item) => item.status === "active").length / employees.length) * 100 : 0}%` }} /></div></div><div className="list-lines">{brands.slice(0, 5).map((brand) => <div key={brand.id}><span className="dot blue" />{brand.name}<small>{assignments.filter((item) => item.brand_id === brand.id).length} assignments</small></div>)}{!brands.length && <p className="muted">Create brands and operating rules to begin scheduling.</p>}</div></section><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Roster status</p><h3>{roster ? `${roster.year}-${String(roster.month).padStart(2, "0")}` : "No saved roster"}</h3></div><CalendarDays className="muted-icon" /></div>{roster ? <><div className="status-block success"><CheckCircle2 size={20} /><div><strong>Roster saved</strong><span>Current version #{roster.current_version_id ?? "pending"}</span></div></div><p className="muted">Assignments are persisted and ready for review in the roster planner.</p></> : <div className="empty-inline"><CalendarDays size={22} /><span>Generate a monthly roster to see coverage, conflicts and validation diagnostics.</span></div>}</section></div></div>;
}

function Availability({ employees, token, roster, rows, onError, onNotice }: { employees: Entity[]; token: string; roster: Roster | null; rows: RosterAssignment[]; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [employeeId, setEmployeeId] = useState("");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("Unavailable for assessment demonstration");
  const [overrides, setOverrides] = useState<AvailabilityOverride[]>([]);
  const [loadingOverrides, setLoadingOverrides] = useState(true);
  const [validation, setValidation] = useState<RosterValidation | null>(null);
  const [solverStatus, setSolverStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadOverrides() {
    setLoadingOverrides(true);
    try {
      const result = await request<{ items: AvailabilityOverride[] }>(
        "/api/availability-overrides?limit=200",
        token,
      );
      setOverrides(result.items);
    } catch (reasonValue) {
      onError(reasonValue instanceof Error ? reasonValue.message : "Unable to load saved availability");
    } finally {
      setLoadingOverrides(false);
    }
  }

  useEffect(() => { void loadOverrides(); }, [token]);

  async function markUnavailable(event: React.FormEvent) {
    event.preventDefault();
    if (!employeeId || !date) return;
    setBusy(true); onError("");
    try {
      const result = await request<AvailabilityOverride>("/api/availability-overrides", token, {
        method: "POST",
        body: JSON.stringify({
          employee_id: Number(employeeId),
          date,
          status: "unavailable",
          reason,
          approval_status: "approved",
        }),
      });
      setOverrides((current) => [result, ...current.filter((item) => item.id !== result.id)]);
      if (roster && rows.length) {
        const checked = await request<RosterValidation>("/api/rosters/validate", token, {
          method: "POST",
          body: JSON.stringify({ year: roster.year, month: roster.month, solver_status: "feasible", assignments: rows }),
        });
        setValidation(checked);
        const refreshed = await request<RosterPreview>("/api/rosters/preview", token, {
          method: "POST",
          body: JSON.stringify({ year: roster.year, month: roster.month }),
        });
        setSolverStatus(refreshed.solver_status);
        setValidation(refreshed.validation);
        onNotice(refreshed.validation.is_valid ? `Availability saved; refreshed solver result is ${refreshed.solver_status}.` : `Availability saved; refreshed validation found ${refreshed.validation.error_count} error(s).`);
      } else {
        onNotice("Availability override saved.");
      }
    } catch (reasonValue) {
      onError(reasonValue instanceof Error ? reasonValue.message : "Unable to save availability");
    } finally { setBusy(false); }
  }

  return <div className="content-stack">
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">Availability</p><h3>Mark an employee unavailable</h3></div><span className="count-badge">{employees.length}</span></div>
      <p className="muted">This creates an approved date-specific availability override through the authenticated API.</p>
      <form className="inline-form" onSubmit={markUnavailable}>
        <select required value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}><option value="">Select employee</option>{employees.map((employee) => <option value={employee.id} key={employee.id}>{employee.name} · {employee.employee_code}</option>)}</select>
        <input required type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        <input required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason" />
        <button className="primary-button" disabled={busy}>{busy ? "Saving..." : "Mark unavailable"}</button>
      </form>
    </section>
    <section className="panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Saved records</p><h3>Availability overrides <span className="count-badge">{overrides.length}</span></h3></div>
        <button className="secondary-button" disabled={loadingOverrides} onClick={() => void loadOverrides()}>
          <RefreshCw size={15} className={loadingOverrides ? "spin" : undefined} /> {loadingOverrides ? "Refreshing..." : "Refresh list"}
        </button>
      </div>
      {loadingOverrides ? <div className="empty-state"><RefreshCw className="spin" /> Loading saved availability...</div> : overrides.length ? <div className="table-wrap"><table><thead><tr><th>Date</th><th>Employee</th><th>Status</th><th>Approval</th><th>Reason</th></tr></thead><tbody>{[...overrides].sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id).map((item) => <tr key={item.id}><td>{new Date(`${item.date}T00:00:00`).toLocaleDateString()}</td><td>{employees.find((employee) => employee.id === item.employee_id)?.name ?? `Employee #${item.employee_id}`}</td><td>{item.status}</td><td>{item.approval_status}</td><td>{item.reason}</td></tr>)}</tbody></table></div> : <div className="empty-state">No availability overrides have been saved yet.</div>}
    </section>
    {validation && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Roster validation</p><h3>{validation.is_valid ? "No validation errors" : "Coverage or validation issues found"}</h3></div><span className={`count-badge ${validation.error_count ? "text-red" : "text-green"}`}>{validation.error_count} errors</span></div><p className="muted">Solver result: {solverStatus || "saved roster validation"} · {validation.warning_count} warning(s); affected dates: {validation.affected_dates.join(", ") || "none"}.</p>{validation.diagnostics.slice(0, 20).map((item, index) => <div className={`diagnostic ${item.severity}`} key={`${item.code}-${index}`}><span>{item.code}</span><p>{item.message}</p><small>{item.target_date ?? "Roster-wide"}{item.employee_id ? ` · employee #${item.employee_id}` : ""}</small></div>)}</section>}
  </div>;
}

function Directory({ title, items, icon: Icon }: { title: string; items: Entity[]; icon: typeof Network }) {
  return <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Organization</p><h3>{title} directory</h3></div><span className="count-badge">{items.length}</span></div><div className="table-wrap"><table><thead><tr><th>Code</th><th>Name</th><th>Status</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><span className="code-cell"><Icon size={14} />{item.code ?? item.employee_code ?? `#${item.id}`}</span></td><td>{item.name}</td><td><span className="status-dot"><i />{item.is_active === false ? "Inactive" : "Active"}</span></td></tr>)}</tbody></table>{!items.length && <div className="empty-state">No {title.toLowerCase()} found.</div>}</div></section>;
}

function People({ employees, pods, token, onRefresh, name }: { employees: Entity[]; pods: Entity[]; token: string; onRefresh: () => void; name: (items: Entity[], id: number) => string }) {
  const [form, setForm] = useState({ employee_code: "", name: "", email: "", pod_id: "" });
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function addEmployee(event: React.FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await request("/api/employees", token, { method: "POST", body: JSON.stringify({ ...form, pod_id: form.pod_id ? Number(form.pod_id) : null }) }); setForm({ employee_code: "", name: "", email: "", pod_id: "" }); onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to add employee"); } finally { setBusy(false); } }
  return <div className="content-stack"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Workforce</p><h3>Employees <span className="count-badge">{employees.length}</span></h3></div></div><form className="inline-form" onSubmit={addEmployee}><input required placeholder="Employee ID" value={form.employee_code} onChange={(e) => setForm({ ...form, employee_code: e.target.value })} /><input required placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><input required type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /><select value={form.pod_id} onChange={(e) => setForm({ ...form, pod_id: e.target.value })}><option value="">No pod</option>{pods.map((pod) => <option key={pod.id} value={pod.id}>{pod.name}</option>)}</select><button className="primary-button" disabled={busy}><Plus size={16} /> Add</button></form>{error && <p className="field-error">{error}</p>}<div className="table-wrap"><table><thead><tr><th>Employee</th><th>Contact</th><th>Pod</th><th>Status</th></tr></thead><tbody>{employees.map((employee) => <tr key={employee.id}><td><div className="person-cell"><div className="avatar">{employee.name.charAt(0)}</div><div><strong>{employee.name}</strong><small>{employee.employee_code}</small></div></div></td><td>{employee.email}</td><td>{employee.pod_id ? name(pods, employee.pod_id) : "Unassigned"}</td><td><span className="status-dot"><i />{employee.status ?? "active"}</span></td></tr>)}</tbody></table>{!employees.length && <div className="empty-state">No employees yet. Add your first operator above.</div>}</div></section></div>;
}

function Assignments({ employees, brands, processes, assignments, token, onRefresh, name }: { employees: Entity[]; brands: Entity[]; processes: Entity[]; assignments: Assignment[]; token: string; onRefresh: () => void; name: (items: Entity[], id: number) => string }) {
  const [form, setForm] = useState({ employee_id: "", brand_id: "", process_id: "", effective_start_date: new Date().toISOString().slice(0, 10) }); const [error, setError] = useState("");
  async function add(event: React.FormEvent) { event.preventDefault(); setError(""); try { await request("/api/assignments", token, { method: "POST", body: JSON.stringify({ ...form, employee_id: Number(form.employee_id), brand_id: Number(form.brand_id), process_id: Number(form.process_id), skill_level: 1, is_primary: false, is_active: true }) }); onRefresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Assignment failed"); } }
  return <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Eligibility</p><h3>Employee assignments <span className="count-badge">{assignments.length}</span></h3></div></div><form className="inline-form" onSubmit={add}><select required value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}><option value="">Employee</option>{employees.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><select required value={form.brand_id} onChange={(e) => setForm({ ...form, brand_id: e.target.value })}><option value="">Brand</option>{brands.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><select required value={form.process_id} onChange={(e) => setForm({ ...form, process_id: e.target.value })}><option value="">Process</option>{processes.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><input required type="date" value={form.effective_start_date} onChange={(e) => setForm({ ...form, effective_start_date: e.target.value })} /><button className="primary-button"><Plus size={16} /> Assign</button></form>{error && <p className="field-error">{error}</p>}<div className="table-wrap"><table><thead><tr><th>Employee</th><th>Brand</th><th>Process</th><th>Effective from</th><th>Status</th></tr></thead><tbody>{assignments.map((item) => <tr key={item.id}><td>{name(employees, item.employee_id)}</td><td>{name(brands, item.brand_id)}</td><td>{name(processes, item.process_id)}</td><td>{item.effective_start_date}</td><td><span className="status-dot"><i />{item.is_active ? "Active" : "Inactive"}</span></td></tr>)}</tbody></table></div></section>;
}

function RosterPanel({ employees, brands, processes, roster, rows, preview, generating, saving, onGenerate, onSave, onLoad, name, token }: { employees: Entity[]; brands: Entity[]; processes: Entity[]; roster: Roster | null; rows: RosterAssignment[]; preview: RosterPreview | null; generating: boolean; saving: boolean; onGenerate: (year: number, month: number) => void; onSave: () => void; onLoad: (id: number) => void; name: (items: Entity[], id: number) => string; token: string }) {
  const now = new Date(); const [year, setYear] = useState(now.getFullYear()); const [month, setMonth] = useState(now.getMonth() + 1);
  const shown = preview?.assignments ?? rows; const diagnostics = preview?.validation.diagnostics ?? [];
  return <div className="content-stack"><section className="planner-head"><div><p className="eyebrow">Monthly planning</p><h2>Roster planner</h2><p className="muted">Generate, validate and save a solver-backed roster for the selected period.</p></div><div className="period-controls"><input type="number" min="2000" max="2100" value={year} onChange={(e) => setYear(Number(e.target.value))} /><select value={month} onChange={(e) => setMonth(Number(e.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{new Date(2000, i, 1).toLocaleString("en", { month: "long" })}</option>)}</select><button className="primary-button" disabled={generating} onClick={() => onGenerate(year, month)}><CalendarDays size={16} /> {generating ? "Generating..." : "Generate"}</button>{preview?.validation.is_valid && <button className="secondary-button" disabled={saving} onClick={onSave}>{saving ? "Saving..." : "Save roster"}</button>}</div></section>{preview && <section className="stat-grid compact"><div className="stat-card"><span>Solver result</span><strong className="text-green">{preview.solver_status}</strong></div><div className="stat-card"><span>Assignments</span><strong>{preview.assignments.length}</strong></div><div className="stat-card"><span>Errors</span><strong className={preview.validation.error_count ? "text-red" : "text-green"}>{preview.validation.error_count}</strong></div><div className="stat-card"><span>Warnings</span><strong>{preview.validation.warning_count}</strong></div></section>}{preview && diagnostics.length > 0 && <section className="panel diagnostics"><div className="panel-heading"><h3><AlertTriangle size={18} /> Validation diagnostics</h3></div>{diagnostics.slice(0, 20).map((item, index) => <div className={`diagnostic ${item.severity}`} key={`${item.code}-${index}`}><span>{item.code}</span><p>{item.message}</p><small>{item.target_date ?? "Roster-wide"}{item.employee_id ? ` · employee #${item.employee_id}` : ""}</small></div>)}</section>}<section className="panel"><div className="panel-heading"><div><p className="eyebrow">Coverage view</p><h3>{roster ? `Saved roster #${roster.id}` : preview ? "Generated preview" : "No roster selected"}</h3></div>{roster && <button className="secondary-button" onClick={() => onLoad(roster.id)}>Reload saved roster</button>}</div>{shown.length ? <div className="table-wrap"><table><thead><tr><th>Date</th><th>Employee</th><th>Brand</th><th>Process</th><th>Workload</th></tr></thead><tbody>{shown.map((item, index) => <tr key={`${item.date}-${item.employee_id}-${item.brand_id}-${item.process_id}-${index}`}><td>{item.date}</td><td>{name(employees, item.employee_id)}</td><td>{name(brands, item.brand_id)}</td><td>{name(processes, item.process_id)}</td><td>{item.workload_units ?? "—"} units</td></tr>)}</tbody></table></div> : <div className="empty-state"><CalendarDays size={24} />Generate a roster to display monthly coverage.</div>}</section><ManualChange roster={roster} rows={rows} employees={employees} token={token} /></div>;
}

function ManualChange({ roster, rows, employees, token }: { roster: Roster | null; rows: RosterAssignment[]; employees: Entity[]; token: string }) {
  const [selected, setSelected] = useState(""); const [replacement, setReplacement] = useState(""); const [changePreview, setChangePreview] = useState<{ validation: { is_valid: boolean; error_count: number; diagnostics: Diagnostic[] } } | null>(null); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const assignment = rows[Number(selected)]; const canChange = Boolean(roster?.current_version_id && assignment && replacement);
  const payload = canChange ? { operation: "replace", expected_version_id: roster?.current_version_id, changed_by: "authenticated operator", assignment: { ...assignment, employee_id: Number(replacement) }, previous_assignment: assignment } : null;
  async function previewChange() { if (!payload || !roster) return; setBusy(true); setMessage(""); try { const result = await request<{ validation: { is_valid: boolean; error_count: number; diagnostics: Diagnostic[] } }>(`/api/rosters/${roster.id}/manual/preview`, token, { method: "POST", body: JSON.stringify(payload) }); setChangePreview(result); setMessage(result.validation.is_valid ? "Manual change passed independent validation. Accept to create a new roster version." : "Manual change rejected by validation."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Manual preview failed"); } finally { setBusy(false); } }
  async function acceptChange() { if (!payload || !roster || !changePreview?.validation.is_valid) return; setBusy(true); try { await request(`/api/rosters/${roster.id}/manual/accept`, token, { method: "POST", body: JSON.stringify(payload) }); setMessage("Manual change accepted as a new roster version. Reload the roster to view it."); setChangePreview(null); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Manual change acceptance failed"); } finally { setBusy(false); } }
  return <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Controlled change</p><h3>Manual roster change</h3></div><ShieldCheck className="muted-icon" /></div><p className="muted">Manual changes are independently validated by the backend before acceptance. Select a saved assignment to prepare a replacement.</p><div className="inline-form"><select value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">Select saved assignment</option>{rows.map((item, index) => <option value={index} key={`${item.date}-${item.employee_id}-${index}`}>{item.date} · employee #{item.employee_id}</option>)}</select><select value={replacement} onChange={(e) => setReplacement(e.target.value)}><option value="">Replacement employee</option>{employees.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><button className="secondary-button" disabled={!canChange || busy} onClick={() => void previewChange()}>Preview change</button>{changePreview?.validation.is_valid && <button className="primary-button" disabled={busy} onClick={() => void acceptChange()}>Accept change</button>}</div>{message && <p className="field-note">{message}</p>}</section>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

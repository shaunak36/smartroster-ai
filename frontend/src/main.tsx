import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";

function App() {
  return (
    <main className="min-h-screen bg-slate-50 p-8 text-navy">
      <div className="mx-auto max-w-5xl rounded-2xl bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-violet-600">
          SmartRoster AI
        </p>
        <h1 className="mt-2 text-3xl font-bold">Roster management foundation</h1>
        <p className="mt-3 text-slate-600">
          Stage 1 project foundation is ready. Operations modules will be added
          in later implementation stages.
        </p>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);


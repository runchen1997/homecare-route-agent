import { useState } from "react";
import MapView from "./MapView.jsx";
import PlanForm from "./PlanForm.jsx";
import Schedule from "./Schedule.jsx";
import Steps from "./Steps.jsx";
import { streamPlan } from "./plan.js";

const TABS = [
  ["plan", "Plan"],
  ["day", "Tomorrow"],
  ["steps", "How it was planned"],
];

export default function App() {
  const [tab, setTab] = useState("plan");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([]);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);

  async function start(request) {
    setRunning(true);
    setSteps([]);
    setPlan(null);
    setError(null);
    setTab("steps"); // watch the planner work
    try {
      await streamPlan(request, (name, data) => {
        if (name === "step") setSteps((before) => [...before, data]);
        else if (name === "plan") {
          setPlan(data);
          setTab("day");
        } else if (name === "error") setError(data.message);
      });
    } catch (problem) {
      setError(problem.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <header>
          <h1>Route Planner</h1>
          <p>Tomorrow's home visits, planned on this computer. Patient addresses never leave it.</p>
        </header>
        <nav className="tabs" role="tablist">
          {TABS.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""}
                    onClick={() => setTab(id)}>
              {label}
              {id === "steps" && running && <span className="dot" aria-label="working" />}
            </button>
          ))}
        </nav>
        {error && <p className="notice error">{error}</p>}
        {/* Every panel stays mounted, so switching tabs keeps what the nurse typed. */}
        <div className="panel" hidden={tab !== "plan"}><PlanForm onSubmit={start} running={running} /></div>
        <div className="panel" hidden={tab !== "day"}><Schedule plan={plan} /></div>
        <div className="panel" hidden={tab !== "steps"}><Steps steps={steps} running={running} /></div>
      </aside>
      <main className="map-area">
        <MapView plan={plan} />
      </main>
    </div>
  );
}

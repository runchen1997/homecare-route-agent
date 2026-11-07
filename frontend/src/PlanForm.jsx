import { useEffect, useState } from "react";
import { examples } from "./plan.js";

// What the nurse tells the planner: the patient list, home, how they travel, and how much work the day holds.
export default function PlanForm({ onSubmit, running }) {
  const [list, setList] = useState(null); // { name, text }
  const [samples, setSamples] = useState([]);
  const [home, setHome] = useState("");
  const [mode, setMode] = useState("walking");
  const [maxVisits, setMaxVisits] = useState(5);
  const [workHours, setWorkHours] = useState("");
  const [dayStart, setDayStart] = useState("08:00");
  const [dayEnd, setDayEnd] = useState("17:00");
  const [visitMinutes, setVisitMinutes] = useState(30);
  const [slack, setSlack] = useState(10);
  const [maxWait, setMaxWait] = useState("20");
  const [prefer, setPrefer] = useState("least travel");

  useEffect(() => {
    examples().then(setSamples);
  }, []);

  function pickFile(event) {
    const file = event.target.files[0];
    if (file) file.text().then((text) => setList({ name: file.name, text }));
  }

  function pickSample(sample) {
    setList({ name: sample.name, text: sample.csv });
    setHome(sample.home);
  }

  function submit(event) {
    event.preventDefault();
    onSubmit({
      csv: list.text,
      home,
      mode,
      rules: {
        max_visits: Number(maxVisits),
        work_hours: workHours === "" ? null : Number(workHours),
        day_start: dayStart,
        day_end: dayEnd,
        visit_minutes: Number(visitMinutes),
        window_slack_minutes: Number(slack),
        max_wait_minutes: maxWait === "" ? null : Number(maxWait),
        prefer,
      },
    });
  }

  return (
    <form className="plan-form" onSubmit={submit}>
      <section>
        <h2>Patients</h2>
        <label className="file">
          <input type="file" accept=".csv,text/csv" onChange={pickFile} />
          <span className="button secondary">Choose a CSV file</span>
          <span className="file-name">{list ? list.name : "No list yet"}</span>
        </label>
        {samples.length > 0 && (
          <p className="samples">
            Or try a sample:{" "}
            {samples.map((sample) => (
              <button type="button" className="link" key={sample.name} onClick={() => pickSample(sample)}>
                {sample.name}
              </button>
            ))}
          </p>
        )}
        {list && <pre className="preview">{list.text.trim()}</pre>}
        <p className="hint">One row per patient: a name, an address, and a time window if there is one, written any way.</p>
      </section>

      <section>
        <h2>Home</h2>
        <input
          type="text"
          value={home}
          onChange={(e) => setHome(e.target.value)}
          placeholder="e.g. 1025 70th St, Brooklyn"
          required
        />
      </section>

      <section>
        <h2>Getting around</h2>
        <Choice name="mode" value={mode} onChange={setMode} options={[["walking", "Walking"], ["driving", "Driving"]]} />
      </section>

      <section>
        <h2>Best plan</h2>
        <Choice name="prefer" value={prefer} onChange={setPrefer}
                options={[["least travel", "Least travel"], ["tightest group", "Patients close together"]]} />
        <p className="hint">
          {prefer === "least travel"
            ? "The shortest day of travel, counting the trips from home and back."
            : "The least travel from one patient to the next, even if home is a little farther away."}
        </p>
      </section>

      <section>
        <h2>Tomorrow's workload</h2>
        <div className="row">
          <label>
            Most visits
            <input type="number" min="1" max="12" value={maxVisits} onChange={(e) => setMaxVisits(e.target.value)} required />
          </label>
          <label>
            Longest day (hours)
            <input type="number" min="0.5" step="0.5" value={workHours} placeholder="no limit"
                   onChange={(e) => setWorkHours(e.target.value)} />
          </label>
        </div>
        <details className="more">
          <summary>More rules</summary>
          <div className="row">
            <label>
              Leave from
              <input type="time" value={dayStart} onChange={(e) => setDayStart(e.target.value)} required />
            </label>
            <label>
              Back by
              <input type="time" value={dayEnd} onChange={(e) => setDayEnd(e.target.value)} required />
            </label>
          </div>
          <div className="row">
            <label>
              Visit length (min)
              <input type="number" min="5" value={visitMinutes} onChange={(e) => setVisitMinutes(e.target.value)} required />
            </label>
            <label>
              Window slack (min)
              <input type="number" min="0" value={slack} onChange={(e) => setSlack(e.target.value)} required />
            </label>
            <label>
              Longest wait (min)
              <input type="number" min="0" value={maxWait} placeholder="no limit" onChange={(e) => setMaxWait(e.target.value)} />
            </label>
          </div>
        </details>
      </section>

      <button type="submit" className="button primary" disabled={running || !list || !home.trim()}>
        {running ? "Planning…" : "Plan tomorrow"}
      </button>
    </form>
  );
}

// One of a few choices, shown as a row of buttons.
function Choice({ name, value, onChange, options }) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map(([option, label]) => (
        <label key={option} className={value === option ? "on" : ""}>
          <input type="radio" name={name} value={option} checked={value === option} onChange={() => onChange(option)} />
          {label}
        </label>
      ))}
    </div>
  );
}

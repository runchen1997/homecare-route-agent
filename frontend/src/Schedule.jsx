// Tomorrow, as planned: when to leave, each visit in order, when the nurse is home, and why.

// A patient's name, as the list writes it: the first cell that isn't empty.
export function patientName(patient) {
  return patient.cells.find(([, value]) => value)?.[1] ?? patient.id;
}

function duration(minutes) {
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

function windowText(earliest, latest) {
  if (earliest && latest) return `${earliest}–${latest}`;
  if (earliest) return `from ${earliest}`;
  if (latest) return `by ${latest}`;
  return "any time";
}

export default function Schedule({ plan }) {
  if (!plan) return <p className="empty">The plan for tomorrow shows here.</p>;
  const patients = Object.fromEntries(plan.patients.map((patient) => [patient.id, patient]));
  if (plan.ended !== "submitted") {
    return <p className="notice warning">The planner didn't hand in a plan within its steps. Try again, or check the list.</p>;
  }
  const s = plan.schedule;
  if (!s) {
    return (
      <p className="notice warning">
        The planner handed in {plan.order.join(" → ")}, but not every address on it was found, so the day can't be
        worked out. Check how the addresses are written.
      </p>
    );
  }
  const notVisited = plan.patients.filter((patient) => !plan.order.includes(patient.id));

  return (
    <div className="schedule">
      <div className="totals">
        <div><strong>{s.stops.length}</strong><span>visits</span></div>
        <div><strong>{duration(s.travel_minutes)}</strong><span>travel</span></div>
        <div><strong>{duration(s.waiting_minutes)}</strong><span>waiting</span></div>
        <div><strong>{s.leave}–{s.back}</strong><span>{duration(s.working_minutes)} day</span></div>
      </div>

      {plan.reasons && <p className="why">{plan.reasons}</p>}

      {s.problems.length > 0 && (
        <div className="notice warning">
          <strong>This plan breaks the rules:</strong>
          <ul>{s.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </div>
      )}

      <ol className="timeline">
        <li className="home-stop"><span className="time">{s.leave}</span>Leave home</li>
        {s.stops.map((stop, i) => {
          const patient = patients[stop.patient];
          return [
            <li key={`${stop.patient}-leg`} className="leg">{stop.travel_minutes} min</li>,
            <li key={stop.patient} className={`visit${stop.late ? " late" : ""}`}>
              <span className="time">{stop.start}</span>
              <span className="badge">{i + 1}</span>
              <div>
                <div className="visit-name">{patientName(patient)} <small>{stop.patient}</small></div>
                <div className="visit-address">{patient.place?.address}</div>
                <div className="visit-times">
                  {stop.start}–{stop.finish} · window {windowText(stop.earliest, stop.latest)}
                  {stop.wait_minutes > 0 && ` · arrive ${stop.arrive}, wait ${stop.wait_minutes} min`}
                  {stop.late && <span className="tag">late</span>}
                </div>
              </div>
            </li>,
          ];
        })}
        <li className="leg">{s.travel_home_minutes} min</li>
        <li className="home-stop"><span className="time">{s.back}</span>Back home</li>
      </ol>

      {notVisited.length > 0 && (
        <section className="not-visited">
          <h3>Not visited tomorrow</h3>
          <ul>
            {notVisited.map((patient) => (
              <li key={patient.id}>{patientName(patient)} <small>{patient.id}</small></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

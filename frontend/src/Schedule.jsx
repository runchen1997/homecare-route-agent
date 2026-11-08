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
        <div><strong>{duration(s.travel_minutes)}</strong><span>travel, {duration(s.between_minutes)} between patients</span></div>
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
            <Leg key={`${stop.patient}-leg`} minutes={stop.travel_minutes} trip={plan.transit?.[i]}
                 why={plan.transit_why?.[i]} />,
            <li key={stop.patient} className={`visit${stop.late ? " late" : ""}`}>
              <span className="time">{stop.start}</span>
              <span className="badge">{i + 1}</span>
              <div>
                <div className="visit-name">{patientName(patient)} <small>{stop.patient}</small></div>
                <div className="visit-address">{patient.place?.address}</div>
                {patient.place?.note && <div className="visit-note">{patient.place.note}</div>}
                <div className="visit-times">
                  {stop.start}–{stop.finish} · window {windowText(stop.earliest, stop.latest)}
                  {stop.wait_minutes > 0 && ` · arrive ${stop.arrive}, wait ${stop.wait_minutes} min`}
                  {stop.late && <span className="tag">late</span>}
                </div>
              </div>
            </li>,
          ];
        })}
        <Leg minutes={s.travel_home_minutes} trip={plan.transit?.[s.stops.length]}
             why={plan.transit_why?.[s.stops.length]} />
        <li className="home-stop"><span className="time">{s.back}</span>Back home</li>
      </ol>

      {notVisited.length > 0 && (
        <section className="not-visited">
          <h3>Not visited tomorrow</h3>
          <ul>
            {notVisited.map((patient) => (
              <li key={patient.id}>
                {patientName(patient)} <small>{patient.id}{!patient.place && " · address not found"}</small>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// The travel between two places. By subway and bus, also the way to go: the quickest at the time the
// nurse sets off, as an example (the times above are typical ones, so it can take a little more or less).
function Leg({ minutes, trip, why }) {
  if (!trip) return <li className="leg">{minutes} min</li>;
  return (
    <li className="leg">
      <span>{minutes} min typical</span>
      <ol className="trip" aria-label="For example">
        {trip.map((part, i) =>
          part.mode === "walk" ? (
            <li key={i} className="walk">Walk {part.minutes} min</li>
          ) : (
            <li key={i}>
              <span className="route" style={{ background: part.color ?? undefined, color: part.text_color ?? undefined }}>
                {part.route}
              </span>
              {" "}{part.depart} {part.start} → {part.end}, {part.minutes} min
            </li>
          ),
        )}
      </ol>
      {why && <p className="trip-why">{why}</p>}
    </li>
  );
}

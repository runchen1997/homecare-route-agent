// How the plan was worked out: each step the model took, as it takes them.

const ACTIONS = {
  find_address: "Find addresses",
  travel_times: "Travel times",
  best_plans: "Best plans",
  check_plan: "Check a plan",
  submit_plan: "Hand in the plan",
};

export default function Steps({ steps, running }) {
  if (!steps.length && !running) {
    return <p className="empty">Each step the planner takes shows here: what it thinks, the tool it uses, and what it gets back.</p>;
  }
  return (
    <ol className="steps">
      {steps.map((step) => (
        <li key={step.number} className="step">
          <div className="step-head">
            <span className="step-number">{step.number}</span>
            <span className="step-action">{ACTIONS[step.action] ?? step.action}</span>
            <code className="step-tool">{step.action}</code>
          </div>
          <p className="step-thinking">{step.thinking}</p>
          <details>
            <summary>What it asked, and the answer</summary>
            <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
            <pre>{step.result}</pre>
          </details>
        </li>
      ))}
      {running && (
        <li className="step thinking">
          <span className="spinner" aria-hidden="true" />
          Thinking about step {steps.length + 1}…
        </li>
      )}
    </ol>
  );
}

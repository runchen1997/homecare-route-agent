// Talking to the planner (homecare/web.py).

// Ask for a plan, and call onEvent(name, data) for each event as it comes: "step" for each step the
// model takes, then "plan" or "error". The planner answers with Server-Sent Events; the browser's own
// EventSource can only send GET, so the stream is read from fetch.
export async function streamPlan(request, onEvent) {
  let response;
  try {
    response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new Error("Can't reach the planner. Is it running (python -m homecare.web)?");
  }
  if (!response.ok) throw new Error(await refusal(response));

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    // Each event ends with an empty line; a chunk can hold several events, or part of one.
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      onEvent(name, JSON.parse(data));
    }
  }
}

// Why the planner refused a request, in a sentence.
async function refusal(response) {
  try {
    const { detail } = await response.json();
    if (typeof detail === "string") return detail;
    // A request that doesn't make sense (422): each field and what is wrong with it.
    return detail.map((d) => `${d.loc.slice(1).join(" ")}: ${d.msg}`).join("; ");
  } catch {
    return `The planner answered ${response.status}.`;
  }
}

export async function examples() {
  try {
    const response = await fetch("/api/examples");
    return response.ok ? await response.json() : [];
  } catch {
    return [];
  }
}

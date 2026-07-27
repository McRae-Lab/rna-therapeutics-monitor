const revision = document.querySelector("#method-revision");
const llmMode = document.querySelector("#llm-mode");
const scoreTable = document.querySelector("#score-table");

fetch("./data/methodology.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((method) => {
    revision.textContent = method.methodology_revision || "unknown";
    revision.dateTime = method.methodology_revision || "";
    llmMode.textContent = method.llm_enabled ? "LLM-assisted" : "Deterministic";
    Object.entries(method.score_components || {}).forEach(([name, maximum]) => {
      const row = document.createElement("div");
      row.className = "method-score-row";
      const label = document.createElement("span");
      label.textContent = name;
      const points = document.createElement("strong");
      points.textContent = `${maximum} pts`;
      row.append(label, points);
      scoreTable.append(row);
    });
  })
  .catch(() => {
    llmMode.textContent = "Method file unavailable";
  });

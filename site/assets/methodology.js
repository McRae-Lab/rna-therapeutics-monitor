const revision = document.querySelector("#method-revision");
const llmMode = document.querySelector("#llm-mode");

fetch("./data/methodology.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((method) => {
    revision.textContent = method.methodology_revision || "unknown";
    revision.dateTime = method.methodology_revision || "";
    llmMode.textContent = method.llm_enabled ? "LLM-assisted" : "Deterministic";
  })
  .catch(() => {
    llmMode.textContent = "Method file unavailable";
  });

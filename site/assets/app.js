const PAGE_SIZE = 25;
const state = {
  records: [],
  filtered: [],
  visible: PAGE_SIZE,
  preset: "latest",
  loadedFull: false,
  asOfDate: "",
};

const byId = (id) => document.getElementById(id);
const controls = {
  search: byId("search"),
  dateFrom: byId("date-from"),
  dateTo: byId("date-to"),
  minScore: byId("min-score"),
  technology: byId("technology"),
  modality: byId("modality"),
  delivery: byId("delivery"),
  disease: byId("disease"),
  stage: byId("stage"),
  source: byId("source"),
  evidence: byId("evidence"),
  reviewStatus: byId("review-status"),
  trialStatus: byId("trial-status"),
  company: byId("company"),
  institution: byId("institution"),
  watchedPerson: byId("watched-person"),
  sort: byId("sort"),
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function safeUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function normalize(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, " ")
    .trim();
}

function recordDate(record) {
  return record.updated_date || record.published_date || record.first_date || "";
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function shiftDate(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return isoDate(date);
}

function updateDateShortcutState() {
  const asOfDate = state.asOfDate || isoDate(new Date());
  document.querySelectorAll("[data-date-days]").forEach((button) => {
    const days = button.dataset.dateDays;
    const expectedFrom = days === "all" ? "" : shiftDate(asOfDate, -(Number(days) - 1));
    const expectedTo = days === "all" ? "" : asOfDate;
    button.classList.toggle(
      "active",
      controls.dateFrom.value === expectedFrom && controls.dateTo.value === expectedTo,
    );
  });
}

function setDateWindow(days) {
  const asOfDate = state.asOfDate || isoDate(new Date());
  if (days === "all") {
    controls.dateFrom.value = "";
    controls.dateTo.value = "";
  } else {
    controls.dateFrom.value = shiftDate(asOfDate, -(Number(days) - 1));
    controls.dateTo.value = asOfDate;
  }
  state.visible = PAGE_SIZE;
  updateDateShortcutState();
  applyFilters();
}

function searchable(record) {
  const authors = (record.authors || []).map((item) => item.name);
  const organizations = (record.organizations || []).map((item) => item.name);
  return normalize([
    record.title,
    record.abstract,
    record.description,
    ...authors,
    ...organizations,
    ...(record.companies || []),
    ...(record.institutions || []),
    ...(record.watched_people || []),
    ...(record.therapeutic_targets || []),
    ...(record.modalities || []),
    ...(record.delivery_systems || []),
    ...(record.disease_areas || []),
    record.doi,
    record.pmid,
    record.nct_id,
  ].filter(Boolean).join(" "));
}

function contains(record, field, value) {
  return !value || (record[field] || []).includes(value);
}

function technologyMatch(record, value) {
  if (!value) return true;
  const modalities = record.modalities || [];
  const topics = record.topics || [];
  if (["mRNA", "siRNA", "ASO"].includes(value)) return modalities.includes(value);
  if (value === "CRISPR") return modalities.includes("CRISPR RNA") || topics.includes("CRISPR");
  if (value === "base editing") return topics.includes("base editing");
  if (value === "gene editing") {
    return topics.some((topic) => ["gene editing", "base editing", "CRISPR"].includes(topic));
  }
  return false;
}

function presetMatch(record) {
  switch (state.preset) {
    case "mrna":
      return (record.modalities || []).includes("mRNA");
    case "sirna":
      return (record.modalities || []).includes("siRNA");
    case "aso":
      return (record.modalities || []).includes("ASO");
    case "crispr":
      return technologyMatch(record, "CRISPR");
    case "base-editing":
      return technologyMatch(record, "base editing");
    case "clinical":
      return record.record_type === "clinical_trial" ||
        (record.development_stages || []).some((stage) => stage.startsWith("Phase"));
    case "preclinical":
      return (record.development_stages || []).some((stage) => stage.startsWith("preclinical"));
    case "delivery":
      return (record.delivery_systems || []).length > 0 || (record.topics || []).includes("delivery");
    case "regulatory":
      return record.record_type === "regulatory" ||
        record.evidence_level === "regulatory document" ||
        (record.topics || []).includes("regulation");
    case "aptamers":
      return (record.modalities || []).includes("aptamer");
    case "nanotechnology":
      return (record.modalities || []).includes("RNA nanostructure");
    case "trial-changes":
      return record.record_type === "clinical_trial" && (record.change_history || []).length > 0;
    case "srt-authors":
      return (record.watched_people || []).length > 0;
    default:
      return true;
  }
}

function applyFilters() {
  const terms = normalize(controls.search.value).split(" ").filter(Boolean);
  const minimum = Number(controls.minScore.value);
  state.filtered = state.records.filter((record) => {
    if (record.excluded) return false;
    const haystack = searchable(record);
    return presetMatch(record) &&
      terms.every((term) => haystack.includes(term)) &&
      (!controls.dateFrom.value || recordDate(record) >= controls.dateFrom.value) &&
      (!controls.dateTo.value || recordDate(record) <= controls.dateTo.value) &&
      Number(record.relevance_score || 0) >= minimum &&
      technologyMatch(record, controls.technology.value) &&
      contains(record, "modalities", controls.modality.value) &&
      contains(record, "delivery_systems", controls.delivery.value) &&
      contains(record, "disease_areas", controls.disease.value) &&
      contains(record, "development_stages", controls.stage.value) &&
      contains(record, "source_types", controls.source.value) &&
      (!controls.evidence.value || record.evidence_level === controls.evidence.value) &&
      (!controls.reviewStatus.value || record.evidence_level === controls.reviewStatus.value) &&
      (!controls.trialStatus.value || record.trial?.overall_status === controls.trialStatus.value) &&
      contains(record, "companies", controls.company.value) &&
      contains(record, "institutions", controls.institution.value) &&
      contains(record, "watched_people", controls.watchedPerson.value);
  });
  const sorter = controls.sort.value;
  state.filtered.sort((a, b) => {
    if (sorter === "score-desc") return (b.relevance_score || 0) - (a.relevance_score || 0) || recordDate(b).localeCompare(recordDate(a)) || a.id.localeCompare(b.id);
    if (sorter === "title-asc") return a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
    return recordDate(b).localeCompare(recordDate(a)) || (b.relevance_score || 0) - (a.relevance_score || 0) || a.id.localeCompare(b.id);
  });
  render();
}

function appendTags(card, record) {
  const container = element("div", "tags");
  const groups = [
    ["modalities", "modality"],
    ["development_stages", ""],
    ["disease_areas", ""],
    ["delivery_systems", ""],
  ];
  groups.forEach(([field, className]) => {
    (record[field] || []).forEach((value) => container.append(element("span", `tag ${className}`.trim(), value)));
  });
  if (container.children.length) card.append(container);
}

function link(href, text) {
  const url = safeUrl(href);
  if (!url) return element("span", "", text);
  const anchor = element("a", "", text);
  anchor.href = url;
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function detailSection(title, content) {
  const section = element("section", "details-section");
  section.append(element("h4", "", title), content);
  return section;
}

function list(values) {
  const ul = element("ul");
  values.filter(Boolean).forEach((value) => ul.append(element("li", "", value)));
  return ul;
}

function renderDetails(record) {
  const details = element("details", "card-details");
  details.append(element("summary", "", "Inspect record details"));
  const grid = element("div", "details-grid");
  const fullText = record.abstract || record.description;
  if (fullText) grid.append(detailSection(record.abstract ? "Abstract" : "Description", element("p", "", fullText)));
  if ((record.authors || []).length) {
    const authors = record.authors.map((author) => {
      const affiliations = (author.affiliations || []).join("; ");
      return affiliations ? `${author.name} — ${affiliations}` : author.name;
    });
    grid.append(detailSection("Authors & affiliations", list(authors)));
  }
  if (record.trial) {
    const interventions = [...(record.trial.interventions || []), ...(record.trial.intervention_aliases || [])];
    if (interventions.length) grid.append(detailSection("Interventions", list(interventions)));
    const outcomes = (record.trial.outcomes || []).map((item) => {
      const frame = item.time_frame ? ` — ${item.time_frame}` : "";
      return `${item.outcome_type}: ${item.measure}${frame}`;
    });
    if (outcomes.length) grid.append(detailSection("Outcomes", list(outcomes)));
  }
  const rationale = [];
  Object.entries(record.classification_evidence || {}).forEach(([category, entries]) => {
    entries.forEach((item) => {
      rationale.push(`${category} · ${item.label} (${Math.round(item.confidence * 100)}%): ${(item.matched_phrases || []).join(", ")} [${(item.fields || []).join(", ")}]`);
    });
  });
  if (rationale.length) grid.append(detailSection("Classification rationale", list(rationale)));
  if ((record.score_components || []).length) {
    const score = element("div");
    record.score_components.forEach((item) => {
      const row = element("div", "score-row");
      row.append(element("span", "", item.name), element("strong", "", `${item.points}/${item.maximum}`), element("span", "", item.reason));
      score.append(row);
    });
    grid.append(detailSection("Scoring breakdown", score));
  }
  if ((record.provenance || []).length) {
    const values = record.provenance.map((item) => `${item.source} · ${item.source_id} · retrieved ${new Date(item.retrieved_at).toLocaleString()}`);
    grid.append(detailSection("Provenance", list(values)));
  }
  if ((record.change_history || []).length) {
    const values = record.change_history.map((item) => `${item.changed_at.slice(0, 10)} · ${item.summary}`);
    grid.append(detailSection("Change history", list(values)));
  }
  details.append(grid);
  return details;
}

function renderCard(record) {
  const card = element("article", "result-card");
  const top = element("div", "card-topline");
  top.append(element("span", "evidence-dot"), element("time", "", recordDate(record) || "Date unavailable"));
  top.append(element("span", "", record.evidence_level || "Unknown evidence"));
  top.append(element("span", "", (record.source_types || []).join(" + ")));
  if ((record.change_history || []).length) top.append(element("span", "changed", "Recently changed"));
  card.append(top);
  const score = element("div", "score-badge");
  score.title = "Relevance priority score; not scientific quality";
  score.append(element("strong", "", Math.round(record.relevance_score || 0)), document.createTextNode("/100"));
  card.append(score);
  const heading = element("h3", "card-title");
  heading.append(link(record.url, record.title));
  card.append(heading);
  const summary = record.summary || record.abstract || record.description;
  if (summary) card.append(element("p", "summary", summary.length > 360 ? `${summary.slice(0, 357)}…` : summary));
  if ((record.watched_people || []).length) {
    card.append(element("p", "watched-person", `SRT author: ${record.watched_people.join(", ")}`));
  }
  appendTags(card, record);
  const ids = element("div", "identifier-row");
  if (record.doi) ids.append(link(`https://doi.org/${record.doi}`, `DOI ${record.doi}`));
  if (record.pmid) ids.append(link(`https://pubmed.ncbi.nlm.nih.gov/${record.pmid}/`, `PMID ${record.pmid}`));
  if (record.nct_id) ids.append(link(`https://clinicaltrials.gov/study/${record.nct_id}`, record.nct_id));
  const alternates = (record.alternate_urls || []).filter((url) => safeUrl(url) && url !== record.url);
  if (alternates.length) {
    const group = element("span", "alternate-links");
    group.append(document.createTextNode("Also:"));
    alternates.slice(0, 4).forEach((url, index) => group.append(link(url, `source ${index + 2}`)));
    ids.append(group);
  }
  if (ids.children.length) card.append(ids);
  card.append(renderDetails(record));
  return card;
}

function activeLabels() {
  const labels = [];
  if (state.preset !== "latest") labels.push(`View: ${state.preset.replace("-", " ")}`);
  if (controls.search.value) labels.push(`Search: ${controls.search.value}`);
  if (controls.dateFrom.value) labels.push(`From ${controls.dateFrom.value}`);
  if (controls.dateTo.value) labels.push(`To ${controls.dateTo.value}`);
  if (Number(controls.minScore.value)) labels.push(`Score ≥ ${controls.minScore.value}`);
  const names = {
    technology: "Technology", modality: "Modality", delivery: "Delivery",
    disease: "Disease", stage: "Stage",
    source: "Source", evidence: "Evidence", reviewStatus: "Review", trialStatus: "Trial",
    company: "Company", institution: "Institution", watchedPerson: "SRT author",
  };
  Object.entries(names).forEach(([key, name]) => {
    if (controls[key].value) labels.push(`${name}: ${controls[key].value}`);
  });
  return labels;
}

function render() {
  byId("result-count").textContent = state.filtered.length.toLocaleString();
  byId("score-output").textContent = controls.minScore.value;
  const chips = byId("active-filters");
  chips.replaceChildren(...activeLabels().map((text) => element("span", "filter-chip", text)));
  const listNode = byId("result-list");
  const visible = state.filtered.slice(0, state.visible);
  if (!visible.length) {
    const empty = element("div", "empty");
    empty.append(element("strong", "", "No records match this view."), element("p", "", "Try resetting filters or broadening the search."));
    listNode.replaceChildren(empty);
  } else {
    listNode.replaceChildren(...visible.map(renderCard));
  }
  const loadMore = byId("load-more");
  loadMore.hidden = visible.length >= state.filtered.length;
  loadMore.textContent = `Load ${Math.min(PAGE_SIZE, state.filtered.length - visible.length)} more`;
}

function optionValues(records, field, nested) {
  const values = records.flatMap((record) => {
    if (nested) return nested(record) || [];
    return record[field] || [];
  }).filter(Boolean);
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

function populateSelect(select, values) {
  const current = select.value;
  while (select.options.length > 1) select.remove(1);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
  select.value = values.includes(current) ? current : "";
}

function populateFacets(records) {
  populateSelect(controls.modality, optionValues(records, "modalities"));
  populateSelect(controls.delivery, optionValues(records, "delivery_systems"));
  populateSelect(controls.disease, optionValues(records, "disease_areas"));
  populateSelect(controls.stage, optionValues(records, "development_stages"));
  populateSelect(controls.source, optionValues(records, "source_types"));
  populateSelect(controls.evidence, [...new Set(records.map((record) => record.evidence_level).filter(Boolean))].sort());
  populateSelect(controls.company, optionValues(records, "companies"));
  populateSelect(controls.institution, optionValues(records, "institutions"));
  populateSelect(controls.watchedPerson, optionValues(records, "watched_people"));
  populateSelect(controls.trialStatus, optionValues(records, "", (record) => record.trial?.overall_status ? [record.trial.overall_status] : []));
}

function resetFilters() {
  Object.values(controls).forEach((control) => {
    if (control === controls.sort) control.value = "date-desc";
    else if (control === controls.minScore) control.value = "0";
    else control.value = "";
  });
  state.preset = "latest";
  state.visible = PAGE_SIZE;
  document.querySelectorAll(".preset").forEach((button) => button.classList.toggle("active", button.dataset.preset === "latest"));
  setDateWindow("30");
}

function download(format) {
  const records = state.filtered.map((record) => ({ ...record }));
  let content;
  let type;
  if (format === "json") {
    content = JSON.stringify(records, null, 2);
    type = "application/json";
  } else {
    const columns = ["date", "title", "url", "evidence_level", "modalities", "delivery_systems", "disease_areas", "development_stages", "watched_people", "relevance_score", "doi", "pmid", "nct_id"];
    const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const rows = records.map((record) => [
      recordDate(record), record.title, record.url, record.evidence_level,
      (record.modalities || []).join("; "), (record.delivery_systems || []).join("; "),
      (record.disease_areas || []).join("; "), (record.development_stages || []).join("; "),
      (record.watched_people || []).join("; "), record.relevance_score,
      record.doi, record.pmid, record.nct_id,
    ].map(escape).join(","));
    content = [columns.join(","), ...rows].join("\n");
    type = "text/csv";
  }
  const blobUrl = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = `rna-therapeutics-filtered.${format}`;
  anchor.click();
  URL.revokeObjectURL(blobUrl);
}

function bindEvents() {
  Object.values(controls).forEach((control) => {
    control.addEventListener(control === controls.search ? "input" : "change", () => {
      state.visible = PAGE_SIZE;
      if (control === controls.dateFrom || control === controls.dateTo) updateDateShortcutState();
      applyFilters();
    });
  });
  document.querySelectorAll("[data-date-days]").forEach((button) => {
    button.addEventListener("click", () => setDateWindow(button.dataset.dateDays));
  });
  document.querySelectorAll(".preset").forEach((button) => {
    button.addEventListener("click", () => {
      state.preset = button.dataset.preset;
      state.visible = PAGE_SIZE;
      document.querySelectorAll(".preset").forEach((item) => item.classList.toggle("active", item === button));
      applyFilters();
    });
  });
  byId("reset-filters").addEventListener("click", resetFilters);
  byId("load-more").addEventListener("click", () => {
    state.visible += PAGE_SIZE;
    render();
  });
  const downloadButton = byId("download-button");
  const options = byId("download-options");
  downloadButton.addEventListener("click", () => {
    options.hidden = !options.hidden;
    downloadButton.setAttribute("aria-expanded", String(!options.hidden));
  });
  options.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
    download(button.dataset.format);
    options.hidden = true;
    downloadButton.setAttribute("aria-expanded", "false");
  }));
}

async function load() {
  bindEvents();
  try {
    const [latestResponse, statisticsResponse, updatedResponse] = await Promise.all([
      fetch("./data/latest.json"),
      fetch("./data/statistics.json"),
      fetch("./data/last_updated.json"),
    ]);
    if (![latestResponse, statisticsResponse, updatedResponse].every((response) => response.ok)) throw new Error("One or more data files could not be loaded.");
    const [latest, statistics, updated] = await Promise.all([
      latestResponse.json(), statisticsResponse.json(), updatedResponse.json(),
    ]);
    state.records = latest;
    byId("total-count").textContent = Number(statistics.total_records || 0).toLocaleString();
    const time = byId("last-updated");
    time.textContent = updated.generated_at ? new Date(updated.generated_at).toLocaleString() : "unknown";
    time.dateTime = updated.generated_at || "";
    state.asOfDate = updated.generated_at?.slice(0, 10) || isoDate(new Date());
    setDateWindow("30");
    populateFacets(state.records);
    byId("loading").hidden = true;

    const fullResponse = await fetch("./data/records.min.json");
    if (!fullResponse.ok) throw new Error(`Full dataset HTTP ${fullResponse.status}`);
    state.records = await fullResponse.json();
    state.loadedFull = true;
    populateFacets(state.records);
    applyFilters();
  } catch (error) {
    byId("loading").hidden = true;
    const notice = byId("error");
    notice.hidden = false;
    notice.textContent = `The monitor data could not be loaded. ${error.message}`;
  }
}

load();

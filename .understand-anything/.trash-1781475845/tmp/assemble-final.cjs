const fs = require("fs");
const dir = process.argv[2];
const analyzedAt = process.argv[3];
const commit = process.argv[4];
const P = (f) => `${dir}/.understand-anything/intermediate/${f}`;

const g = JSON.parse(fs.readFileSync(P("assembled-graph.json"), "utf8"));
const ids = new Set(g.nodes.map((n) => n.id));
const fileTypes = new Set(["file","config","document","service","pipeline","table","schema","resource","endpoint"]);

// --- layers: unwrap, rename, synth ids, drop dangling ---
let layers = JSON.parse(fs.readFileSync(P("layers.json"), "utf8"));
if (!Array.isArray(layers) && Array.isArray(layers.layers)) layers = layers.layers;
const kebab = (s) => "layer:" + String(s||"layer").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
layers = layers.map((l) => {
  let nodeIds = l.nodeIds || l.nodes || [];
  nodeIds = nodeIds.map((x) => (typeof x === "string" ? x : x && x.id)).filter(Boolean);
  nodeIds = nodeIds.filter((id) => ids.has(id));
  return { id: l.id || kebab(l.name), name: l.name, description: l.description || "", nodeIds };
});

// --- tour: unwrap, rename, drop dangling, sort ---
let tour = JSON.parse(fs.readFileSync(P("tour.json"), "utf8"));
if (!Array.isArray(tour) && Array.isArray(tour.steps)) tour = tour.steps;
tour = tour.map((s) => {
  let nodeIds = s.nodeIds || s.nodesToInspect || [];
  nodeIds = nodeIds.map((x) => (typeof x === "string" ? x : x && x.id)).filter(Boolean).filter((id) => ids.has(id));
  const step = {
    order: s.order,
    title: s.title,
    description: s.description || s.whyItMatters || "",
    nodeIds,
  };
  if (s.languageLesson) step.languageLesson = s.languageLesson;
  return step;
});
tour.sort((a, b) => (a.order || 0) - (b.order || 0));

const graph = {
  version: "1.0.0",
  project: {
    name: "sdd-pipeline",
    languages: ["python", "markdown", "json", "yaml", "toml", "html", "powershell"],
    frameworks: ["Pydantic", "Typer", "sentence-transformers", "LangChain", "BeautifulSoup", "Textual", "pytest", "Docker"],
    description: g.project && g.project.description ? g.project.description : "Semantic search pipeline that converts Confluence-exported markdown into a vector-search index for Software Design Documents, plus an HTML to GitLab-Markdown converter.",
    analyzedAt,
    gitCommitHash: commit,
  },
  nodes: g.nodes,
  edges: g.edges,
  layers,
  tour,
};

fs.writeFileSync(P("assembled-graph.json"), JSON.stringify(graph, null, 2));
console.log("assembled:", graph.nodes.length, "nodes,", graph.edges.length, "edges,", layers.length, "layers,", tour.length, "tour steps");

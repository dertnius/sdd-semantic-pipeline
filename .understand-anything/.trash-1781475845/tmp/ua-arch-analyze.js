#!/usr/bin/env node
"use strict";
const fs = require("fs");

function main() {
  const inPath = process.argv[2];
  const outPath = process.argv[3];
  if (!inPath || !outPath) {
    console.error("usage: node ua-arch-analyze.js <input.json> <output.json>");
    process.exit(1);
  }
  const data = JSON.parse(fs.readFileSync(inPath, "utf8"));
  const fileNodes = data.fileNodes || [];
  const importEdges = data.importEdges || [];
  const allEdges = data.allEdges || [];

  const idToNode = new Map();
  for (const n of fileNodes) idToNode.set(n.id, n);

  // --- Common prefix of all filePaths ---
  const paths = fileNodes.map((n) => n.filePath || "");
  function commonPrefixDir(ps) {
    if (ps.length === 0) return "";
    const split = ps.map((p) => p.split("/"));
    const first = split[0];
    let prefix = [];
    for (let i = 0; i < first.length - 1; i++) {
      const seg = first[i];
      if (split.every((s) => s.length > i + 1 && s[i] === seg)) prefix.push(seg);
      else break;
    }
    return prefix.length ? prefix.join("/") + "/" : "";
  }
  const prefix = commonPrefixDir(paths);

  // --- A. Directory grouping ---
  const directoryGroups = {};
  const fileToGroup = {};
  for (const n of fileNodes) {
    let p = n.filePath || "";
    let rel = prefix && p.startsWith(prefix) ? p.slice(prefix.length) : p;
    const segs = rel.split("/");
    let group;
    if (segs.length > 1) group = segs[0];
    else group = "(root)";
    (directoryGroups[group] = directoryGroups[group] || []).push(n.id);
    fileToGroup[n.id] = group;
  }

  // --- B. Node type grouping ---
  const nodeTypeGroups = {};
  for (const n of fileNodes) {
    (nodeTypeGroups[n.type] = nodeTypeGroups[n.type] || []).push(n.id);
  }

  // --- C. Import adjacency: fan-in / fan-out ---
  const fileFanOut = {};
  const fileFanIn = {};
  for (const n of fileNodes) {
    fileFanOut[n.id] = 0;
    fileFanIn[n.id] = 0;
  }
  for (const e of importEdges) {
    if (fileFanOut[e.source] !== undefined) fileFanOut[e.source]++;
    if (fileFanIn[e.target] !== undefined) fileFanIn[e.target]++;
  }

  // --- D. Cross-category dependency analysis (allEdges) ---
  const crossMap = {}; // key fromType|toType|edgeType
  for (const e of allEdges) {
    const s = idToNode.get(e.source);
    const t = idToNode.get(e.target);
    if (!s || !t) continue;
    if (s.type === t.type) continue; // cross-category only
    const key = s.type + "|" + t.type + "|" + e.type;
    crossMap[key] = (crossMap[key] || 0) + 1;
  }
  const crossCategoryEdges = Object.entries(crossMap).map(([k, count]) => {
    const [fromType, toType, edgeType] = k.split("|");
    return { fromType, toType, edgeType, count };
  }).sort((a, b) => b.count - a.count);

  // --- E. Inter-group import frequency ---
  const interMap = {};
  for (const e of importEdges) {
    const g1 = fileToGroup[e.source];
    const g2 = fileToGroup[e.target];
    if (g1 === undefined || g2 === undefined || g1 === g2) continue;
    const key = g1 + "|" + g2;
    interMap[key] = (interMap[key] || 0) + 1;
  }
  const interGroupImports = Object.entries(interMap).map(([k, count]) => {
    const [from, to] = k.split("|");
    return { from, to, count };
  }).sort((a, b) => b.count - a.count);

  // --- F. Intra-group import density ---
  const intraGroupDensity = {};
  for (const g of Object.keys(directoryGroups)) {
    intraGroupDensity[g] = { internalEdges: 0, totalEdges: 0, density: 0 };
  }
  for (const e of importEdges) {
    const g1 = fileToGroup[e.source];
    const g2 = fileToGroup[e.target];
    if (g1 === g2 && g1 !== undefined) {
      intraGroupDensity[g1].internalEdges++;
      intraGroupDensity[g1].totalEdges++;
    } else {
      if (g1 !== undefined) intraGroupDensity[g1].totalEdges++;
      if (g2 !== undefined) intraGroupDensity[g2].totalEdges++;
    }
  }
  for (const g of Object.keys(intraGroupDensity)) {
    const d = intraGroupDensity[g];
    d.density = d.totalEdges ? +(d.internalEdges / d.totalEdges).toFixed(3) : 0;
  }

  // --- G. Directory pattern matching ---
  const dirPatterns = [
    [["routes", "api", "controllers", "endpoints", "handlers", "controller", "routers", "serializers", "blueprints"], "api"],
    [["services", "core", "lib", "domain", "logic", "composables", "signals", "mailers", "jobs", "channels", "internal"], "service"],
    [["models", "db", "data", "persistence", "repository", "entities", "migrations", "entity", "sql", "database"], "data"],
    [["components", "views", "pages", "ui", "layouts", "screens"], "ui"],
    [["middleware", "plugins", "interceptors", "guards"], "middleware"],
    [["utils", "helpers", "common", "shared", "tools", "templatetags", "pkg"], "utility"],
    [["config", "constants", "env", "settings", "management", "commands"], "config"],
    [["__tests__", "test", "tests", "spec", "specs"], "test"],
    [["types", "interfaces", "schemas", "contracts", "dtos", "dto", "request", "response"], "types"],
    [["hooks"], "hooks"],
    [["store", "state", "reducers", "actions", "slices"], "state"],
    [["assets", "static", "public"], "assets"],
    [["cmd", "bin"], "entry"],
    [["docs", "documentation", "wiki"], "documentation"],
    [["deploy", "deployment", "infra", "infrastructure", "k8s", "kubernetes", "helm", "charts", "terraform", "tf", "docker"], "infrastructure"],
    [[".github", ".gitlab", ".circleci"], "ci-cd"],
  ];
  function matchDir(name) {
    const lower = name.toLowerCase();
    for (const [keys, label] of dirPatterns) {
      if (keys.includes(lower)) return label;
    }
    return null;
  }
  const patternMatches = {};
  for (const g of Object.keys(directoryGroups)) {
    const m = matchDir(g);
    if (m) patternMatches[g] = m;
  }

  // --- H. Deployment topology ---
  const allPaths = fileNodes.map((n) => n.filePath || "");
  const infraFiles = [];
  let hasDockerfile = false, hasCompose = false, hasK8s = false, hasTerraform = false, hasCI = false;
  for (const p of allPaths) {
    const base = p.split("/").pop().toLowerCase();
    const lp = p.toLowerCase();
    if (base === "dockerfile" || base.startsWith("dockerfile.")) { hasDockerfile = true; infraFiles.push(p); }
    else if (base.startsWith("docker-compose")) { hasCompose = true; infraFiles.push(p); }
    else if (base.endsWith(".tf") || base.endsWith(".tfvars")) { hasTerraform = true; infraFiles.push(p); }
    else if (lp.includes("k8s/") || lp.includes("kubernetes/") || lp.includes("helm/")) { hasK8s = true; infraFiles.push(p); }
    else if (lp.includes(".github/workflows/") || base === ".gitlab-ci.yml" || base === "jenkinsfile") { hasCI = true; infraFiles.push(p); }
    else if (base === "devfile.yaml" || base === "environment.yml" || lp.includes(".devcontainer/")) { infraFiles.push(p); }
  }
  const deploymentTopology = { hasDockerfile, hasCompose, hasK8s, hasTerraform, hasCI, infraFiles };

  // --- I. Data pipeline ---
  const dataPipeline = { schemaFiles: [], migrationFiles: [], dataModelFiles: [], apiHandlerFiles: [] };
  for (const n of fileNodes) {
    const p = n.filePath || "";
    const lp = p.toLowerCase();
    const base = p.split("/").pop().toLowerCase();
    if (base.endsWith(".sql") || base.endsWith(".graphql") || base.endsWith(".gql") || base.endsWith(".proto") || base.endsWith(".prisma")) dataPipeline.schemaFiles.push(p);
    if (lp.includes("migration")) dataPipeline.migrationFiles.push(p);
    if (lp.includes("model") || (n.tags || []).includes("data-model")) dataPipeline.dataModelFiles.push(p);
    if ((n.tags || []).includes("api-handler") || lp.includes("/routes/") || lp.includes("/controllers/")) dataPipeline.apiHandlerFiles.push(p);
  }

  // --- J. Documentation coverage ---
  const groupHasDocs = {};
  for (const n of fileNodes) {
    if (n.type === "document" || (n.name || "").toLowerCase().endsWith(".md")) {
      groupHasDocs[fileToGroup[n.id]] = true;
    }
  }
  const allGroups = Object.keys(directoryGroups);
  const groupsWithDocs = allGroups.filter((g) => groupHasDocs[g]);
  const undocumentedGroups = allGroups.filter((g) => !groupHasDocs[g]);
  const docCoverage = {
    groupsWithDocs: groupsWithDocs.length,
    totalGroups: allGroups.length,
    coverageRatio: allGroups.length ? +(groupsWithDocs.length / allGroups.length).toFixed(3) : 0,
    undocumentedGroups,
  };

  // --- K. Dependency direction ---
  const pairNet = {};
  for (const { from, to, count } of interGroupImports) {
    const key = [from, to].sort().join("||");
    if (!pairNet[key]) pairNet[key] = {};
    pairNet[key][from + ">" + to] = count;
  }
  const dependencyDirection = [];
  for (const { from, to, count } of interGroupImports) {
    const rev = interGroupImports.find((x) => x.from === to && x.to === from);
    const revCount = rev ? rev.count : 0;
    if (count > revCount) {
      if (!dependencyDirection.some((d) => d.dependent === from && d.dependsOn === to))
        dependencyDirection.push({ dependent: from, dependsOn: to });
    }
  }

  // --- Stats ---
  const filesPerGroup = {};
  for (const g of Object.keys(directoryGroups)) filesPerGroup[g] = directoryGroups[g].length;
  const nodeTypeCounts = {};
  for (const t of Object.keys(nodeTypeGroups)) nodeTypeCounts[t] = nodeTypeGroups[t].length;

  const result = {
    scriptCompleted: true,
    commonPrefix: prefix,
    directoryGroups,
    nodeTypeGroups,
    crossCategoryEdges,
    interGroupImports,
    intraGroupDensity,
    patternMatches,
    deploymentTopology,
    dataPipeline,
    docCoverage,
    dependencyDirection,
    fileStats: {
      totalFileNodes: fileNodes.length,
      filesPerGroup,
      nodeTypeCounts,
    },
    fileFanIn,
    fileFanOut,
  };
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  console.log("OK wrote", outPath);
}

try {
  main();
} catch (e) {
  console.error("FATAL:", e && e.stack ? e.stack : e);
  process.exit(1);
}

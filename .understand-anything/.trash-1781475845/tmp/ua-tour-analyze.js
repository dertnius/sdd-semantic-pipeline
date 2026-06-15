#!/usr/bin/env node
"use strict";

const fs = require("fs");

function main() {
  const inPath = process.argv[2];
  const outPath = process.argv[3];
  if (!inPath || !outPath) {
    console.error("Usage: node ua-tour-analyze.js <input.json> <output.json>");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(inPath, "utf8"));
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  const layers = data.layers || [];

  const byId = new Map();
  for (const n of nodes) byId.set(n.id, n);

  // Fan-in / fan-out
  const fanIn = new Map();
  const fanOut = new Map();
  for (const n of nodes) {
    fanIn.set(n.id, 0);
    fanOut.set(n.id, 0);
  }
  // adjacency for traversal-edge types
  const traversalOut = new Map(); // imports/calls forward
  for (const n of nodes) traversalOut.set(n.id, []);

  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    fanOut.set(e.source, fanOut.get(e.source) + 1);
    fanIn.set(e.target, fanIn.get(e.target) + 1);
    if (e.type === "imports" || e.type === "calls") {
      traversalOut.get(e.source).push(e.target);
    }
  }

  const nameOf = (id) => (byId.get(id) ? byId.get(id).name : id);
  const sumOf = (id) => (byId.get(id) ? byId.get(id).summary : "");
  const typeOf = (id) => (byId.get(id) ? byId.get(id).type : "");

  // A. Fan-in ranking
  const fanInRanking = [...fanIn.entries()]
    .map(([id, v]) => ({ id, fanIn: v, name: nameOf(id) }))
    .sort((a, b) => b.fanIn - a.fanIn)
    .slice(0, 20);

  // B. Fan-out ranking
  const fanOutRanking = [...fanOut.entries()]
    .map(([id, v]) => ({ id, fanOut: v, name: nameOf(id) }))
    .sort((a, b) => b.fanOut - a.fanOut)
    .slice(0, 20);

  // For entry-point scoring: top 10% fan-out, bottom 25% fan-in
  const fanOutVals = [...fanOut.values()].sort((a, b) => b - a);
  const top10FanOut = fanOutVals.length
    ? fanOutVals[Math.floor(fanOutVals.length * 0.1)]
    : 0;
  const fanInValsAsc = [...fanIn.values()].sort((a, b) => a - b);
  const bottom25FanIn = fanInValsAsc.length
    ? fanInValsAsc[Math.floor(fanInValsAsc.length * 0.25)]
    : 0;

  const ENTRY_NAMES = new Set([
    "index.ts", "index.js", "main.ts", "main.js", "app.ts", "app.js",
    "server.ts", "server.js", "mod.rs", "main.go", "main.py", "main.rs",
    "manage.py", "app.py", "wsgi.py", "asgi.py", "run.py", "__main__.py",
    "Application.java", "Main.java", "Program.cs", "config.ru", "index.php",
    "App.swift", "Application.kt", "main.cpp", "main.c", "cli.py",
  ]);

  function depth(filePath) {
    if (!filePath) return 99;
    return filePath.split("/").length - 1;
  }

  const entryScores = [];
  for (const n of nodes) {
    let score = 0;
    if (n.type === "document") {
      const fp = n.filePath || "";
      const isRoot = !fp.includes("/");
      if (n.name === "README.md" && isRoot) score += 5;
      else if (fp.endsWith(".md") && isRoot) score += 2;
    } else if (n.type === "file" || n.type === "config") {
      if (ENTRY_NAMES.has(n.name)) score += 3;
      if (depth(n.filePath) <= 2) score += 1;
      if (fanOut.get(n.id) >= top10FanOut && top10FanOut > 0) score += 1;
      if (fanIn.get(n.id) <= bottom25FanIn) score += 1;
    }
    if (score > 0) {
      entryScores.push({ id: n.id, score, name: n.name, summary: n.summary });
    }
  }
  entryScores.sort((a, b) => b.score - a.score);
  const entryPointCandidates = entryScores.slice(0, 5);

  // D. BFS from top code entry point
  const codeEntry = entryScores.find(
    (e) => typeOf(e.id) === "file" || typeOf(e.id) === "config"
  );
  let bfsTraversal = { startNode: null, order: [], depthMap: {}, byDepth: {} };
  if (codeEntry) {
    const start = codeEntry.id;
    const visited = new Set([start]);
    const order = [start];
    const depthMap = { [start]: 0 };
    const queue = [start];
    while (queue.length) {
      const cur = queue.shift();
      const d = depthMap[cur];
      for (const nxt of traversalOut.get(cur) || []) {
        if (!visited.has(nxt)) {
          visited.add(nxt);
          depthMap[nxt] = d + 1;
          order.push(nxt);
          queue.push(nxt);
        }
      }
    }
    const byDepth = {};
    for (const id of order) {
      const d = depthMap[id];
      (byDepth[d] = byDepth[d] || []).push(id);
    }
    bfsTraversal = { startNode: start, order, depthMap, byDepth };
  }

  // E. Non-code inventory
  const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
  for (const n of nodes) {
    const rec = { id: n.id, name: n.name, type: n.type, summary: n.summary };
    if (n.type === "document") nonCodeFiles.documentation.push(rec);
    else if (["service", "pipeline", "resource"].includes(n.type))
      nonCodeFiles.infrastructure.push(rec);
    else if (["table", "schema", "endpoint"].includes(n.type))
      nonCodeFiles.data.push(rec);
    else if (n.type === "config") nonCodeFiles.config.push(rec);
  }

  // F. Clusters from bidirectional edges
  const pairKey = (a, b) => (a < b ? a + "|" + b : b + "|" + a);
  const edgeSet = new Set();
  const undirectedCount = new Map();
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    edgeSet.add(e.source + ">" + e.target);
    const k = pairKey(e.source, e.target);
    undirectedCount.set(k, (undirectedCount.get(k) || 0) + 1);
  }
  // seed clusters from bidirectional pairs
  const clusters = [];
  const seedPairs = [];
  for (const e of edges) {
    if (e.type !== "imports" && e.type !== "calls") continue;
    if (edgeSet.has(e.target + ">" + e.source) && e.source < e.target) {
      seedPairs.push([e.source, e.target]);
    }
  }
  const neighbors = new Map();
  for (const n of nodes) neighbors.set(n.id, new Set());
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    neighbors.get(e.source).add(e.target);
    neighbors.get(e.target).add(e.source);
  }
  const usedSig = new Set();
  for (const [a, b] of seedPairs) {
    const members = new Set([a, b]);
    // expand: add nodes connecting to 2+ members
    for (const n of nodes) {
      if (members.has(n.id) || members.size >= 5) continue;
      let conn = 0;
      for (const m of members) if (neighbors.get(n.id).has(m)) conn++;
      if (conn >= 2) members.add(n.id);
    }
    const arr = [...members].sort();
    const sig = arr.join("|");
    if (usedSig.has(sig)) continue;
    usedSig.add(sig);
    let edgeCount = 0;
    for (const x of arr)
      for (const y of arr)
        if (x !== y && edgeSet.has(x + ">" + y)) edgeCount++;
    clusters.push({ nodes: arr, edgeCount });
  }
  clusters.sort((a, b) => b.edgeCount - a.edgeCount);
  const topClusters = clusters.slice(0, 10);

  // G. Layers
  const layerOut = {
    count: layers.length,
    list: layers.map((l) => ({ id: l.id, name: l.name, description: l.description })),
  };

  // H. Node summary index
  const nodeSummaryIndex = {};
  for (const n of nodes) {
    nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary };
  }

  const result = {
    scriptCompleted: true,
    entryPointCandidates,
    fanInRanking,
    fanOutRanking,
    bfsTraversal,
    nonCodeFiles,
    clusters: topClusters,
    layers: layerOut,
    nodeSummaryIndex,
    totalNodes: nodes.length,
    totalEdges: edges.length,
  };

  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  process.exit(0);
}

try {
  main();
} catch (err) {
  console.error("Fatal:", err && err.stack ? err.stack : err);
  process.exit(1);
}

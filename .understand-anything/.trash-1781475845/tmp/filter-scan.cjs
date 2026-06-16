const fs = require("fs");
const p = process.argv[2];
const s = JSON.parse(fs.readFileSync(p, "utf8"));
const drop = (path) =>
  path.startsWith(".tmp_pytest/") || path.startsWith(".understand-anything/");

const before = (s.files || []).length;
s.files = (s.files || []).filter((f) => !drop(f.path));
const removed = before - s.files.length;

// importMap is an object keyed by path -> string[] of imported paths
if (s.importMap && !Array.isArray(s.importMap)) {
  const next = {};
  for (const [k, v] of Object.entries(s.importMap)) {
    if (drop(k)) continue;
    next[k] = Array.isArray(v) ? v.filter((dep) => !drop(dep)) : v;
  }
  s.importMap = next;
}

s.totalFiles = s.files.length;
s.filteredByIgnore = (s.filteredByIgnore || 0) + removed;
// strip the >100-files advisory the scanner appended to the description
s.description = s.description.replace(/\s*Note: this project has over 100 source files;[^.]*\./, "").trim();

fs.writeFileSync(p, JSON.stringify(s, null, 2));
console.log("removed:", removed, "-> totalFiles:", s.totalFiles);

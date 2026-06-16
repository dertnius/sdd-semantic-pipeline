import { build, context } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname } from "node:path";

const production = process.argv.includes("--production");
const watch = process.argv.includes("--watch");

/**
 * Copy the offline webview vendor assets out of node_modules into media/vendor/
 * so the sandboxed webview can load them via asWebviewUri (CSP blocks CDNs).
 */
async function copyVendor() {
  const jobs = [
    ["node_modules/chart.js/dist/chart.umd.js", "media/vendor/chart.umd.min.js"],
    ["node_modules/gridstack/dist/gridstack-all.js", "media/vendor/gridstack-all.js"],
    ["node_modules/gridstack/dist/gridstack.min.css", "media/vendor/gridstack.min.css"],
  ];
  for (const [from, to] of jobs) {
    if (!existsSync(from)) {
      console.warn(`[esbuild] vendor source missing: ${from} (run npm install)`);
      continue;
    }
    await mkdir(dirname(to), { recursive: true });
    await copyFile(from, to);
    console.log(`[esbuild] vendor: ${from} -> ${to}`);
  }
}

const options = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  platform: "node",
  format: "cjs",
  target: "node18",
  // The host bundles js-tiktoken + its o200k ranks. 'vscode' is provided at runtime.
  external: ["vscode"],
  sourcemap: !production,
  minify: production,
  logLevel: "info",
};

await copyVendor();

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("[esbuild] watching...");
} else {
  await build(options);
  console.log("[esbuild] build complete");
}

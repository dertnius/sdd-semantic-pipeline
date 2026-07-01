> Companion to [grounding-how-to.md](grounding-how-to.md). Two pieces sit behind the Grounding
> step — the **search engine** (finds the info) and the **connector / MCP** (how the AI reaches
> it). Here are your alternatives for each, in plain words. Bold words are in the [glossary](glossary.md).
# Grounding your SDD pipeline: the search engine vs. the connector

## 1. The two layers

Think of it as a **library** and a **doorway**. The **search engine** is the library — it holds your code and docs and finds the most relevant bits when asked. The **connector** is the doorway — how the AI worker actually walks in and asks the question. The nice part: these are independent. You can swap the search engine without touching the connector, and vice versa.

---

## 2. Search-engine alternatives (finds the info)

Your repo already has a working engine (embeddings + vector store + keyword search + hybrid ranking). It is **fine at your scale** — don't replace it to chase benchmarks. The key realization: **GitHub Copilot already searches your *code* automatically** (the `#codebase` feature), so a separate engine's real job is your **docs corpus** (converted Confluence/SharePoint, ADRs, SADs) that Copilot doesn't index.

| Option | What it is (1 line) | When to pick it |
|---|---|---|
| **REUSE — your current pipeline** | Local/Azure embeddings + in-memory/Chroma store + keyword + hybrid ranking, already built. | **Default. Keep it — especially for the DOCS corpus, its unique value.** |
| SIMPLEST UPGRADE — Postgres + pgvector | Adds vector search to a normal SQL database; one durable index instead of a rewritten JSON file. | You want a sturdier, queryable store with almost no new infrastructure. |
| SIMPLEST UPGRADE — add a reranker | A cheap second pass that re-sorts your top results by relevance before the AI sees them. | The single biggest *quality* win for the least effort; works with any store. |
| MANAGED — Azure AI Search | Fully hosted search (keyword + vector) inside your Azure tenant; connectors for SharePoint. | You'd rather stop running a pipeline and you're already on Azure. Adds cloud lock-in. |
| MANAGED — Qdrant / OpenSearch | The standard self-host picks if you outgrow local files (millions of vectors, many users). | Only if you scale well past today's corpus. |
| NATIVE — Copilot `#codebase` | Copilot builds its **own** semantic index of your **code** and searches it by meaning. | **For finding relevant CODE, you likely need nothing extra.** (On GitLab repos it builds a *local* index — a few minutes, kept fresh in the background.) |
| NATIVE — GitLab Duo semantic code search | GitLab's own built-in semantic search over your repo, exposed as an MCP tool. | A code-search baseline if you license Duo. (Beta, feature-flagged — verify before relying on it.) |

**Bottom line:** your engine owns the **docs**; Copilot (and optionally Duo) already own the **code**.

---

## 3. Connector alternatives (how the AI reaches the engine)

**MCP is the strong default.** It's an open standard (a "USB port for AI" — write the server once, any AI tool that speaks MCP plugs in). You **already have it** (`sdd-semantic`), and it's the *only* option that works with **both** GitHub Copilot **and** GitLab Duo from a single build. GitHub even retired its old proprietary "Copilot Extensions" in favor of MCP.

| Option | What it is | Portability vs. simplicity |
|---|---|---|
| **MCP** (what you have) | Open-standard doorway; one server, many AI clients. | **Most portable** — works with Copilot AND Duo. Medium setup, but yours is already built. **Recommended.** |
| Copilot `#codebase` / Duo native | The AI's built-in code search — no connector at all. | Simplest possible (zero setup), but each is locked to its own tool and only covers **code**, not your curated docs. |
| Plain CLI / REST call | The AI just runs your `sdd-pipeline search` command or hits a URL. | Very portable, very simple, no lock-in. Trade-off: you must *tell* the AI it exists. **Great for CI / scripted grounding.** |
| Direct tool-calling / frameworks (LangChain etc.) | Define the search as a tool inside one agent's own code. | Simple for one app, but you re-code it per tool — no free portability. Only if you build your own agent. |
| ~~Copilot Extensions / GitHub Apps~~ | The old GitHub-only add-on path. | **Avoid — deprecated and retired in favor of MCP.** |

---

## 4. Recommendation for you

Given **GitLab + Copilot + your existing pipeline**:

1. **Keep your current search engine and keep MCP.** Both are already built, both work with your harness, and both are fine at your scale. No change needed to start.
2. **Let Copilot's `#codebase` handle CODE grounding.** Point your own engine at what it's uniquely good for: the **docs/ADR/SAD corpus**. Don't build a second code index.
3. **For CI or scripted grounding steps, just call the CLI** (`sdd-pipeline search --hybrid …`) — no protocol needed.
4. **Only swap pieces when you hit a real limit:**
   - *Store* → move to **pgvector** when the in-memory JSON file gets slow or unwieldy.
   - *Quality* → add a **reranker** if results feel "close but not quite."
   - *Scale/ops* → **Qdrant/OpenSearch** (self-host) or **Azure AI Search** (managed) only if the corpus grows into the millions of vectors or you want to stop running infrastructure.

**One line:** *Two layers — the search engine finds the info, the connector hands it over. Yours are both fine; the free win is remembering Copilot already indexes your code, so your engine just needs to own the docs — and MCP stays the doorway because it's the only one both Copilot and GitLab Duo already open.*
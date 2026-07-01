# Installing it — a simple checklist

What "setting it up" looks like, step by step. The exact commands depend on the final tool;
this is the **shape** so you know what to expect. Bold words are in the [glossary](glossary.md).

## Before you start (once)

- A computer with the basics installed (the runtime + a command-line tool).
- **Access keys** for the AI service — kept private (see step 3).

## The steps

1. **Get the package.** Install it with one command, like installing an app.
   *Example:* `pip install sdd-agents`

2. **Turn on only the parts you need.** Optional add-ons come as "extras" — e.g. safety
   checks, evaluation, cloud AI. Install just what you use.
   *Example:* `pip install "sdd-agents[guardrails,eval]"`

3. **Add your settings and secret keys.** Put ordinary settings in a config file; put
   **secret keys in your environment, never in the file, never shared**.
   *Example:* copy `.env.example` to `.env` and fill in your keys.

4. **Register the workers and recipes.** The tool finds the **agents** and **skills** from a
   folder (each described by a small file) — nothing to hand-wire.

5. **Run the check (the "doctor").** One command confirms everything is ready: the AI is
   reachable, the safety settings are valid, and **every AI worker has passed its tests**.
   *Example:* `sdd-agents doctor`

6. **Run your first job.** Point it at a request and watch it flow through the line, pausing
   for your approvals.

## If the check fails

The **doctor** tells you exactly what's missing — a key, a dependency, or a worker that
hasn't passed its tests. Fix that one thing and run it again. It won't let you run a broken
setup.

## Keeping it up to date

Each version is **labelled**. If you built something with an older version, the tool **warns
you** so your results stay consistent.

---

### What's actually inside "the package"

So you know what you installed:

- the **assembly line** (the plain software that moves work along),
- the **AI workers** (agents) and their **recipes** (skills / micro-skills),
- the **settings**: which AI brain each worker uses, the safety rules, and which approvals are required,
- the **safety checks** and the **tests** each worker must pass.

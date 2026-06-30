---
name: sample-skill
description: >-
  A minimal, spec-valid Agent Skill used as the green fixture for the
  validate-skills component's selftest. It exists only so the parent
  pipeline can run the real component against a known-good SKILL.md and
  assert it passes. Not a usable skill — replace with your own.
---

# sample-skill

This is a fixture. The `validate-skills` component validates the YAML
frontmatter above (a `name` equal to this directory and matching the Agent
Skills grammar, and a non-empty `description` of at most 1024 characters);
the body is not inspected.

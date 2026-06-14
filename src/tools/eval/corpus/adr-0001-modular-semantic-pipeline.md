---
title: "ADR-0001: Adopt a Modular 7-Stage Semantic Pipeline"
status: "Proposed"
date: "2026-06-06"
authors: "Pipeline Maintainers, Platform Engineering, Documentation Engineering"
tags: ["architecture", "decision", "semantic-search", "python"]
supersedes: ""
superseded_by: ""
---

## Status

**Proposed**

## Context

The project must transform Confluence-derived documentation into a searchable semantic index with reproducible behavior, testability, and clear operational boundaries. The system has two related but distinct flows: indexing and search over markdown content, and HTML-to-markdown conversion for ingestion preparation. The team needs deterministic preprocessing and chunk construction, while preserving flexibility at embedding time for local and cloud providers. Additional constraints include minimizing cross-module coupling, keeping external service integrations isolated, enabling fast unit tests without heavyweight dependencies, and retaining provenance and metadata needed for reliable retrieval and downstream exports.

## Decision

Adopt and preserve a modular 7-stage pipeline architecture with strict module boundaries and protocol-driven integration points. The indexing and search path will remain decomposed into dedicated modules for AST parsing, structural modeling, semantic enrichment, chunking, embeddings, and vector storage, orchestrated by a central pipeline layer with lazy dependency wiring. The HTML-to-markdown converter remains an independent flow in the same package, separate from vector indexing logic. Embedding providers remain pluggable behind a shared embedder protocol, while ChromaDB access remains isolated to the vector-store module.

This decision is selected to maximize correctness, maintainability, and substitution safety: deterministic stages are unit-testable, service-heavy stages are isolated, and provider swaps do not force cross-cutting refactors.

## Consequences

### Positive

- **POS-001**: Architectural boundaries reduce accidental coupling and clarify ownership of pandoc, embedding, and vector-store responsibilities
- **POS-002**: Deterministic structural, enrichment, and chunking stages improve test reliability and speed by avoiding external-service dependency in default test paths
- **POS-003**: Embedder protocol abstraction enables local and Azure provider substitution without changing orchestration or retrieval interfaces
- **POS-004**: Pipeline orchestration with lazy initialization supports dependency injection and lowers initialization side effects in unit tests
- **POS-005**: Separation of conversion flow from indexing flow keeps concerns focused and allows independent evolution of ingestion-prep and retrieval features

### Negative

- **NEG-001**: More modules and explicit boundaries increase coordination overhead for cross-cutting features
- **NEG-002**: Strict separation can require additional interface work when introducing features spanning deterministic and service-backed stages
- **NEG-003**: Pluggable provider support introduces provenance validation and compatibility checks that add implementation complexity
- **NEG-004**: Maintaining compatibility contracts across modules can slow rapid prototyping compared to a monolithic implementation

## Alternatives Considered

### Monolithic End-to-End Pipeline Module

- **ALT-001**: **Description**: Implement parsing, enrichment, chunking, embedding, and storage in one tightly coupled module
- **ALT-002**: **Rejection Reason**: Rejected because it increases regression risk, weakens test isolation, and makes provider substitution and boundary enforcement difficult

### Managed External Search Service as Primary Architecture

- **ALT-003**: **Description**: Move core retrieval and indexing logic to an external managed platform and keep this project as a thin adapter
- **ALT-004**: **Rejection Reason**: Rejected because it reduces local reproducibility, limits deterministic stage control, and increases dependency on vendor-specific runtime behavior

### Keyword-First Retrieval Without Embeddings

- **ALT-005**: **Description**: Use lexical-only indexing and ranking without semantic embeddings
- **ALT-006**: **Rejection Reason**: Rejected because it underperforms for semantic intent queries and does not meet project goals for concept-level retrieval over SDD content

### Do Nothing (No Formalized Architecture Decision)

- **ALT-007**: **Description**: Continue implementation without an explicit architecture ADR and enforce boundaries informally
- **ALT-008**: **Rejection Reason**: Rejected because undocumented decisions degrade onboarding, increase drift risk, and make future superseding decisions harder to evaluate

## Implementation Notes

- **IMP-001**: Keep boundary enforcement explicit in code reviews: only the AST parser invokes pandoc, only embeddings loads embedding backends, and only vector_store touches ChromaDB
- **IMP-002**: Preserve deterministic behavior in structural, enrichment, and chunking modules; mark tests requiring pandoc or model downloads as slow
- **IMP-003**: Continue recording index provenance (provider, model, dimension) and enforce compatibility checks before query execution
- **IMP-004**: For new embedding providers, implement the embedder protocol first, then integrate through pipeline wiring without bypassing module boundaries
- **IMP-005**: Re-evaluate this ADR when introducing major retrieval changes such as re-ranking layers, hybrid retrieval, or non-Chroma storage backends

## References

- **REF-001**: [README.md](../../README.md)
- **REF-002**: [CLAUDE.md](../../CLAUDE.md)
- **REF-003**: [src/sdd_pipeline/pipeline.py](../../src/sdd_pipeline/pipeline.py)
- **REF-004**: [src/sdd_pipeline/embeddings.py](../../src/sdd_pipeline/embeddings.py)
- **REF-005**: [src/sdd_pipeline/vector_store.py](../../src/sdd_pipeline/vector_store.py)
- **REF-006**: [src/sdd_pipeline/models.py](../../src/sdd_pipeline/models.py)

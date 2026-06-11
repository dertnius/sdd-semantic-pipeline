"""
sdd_pipeline — Semantic search pipeline for Confluence SDD documents.

Stages
------
1. Confluence → Markdown        (external; handled by Confluence/pandoc export)
2. Pandoc JSON AST              ast_parser.generate_ast()
3+4. Structural model           structural.build_structural_model()
5. Semantic enrichment          enrichment.enrich_document()
6. Semantic chunking            chunking.chunk_document()
7. Embed + index                embeddings.make_embedder + vector_store.make_vector_store

Quick start
-----------
>>> from sdd_pipeline import SemanticPipeline, PipelineConfig
>>> pipeline = SemanticPipeline(PipelineConfig(embedding_model="all-MiniLM-L6-v2"))
>>> pipeline.index_directory(Path("docs/"))
>>> results = pipeline.search("How does token refresh work?")
"""

from .config import PipelineConfig
from .models import ContentType, DocumentModel, SectionType, SemanticChunk
from .pipeline import SemanticPipeline

__version__ = "0.1.0"
__all__ = [
    "ContentType",
    "DocumentModel",
    "PipelineConfig",
    "SectionType",
    "SemanticChunk",
    "SemanticPipeline",
]

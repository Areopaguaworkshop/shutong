"""Chat Pipeline — deterministic retrieval + LLM generation + memory.

Matches ``.agent/pipeline/chat_mode.yaml``.

Flow: receive prompt → deterministic retrieval → assemble context →
      call LLM → quality gate → integrity check → save memory → output response.

Supports staged execution with checkpoints for human-in-the-loop review.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    PipelineCheckpoint,
    PipelineResume,
    PipelineStage,
    QualityReport,
    SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

# ── Staged Pipeline ───────────────────────────────────────────────────


class StagedChatPipeline:
    """Chat pipeline with configurable checkpoints between stages.

    Each stage is a callable that receives accumulated state and returns
    updated state. Stages marked ``checkpoint=True`` pause the pipeline
    and return a :class:`PipelineCheckpoint` for the caller to review.
    The caller can then resume with a :class:`PipelineResume`.
    """

    STAGES: List[PipelineStage] = [
        PipelineStage(name="load_corpus", checkpoint=False, description="Load and index the corpus"),
        PipelineStage(name="plan_query", checkpoint=False, description="Plan the query from user input"),
        PipelineStage(name="clarify", checkpoint=True, description="Resolve ambiguity before retrieval"),
        PipelineStage(name="delegate_code", checkpoint=False, description="Delegate code-related instructions to code subagent"),
        PipelineStage(name="retrieve", checkpoint=True, description="Retrieve and rank evidence"),
        PipelineStage(name="generate", checkpoint=True, description="Generate answer from evidence"),
        PipelineStage(name="quality_gate", checkpoint=False, description="Run deterministic quality checks"),
        PipelineStage(name="integrity", checkpoint=False, description="Verify Merkle integrity and citations"),
        PipelineStage(name="save_memory", checkpoint=False, description="Persist conversation memory"),
    ]

    def __init__(
        self,
        corpus_root: str = "corpus",
        llm_model: str = "ollama/qwen3",
        schema_version: str = SCHEMA_VERSION,
        pipeline_dir: Optional[str] = None,
    ) -> None:
        self.corpus_root = corpus_root
        self.llm_model = llm_model
        self.schema_version = schema_version
        self.pipeline_dir = pipeline_dir or os.path.join(corpus_root, ".shutong", "pipelines")

    # ── Full run (no checkpoints) ────────────────────────────────────

    def chat(self, prompt: str, thread_id: str = "default") -> Dict[str, Any]:
        """Run the full pipeline, skipping all checkpoints. Backward-compatible with ChatPipeline."""
        state: Dict[str, Any] = {"prompt": prompt, "thread_id": thread_id}
        for stage in self.STAGES:
            state = self._run_stage(stage, state)
            if state.get("status") in ("no_corpus", "llm_error", "needs_clarification", "needs_checkpoint"):
                # Checkpoints that aren't being used fall through;
                # needs_clarification and no_corpus are genuine early exits.
                if stage.name == "clarify" and state.get("status") == "needs_checkpoint":
                    # Auto-resolve clarification checkpoint
                    state["status"] = "ok"
                    state = self._resolve_clarification(state, {})
                    state.pop("checkpoint", None)
                    continue
                if stage.name == "retrieve" and state.get("status") == "needs_checkpoint":
                    # Auto-resolve retrieval checkpoint — proceed with found evidence
                    state["status"] = "ok"
                    state.pop("checkpoint", None)
                    continue
                if stage.name == "generate" and state.get("status") == "needs_checkpoint":
                    # Auto-resolve generation checkpoint — accept the answer
                    state["status"] = "ok"
                    state.pop("checkpoint", None)
                    continue
                return state
        return state

    # ── Staged run (with checkpoints) ─────────────────────────────────

    def chat_staged(
        self,
        prompt: str,
        thread_id: str = "default",
        resume_from: Optional[PipelineResume] = None,
    ) -> Tuple[Dict[str, Any], Optional[PipelineCheckpoint]]:
        """Run the pipeline stage-by-stage, pausing at checkpoints.

        Returns (result, checkpoint). If checkpoint is not None, the caller
        should present it to the user and resume with a PipelineResume.

        If resume_from is provided, loads saved pipeline state and resumes
        from the checkpoint stage.
        """
        if resume_from:
            state = self._load_pipeline(resume_from.pipeline_id)
            if not state:
                return {"status": "error", "message": f"Pipeline {resume_from.pipeline_id} not found or expired."}, None

            if resume_from.user_choice == "abort":
                self._delete_pipeline(resume_from.pipeline_id)
                return {"status": "aborted", "pipeline_id": resume_from.pipeline_id}, None

            # Apply user's choice to the checkpoint state
            state = self._apply_checkpoint_choice(state, resume_from)
            state["status"] = "ok"
            start_index = state.get("checkpoint_stage_index", 0) + 1
        else:
            state: Dict[str, Any] = {"prompt": prompt, "thread_id": thread_id}
            start_index = 0

        for i in range(start_index, len(self.STAGES)):
            stage = self.STAGES[i]
            state = self._run_stage(stage, state)

            if state.get("status") in ("no_corpus", "llm_error", "error"):
                return state, None

            if stage.checkpoint and state.get("status") != "needs_clarification":
                # Save state and return checkpoint
                pipeline_id = str(uuid.uuid4())[:8]
                state["pipeline_id"] = pipeline_id
                state["checkpoint_stage_index"] = i
                checkpoint = PipelineCheckpoint(
                    pipeline_id=pipeline_id,
                    stage_name=stage.name,
                    stage_index=i,
                    intermediate_result=self._extract_checkpoint_result(stage.name, state),
                    question=self._checkpoint_question(stage.name, state),
                    options=["proceed", "refine", "abort"],
                )
                self._save_pipeline(pipeline_id, state)
                return state, checkpoint

            # Auto-resolve clarification early exit
            if state.get("status") == "needs_clarification":
                return state, None

        # Pipeline completed successfully
        if "pipeline_id" in state:
            self._delete_pipeline(state["pipeline_id"])
        return state, None

    # ── Stage implementations ──────────────────────────────────────────

    def _run_stage(self, stage: PipelineStage, state: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch to the appropriate stage handler."""
        handler = {
            "load_corpus": self._stage_load_corpus,
            "plan_query": self._stage_plan_query,
            "clarify": self._stage_clarify,
            "delegate_code": self._stage_delegate_code,
            "retrieve": self._stage_retrieve,
            "generate": self._stage_generate,
            "quality_gate": self._stage_quality_gate,
            "integrity": self._stage_integrity,
            "save_memory": self._stage_save_memory,
        }.get(stage.name)
        if handler is None:
            logger.warning("Unknown pipeline stage: %s", stage.name)
            return state
        return handler(state)

    def _stage_load_corpus(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .corpus_loader import CorpusLoader
        from .indexing import IndexingAgent

        loader = CorpusLoader(self.corpus_root)
        loader.load()
        indexer = IndexingAgent(self.schema_version)
        index_output = indexer.run(loader.all_nodes)

        state["loader"] = loader
        state["index_output"] = index_output
        if not loader.all_nodes:
            state["corpus_empty"] = True
            state["message"] = "No ingested documents found. Continuing without corpus evidence."
        return state

    def _stage_plan_query(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .query_planner import QueryPlanner

        planner = QueryPlanner(self.schema_version)
        query_plan = planner.plan(
            state["prompt"],
            csl_registry=state["loader"].csl_registry,
        )
        state["query_plan"] = query_plan
        return state

    def _stage_clarify(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .clarification import ClarificationAgent

        clarifier = ClarificationAgent(self.schema_version)
        clarification = clarifier.check(state["query_plan"].to_dict())

        if clarification.needs_user_input:
            return {**state, "status": "needs_clarification", "questions": clarification.questions, "query_id": state["query_plan"].query_id}

        state["resolved_plan"] = clarification.resolved_plan or state["query_plan"].to_dict()
        return state

    def _stage_delegate_code(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .code_subagent import detect_code_intent, CodeSubagentAgent

        prompt = state.get("prompt", "")
        if not detect_code_intent(prompt):
            return state

        try:
            agent = CodeSubagentAgent(corpus_root=self.corpus_root, llm_model=self.llm_model)
            result = agent.run(instruction=prompt, code_root=self.corpus_root)
            state["code_result"] = result
            if result.get("files_modified"):
                state["code_changes"] = result.get("changes_made", [])
                state["files_modified"] = result.get("files_modified", [])
        except Exception as exc:
            logger.warning("Code subagent failed, continuing pipeline: %s", exc)
        return state

    def _stage_retrieve(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .retrieval import RetrievalAgent

        retriever = RetrievalAgent(self.schema_version)
        resolved = state.get("resolved_plan") or state["query_plan"].to_dict()
        retrieval_result = retriever.run(
            resolved,
            state["loader"].all_nodes,
            state["index_output"].inverted_index,
            state["loader"].csl_registry,
        )
        state["retrieval_result"] = retrieval_result
        return state

    def _stage_generate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .generation import GenerationAgent

        generator = GenerationAgent(self.schema_version)
        gen_output = generator.generate(
            query_id=state["query_plan"].query_id,
            user_query=state["prompt"],
            retrieval_result=state["retrieval_result"].to_dict(),
            csl_registry=state["loader"].csl_registry,
            merkle_registry=state["loader"].merkle_registry,
            llm_model=self.llm_model,
        )
        state["gen_output"] = gen_output
        if getattr(gen_output, "status", "ok") == "llm_error":
            state["status"] = "llm_error"
            state["message"] = gen_output.message or gen_output.answer_human
        return state

    def _stage_quality_gate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .quality_gate import ContentQualityGate

        if not state["gen_output"].answer_machine.get("evidence"):
            return state

        gate = ContentQualityGate(self.schema_version)
        quality = gate.check(
            answer_human=state["gen_output"].answer_human,
            answer_machine=state["gen_output"].answer_machine,
            retrieval_result=state["retrieval_result"].to_dict(),
        )
        state["quality_report"] = quality
        return state

    def _stage_integrity(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .integrity import IntegrityVerifier

        if not state["gen_output"].answer_machine.get("evidence"):
            return state

        verifier = IntegrityVerifier(self.schema_version)
        integrity = verifier.verify(
            state["gen_output"].answer_machine,
            state["loader"].all_nodes,
            state["loader"].merkle_registry,
            state["loader"].csl_registry,
        )
        state["integrity"] = integrity
        return state

    def _stage_save_memory(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .memory import MemoryStore

        memory = MemoryStore(memory_dir=f"{self.corpus_root}/.memory")
        evidence_ids = [
            e.get("node_id", "") for e in state["gen_output"].answer_machine.get("evidence", [])
        ]
        memory.save(
            thread_id=state["thread_id"],
            query=state["prompt"],
            response=state["gen_output"].answer_human,
            evidence_node_ids=evidence_ids,
        )
        return state

    # ── Checkpoint helpers ─────────────────────────────────────────────

    def _resolve_clarification(self, state: Dict[str, Any], user_answers: Dict[str, str]) -> Dict[str, Any]:
        """Apply clarification answers and produce a resolved plan."""
        from .clarification import ClarificationAgent
        clarifier = ClarificationAgent(self.schema_version)
        result = clarifier.resolve(state["query_plan"].to_dict(), user_answers)
        state["resolved_plan"] = result.resolved_plan or state["query_plan"].to_dict()
        return state

    def _apply_checkpoint_choice(self, state: Dict[str, Any], resume: PipelineResume) -> Dict[str, Any]:
        """Apply the user's checkpoint choice to pipeline state."""
        stage_name = state.get("checkpoint_stage_name", "")

        if stage_name == "retrieve" and resume.user_choice == "refine":
            # User wants to refine the query — apply refinement as additional search terms
            if resume.refinement:
                from .indexing import tokenize
                extra_terms = tokenize(resume.refinement)
                resolved = state.get("resolved_plan", {})
                resolved.setdefault("search_terms", []).extend(extra_terms)
                state["resolved_plan"] = resolved

        if stage_name == "generate" and resume.user_choice == "refine":
            # User wants to refine the answer — store the refinement for context
            if resume.refinement:
                state["answer_refinement"] = resume.refinement

        return state

    def _extract_checkpoint_result(self, stage_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the relevant result data for a checkpoint."""
        if stage_name == "clarify":
            return {"questions": state.get("questions", []), "query_id": state.get("query_id", "")}
        if stage_name == "retrieve":
            return {"result_count": len(state.get("retrieval_result", type("", (), {}).ranked_nodes)) if hasattr(state.get("retrieval_result", type("", (), {})), "ranked_nodes") else 0}
        if stage_name == "generate":
            gen = state.get("gen_output")
            if gen:
                return {"answer_preview": gen.answer_human[:200] + ("..." if len(gen.answer_human) > 200 else "")}
        return {}

    def _checkpoint_question(self, stage_name: str, state: Dict[str, Any]) -> str:
        """Generate a human-readable question for the checkpoint."""
        questions = {
            "clarify": "Ambiguity detected in your query. Please clarify before proceeding.",
            "retrieve": f"Found evidence. Review retrieved sources before generating an answer?",
            "generate": "Answer generated. Review the draft before final verification?",
        }
        return questions.get(stage_name, "Review the pipeline result before proceeding?")

    # ── Pipeline persistence ───────────────────────────────────────────

    TTL_SECONDS = 600  # 10 minutes

    def _save_pipeline(self, pipeline_id: str, state: Dict[str, Any]) -> None:
        """Save pipeline state to disk for later resumption."""
        os.makedirs(self.pipeline_dir, exist_ok=True)
        # Strip non-serializable objects
        saveable = {k: v for k, v in state.items() if not k.startswith("_") and not callable(v)}
        # Store serializable copies of complex objects
        for key in ("loader", "index_output", "query_plan", "retrieval_result", "gen_output", "integrity", "quality_report"):
            if key in saveable:
                obj = saveable[key]
                if hasattr(obj, "to_dict"):
                    saveable[key] = obj.to_dict()
                elif hasattr(obj, "__dict__") and not isinstance(obj, dict):
                    saveable[key] = str(type(obj))
        saveable["_saved_at"] = time.time()
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        with open(path, "w") as f:
            json.dump(saveable, f, default=str)

    def _load_pipeline(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        """Load a saved pipeline state. Returns None if expired or missing."""
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            state = json.load(f)
        saved_at = state.get("_saved_at", 0)
        if time.time() - saved_at > self.TTL_SECONDS:
            os.remove(path)
            return None
        return state

    def _delete_pipeline(self, pipeline_id: str) -> None:
        """Remove a completed or expired pipeline state file."""
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        if os.path.exists(path):
            os.remove(path)


# ── Legacy ChatPipeline (backward-compatible) ────────────────────────


class ChatPipeline:
    """End-to-end chat pipeline with retrieval-augmented generation.

    This is a thin wrapper around StagedChatPipeline that runs all stages
    without pausing at checkpoints, preserving backward compatibility.
    """

    def __init__(
        self,
        corpus_root: str = "corpus",
        llm_model: str = "ollama/qwen3",
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.corpus_root = corpus_root
        self.llm_model = llm_model
        self.schema_version = schema_version

    def chat(
        self,
        prompt: str,
        thread_id: str = "default",
    ) -> Dict[str, Any]:
        """Run the full chat pipeline for a single prompt."""
        staged = StagedChatPipeline(
            corpus_root=self.corpus_root,
            llm_model=self.llm_model,
            schema_version=self.schema_version,
        )
        result = staged.chat(prompt=prompt, thread_id=thread_id)

        # Flatten staged result into the legacy format
        if result.get("status") == "no_corpus":
            return result

        if result.get("status") == "llm_error":
            gen = result.get("gen_output")
            return {
                "status": "llm_error",
                "thread": thread_id,
                "query_id": result.get("query_plan", {}).query_id if hasattr(result.get("query_plan", {}), "query_id") else "",
                "answer_human": gen.answer_human if gen else result.get("message", ""),
                "answer_machine": gen.answer_machine if gen else {},
                "message": result.get("message", ""),
            }

        if result.get("status") == "needs_clarification":
            return result

        # Successful completion — extract fields from staged state
        gen = result.get("gen_output")
        integrity = result.get("integrity")
        quality = result.get("quality_report")
        retrieval = result.get("retrieval_result")

        output = {
            "status": "ok",
            "thread": thread_id,
            "query_id": result.get("query_plan", {}).query_id if hasattr(result.get("query_plan", {}), "query_id") else "",
            "answer_human": gen.answer_human if gen else "",
            "answer_machine": gen.answer_machine if gen else {},
            "integrity": integrity.to_dict() if integrity and hasattr(integrity, "to_dict") else (integrity if isinstance(integrity, dict) else {}),
            "retrieval_debug": retrieval.retrieval_debug if retrieval and hasattr(retrieval, "retrieval_debug") else {},
        }

        if quality and hasattr(quality, "to_dict"):
            output["quality"] = quality.to_dict()

        return output


class SearchPipeline:
    """Standalone search pipeline (no LLM, no memory) for ``citeindex search``."""

    def __init__(
        self,
        corpus_root: str = "corpus",
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.corpus_root = corpus_root
        self.schema_version = schema_version

    def search(
        self,
        query: str,
        top_k: int = 20,
        cite_style: str = "chicago-author-date",
        retrieval: str = "auto",
        pageindex_model: str = "ollama/glm-5.3-flash:cloud",
        allowed_source_ids: set[str] | None = None,
    ) -> Dict[str, Any]:
        from .corpus_loader import CorpusLoader
        from .indexing import IndexingAgent
        from .query_planner import QueryPlanner
        from .retrieval import RetrievalAgent

        # Load corpus
        loader = CorpusLoader(self.corpus_root)
        loader.load()

        if allowed_source_ids is not None:
            loader.all_nodes = [node for node in loader.all_nodes if node.get("source_id") in allowed_source_ids]
            loader.sources = [source for source in loader.sources if source.get("source_id") in allowed_source_ids]
            loader.csl_registry = [csl for csl in loader.csl_registry if csl.get("_source_id") in allowed_source_ids]

        if not loader.all_nodes:
            return {
                "status": "no_corpus",
                "message": "No approved sources found for this paper." if allowed_source_ids is not None else "No ingested documents found in corpus. Run `citeindex ingest` first.",
                "query": query,
            }

        # Plan query
        planner = QueryPlanner(self.schema_version)
        query_plan = planner.plan(query, csl_registry=loader.csl_registry)

        if query_plan.clarification_required:
            return {
                "status": "needs_clarification",
                "query_id": query_plan.query_id,
                "questions": query_plan.clarification_questions,
                "query": query,
            }

        # Decide retrieval method
        use_pageindex = (
            allowed_source_ids is None and (retrieval == "pageindex"
            or (retrieval == "auto" and "pageindex_tree_search" in query_plan.retrieval_policy)
            )
        )

        if use_pageindex:
            result = self._pageindex_search(query, top_k, pageindex_model)
        else:
            # Build indexes and use BM25
            indexer = IndexingAgent(self.schema_version)
            index_output = indexer.run(loader.all_nodes)

            retriever = RetrievalAgent(self.schema_version, top_k=top_k)
            result = retriever.run(
                query_plan.to_dict(),
                loader.all_nodes,
                index_output.inverted_index,
                loader.csl_registry,
            )

        # Enrich results with citation info
        csl_by_source: Dict[str, Dict[str, Any]] = {}
        for csl in loader.csl_registry:
            sid = csl.get("_source_id") or csl.get("id", "")
            csl_by_source[sid] = csl

        enriched_nodes: List[Dict[str, Any]] = []
        for node in result.ranked_nodes:
            source_id = node.get("source_id", "")
            csl = csl_by_source.get(source_id, {})
            node_copy = dict(node)
            node_copy["title"] = csl.get("title", "")
            authors = csl.get("author", [])
            if authors:
                first = authors[0]
                node_copy["author"] = f"{first.get('family', '')} {first.get('given', '')}".strip()
            # Generate formatted citation from CSL data
            if csl:
                try:
                    from citeindex.citation_style import format_bibliography
                    bib, _in_text = format_bibliography([csl], cite_style)
                    node_copy["formatted_citation"] = bib.strip() if bib and not bib.startswith("Error") else ""
                except Exception:
                    node_copy["formatted_citation"] = ""
            else:
                node_copy["formatted_citation"] = ""
            enriched_nodes.append(node_copy)

        return {
            "status": "ok",
            "query_id": query_plan.query_id,
            "intent_type": query_plan.intent_type,
            "retrieval_method": "pageindex" if use_pageindex else "bm25",
            "total_results": len(enriched_nodes),
            "results": enriched_nodes,
            "retrieval_debug": result.retrieval_debug,
        }

    def _pageindex_search(
        self, query: str, top_k: int, model: str
    ) -> "RetrievalResult":
        """Run PageIndex reasoning-based retrieval."""
        from .pageindex_retrieval import PageIndexRetrievalAgent
        from .models import RetrievalResult

        agent = PageIndexRetrievalAgent(
            corpus_root=self.corpus_root,
            model=model,
            top_k=top_k,
        )
        return agent.run(query=query)

"""Academic Pipeline — the agentic orchestrator.

Composes the existing research, writing, and review pipelines into one
state machine that owns the full research→publication workflow:

    research → outline → draft → style → quality → review

Each stage is a real, already-built component (SearchPipeline, WritingPipeline,
ReviewOrchestrator). This orchestrator is the single entry point that the MCP
surface exposes, so host skills delegate to it instead of re-describing the
workflow in prose.

State persists to ``<storage_dir>/pipelines/<pipeline_id>.json`` with a TTL,
using the same checkpoint/resume contract as StagedChatPipeline.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .models import PipelineCheckpoint, PipelineResume, PipelineStage, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class AcademicPipeline:
    """Orchestrate research → outline → draft → style → quality → review."""

    STAGES: List[PipelineStage] = [
        PipelineStage(name="research", checkpoint=True, description="Retrieve and verify evidence from the corpus"),
        PipelineStage(name="outline", checkpoint=True, description="Generate a hierarchical outline"),
        PipelineStage(name="draft", checkpoint=True, description="Draft prose from the outline and evidence"),
        PipelineStage(name="style", checkpoint=False, description="Style calibration and anti-AI-slop check"),
        PipelineStage(name="quality", checkpoint=False, description="Writing quality metrics"),
        PipelineStage(name="review", checkpoint=True, description="7-agent peer review panel"),
    ]

    def __init__(
        self,
        corpus_root: str = "corpus",
        storage_dir: str = ".shutong",
        llm_model: str = "ollama/glm-5.3-flash:cloud",
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.corpus_root = corpus_root
        self.storage_dir = storage_dir
        self.llm_model = llm_model
        self.schema_version = schema_version
        self.pipeline_dir = os.path.join(storage_dir, "pipelines")

    # ── Entry points ──────────────────────────────────────────────────

    def run(
        self,
        topic: str,
        mode: str = "full",
        sources: Optional[List[str]] = None,
        top_k: int = 20,
        scope: str = "comprehensive",
        skip_checkpoints: bool = False,
    ) -> Dict[str, Any]:
        """Run the pipeline from the start.

        ``mode`` selects a prefix of stages: research, outline, draft, review,
        or full (all stages). ``skip_checkpoints`` runs straight through.
        """
        stage_names = self._stage_names_for_mode(mode)
        state: Dict[str, Any] = {
            "topic": topic,
            "sources": sources or [],
            "top_k": top_k,
            "scope": scope,
            "mode": mode,
        }
        return self._run_from(state, stage_names, 0, skip_checkpoints)

    def resume(
        self,
        pipeline_id: str,
        user_choice: str = "proceed",
        refinement: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resume a paused pipeline from its checkpoint."""
        state = self._load_state(pipeline_id)
        if not state:
            return {"status": "error", "message": f"Pipeline {pipeline_id} not found or expired."}

        if user_choice == "abort":
            self._delete_state(pipeline_id)
            return {"status": "aborted", "pipeline_id": pipeline_id}

        stage_names = self._stage_names_for_mode(state.get("mode", "full"))
        start_index = state.get("checkpoint_stage_index", 0) + 1

        if refinement:
            state["refinement"] = refinement

        state["status"] = "ok"
        return self._run_from(state, stage_names, start_index, skip_checkpoints=False)

    # ── Stage selection ───────────────────────────────────────────────

    def _stage_names_for_mode(self, mode: str) -> List[str]:
        all_names = [s.name for s in self.STAGES]
        prefixes = {
            "research": ["research"],
            "outline": ["research", "outline"],
            "draft": ["research", "outline", "draft"],
            "review": ["research", "outline", "draft", "style", "quality", "review"],
            "full": all_names,
        }
        return prefixes.get(mode, all_names)

    # ── Run loop ──────────────────────────────────────────────────────

    def _run_from(
        self,
        state: Dict[str, Any],
        stage_names: List[str],
        start_index: int,
        skip_checkpoints: bool,
    ) -> Dict[str, Any]:
        for i in range(start_index, len(stage_names)):
            stage_name = stage_names[i]
            stage = next(s for s in self.STAGES if s.name == stage_name)
            state = self._run_stage(stage, state)

            if state.get("status") == "error":
                return state

            if stage.checkpoint and not skip_checkpoints:
                pipeline_id = str(uuid.uuid4())[:8]
                state["pipeline_id"] = pipeline_id
                state["checkpoint_stage_index"] = i
                state["checkpoint_stage_name"] = stage.name
                self._save_state(pipeline_id, state)
                checkpoint = PipelineCheckpoint(
                    pipeline_id=pipeline_id,
                    stage_name=stage.name,
                    stage_index=i,
                    intermediate_result=self._extract_result(stage.name, state),
                    question=self._checkpoint_question(stage.name),
                    options=["proceed", "refine", "abort"],
                )
                return {
                    "status": "needs_checkpoint",
                    "checkpoint": checkpoint.to_dict(),
                    "stage": stage.name,
                }

        if "pipeline_id" in state:
            self._delete_state(state["pipeline_id"])

        return {
            "status": "ok",
            "mode": state.get("mode", "full"),
            "topic": state.get("topic", ""),
            "evidence": state.get("evidence", []),
            "outline": state.get("outline", {}),
            "draft": state.get("draft", {}),
            "style_report": state.get("style_report", {}),
            "quality_report": state.get("quality_report", {}),
            "review": state.get("review", {}),
        }

    # ── Stage implementations ─────────────────────────────────────────

    def _run_stage(self, stage: PipelineStage, state: Dict[str, Any]) -> Dict[str, Any]:
        handler = {
            "research": self._stage_research,
            "outline": self._stage_outline,
            "draft": self._stage_draft,
            "style": self._stage_style,
            "quality": self._stage_quality,
            "review": self._stage_review,
        }.get(stage.name)
        if handler is None:
            logger.warning("Unknown pipeline stage: %s", stage.name)
            return state
        return handler(state)

    def _stage_research(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .chat import SearchPipeline

        pipeline = SearchPipeline(corpus_root=self.corpus_root)
        result = pipeline.search(
            state["topic"],
            top_k=state.get("top_k", 20),
        )
        if result.get("status") == "no_corpus":
            state["status"] = "error"
            state["message"] = result.get("message", "No corpus evidence found.")
            return state
        if result.get("status") == "needs_clarification":
            state["status"] = "error"
            state["message"] = "Query needs clarification: " + "; ".join(result.get("questions", []))
            return state

        state["evidence"] = result.get("results", [])
        state["retrieval_debug"] = result.get("retrieval_debug", {})
        return state

    def _stage_outline(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .writing.pipeline import WritingPipeline

        pipeline = WritingPipeline(corpus_root=self.corpus_root, llm_model=self.llm_model)
        outline = pipeline.run_outline(
            topic=state["topic"],
            sources=state.get("sources", []),
            scope=state.get("scope", "comprehensive"),
        )
        state["outline"] = outline
        return state

    def _stage_draft(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .writing.pipeline import WritingPipeline

        pipeline = WritingPipeline(corpus_root=self.corpus_root, llm_model=self.llm_model)
        evidence = {"ranked_nodes": state.get("evidence", [])}
        draft = pipeline.run_draft(
            outline=state.get("outline", {}),
            evidence=evidence,
        )
        state["draft"] = draft
        return state

    def _stage_style(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .writing.pipeline import WritingPipeline

        pipeline = WritingPipeline(corpus_root=self.corpus_root, llm_model=self.llm_model)
        state["style_report"] = pipeline.run_style(state.get("draft", {}))
        return state

    def _stage_quality(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .writing.pipeline import WritingPipeline

        pipeline = WritingPipeline(corpus_root=self.corpus_root, llm_model=self.llm_model)
        state["quality_report"] = pipeline.run_quality(state.get("draft", {}))
        return state

    def _stage_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from .review import ReviewOrchestrator

        orchestrator = ReviewOrchestrator(llm_model=self.llm_model)
        decision = orchestrator.review(state.get("draft", {}))
        state["review"] = decision.to_dict()
        return state

    # ── Checkpoint helpers ────────────────────────────────────────────

    @staticmethod
    def _extract_result(stage_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        if stage_name == "research":
            return {"result_count": len(state.get("evidence", []))}
        if stage_name == "outline":
            outline = state.get("outline", {})
            return {"title": outline.get("title", ""), "sections": len(outline.get("sections", []))}
        if stage_name == "draft":
            draft = state.get("draft", {})
            return {"total_word_count": draft.get("total_word_count", 0), "sections": len(draft.get("sections", []))}
        if stage_name == "review":
            review = state.get("review", {})
            return {"verdict": review.get("overall_verdict", ""), "actionable_items": len(review.get("actionable_items", []))}
        return {}

    @staticmethod
    def _checkpoint_question(stage_name: str) -> str:
        questions = {
            "research": "Review the retrieved evidence before outlining?",
            "outline": "Review the generated outline before drafting?",
            "draft": "Review the draft before style/quality/review?",
            "review": "Review the peer-review verdict?",
        }
        return questions.get(stage_name, "Review the result before proceeding?")

    # ── State persistence ─────────────────────────────────────────────

    TTL_SECONDS = 3600  # 1 hour

    def _save_state(self, pipeline_id: str, state: Dict[str, Any]) -> None:
        os.makedirs(self.pipeline_dir, exist_ok=True)
        saveable = {k: v for k, v in state.items() if not callable(v)}
        saveable["_saved_at"] = time.time()
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        with open(path, "w") as f:
            json.dump(saveable, f, default=str)

    def _load_state(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            state = json.load(f)
        if time.time() - state.get("_saved_at", 0) > self.TTL_SECONDS:
            os.remove(path)
            return None
        return state

    def _delete_state(self, pipeline_id: str) -> None:
        path = os.path.join(self.pipeline_dir, f"{pipeline_id}.json")
        if os.path.exists(path):
            os.remove(path)

"""Writing Pipeline — orchestrate outline → draft → style → quality with checkpoints.

Uses the same checkpoint/resume mechanism as StagedChatPipeline.
State persists to .shutong/writing/<outline_id>/<stage>.json.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..models import PipelineCheckpoint, PipelineStage, SCHEMA_VERSION
from .outline import OutlineAgent
from .draft import DraftAgent
from .style import StyleCalibrationAgent
from .quality import WritingQualityAgent

logger = logging.getLogger(__name__)


class WritingPipeline:
    """Orchestrate the writing pipeline with optional checkpoints.

    Stages:
    1. outline (checkpoint) — user reviews the generated outline
    2. draft (checkpoint) — user reviews the generated draft
    3. style — automatic style calibration
    4. quality — automatic quality metrics
    """

    STAGES: List[PipelineStage] = [
        PipelineStage(name="outline", checkpoint=True, description="Review the generated outline"),
        PipelineStage(name="draft", checkpoint=True, description="Review the generated draft"),
        PipelineStage(name="style", checkpoint=False, description="Style calibration and anti-AI-slop check"),
        PipelineStage(name="quality", checkpoint=False, description="Writing quality metrics"),
    ]

    def __init__(
        self,
        corpus_root: str = "corpus",
        llm_model: str = "ollama/glm-5.3-flash:cloud",
        schema_version: str = SCHEMA_VERSION,
        writing_dir: Optional[str] = None,
    ) -> None:
        self.corpus_root = corpus_root
        self.llm_model = llm_model
        self.schema_version = schema_version
        self.writing_dir = writing_dir or os.path.join(corpus_root, ".shutong", "writing")

    def run(
        self,
        topic: str,
        sources: Optional[List[str]] = None,
        scope: str = "comprehensive",
        skip_checkpoints: bool = True,
        glossary: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run the full writing pipeline, optionally pausing at checkpoints.

        If skip_checkpoints is True (default), all stages run without pausing.
        If False, returns a PipelineCheckpoint at each checkpoint stage.
        """
        state: Dict[str, Any] = {
            "topic": topic,
            "sources": sources or [],
            "scope": scope,
            "glossary": glossary or {},
        }

        for i, stage in enumerate(self.STAGES):
            state = self._run_stage(stage, state)

            if state.get("status") == "error":
                return state

            if stage.checkpoint and not skip_checkpoints:
                pipeline_id = str(uuid.uuid4())[:8]
                state["pipeline_id"] = pipeline_id
                state["checkpoint_stage_index"] = i
                self._save_state(pipeline_id, state)
                checkpoint = PipelineCheckpoint(
                    pipeline_id=pipeline_id,
                    stage_name=stage.name,
                    stage_index=i,
                    intermediate_result=self._extract_result(stage.name, state),
                    question=self._checkpoint_question(stage.name, state),
                    options=["proceed", "refine", "abort"],
                )
                return {
                    "status": "needs_checkpoint",
                    "checkpoint": checkpoint.to_dict(),
                    **state,
                }

        # Cleanup
        if "pipeline_id" in state:
            self._delete_state(state["pipeline_id"])

        return state

    def resume(
        self,
        pipeline_id: str,
        user_choice: str = "proceed",
        refinement: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resume a paused writing pipeline."""
        state = self._load_state(pipeline_id)
        if not state:
            return {"status": "error", "message": f"Pipeline {pipeline_id} not found or expired."}

        if user_choice == "abort":
            self._delete_state(pipeline_id)
            return {"status": "aborted", "pipeline_id": pipeline_id}

        start_index = state.get("checkpoint_stage_index", 0) + 1

        # Apply refinement if provided
        if refinement and state.get("checkpoint_stage_name") == "outline":
            state["outline_refinement"] = refinement
        elif refinement and state.get("checkpoint_stage_name") == "draft":
            state["draft_refinement"] = refinement

        state["status"] = "ok"
        for i in range(start_index, len(self.STAGES)):
            stage = self.STAGES[i]
            state = self._run_stage(stage, state)

            if state.get("status") == "error":
                return state

            if stage.checkpoint:
                pipeline_id_new = str(uuid.uuid4())[:8]
                state["pipeline_id"] = pipeline_id_new
                state["checkpoint_stage_index"] = i
                self._save_state(pipeline_id_new, state)
                checkpoint = PipelineCheckpoint(
                    pipeline_id=pipeline_id_new,
                    stage_name=stage.name,
                    stage_index=i,
                    intermediate_result=self._extract_result(stage.name, state),
                    question=self._checkpoint_question(stage.name, state),
                    options=["proceed", "refine", "abort"],
                )
                return {
                    "status": "needs_checkpoint",
                    "checkpoint": checkpoint.to_dict(),
                    **state,
                }

        if "pipeline_id" in state:
            self._delete_state(state["pipeline_id"])
        return state

    # ── Single-stage entry points (used by the academic orchestrator) ──

    def run_outline(self, topic: str, sources: Optional[List[str]] = None, scope: str = "comprehensive") -> Dict[str, Any]:
        """Run only the outline stage. Returns the outline dict."""
        state: Dict[str, Any] = {"topic": topic, "sources": sources or [], "scope": scope}
        return self._stage_outline(state)["outline"]

    def run_draft(self, outline: Dict[str, Any], evidence: Optional[Dict[str, Any]] = None, style: str = "academic", glossary: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Run only the draft stage. Returns the draft dict."""
        state: Dict[str, Any] = {
            "outline": outline,
            "retrieval_result": evidence or {"ranked_nodes": []},
            "style": style,
            "glossary": glossary or {},
        }
        return self._stage_draft(state)["draft"]

    def run_style(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Run only the style stage. Returns the style report dict."""
        return self._stage_style({"draft": draft})["style_report"]

    def run_quality(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Run only the quality stage. Returns the quality report dict."""
        return self._stage_quality({"draft": draft})["quality_report"]

    # ── Stage implementations ──────────────────────────────────────────

    def _run_stage(self, stage: PipelineStage, state: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch to the appropriate stage handler."""
        handler = {
            "outline": self._stage_outline,
            "draft": self._stage_draft,
            "style": self._stage_style,
            "quality": self._stage_quality,
        }.get(stage.name)
        if handler is None:
            logger.warning("Unknown writing pipeline stage: %s", stage.name)
            return state
        return handler(state)

    def _stage_outline(self, state: Dict[str, Any]) -> Dict[str, Any]:
        agent = OutlineAgent(schema_version=self.schema_version, llm_model=self.llm_model)
        outline = agent.generate(
            topic=state["topic"],
            sources=state.get("sources", []),
            scope=state.get("scope", "comprehensive"),
        )
        # Apply refinement if provided
        if state.get("outline_refinement"):
            outline["outline_refinement"] = state["outline_refinement"]
        state["outline"] = outline
        return state

    def _stage_draft(self, state: Dict[str, Any]) -> Dict[str, Any]:
        agent = DraftAgent(schema_version=self.schema_version, llm_model=self.llm_model)
        outline = state.get("outline", {})
        # Build evidence dict from corpus if available
        evidence = state.get("retrieval_result", {"ranked_nodes": []})
        draft = agent.generate(
            outline=outline,
            evidence=evidence,
            style=state.get("style", "academic"),
            glossary=state.get("glossary"),
        )
        if state.get("draft_refinement"):
            draft["draft_refinement"] = state["draft_refinement"]
        state["draft"] = draft
        return state

    def _stage_style(self, state: Dict[str, Any]) -> Dict[str, Any]:
        agent = StyleCalibrationAgent(schema_version=self.schema_version)
        style_report = agent.check(state.get("draft", {}))
        state["style_report"] = style_report
        return state

    def _stage_quality(self, state: Dict[str, Any]) -> Dict[str, Any]:
        agent = WritingQualityAgent(schema_version=self.schema_version)
        quality_report = agent.check(state.get("draft", {}))
        state["quality_report"] = quality_report
        return state

    # ── Checkpoint helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_result(stage_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        if stage_name == "outline":
            outline = state.get("outline", {})
            return {"title": outline.get("title", ""), "sections": len(outline.get("sections", []))}
        if stage_name == "draft":
            draft = state.get("draft", {})
            return {"total_word_count": draft.get("total_word_count", 0), "sections": len(draft.get("sections", []))}
        return {}

    @staticmethod
    def _checkpoint_question(stage_name: str, state: Dict[str, Any]) -> str:
        questions = {
            "outline": "Review the generated outline. Proceed, refine the topic, or abort?",
            "draft": "Review the generated draft. Proceed, refine the writing, or abort?",
        }
        return questions.get(stage_name, "Review the result before proceeding?")

    # ── State persistence ───────────────────────────────────────────────

    TTL_SECONDS = 3600  # 1 hour for writing pipelines

    def _save_state(self, pipeline_id: str, state: Dict[str, Any]) -> None:
        os.makedirs(self.writing_dir, exist_ok=True)
        saveable = {k: v for k, v in state.items() if not callable(v)}
        for key in ("outline", "draft", "style_report", "quality_report"):
            if key in saveable and hasattr(saveable[key], "to_dict"):
                saveable[key] = saveable[key].to_dict()
        saveable["_saved_at"] = time.time()
        path = os.path.join(self.writing_dir, f"{pipeline_id}.json")
        with open(path, "w") as f:
            json.dump(saveable, f, default=str)

    def _load_state(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.writing_dir, f"{pipeline_id}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            state = json.load(f)
        saved_at = state.get("_saved_at", 0)
        if time.time() - saved_at > self.TTL_SECONDS:
            os.remove(path)
            return None
        return state

    def _delete_state(self, pipeline_id: str) -> None:
        path = os.path.join(self.writing_dir, f"{pipeline_id}.json")
        if os.path.exists(path):
            os.remove(path)

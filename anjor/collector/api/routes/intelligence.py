"""GET /intelligence/* — Phase 3 intelligence endpoints.

Active recommendations derived from historical event data:
- /intelligence/failures      — failure clusters + natural language patterns
- /intelligence/optimization  — token optimization suggestions
- /intelligence/quality/tools — per-tool quality scores
- /intelligence/quality/runs  — per-run quality scores
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from anjor.analysis.intelligence.failure_clustering import FailureClusterer
from anjor.analysis.intelligence.quality_scorer import QualityScorer
from anjor.analysis.intelligence.root_cause import RootCauseAdvisor
from anjor.analysis.intelligence.token_optimizer import TokenOptimizer
from anjor.analysis.tracing.attribution import AttributionAnalyser
from anjor.collector.api.schemas import (
    AgentAttributionItem,
    AgentRunQualityScoreItem,
    FailureClusterItem,
    OptimizationSuggestionItem,
    PromptVersionItem,
    RootCauseHypothesisItem,
    ToolQualityScoreItem,
)
from anjor.collector.storage.base import LLMQueryFilters

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_intelligence_router(service: CollectorService) -> APIRouter:
    router = APIRouter(prefix="/intelligence", tags=["intelligence"])

    @router.get("/failures", response_model=list[FailureClusterItem])
    async def get_failure_patterns() -> list[FailureClusterItem]:
        """Return failure clusters derived from all historical tool call data.

        Clusters are sorted by failure_rate descending so the worst offenders
        appear first.
        """
        tool_calls = await service.storage.query_tool_calls_for_analysis()
        clusterer = FailureClusterer()
        clusters = clusterer.cluster(tool_calls)
        return [
            FailureClusterItem(
                tool_name=c.tool_name,
                failure_type=c.failure_type,
                occurrence_count=c.occurrence_count,
                total_calls=c.total_calls,
                failure_rate=c.failure_rate,
                avg_latency_ms=c.avg_latency_ms,
                pattern_description=c.pattern_description,
                suggestion=c.suggestion,
                example_trace_ids=c.example_trace_ids,
            )
            for c in clusters
        ]

    @router.get("/optimization", response_model=list[OptimizationSuggestionItem])
    async def get_optimization_suggestions() -> list[OptimizationSuggestionItem]:
        """Return token optimization suggestions for context-bloating tools.

        Only tools whose average output exceeds 5% of the context window are
        returned. Suggestions include estimated cost savings per 1,000 calls.
        """
        tool_calls = await service.storage.query_tool_calls_for_analysis()
        llm_calls = await service.storage.query_llm_calls(LLMQueryFilters(limit=2000))
        optimizer = TokenOptimizer()
        suggestions = optimizer.optimize(tool_calls, llm_calls)
        return [
            OptimizationSuggestionItem(
                tool_name=s.tool_name,
                avg_output_tokens=s.avg_output_tokens,
                avg_context_fraction=s.avg_context_fraction,
                waste_score=s.waste_score,
                estimated_savings_tokens_per_call=s.estimated_savings_tokens_per_call,
                estimated_savings_usd_per_1k_calls=s.estimated_savings_usd_per_1k_calls,
                suggestion_text=s.suggestion_text,
                sample_models=s.sample_models,
            )
            for s in suggestions
        ]

    @router.get("/quality/tools", response_model=list[ToolQualityScoreItem])
    async def get_tool_quality_scores() -> list[ToolQualityScoreItem]:
        """Return quality scores for all tools, sorted by overall_score ascending.

        Worst tools appear first so engineers can triage immediately.
        """
        tool_calls = await service.storage.query_tool_calls_for_analysis()
        scorer = QualityScorer()
        scores = scorer.score_tools(tool_calls)
        return [
            ToolQualityScoreItem(
                tool_name=s.tool_name,
                call_count=s.call_count,
                reliability_score=s.reliability_score,
                schema_stability_score=s.schema_stability_score,
                latency_consistency_score=s.latency_consistency_score,
                overall_score=s.overall_score,
                grade=s.grade,
            )
            for s in scores
        ]

    @router.get("/quality/runs", response_model=list[AgentRunQualityScoreItem])
    async def get_run_quality_scores() -> list[AgentRunQualityScoreItem]:
        """Return quality scores per agent run (trace_id), sorted by overall_score ascending."""
        tool_calls = await service.storage.query_tool_calls_for_analysis()
        llm_calls = await service.storage.query_llm_calls(LLMQueryFilters(limit=2000))
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        return [
            AgentRunQualityScoreItem(
                trace_id=s.trace_id,
                llm_call_count=s.llm_call_count,
                tool_call_count=s.tool_call_count,
                context_efficiency_score=s.context_efficiency_score,
                failure_recovery_score=s.failure_recovery_score,
                tool_diversity_score=s.tool_diversity_score,
                overall_score=s.overall_score,
                grade=s.grade,
            )
            for s in scores
        ]

    @router.get("/attribution", response_model=list[AgentAttributionItem])
    async def get_attribution(trace_id: str | None = None) -> list[AgentAttributionItem]:
        """Return per-agent token and failure attribution.

        If trace_id is provided, attribution is scoped to that trace only.
        Otherwise covers all spans. Sorted by total token consumption descending.
        """
        if trace_id:
            spans = await service.storage.query_spans(trace_id)
        else:
            spans = await service.storage.query_spans_all()
        analyser = AttributionAnalyser()
        results = analyser.analyse(spans)
        return [
            AgentAttributionItem(
                agent_name=a.agent_name,
                span_count=a.span_count,
                token_input=a.token_input,
                token_output=a.token_output,
                token_total=a.token_total,
                token_share_pct=a.token_share_pct,
                tool_calls_count=a.tool_calls_count,
                llm_calls_count=a.llm_calls_count,
                failure_count=a.failure_count,
                failure_rate=a.failure_rate,
            )
            for a in results
        ]

    @router.get("/prompt_versions", response_model=list[PromptVersionItem])
    async def get_prompt_versions(
        project: str | None = None, limit: int = 50
    ) -> list[PromptVersionItem]:
        rows = await service.storage.list_prompt_versions(project=project, limit=limit)
        return [PromptVersionItem(**r) for r in rows]

    @router.get("/root_causes", response_model=list[RootCauseHypothesisItem])
    async def get_root_causes() -> list[RootCauseHypothesisItem]:
        """Return ranked root-cause hypotheses from failure clusters, tool stats, and LLM stats."""
        tool_calls = await service.storage.query_tool_calls_for_analysis()

        clusterer = FailureClusterer()
        clusters = [
            {
                "tool_name": c.tool_name,
                "failure_type": c.failure_type,
                "occurrence_count": c.occurrence_count,
                "total_calls": c.total_calls,
                "failure_rate": c.failure_rate,
            }
            for c in clusterer.cluster(tool_calls)
        ]

        tool_summaries_raw = await service.storage.list_tool_summaries()
        tool_summaries = [
            {
                "tool_name": s.tool_name,
                "call_count": s.call_count,
                "success_rate": s.success_rate,
                "avg_latency_ms": s.avg_latency_ms,
                "p95_latency_ms": s.p95_latency_ms,
                "drift_rate": 0.0,
            }
            for s in tool_summaries_raw
        ]

        llm_summaries_raw = await service.storage.list_llm_summaries()
        llm_summaries = [
            {
                "model": s.model,
                "avg_context_utilisation": s.avg_context_utilisation,
            }
            for s in llm_summaries_raw
        ]

        advisor = RootCauseAdvisor()
        hypotheses = advisor.generate(clusters, tool_summaries, llm_summaries)
        return [
            RootCauseHypothesisItem(
                title=h.title,
                evidence=h.evidence,
                confidence=h.confidence,
                action=h.action,
            )
            for h in hypotheses
        ]

    return router

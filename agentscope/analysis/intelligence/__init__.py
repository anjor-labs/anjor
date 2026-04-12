"""Intelligence analysis layer — Phase 3.

Provides active recommendations on top of passive observability data:
- FailureClusterer: group historical failures into patterns with explanations
- TokenOptimizer: identify tools with bloated outputs + cost savings
- QualityScorer: reliability and efficiency scores per tool and per run
"""

from __future__ import annotations

from agentscope.analysis.intelligence.failure_clustering import (
    FailureCluster,
    FailureClusterer,
)
from agentscope.analysis.intelligence.quality_scorer import (
    AgentRunQualityScore,
    QualityScorer,
    ToolQualityScore,
)
from agentscope.analysis.intelligence.token_optimizer import (
    CostEstimator,
    OptimizationSuggestion,
    TokenOptimizer,
)

__all__ = [
    "FailureCluster",
    "FailureClusterer",
    "OptimizationSuggestion",
    "TokenOptimizer",
    "CostEstimator",
    "ToolQualityScore",
    "AgentRunQualityScore",
    "QualityScorer",
]

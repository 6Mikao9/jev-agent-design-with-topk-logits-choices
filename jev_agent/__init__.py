"""Jev-native tool-agent research prototype."""

from .agent import Agent, AgentResult, ToolDefinition
from .arguments import ArgumentField, ArgumentInput, ArgumentInputResult, FieldContext, ValueProposal
from .context_residency import ContextBlock, ContextCandidate, ContextFault, ContextResidencyManager
from .context_refresh import ContextRefreshCoordinator, ContextRefreshResult, ContextVerification, JevContextVerifier
from .context_materialization import (
    ContextMaterializationBudgetExceeded,
    ContextMaterializationError,
    ContextMaterializer,
    ContextSourceNotFound,
    MaterializedContext,
    StaleContextMaterialization,
)
from .context_recovery import ContextEvidenceFallback, ContextEvidenceRecoveryResult
from .context_budget import (
    ContextBudget,
    ContextBudgetController,
    ContextBudgetExceeded,
    ContextSlice,
    PackedContext,
)
from .decision_model import ChoiceBackendAdapter, DecisionModel, DecisionRequest, OracleDecisionModel, ReplayDecisionModel
from .diffusion import DiffusionCandidate, ParallelCandidateGenerator
from .fast_logits import FastLogitsHelper, FastLogitsState, FastToken
from .memory import DependencyIndex, MemoryBank, MemoryRecord
from .memory_selection import MemorySelectionResult, TwoStageMemorySelector
from .memory_recovery import EvidenceRecoveryResult, RawEvidenceFallback
from .grounded import GroundedArgumentAgent, GroundedResult
from .models import Candidate, ChoiceOption, ChoiceResult, TaskState
from .option_space import OptionSpace, OptionSpaceRegistry, SpaceOption
from .option_budget import (
    DEFAULT_OPTION_PAGE_BUDGET,
    DEFAULT_CONTROL_RESERVE,
    DEFAULT_DECISION_TARGET,
    JEV_MAX_OPTIONS,
    OptionCall,
    OptionPageBudget,
)
from .parameter_prior import ParameterCandidate, ParameterPrior, ParameterRecord
from .orchestrator import JevAgentOrchestrator, OrchestratorResult
from .runtime import DecisionRuntime, RuntimeState, RuntimeStepResult
from .speculation import ShadowPage, SpeculationBuffer, SpeculationEvent, rank_pages
from .paged_memory import (
    MemoryPage,
    MemoryReadBudgetExceeded,
    PageCandidate,
    PagedMemoryIndex,
    StaleMemoryPage,
)
from .state_machine import CompiledDecisionRule, DecisionTraceGraph, ErrorSummaryQueue, TraceEdge
from .topk import TopKBuilder, TopKResult, TransformersLogitsBackend
from .virtual_option import (
    OptionFault,
    OptionPage,
    RefineFault,
    StaleVirtualOption,
    VirtualOption,
    VirtualOptionManager,
)

__all__ = [
    "Agent",
    "AgentResult",
    "ArgumentField",
    "ArgumentInput",
    "ArgumentInputResult",
    "FieldContext",
    "ValueProposal",
    "ContextBlock",
    "ContextCandidate",
    "ContextFault",
    "ContextResidencyManager",
    "ContextRefreshCoordinator",
    "ContextRefreshResult",
    "ContextVerification",
    "JevContextVerifier",
    "ContextMaterializationBudgetExceeded",
    "ContextMaterializationError",
    "ContextMaterializer",
    "ContextSourceNotFound",
    "MaterializedContext",
    "StaleContextMaterialization",
    "ContextEvidenceFallback",
    "ContextEvidenceRecoveryResult",
    "ContextBudget",
    "ContextBudgetController",
    "ContextBudgetExceeded",
    "ContextSlice",
    "PackedContext",
    "ChoiceBackendAdapter",
    "DecisionModel",
    "DecisionRequest",
    "OracleDecisionModel",
    "ReplayDecisionModel",
    "DiffusionCandidate",
    "FastLogitsHelper",
    "FastLogitsState",
    "FastToken",
    "Candidate",
    "ChoiceOption",
    "ChoiceResult",
    "DependencyIndex",
    "MemoryBank",
    "MemoryRecord",
    "MemorySelectionResult",
    "TwoStageMemorySelector",
    "EvidenceRecoveryResult",
    "RawEvidenceFallback",
    "GroundedArgumentAgent",
    "GroundedResult",
    "MemoryPage",
    "MemoryReadBudgetExceeded",
    "PageCandidate",
    "PagedMemoryIndex",
    "StaleMemoryPage",
    "ParallelCandidateGenerator",
    "OptionSpace",
    "OptionSpaceRegistry",
    "SpaceOption",
    "DEFAULT_OPTION_PAGE_BUDGET",
    "DEFAULT_CONTROL_RESERVE",
    "DEFAULT_DECISION_TARGET",
    "JEV_MAX_OPTIONS",
    "OptionCall",
    "OptionPageBudget",
    "ParameterCandidate",
    "ParameterPrior",
    "ParameterRecord",
    "JevAgentOrchestrator",
    "OrchestratorResult",
    "DecisionRuntime",
    "RuntimeState",
    "RuntimeStepResult",
    "ShadowPage",
    "SpeculationBuffer",
    "SpeculationEvent",
    "rank_pages",
    "CompiledDecisionRule",
    "DecisionTraceGraph",
    "ErrorSummaryQueue",
    "TraceEdge",
    "TaskState",
    "ToolDefinition",
    "TopKBuilder",
    "TopKResult",
    "TransformersLogitsBackend",
    "OptionFault",
    "OptionPage",
    "RefineFault",
    "StaleVirtualOption",
    "VirtualOption",
    "VirtualOptionManager",
]

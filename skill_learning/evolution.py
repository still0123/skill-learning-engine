from __future__ import annotations

from pathlib import Path

from .components import KnowledgeMaintainer, SkillProposer, TaskExecutor
from .gate import EvaluationGate
from .models import EvolutionSummary
from .runtime import StructuredRuntime
from .tasks import TaskAdapter
from .workspace import Workspace


class EvolutionEngine:
    def __init__(
        self,
        *,
        workspace: Workspace,
        runtime: StructuredRuntime,
        adapter: TaskAdapter,
        gate: EvaluationGate | None = None,
    ) -> None:
        self.workspace = workspace
        self.executor = TaskExecutor(runtime, adapter)
        self.maintainer = KnowledgeMaintainer(runtime)
        self.proposer = SkillProposer(runtime)
        self.adapter = adapter
        self.gate = gate or EvaluationGate()

    def run(self, *, iterations: int) -> EvolutionSummary:
        if iterations < 1:
            raise ValueError("iterations must be at least 1")
        state = self.workspace.load_state()
        skill_name = state["skill_name"]
        initial_version = int(state["version"])
        iteration = int(state["iteration"])
        active_skill = self.workspace.read_skill(skill_name)

        if state["best_validation_score"] is None:
            baseline_eval = self.executor.evaluate(
                tasks=self.adapter.tasks("validation"),
                skill_name=skill_name,
                skill_version=state["version"],
                skill_text=active_skill,
                iteration=iteration,
                phase="validation-baseline",
                workdir=self.workspace.root,
            )
            self.workspace.write_traces(baseline_eval.traces)
            state["best_validation_score"] = baseline_eval.mean_score
            self.workspace.save_state(state)
        initial_validation = float(state["best_validation_score"])
        accepted = 0
        rejected = 0
        completed = 0

        for _ in range(iterations):
            iteration = int(state["iteration"])
            version = int(state["version"])
            active_skill = self.workspace.read_skill(skill_name)
            train_eval = self.executor.evaluate(
                tasks=self.adapter.tasks("train"),
                skill_name=skill_name,
                skill_version=version,
                skill_text=active_skill,
                iteration=iteration,
                phase="train",
                workdir=self.workspace.root,
            )
            self.workspace.write_traces(train_eval.traces)
            if all(trace.passed for trace in train_eval.traces):
                self.workspace.append_log(
                    f"\n## Iteration {iteration}\n\nAll training tasks passed; evolution stopped early.\n"
                )
                break

            patterns = self.maintainer.update(
                wiki_index=self.workspace.read_wiki_index(),
                traces=train_eval.traces,
                workdir=self.workspace.root,
            )
            self.workspace.update_patterns(iteration=iteration, patterns=patterns)

            proposal = None
            try:
                proposal = self.proposer.propose(
                    skill_name=skill_name,
                    skill_text=active_skill,
                    patterns=patterns,
                    traces=train_eval.traces,
                    impact_log=self.workspace.read_impact_log(),
                    workdir=self.workspace.root,
                )
                candidate_dir = self.workspace.build_candidate(
                    iteration=iteration,
                    proposal=proposal,
                )
                candidate_skill = (candidate_dir / "SKILL.md").read_text(encoding="utf-8")
                candidate_eval = self.executor.evaluate(
                    tasks=self.adapter.tasks("validation"),
                    skill_name=skill_name,
                    skill_version=version + 1,
                    skill_text=candidate_skill,
                    iteration=iteration,
                    phase="validation-candidate",
                    workdir=candidate_dir,
                )
                self.workspace.write_traces(candidate_eval.traces)
                baseline_score = float(state["best_validation_score"])
                decision = self.gate.decide(
                    baseline=baseline_score,
                    candidate=candidate_eval.mean_score,
                )
                if decision.accepted:
                    state["version"] = self.workspace.promote(
                        candidate_dir=candidate_dir,
                        skill_name=skill_name,
                        current_version=version,
                    )
                    state["best_validation_score"] = candidate_eval.mean_score
                    accepted += 1
                    decision_name = "accepted"
                else:
                    rejected += 1
                    decision_name = "rejected"
                self.workspace.record_impact(
                    iteration=iteration,
                    skill_name=skill_name,
                    decision=decision_name,
                    baseline=baseline_score,
                    candidate=candidate_eval.mean_score,
                    summary=proposal.summary,
                    reason=decision.reason,
                )
            except Exception as exc:
                self.workspace.record_impact(
                    iteration=iteration,
                    skill_name=skill_name,
                    decision="failed",
                    baseline=float(state["best_validation_score"]),
                    candidate=None,
                    summary=proposal.summary if proposal else "proposal not created",
                    reason=f"{type(exc).__name__}: {exc}",
                )
                raise

            state["iteration"] = iteration + 1
            self.workspace.save_state(state)
            completed += 1

        final_skill = self.workspace.read_skill(skill_name)
        final_test = self.executor.evaluate(
            tasks=self.adapter.tasks("test"),
            skill_name=skill_name,
            skill_version=int(state["version"]),
            skill_text=final_skill,
            iteration=int(state["iteration"]),
            phase="test-final",
            workdir=self.workspace.root,
        )
        self.workspace.write_traces(final_test.traces)
        return EvolutionSummary(
            skill_name=skill_name,
            initial_version=initial_version,
            final_version=int(state["version"]),
            initial_validation_score=initial_validation,
            final_validation_score=float(state["best_validation_score"]),
            final_test_score=final_test.mean_score,
            accepted=accepted,
            rejected=rejected,
            completed_iterations=completed,
        )

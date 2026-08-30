from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
from typing import Mapping

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
        prompts: Mapping[str, str] | None = None,
    ) -> None:
        prompt_set = prompts or {}
        self.workspace = workspace
        self.executor = TaskExecutor(
            runtime,
            adapter,
            system_prompt=prompt_set.get("executor.md"),
        )
        self.maintainer = KnowledgeMaintainer(
            runtime,
            system_prompt=prompt_set.get("maintainer.md"),
        )
        self.proposer = SkillProposer(
            runtime,
            system_prompt=prompt_set.get("proposer.md"),
        )
        self.adapter = adapter
        self.gate = gate or EvaluationGate()

    def run(self, *, iterations: int, evaluate_test: bool = True) -> EvolutionSummary:
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
            self.workspace.record_evaluation(baseline_eval)
            state["best_validation_score"] = baseline_eval.mean_score
            state["best_validation_iteration"] = iteration
            state["best_validation_phase"] = baseline_eval.phase
            self.workspace.save_state(state)
            best_validation = baseline_eval
        else:
            best_iteration = state.get("best_validation_iteration")
            best_phase = state.get("best_validation_phase")
            if best_iteration is None or not best_phase:
                raise ValueError(
                    "workspace lacks V2 best-validation pointer; start a fresh experiment workspace"
                )
            best_validation = self.workspace.load_evaluation(
                iteration=int(best_iteration),
                phase=str(best_phase),
            )
        initial_validation = float(state["best_validation_score"])
        accepted = 0
        rejected = 0
        completed = 0

        for _ in range(iterations):
            if best_validation.mean_score >= 1.0:
                self.workspace.append_log(
                    f"\n## Iteration {state['iteration']}\n\n"
                    "Best validation score reached 1.0; evolution stopped early.\n"
                )
                break
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
            self.workspace.record_evaluation(train_eval)
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
            candidate_skill = ""
            diff = ""
            try:
                proposer_view = self.workspace.prepare_proposer_view(
                    iteration=iteration,
                    skill_name=skill_name,
                    traces=train_eval.traces,
                )
                proposal = self.proposer.propose(
                    skill_name=skill_name,
                    skill_text=active_skill,
                    patterns=patterns,
                    traces=train_eval.traces,
                    impact_log=self.workspace.read_impact_log(),
                    workdir=proposer_view,
                )
                candidate_dir = self.workspace.build_candidate(
                    iteration=iteration,
                    proposal=proposal,
                )
                candidate_skill = (candidate_dir / "SKILL.md").read_text(encoding="utf-8")
                diff = "".join(unified_diff(
                    active_skill.splitlines(keepends=True),
                    candidate_skill.splitlines(keepends=True),
                    fromfile=f"skills/{skill_name}/SKILL.md",
                    tofile=f"candidates/iteration-{iteration:03d}/{skill_name}/SKILL.md",
                ))
                candidate_eval = self.executor.evaluate(
                    tasks=self.adapter.tasks("validation"),
                    skill_name=skill_name,
                    skill_version=version + 1,
                    skill_text=candidate_skill,
                    iteration=iteration,
                    phase="validation-candidate",
                    workdir=candidate_dir,
                )
                self.workspace.record_evaluation(candidate_eval)
                baseline_score = float(state["best_validation_score"])
                decision = self.gate.decide(
                    baseline=best_validation,
                    candidate=candidate_eval,
                )
                if decision.accepted:
                    state["version"] = self.workspace.promote(
                        candidate_dir=candidate_dir,
                        skill_name=skill_name,
                        current_version=version,
                    )
                    state["best_validation_score"] = candidate_eval.mean_score
                    state["best_validation_iteration"] = iteration
                    state["best_validation_phase"] = candidate_eval.phase
                    best_validation = candidate_eval
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
                    proposal=proposal,
                    diff=diff,
                    version_before=version,
                    version_after=int(state["version"]),
                    comparison=decision.to_dict(),
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
                    proposal=proposal,
                    diff=diff,
                    version_before=version,
                    version_after=version,
                )
                raise

            state["iteration"] = iteration + 1
            self.workspace.save_state(state)
            completed += 1

        final_test_score = None
        if evaluate_test:
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
            self.workspace.record_evaluation(final_test)
            final_test_score = final_test.mean_score
        return EvolutionSummary(
            skill_name=skill_name,
            initial_version=initial_version,
            final_version=int(state["version"]),
            initial_validation_score=initial_validation,
            final_validation_score=best_validation.mean_score,
            final_test_score=final_test_score,
            accepted=accepted,
            rejected=rejected,
            completed_iterations=completed,
        )

"""Fixture-backed deterministic producer for the exact three-turn scenario."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid5

from pydantic import Field

from backend.deep_work.base import (
    CancellationToken,
    DeepWorkCancelled,
    DeepWorkFailure,
    DeepWorkInput,
    DeepWorkOutput,
)
from backend.domain.models import (
    ClassifiedText,
    DocumentPatchProposal,
    OpportunityDocument,
    SanitizedError,
    WireModel,
)

ROOT = Path(__file__).resolve().parents[2]


class _SyntheticProject(WireModel):
    """Validated clean-room project fixture consumed by the producer."""

    project_id: UUID
    display_name: str
    industry: str
    goals: tuple[ClassifiedText, ...] = Field(min_length=2)
    current_capabilities: tuple[ClassifiedText, ...] = Field(min_length=2)
    stakeholder_roles: tuple[ClassifiedText, ...] = Field(min_length=2)
    signals: tuple[ClassifiedText, ...] = Field(min_length=2)
    unknowns: tuple[ClassifiedText, ...] = Field(min_length=2)
    source_notes: tuple[str, ...] = Field(min_length=1)


class _ScriptedTurn(WireModel):
    """One exact scripted input and its classified expected focus."""

    sequence: int = Field(ge=1, le=3)
    turn_id: UUID
    transcript: str
    intent: str
    expected_focus: tuple[ClassifiedText, ...] = Field(min_length=1)


class _FixtureBundle(WireModel):
    """Validated deterministic fixture bundle."""

    project: _SyntheticProject
    turns: tuple[_ScriptedTurn, ...]


class DeterministicDeepWorker:
    """Create coherent proposals from fixture claims and the start-time snapshot."""

    def __init__(self, *, fixture_root: Path = ROOT / "fixtures") -> None:
        self._fixtures = _load_fixtures(fixture_root)

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        """Produce the proposal for one exact scripted turn."""

        turn = self._scripted_turn(work_input)
        await _apply_delay(work_input, cancellation)
        if not work_input.controls.late_result:
            cancellation.raise_if_cancelled()
        if work_input.controls.producer_failure:
            raise DeepWorkFailure(
                SanitizedError(
                    code="internal_error",
                    category="document",
                    message="The deterministic producer could not complete.",
                    retryable=True,
                )
            )

        proposal = self._proposal(work_input, turn)
        payload = proposal.model_dump(mode="json", by_alias=True)
        if work_input.controls.malformed_patch:
            operations = payload.get("operations")
            if isinstance(operations, list) and operations:
                malformed = dict(operations[0])
                malformed.pop("op", None)
                operations[0] = malformed
        return DeepWorkOutput(proposal=payload)

    def _scripted_turn(self, work_input: DeepWorkInput) -> _ScriptedTurn:
        try:
            turn = self._fixtures.turns[work_input.sequence - 1]
        except IndexError as error:
            raise DeepWorkFailure(
                SanitizedError(
                    code="validation_error",
                    category="document",
                    message="The deterministic script does not contain this turn.",
                    retryable=False,
                )
            ) from error
        if (
            turn.sequence != work_input.sequence
            or turn.transcript != work_input.transcript
        ):
            raise DeepWorkFailure(
                SanitizedError(
                    code="validation_error",
                    category="document",
                    message="The turn does not match the deterministic script.",
                    retryable=False,
                )
            )
        # The browser owns correlation identities. Fixture IDs validate the
        # clean-room data shape but must never constrain a submitted app turn.
        return turn.model_copy(update={"turn_id": work_input.turn_id})

    def _proposal(
        self,
        work_input: DeepWorkInput,
        turn: _ScriptedTurn,
    ) -> DocumentPatchProposal:
        builders: dict[
            int,
            Callable[[OpportunityDocument, _ScriptedTurn], list[dict[str, object]]],
        ] = {
            1: self._turn_one_operations,
            2: self._turn_two_operations,
            3: self._turn_three_operations,
        }
        operations = builders[turn.sequence](work_input.document, turn)
        summaries = {
            1: "Create the initial evidence-bounded opportunity.",
            2: "Strengthen the operational context and supporting signals.",
            3: "Refine validation value, evidence gaps, and next action.",
        }
        return DocumentPatchProposal.model_validate(
            {
                "patchId": str(uuid5(work_input.turn_id, "document-patch")),
                "sessionId": str(work_input.session_id),
                "turnId": str(work_input.turn_id),
                "documentId": str(work_input.document.document_id),
                "baseVersion": work_input.document.version,
                "summary": summaries[turn.sequence],
                "operations": operations,
            }
        )

    def _turn_one_operations(
        self,
        document: OpportunityDocument,
        turn: _ScriptedTurn,
    ) -> list[dict[str, object]]:
        project = self._fixtures.project
        operations: list[dict[str, object]] = []
        if document.status.value != "refining":
            operations.append(self._set_field(turn.turn_id, "status", "refining"))
        operations.extend(
            [
                self._replace(turn.turn_id, "customerGoal", project.goals[0]),
                self._replace(
                    turn.turn_id,
                    "currentSituation",
                    project.current_capabilities[1],
                ),
                self._replace(
                    turn.turn_id,
                    "opportunityHypothesis",
                    turn.expected_focus[0],
                ),
            ]
        )
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "supportingSignals",
            project.signals[0],
        )
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "stakeholders",
            project.stakeholder_roles[0],
        )
        return operations

    def _turn_two_operations(
        self,
        document: OpportunityDocument,
        turn: _ScriptedTurn,
    ) -> list[dict[str, object]]:
        if document.opportunity_hypothesis is None:
            raise _context_failure()
        operations = [
            self._replace(
                turn.turn_id,
                "currentSituation",
                turn.expected_focus[0],
            )
        ]
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "supportingSignals",
            turn.expected_focus[0],
        )
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "assumptionsAndUncertainties",
            turn.expected_focus[1],
        )
        return operations

    def _turn_three_operations(
        self,
        document: OpportunityDocument,
        turn: _ScriptedTurn,
    ) -> list[dict[str, object]]:
        if document.opportunity_hypothesis is None or not document.supporting_signals:
            raise _context_failure()
        project = self._fixtures.project
        operations = [
            self._replace(
                turn.turn_id,
                "expectedValue",
                project.signals[1],
            ),
            self._replace(
                turn.turn_id,
                "confidenceAndRationale",
                project.unknowns[1],
            ),
            self._set_field(
                turn.turn_id,
                "status",
                "ready_for_validation",
            ),
        ]
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "missingEvidence",
            turn.expected_focus[1],
        )
        self._append_if_missing(
            operations,
            document,
            turn.turn_id,
            "recommendedNextActions",
            turn.expected_focus[0],
        )
        return operations

    @staticmethod
    def _set_field(turn_id: UUID, field: str, value: str) -> dict[str, object]:
        return {
            "operationId": str(uuid5(turn_id, f"set:{field}")),
            "op": "set_field",
            "field": field,
            "value": value,
        }

    @staticmethod
    def _replace(
        turn_id: UUID,
        section: str,
        value: ClassifiedText,
    ) -> dict[str, object]:
        return {
            "operationId": str(uuid5(turn_id, f"replace:{section}")),
            "op": "replace_section",
            "section": section,
            "value": value.model_dump(mode="json", by_alias=True),
        }

    @staticmethod
    def _append_if_missing(
        operations: list[dict[str, object]],
        document: OpportunityDocument,
        turn_id: UUID,
        section: str,
        value: ClassifiedText,
    ) -> None:
        attribute = {
            "supportingSignals": "supporting_signals",
            "stakeholders": "stakeholders",
            "assumptionsAndUncertainties": "assumptions_and_uncertainties",
            "missingEvidence": "missing_evidence",
            "recommendedNextActions": "recommended_next_actions",
        }[section]
        existing = getattr(document, attribute)
        if any(item.text == value.text for item in existing):
            return
        operations.append(
            {
                "operationId": str(uuid5(turn_id, f"append:{section}")),
                "op": "append_list_item",
                "section": section,
                "value": value.model_dump(mode="json", by_alias=True),
            }
        )


async def _apply_delay(
    work_input: DeepWorkInput,
    cancellation: CancellationToken,
) -> None:
    delay_seconds = work_input.controls.delay_ms / 1_000
    if delay_seconds == 0:
        return
    if work_input.controls.late_result:
        await asyncio.sleep(delay_seconds)
        return
    delay_task = asyncio.create_task(asyncio.sleep(delay_seconds))
    cancellation_task = asyncio.create_task(cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            {delay_task, cancellation_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (delay_task, cancellation_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(delay_task, cancellation_task, return_exceptions=True)
    if cancellation_task in done:
        raise DeepWorkCancelled("Deep work was cancelled.")


def _context_failure() -> DeepWorkFailure:
    return DeepWorkFailure(
        SanitizedError(
            code="conflict",
            category="document",
            message="The canonical document is missing required prior context.",
            retryable=False,
        )
    )


def _load_fixtures(fixture_root: Path) -> _FixtureBundle:
    with (fixture_root / "synthetic-project.json").open(encoding="utf-8") as stream:
        project = json.load(stream)
    with (fixture_root / "scripted-turns.json").open(encoding="utf-8") as stream:
        turns = json.load(stream)
    bundle = _FixtureBundle.model_validate({"project": project, "turns": turns})
    if tuple(turn.sequence for turn in bundle.turns) != (1, 2, 3):
        raise ValueError(
            "The deterministic fixture must contain exactly turns 1, 2, and 3."
        )
    if tuple(len(turn.expected_focus) for turn in bundle.turns) != (1, 2, 2):
        raise ValueError(
            "The deterministic fixture focus counts must match the three-turn script."
        )
    if len({turn.turn_id for turn in bundle.turns}) != 3:
        raise ValueError("The deterministic fixture turn identities must be unique.")
    return bundle

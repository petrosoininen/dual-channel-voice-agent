import type { AppCommand } from "./app-commands.ts";
import type {
  AppEvent,
  DocumentResultStatus,
  SanitizedError,
  VoiceStatus,
} from "./app-events.ts";
import type {
  ClassifiedText,
  DocumentListItem,
  DocumentPatchProposal,
  OpportunityDocument,
  SemanticOperation,
} from "./document.ts";

const MAX_WIRE_BYTES = 65_536;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const keys = Object.keys(value);
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => required.includes(key) || optional.includes(key))
  );
}

function isText(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.trim().length <= maximum
  );
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length <= maximum;
}

function isInteger(
  value: unknown,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    ) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isBoundedPayload(value: unknown): boolean {
  try {
    const serialized = JSON.stringify(value);
    return (
      typeof serialized === "string" &&
      new TextEncoder().encode(serialized).byteLength <= MAX_WIRE_BYTES
    );
  } catch {
    return false;
  }
}

function isClassification(
  value: unknown,
): value is ClassifiedText["classification"] {
  return (
    value === "synthetic_evidence" ||
    value === "inference" ||
    value === "unknown"
  );
}

function isClassifiedText(value: unknown): value is ClassifiedText {
  if (
    !isRecord(value) ||
    !hasKeys(value, ["text", "classification"], ["sourceLabel"]) ||
    !isText(value.text, 2_000) ||
    !isClassification(value.classification)
  ) {
    return false;
  }
  const source = value.sourceLabel;
  if (value.classification === "synthetic_evidence") {
    return isText(source, 120);
  }
  return source === undefined || source === null;
}

function isListItem(value: unknown): value is DocumentListItem {
  return (
    isRecord(value) &&
    hasKeys(value, ["itemId", "text", "classification"], ["sourceLabel"]) &&
    isUuid(value.itemId) &&
    isClassifiedText({
      text: value.text,
      classification: value.classification,
      ...(Object.hasOwn(value, "sourceLabel")
        ? { sourceLabel: value.sourceLabel }
        : {}),
    })
  );
}

function isList(
  value: unknown,
  maximum: number,
  predicate: (item: unknown) => boolean,
): value is readonly unknown[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every((item) => predicate(item))
  );
}

export function isOpportunityDocument(
  value: unknown,
): value is OpportunityDocument {
  const keys = [
    "documentId",
    "version",
    "title",
    "status",
    "customerGoal",
    "currentSituation",
    "opportunityHypothesis",
    "supportingSignals",
    "expectedValue",
    "stakeholders",
    "assumptionsAndUncertainties",
    "missingEvidence",
    "recommendedNextActions",
    "confidenceAndRationale",
  ];
  if (!isRecord(value) || !hasKeys(value, keys)) {
    return false;
  }
  const nullableClaim = (claim: unknown) =>
    claim === null || isClassifiedText(claim);
  return (
    isUuid(value.documentId) &&
    isInteger(value.version, 0) &&
    isText(value.title, 160) &&
    (value.status === "draft" ||
      value.status === "refining" ||
      value.status === "ready_for_validation") &&
    nullableClaim(value.customerGoal) &&
    nullableClaim(value.currentSituation) &&
    nullableClaim(value.opportunityHypothesis) &&
    isList(value.supportingSignals, 24, isListItem) &&
    nullableClaim(value.expectedValue) &&
    isList(value.stakeholders, 16, isListItem) &&
    isList(value.assumptionsAndUncertainties, 24, isListItem) &&
    isList(value.missingEvidence, 24, isListItem) &&
    isList(value.recommendedNextActions, 24, isListItem) &&
    nullableClaim(value.confidenceAndRationale)
  );
}

function isClaimSection(value: unknown): boolean {
  return [
    "customerGoal",
    "currentSituation",
    "opportunityHypothesis",
    "expectedValue",
    "confidenceAndRationale",
  ].includes(typeof value === "string" ? value : "");
}

function isListSection(value: unknown): boolean {
  return [
    "supportingSignals",
    "stakeholders",
    "assumptionsAndUncertainties",
    "missingEvidence",
    "recommendedNextActions",
  ].includes(typeof value === "string" ? value : "");
}

function isOperation(value: unknown): value is SemanticOperation {
  if (!isRecord(value) || !isUuid(value.operationId)) {
    return false;
  }
  switch (value.op) {
    case "set_field":
      return (
        hasKeys(value, ["operationId", "op", "field", "value"]) &&
        ((value.field === "title" && isText(value.value, 160)) ||
          (value.field === "status" &&
            (value.value === "draft" ||
              value.value === "refining" ||
              value.value === "ready_for_validation")))
      );
    case "replace_section":
      return (
        hasKeys(value, ["operationId", "op", "section", "value"]) &&
        isClaimSection(value.section) &&
        isClassifiedText(value.value)
      );
    case "append_list_item":
      return (
        hasKeys(value, ["operationId", "op", "section", "value"]) &&
        isListSection(value.section) &&
        isClassifiedText(value.value)
      );
    case "update_list_item":
      return (
        hasKeys(value, [
          "operationId",
          "op",
          "section",
          "itemId",
          "value",
        ]) &&
        isListSection(value.section) &&
        isUuid(value.itemId) &&
        isClassifiedText(value.value)
      );
    case "remove_list_item":
      return (
        hasKeys(value, ["operationId", "op", "section", "itemId"]) &&
        isListSection(value.section) &&
        isUuid(value.itemId)
      );
    default:
      return false;
  }
}

export function isDocumentPatchProposal(
  value: unknown,
): value is DocumentPatchProposal {
  if (
    !isBoundedPayload(value) ||
    !isRecord(value) ||
    !hasKeys(
      value,
      [
        "patchId",
        "sessionId",
        "turnId",
        "documentId",
        "baseVersion",
        "summary",
        "operations",
      ],
      ["reason"],
    ) ||
    !isUuid(value.patchId) ||
    !isUuid(value.sessionId) ||
    !isUuid(value.turnId) ||
    !isUuid(value.documentId) ||
    !isInteger(value.baseVersion, 0) ||
    !isText(value.summary, 500) ||
    !isList(value.operations, 32, isOperation)
  ) {
    return false;
  }
  const operationIds = value.operations
    .filter(isRecord)
    .map((operation) => operation.operationId);
  if (new Set(operationIds).size !== operationIds.length) {
    return false;
  }
  return value.operations.length === 0
    ? isText(value.reason, 240)
    : value.reason === undefined || value.reason === null;
}

function isEnvelope(value: Record<string, unknown>): boolean {
  return (
    isUuid(value.eventId) &&
    isUuid(value.idempotencyKey) &&
    isUuid(value.sessionId) &&
    isUuid(value.turnId) &&
    isTimestamp(value.timestamp)
  );
}

function eventKeys(...payload: string[]): readonly string[] {
  return [
    "eventId",
    "idempotencyKey",
    "sessionId",
    "turnId",
    "timestamp",
    "type",
    ...payload,
  ];
}

function isError(value: unknown): value is SanitizedError {
  return (
    isRecord(value) &&
    hasKeys(value, ["code", "category", "message", "retryable"]) &&
    [
      "validation_error",
      "conflict",
      "queue_full",
      "cancelled",
      "internal_error",
    ].includes(typeof value.code === "string" ? value.code : "") &&
    ["command", "turn", "voice", "document"].includes(
      typeof value.category === "string" ? value.category : "",
    ) &&
    isText(value.message, 240) &&
    typeof value.retryable === "boolean"
  );
}

function isVoiceStatus(value: unknown): value is VoiceStatus {
  return [
    "not_started",
    "speaking",
    "completed",
    "interrupted",
    "failed",
  ].includes(typeof value === "string" ? value : "");
}

function isDocumentStatus(value: unknown): value is DocumentResultStatus {
  return [
    "not_started",
    "pending",
    "committed",
    "no_op",
    "failed",
    "cancelled",
    "rejected",
  ].includes(typeof value === "string" ? value : "");
}

function isLabels(value: unknown): boolean {
  return (
    value === undefined ||
    (Array.isArray(value) &&
      value.length <= 16 &&
      value.every((label) => isText(label, 120)))
  );
}

export function isAppEvent(value: unknown): value is AppEvent {
  if (!isBoundedPayload(value) || !isRecord(value) || !isEnvelope(value)) {
    return false;
  }
  switch (value.type) {
    case "turn.started":
      return (
        hasKeys(value, eventKeys("sequence", "inputMode")) &&
        isInteger(value.sequence, 1) &&
        (value.inputMode === "typed" || value.inputMode === "voice")
      );
    case "turn.queued":
      return (
        hasKeys(value, eventKeys("position"), ["dependsOnTurnId"]) &&
        isInteger(value.position, 1, 3) &&
        (value.dependsOnTurnId === undefined ||
          value.dependsOnTurnId === null ||
          isUuid(value.dependsOnTurnId))
      );
    case "turn.rejected":
      return (
        hasKeys(value, eventKeys("reason", "queueDepth", "error")) &&
        isText(value.reason, 240) &&
        isInteger(value.queueDepth, 0, 4) &&
        isError(value.error)
      );
    case "turn.analysis.started":
      return (
        hasKeys(value, eventKeys("baseDocumentVersion")) &&
        isInteger(value.baseDocumentVersion, 0)
      );
    case "turn.analysis.cancelling":
    case "voice.started":
    case "voice.completed":
      return hasKeys(value, eventKeys());
    case "turn.analysis.cancelled":
      return (
        hasKeys(value, eventKeys("phase")) &&
        (value.phase === "queued" || value.phase === "running")
      );
    case "turn.analysis.completed":
      return (
        hasKeys(
        value,
        eventKeys("outcome", "summary", "documentVersion"),
        ["noOpReason"],
        ) &&
        (value.outcome === "committed" || value.outcome === "no_op") &&
        isText(value.summary, 240) &&
        isInteger(value.documentVersion, 0) &&
        (value.outcome === "no_op"
        ? isText(value.noOpReason, 240)
        : value.noOpReason === undefined || value.noOpReason === null)
      );
    case "voice.acknowledgment":
      return (
        hasKeys(value, eventKeys("intentSummary", "nextStep")) &&
        isText(value.intentSummary, 180) &&
        isText(value.nextStep, 180)
      );
    case "voice.interrupted":
      return (
        hasKeys(value, eventKeys("reason")) &&
        ["barge_in", "user_stop", "playback_error"].includes(
          typeof value.reason === "string" ? value.reason : "",
        )
      );
    case "document.pending":
      return (
        hasKeys(value, eventKeys("documentId", "title")) &&
        isUuid(value.documentId) &&
        isText(value.title, 160)
      );
    case "document.created":
      return (
        hasKeys(
          value,
          eventKeys(
            "documentId",
            "version",
            "document",
            "markdownProjection",
          ),
          ["sourceLabels"],
        ) &&
        isUuid(value.documentId) &&
        isInteger(value.version, 1) &&
        isOpportunityDocument(value.document) &&
        value.documentId === value.document.documentId &&
        value.version === value.document.version &&
        isBoundedString(value.markdownProjection, 16_000) &&
        isLabels(value.sourceLabels)
      );
    case "document.patch":
      return (
        hasKeys(
          value,
          eventKeys("documentId", "baseVersion", "version", "patch"),
        ) &&
        isUuid(value.documentId) &&
        isInteger(value.baseVersion, 0) &&
        isInteger(value.version, 1) &&
        isDocumentPatchProposal(value.patch) &&
        value.documentId === value.patch.documentId &&
        value.sessionId === value.patch.sessionId &&
        value.turnId === value.patch.turnId &&
        value.baseVersion === value.patch.baseVersion &&
        value.version === value.baseVersion + 1
      );
    case "document.committed":
      return (
        hasKeys(
          value,
          eventKeys(
            "documentId",
            "version",
            "document",
            "markdownProjection",
          ),
          ["sourceLabels", "restoredFromVersion"],
        ) &&
        isUuid(value.documentId) &&
        isInteger(value.version, 1) &&
        isOpportunityDocument(value.document) &&
        value.documentId === value.document.documentId &&
        value.version === value.document.version &&
        isBoundedString(value.markdownProjection, 16_000) &&
        isLabels(value.sourceLabels) &&
        (value.restoredFromVersion === undefined ||
          value.restoredFromVersion === null ||
          isInteger(value.restoredFromVersion, 1))
      );
    case "document.failed":
      return (
        hasKeys(value, eventKeys("documentId", "error")) &&
        isUuid(value.documentId) &&
        isError(value.error)
      );
    case "turn.completed":
      return (
        hasKeys(
          value,
          eventKeys("audioStatus", "documentStatus", "timings"),
        ) &&
        isVoiceStatus(value.audioStatus) &&
        isDocumentStatus(value.documentStatus) &&
        isTimings(value.timings)
      );
    default:
      return false;
  }
}

function isTimings(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasKeys(value, ["totalMs"], ["acknowledgmentMs", "documentMs"]) &&
    isInteger(value.totalMs, 0, 86_400_000) &&
    (value.acknowledgmentMs === undefined ||
      value.acknowledgmentMs === null ||
      isInteger(value.acknowledgmentMs, 0, 86_400_000)) &&
    (value.documentMs === undefined ||
      value.documentMs === null ||
      isInteger(value.documentMs, 0, 86_400_000))
  );
}

export function isAppCommand(value: unknown): value is AppCommand {
  if (
    !isBoundedPayload(value) ||
    !isRecord(value) ||
    !isUuid(value.commandId) ||
    !isUuid(value.idempotencyKey) ||
    !isUuid(value.sessionId) ||
    !isTimestamp(value.timestamp)
  ) {
    return false;
  }
  const envelope = [
    "commandId",
    "idempotencyKey",
    "sessionId",
    "timestamp",
    "type",
  ];
  switch (value.type) {
    case "turn.submit":
      return (
        hasKeys(value, [...envelope, "turnId", "inputMode", "transcript"]) &&
        isUuid(value.turnId) &&
        (value.inputMode === "typed" || value.inputMode === "voice") &&
        isText(value.transcript, 4_000)
      );
    case "turn.cancel":
      return (
        hasKeys(value, [...envelope, "turnId", "reason"]) &&
        isUuid(value.turnId) &&
        isText(value.reason, 240)
      );
    case "voice.interrupt":
      return (
        hasKeys(value, [...envelope, "turnId", "reason"]) &&
        isUuid(value.turnId) &&
        (value.reason === "barge_in" || value.reason === "user_stop")
      );
    case "voice.start":
    case "voice.complete":
      return (
        hasKeys(value, [...envelope, "turnId"]) && isUuid(value.turnId)
      );
    case "voice.acknowledge":
      return (
        hasKeys(value, [
          ...envelope,
          "turnId",
          "intentSummary",
          "nextStep",
        ]) &&
        isUuid(value.turnId) &&
        isText(value.intentSummary, 180) &&
        isText(value.nextStep, 180)
      );
    case "document.revert":
      return (
        hasKeys(value, [
          ...envelope,
          "turnId",
          "documentId",
          "targetVersion",
          "summary",
        ]) &&
        isUuid(value.turnId) &&
        isUuid(value.documentId) &&
        isInteger(value.targetVersion, 1) &&
        isText(value.summary, 500)
      );
    default:
      return false;
  }
}

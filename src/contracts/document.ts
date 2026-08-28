export type ClaimClassification =
  | "synthetic_evidence"
  | "inference"
  | "unknown";

export type DocumentStatus = "draft" | "refining" | "ready_for_validation";

export interface ClassifiedText {
  readonly text: string;
  readonly classification: ClaimClassification;
  readonly sourceLabel?: string | null;
}

export interface DocumentListItem extends ClassifiedText {
  readonly itemId: string;
}

export interface OpportunityDocument {
  readonly documentId: string;
  readonly version: number;
  readonly title: string;
  readonly status: DocumentStatus;
  readonly customerGoal: ClassifiedText | null;
  readonly currentSituation: ClassifiedText | null;
  readonly opportunityHypothesis: ClassifiedText | null;
  readonly supportingSignals: readonly DocumentListItem[];
  readonly expectedValue: ClassifiedText | null;
  readonly stakeholders: readonly DocumentListItem[];
  readonly assumptionsAndUncertainties: readonly DocumentListItem[];
  readonly missingEvidence: readonly DocumentListItem[];
  readonly recommendedNextActions: readonly DocumentListItem[];
  readonly confidenceAndRationale: ClassifiedText | null;
}

export type ClaimSection =
  | "customerGoal"
  | "currentSituation"
  | "opportunityHypothesis"
  | "expectedValue"
  | "confidenceAndRationale";

export type ListSection =
  | "supportingSignals"
  | "stakeholders"
  | "assumptionsAndUncertainties"
  | "missingEvidence"
  | "recommendedNextActions";

export interface SetFieldOperation {
  readonly operationId: string;
  readonly op: "set_field";
  readonly field: "title" | "status";
  readonly value: string;
}

export interface ReplaceSectionOperation {
  readonly operationId: string;
  readonly op: "replace_section";
  readonly section: ClaimSection;
  readonly value: ClassifiedText;
}

export interface AppendListItemOperation {
  readonly operationId: string;
  readonly op: "append_list_item";
  readonly section: ListSection;
  readonly value: ClassifiedText;
}

export interface UpdateListItemOperation {
  readonly operationId: string;
  readonly op: "update_list_item";
  readonly section: ListSection;
  readonly itemId: string;
  readonly value: ClassifiedText;
}

export interface RemoveListItemOperation {
  readonly operationId: string;
  readonly op: "remove_list_item";
  readonly section: ListSection;
  readonly itemId: string;
}

export type SemanticOperation =
  | SetFieldOperation
  | ReplaceSectionOperation
  | AppendListItemOperation
  | UpdateListItemOperation
  | RemoveListItemOperation;

export interface DocumentPatchProposal {
  readonly patchId: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly documentId: string;
  readonly baseVersion: number;
  readonly summary: string;
  readonly operations: readonly SemanticOperation[];
  readonly reason?: string | null;
}

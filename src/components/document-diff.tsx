import type { DocumentPatchProposal } from "../contracts/document.ts";

interface DocumentDiffProps {
  readonly patch: DocumentPatchProposal | null;
}

export function DocumentDiff({ patch }: DocumentDiffProps) {
  if (patch === null) {
    return <p className="diff-restored">Restored a complete prior snapshot.</p>;
  }
  return (
    <div className="diff-block">
      <p>{patch.summary}</p>
      <ul>
        {patch.operations.map((operation) => (
          <li key={operation.operationId}>
            <code>{operation.op.replaceAll("_", " ")}</code>
            {"section" in operation ? ` · ${operation.section}` : ""}
            {"field" in operation ? ` · ${operation.field}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

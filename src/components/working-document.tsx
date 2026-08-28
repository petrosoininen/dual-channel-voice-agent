import { parseSafeMarkdown } from "../lib/safe-markdown.ts";
import type { ConversationState } from "../state/conversation-store.ts";
import { VersionHistory } from "./version-history.tsx";

interface WorkingDocumentProps {
  readonly state: ConversationState;
  readonly onRevert: (version: number) => void;
}

export function WorkingDocument({
  state,
  onRevert,
}: WorkingDocumentProps) {
  const blocks =
    state.markdownProjection === null
      ? []
      : parseSafeMarkdown(state.markdownProjection);
  return (
    <section className="document-panel" aria-labelledby="document-heading">
      <div className="section-heading document-heading">
        <div>
          <p className="section-kicker">Canonical artifact</p>
          <h2 id="document-heading">Working document</h2>
        </div>
        <span className="version-pill">
          {state.document ? `Version ${state.document.version}` : "Awaiting analysis"}
        </span>
      </div>
      <p className="trust-note">
        Decision support generated from synthetic inputs. Evidence, inference,
        and unknowns remain explicitly classified.
      </p>
      {blocks.length === 0 ? (
        <div className="document-empty">
          <p>One cumulative opportunity analysis will appear here.</p>
          <span>Committed text survives voice interruption.</span>
        </div>
      ) : (
        <article className="markdown-projection">
          {blocks.map((block, index) => {
            const key = `${block.type}-${index}`;
            if (block.type === "heading") {
              return block.level === 1 ? (
                <h3 key={key}>{block.text}</h3>
              ) : (
                <h4 key={key}>{block.text}</h4>
              );
            }
            if (block.type === "list") {
              return (
                <ul key={key}>
                  {block.items.map((item, itemIndex) => (
                    <li key={`${key}-${itemIndex}`}>{item}</li>
                  ))}
                </ul>
              );
            }
            return <p key={key}>{block.text}</p>;
          })}
        </article>
      )}
      <VersionHistory
        versions={state.versions}
        currentVersion={state.document?.version ?? null}
        onRevert={onRevert}
      />
    </section>
  );
}

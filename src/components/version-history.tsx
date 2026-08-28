import type { DocumentSnapshot } from "../state/conversation-store.ts";
import { DocumentDiff } from "./document-diff.tsx";

interface VersionHistoryProps {
  readonly versions: readonly DocumentSnapshot[];
  readonly currentVersion: number | null;
  readonly onRevert: (version: number) => void;
}

export function VersionHistory({
  versions,
  currentVersion,
  onRevert,
}: VersionHistoryProps) {
  return (
    <details className="version-history">
      <summary>
        Version history <span>{versions.length}</span>
      </summary>
      <ol>
        {[...versions].reverse().map((version) => (
          <li key={version.version}>
            <div className="version-row">
              <strong>
                Version {version.version}
                {version.version === currentVersion ? " · current" : ""}
              </strong>
              {version.version !== currentVersion ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onRevert(version.version)}
                >
                  Restore as new version
                </button>
              ) : null}
            </div>
            {version.restoredFromVersion ? (
              <p>Restored from version {version.restoredFromVersion}.</p>
            ) : null}
            <DocumentDiff patch={version.patch} />
          </li>
        ))}
      </ol>
    </details>
  );
}

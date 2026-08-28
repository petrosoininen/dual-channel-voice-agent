export type SafeMarkdownBlock =
  | { readonly type: "heading"; readonly level: 1 | 2; readonly text: string }
  | { readonly type: "paragraph"; readonly text: string }
  | { readonly type: "list"; readonly items: readonly string[] };

const RAW_OR_ACTIVE_CONTENT = /[<>]|\[[^\]]*\]\([^)]*\)|!\[[^\]]*\]|`|&(?:#\d+|#x[\da-f]+|\w+);/i;

export function parseSafeMarkdown(value: unknown): readonly SafeMarkdownBlock[] {
  if (typeof value !== "string" || value.length > 16_000) {
    throw new Error("Markdown projection is invalid.");
  }
  if (RAW_OR_ACTIVE_CONTENT.test(value)) {
    throw new Error("Raw or active Markdown content is not allowed.");
  }
  const blocks: SafeMarkdownBlock[] = [];
  let listItems: string[] = [];
  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: "list", items: listItems });
      listItems = [];
    }
  };

  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === "") {
      flushList();
      continue;
    }
    if (line.startsWith("###") || /^[-*+]\s*$/.test(line)) {
      throw new Error("Markdown syntax is outside the constrained subset.");
    }
    if (line.startsWith("# ")) {
      flushList();
      blocks.push({ type: "heading", level: 1, text: boundedText(line.slice(2)) });
    } else if (line.startsWith("## ")) {
      flushList();
      blocks.push({ type: "heading", level: 2, text: boundedText(line.slice(3)) });
    } else if (line.startsWith("- ")) {
      listItems.push(boundedText(line.slice(2)));
    } else if (/^[#>*+]/.test(line) || /^\d+\.\s/.test(line)) {
      throw new Error("Markdown syntax is outside the constrained subset.");
    } else {
      flushList();
      blocks.push({ type: "paragraph", text: boundedText(line) });
    }
  }
  flushList();
  if (blocks.length === 0) {
    throw new Error("Markdown projection is empty.");
  }
  return blocks;
}

function boundedText(value: string): string {
  const text = value.trim();
  if (text.length === 0 || text.length > 2_000) {
    throw new Error("Markdown text is outside allowed bounds.");
  }
  return text;
}

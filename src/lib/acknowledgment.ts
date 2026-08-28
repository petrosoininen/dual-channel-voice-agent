const AUTHORITATIVE_CLAIMS = [
  /\b(?:I|we)(?:'ve| have)?\s+(?:found|identified|determined|concluded|recommend)\b/i,
  /\b(?:the|your)\s+(?:best|strongest|primary)\s+\w+(?:\s+\w+){0,3}\s+is\b/i,
  /\b(?:evidence|signals?|analysis|data)\s+(?:shows?|proves?|confirms?|indicates?|demonstrates?)\b/i,
  /\b(?:I am|I'm|we are|we're)\s+confident\b/i,
  /\b(?:will|is going to)\s+(?:deliver|guarantee|increase|reduce|improve)\b/i,
  /\b(?:I|we)(?:'ve| have)\s+(?:completed|finished|updated)\b/i,
] as const;

const ACKNOWLEDGMENT_OPENING =
  /^(?:understood|got it|okay|ok|certainly|absolutely|sure|thanks|thank you|sounds good|I understand|I hear|I'll|I will|I can|let's)\b/i;

const PROCESS_STEP =
  /\b(?:I'll|I’ll|I will|I can|we'll|we’ll|we will|next|now|then|let's|analy[sz]e|review|focus|refine|examine|assess|compare|explore|check|synthesize|identify|update|continue)\b/i;

export function isConstrainedAcknowledgment(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const text = value.trim().replace(/\s+/g, " ");
  if (
    text.length === 0 ||
    text.length > 360 ||
    !ACKNOWLEDGMENT_OPENING.test(text) ||
    !PROCESS_STEP.test(text) ||
    AUTHORITATIVE_CLAIMS.some((pattern) => pattern.test(text))
  ) {
    return false;
  }
  return text.split(/(?<=[.!?])\s+/).filter(Boolean).length <= 2;
}

import { mkdir, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { setTimeout as wait } from "node:timers/promises";
import { dirname, resolve } from "node:path";

import { isConstrainedAcknowledgment } from "../src/lib/acknowledgment.ts";

const outputPath = resolve(
  process.argv[2] ?? "test-results/acknowledgment-latency.json",
);
const acknowledgments = [
  "I understand the request. Next, I will review the synthetic context.",
  "I hear the follow-up. Now I will assess the synthetic signals and unknowns.",
  "I understand the refinement request. Next, I will compare the synthetic context and gaps.",
];
const samples = [];

for (let sample = 1; sample <= 10; sample += 1) {
  const acknowledgment = acknowledgments[(sample - 1) % acknowledgments.length];
  const started = performance.now();
  await wait(1);
  if (!isConstrainedAcknowledgment(acknowledgment)) {
    throw new Error("The deterministic acknowledgment contract was rejected.");
  }
  samples.push({
    sample,
    acknowledgmentMs: Number((performance.now() - started).toFixed(3)),
  });
}

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(
  outputPath,
  `${JSON.stringify(
    {
      kind: "deterministic_local_acknowledgment_handling",
      voiceLiveAudioLatency: false,
      thresholdApplied: false,
      authorityShapesValidated: acknowledgments.length,
      samples,
    },
    null,
    2,
  )}\n`,
  "utf8",
);
console.log(`Recorded ${samples.length} content-free local timing samples.`);

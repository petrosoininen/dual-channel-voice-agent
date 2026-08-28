import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  isAppCommand,
  isAppEvent,
  isDocumentPatchProposal,
} from "../../src/contracts/validators.ts";
import {
  applyAppEvent,
  emptyConversationState,
} from "../../src/state/conversation-store.ts";

const fixturesRoot = new URL("../../contracts/fixtures/", import.meta.url);

async function cases(name) {
  return JSON.parse(await readFile(new URL(name, fixturesRoot), "utf8"));
}

for (const [name, validator] of [
  ["valid-events.json", isAppEvent],
  ["valid-commands.json", isAppCommand],
  ["valid-patches.json", isDocumentPatchProposal],
]) {
  test(`accepts every shared ${name}`, async () => {
    for (const fixture of await cases(name)) {
      assert.equal(validator(fixture.input), true, fixture.name);
    }
  });
}

for (const [name, validator] of [
  ["invalid-events.json", isAppEvent],
  ["invalid-commands.json", isAppCommand],
  ["invalid-patches.json", isDocumentPatchProposal],
]) {
  test(`rejects every shared ${name}`, async () => {
    for (const fixture of await cases(name)) {
      assert.equal(validator(fixture.input), false, fixture.name);
    }
  });
}

test("rejects oversized payloads", async () => {
  const [fixture] = await cases("valid-commands.json");
  assert.equal(
    isAppCommand({ ...fixture.input, transcript: "x".repeat(70_000) }),
    false,
  );
});

test("frontend event application is idempotent and starts empty", async () => {
  const [fixture] = await cases("valid-events.json");
  const empty = emptyConversationState();
  const once = applyAppEvent(empty, fixture.input);
  const twice = applyAppEvent(once, fixture.input);

  assert.equal(empty.turns.length, 0);
  assert.equal(once.turns.length, 1);
  assert.equal(twice, once);
  assert.throws(
    () => applyAppEvent(once, { ...fixture.input, sequence: 2 }),
    /reused with different content/,
  );
});

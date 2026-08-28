import {
  AzureVoiceLiveClient,
  type AzureVoiceLiveClientOptions,
} from "./azure-voice-live.ts";
import { DisabledVoiceClient } from "./disabled.ts";
import type { VoiceClient, VoiceProvider } from "./types.ts";

export function createVoiceClient(
  provider: VoiceProvider,
  options: AzureVoiceLiveClientOptions,
): VoiceClient {
  if (provider === "azure-voice-live") {
    return new AzureVoiceLiveClient(options);
  }
  return new DisabledVoiceClient(options);
}

# Run the reference

## Before you begin

The primary flow is **bring your own**. You need an authorized Azure subscription,
supported region/model quota, Azure Voice Live access, and Azure Foundry Agent Service.
Review [Azure setup](azure-setup.md), cost, preview status, and cleanup first.

Do not put real values in tracked files. Use ignored `.env` or an external environment
file.

## Provision and bootstrap

1. Select [Bicep or Terraform](../infra/README.md).
2. Preview the complete plan before applying it.
3. Apply only to a newly generated ephemeral resource group.
4. Map the public outputs to:

   ```text
   VOICE_PROVIDER=azure-voice-live
   AGENT_PROVIDER=foundry
   AZURE_TOKEN_CREDENTIALS=AzureCliCredential
   AZURE_TENANT_ID=<tenant-id>
   AZURE_VOICE_LIVE_ENDPOINT=<voice-endpoint>
   AZURE_VOICE_LIVE_MODEL=<supported-voice-model>
   FOUNDRY_PROJECT_ENDPOINT=<project-endpoint>
   FOUNDRY_MODEL_DEPLOYMENT=<agent-model-deployment>
   FOUNDRY_AGENT_NAME=<agent-name>
   ```

5. Preview and apply the shared bootstrap:

   ```text
   python -m scripts.bootstrap_agent --env-file <path>
   python -m scripts.bootstrap_agent --apply --env-file <path> --binding-file <path>
   ```

The bootstrap reuses a compatible immutable agent version or creates one. It never
prints configured values and updates only the selected ignored/external binding file.

## Preflight

```text
python -m scripts.doctor --env-file <path>
python -m scripts.preflight_azure
python -m scripts.preflight_foundry
```

The standalone preflight scripts read process environment; load the external file in
your shell first when it is not `.env`. Outputs contain booleans, missing variable
names, counts, and coarse error classes only.

## Start

```text
python -m scripts.run_backend --voice-provider azure-voice-live --agent-provider foundry --env-file <path>
npm run dev
```

Open the loopback URL printed by Vite. Allow microphone access only when you intend to
run the live voice path.

For credential-free executable documentation:

```text
python -m scripts.run_backend --voice-provider off --agent-provider deterministic
npm run dev
```

## Three turns

Submit these synthetic turns in order:

1. "Review this project and identify the strongest expansion opportunity."
2. "Focus on the operational pain behind that opportunity and strengthen the
   supporting signals."
3. "Refine the value proposition, list the missing evidence, and give me the next
   customer action."

Expected application behavior:

- each voice response acknowledges intent and a next step without asserting findings;
- later turns can queue while prior deep work is active;
- one document advances through versions 1, 2, and 3;
- each commit has an inspectable diff;
- interruption stops playback without deleting committed text;
- a revert creates a new restoring version;
- backend restart deletes the session.

## Troubleshooting

| Symptom | Safe check |
| --- | --- |
| Startup rejects configuration | Run `scripts.doctor`; fix only named variables |
| Voice unavailable | Recheck current region/model support, role, preview terms, and browser permission |
| Agent unavailable | Recheck project role, model deployment, bootstrap, and sanitized preflight |
| Queue full | Wait or cancel a pending/running deep task |
| Provider conversation lost | Start a fresh application session; no silent replacement occurs |
| Browser state stale after restart | The client should create a fresh session on close code `4404` |

Never paste tokens, endpoints, IDs, raw provider errors, or transcripts into an issue.

## Stop and clean up

Stop the local processes. Then follow the exact destroy procedure for the IaC path that
created the environment. Verify that the resource group is absent. Do not delete any
pre-existing group or resource.

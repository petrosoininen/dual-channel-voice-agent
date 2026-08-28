# Azure prerequisites with Bicep or Terraform

Both implementations create the same logical management-plane prerequisites. Prompt
Agent creation is performed afterward by the shared `scripts/bootstrap_agent.py`.

## Safety

- Use a newly generated suffix and a new ephemeral resource group.
- Keep real inputs, outputs, plans, state, and logs in an ignored or external directory.
- Resolve current role definition IDs by role name at run time.
- Preview before apply.
- Apply/destroy only after explicit authorization.
- Never point this workflow at a pre-existing resource group.
- Verify deletion before recording sanitized evidence.

## Inputs and outputs

The common input contract is documented in `logical-contract.json`. It covers location,
environment label, unique suffix, agent model choices, Voice Live model, operator/runtime
principals and types, built-in role definitions, capacity, and tags.

Both paths output the generated group/account/project/model-deployment names plus public
Voice Live and project endpoints and Voice Live model selection. Outputs are not secrets,
but real values remain private environment metadata and must not be committed.

## Bicep

Prepare a real parameter file outside the repository from
`bicep/main.parameters.example.json`.

```text
az bicep build --file infra/bicep/main.bicep --stdout
az bicep lint --file infra/bicep/main.bicep
az deployment sub what-if --location <deployment-region> --template-file infra/bicep/main.bicep --parameters <external-parameters>
az deployment sub create --location <deployment-region> --template-file infra/bicep/main.bicep --parameters <external-parameters>
```

Capture outputs only into the ignored/external environment file. After bootstrap and
smoke tests, resolve the exact created group and delete only that group:

```text
az group delete --name <created-group> --yes
az group exists --name <created-group>
```

Deletion verification succeeds only when the final command returns `false`.

## Terraform

Copy `terraform/terraform.tfvars.example` outside the repository and replace every
placeholder. Keep the working directory/state in an ignored or external validation
directory when running a release test.

```text
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -var-file=<external-inputs> -out=<external-plan>
terraform -chdir=infra/terraform apply <external-plan>
```

After bootstrap and smoke tests:

```text
terraform -chdir=infra/terraform destroy -var-file=<external-inputs>
az group exists --name <created-group>
```

If provider cleanup leaves the group, delete only the exact generated group after
resolving its ID and confirming it belongs to this run. Verify absence.

## Shared post-deployment flow

1. Map outputs and Azure tenant selection to an ignored/external environment file.
2. Preview and apply `scripts/bootstrap_agent.py`.
3. Run `scripts/doctor.py`, Azure preflight, and Foundry preflight.
4. Start the browser reference and complete the three synthetic turns where provider
   access permits.
5. Destroy and verify absence.
6. Update only `docs/evidence/tenant-validation.md` with sanitized results.

## Preview, cost, and availability

Voice Live WebRTC is preview. Voice Live usage and model deployments can incur charges.
Region/model support and quota are volatile. Use current links in `docs/azure-setup.md`;
do not treat example inputs as an availability guarantee.

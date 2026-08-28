# Infrastructure instructions

The root `AGENTS.md` applies. Additionally:

- Always check current region, model, quota, policy, and provider registration before
  previewing a deployment.
- Always run Bicep build/lint and Terraform format/init/validate before what-if/plan.
- Keep Bicep and Terraform parameters, logical resources, roles, and outputs equivalent.
- Keep Prompt Agent creation in `scripts/bootstrap_agent.py`; do not add deployment
  scripts or Terraform provisioners for data-plane bootstrap.
- Store real parameters, plans, state, outputs, names, identifiers, and logs only in
  ignored or external locations.
- Require explicit authorization before apply or destroy.
- Create uniquely named ephemeral resource groups and resolve their exact IDs before
  cleanup.
- Never delete a group that was not created by the current validation run.
- Verify deletion and record only sanitized evidence.

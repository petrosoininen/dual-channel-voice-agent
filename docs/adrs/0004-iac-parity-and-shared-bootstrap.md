# ADR 0004: IaC parity and shared bootstrap

Status: Accepted

Bicep and Terraform implement one logical management-plane contract: isolated group,
AIServices account, project, model deployment, roles, and public outputs. Prompt Agent
creation is a shared confirmation-gated data-plane bootstrap so neither IaC path embeds
duplicated imperative logic.

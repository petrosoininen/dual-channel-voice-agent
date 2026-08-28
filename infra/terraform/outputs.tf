output "resource_group_name" {
  description = "Generated resource group name."
  value       = azurerm_resource_group.reference.name
}

output "account_name" {
  description = "Generated AIServices account name."
  value       = azurerm_cognitive_account.reference.name
}

output "project_name" {
  description = "Generated Foundry project name."
  value       = azapi_resource.project.name
}

output "agent_model_deployment_name" {
  description = "Generated Prompt Agent model deployment name."
  value       = azurerm_cognitive_deployment.agent.name
}

output "voice_endpoint" {
  description = "Public endpoint used by the keyless Voice Live broker."
  value       = azurerm_cognitive_account.reference.endpoint
}

output "voice_live_model" {
  description = "Fully managed Voice Live model selection."
  value       = var.voice_live_model
}

output "foundry_project_endpoint" {
  description = "Public project endpoint used by the Prompt Agent client."
  value       = "https://${azurerm_cognitive_account.reference.name}.services.ai.azure.com/api/projects/${azapi_resource.project.name}"
}

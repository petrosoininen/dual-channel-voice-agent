locals {
  normalized_environment = lower(var.environment_label)
  normalized_suffix      = lower(var.unique_suffix)
  name_token             = "${replace(local.normalized_environment, "-", "")}${local.normalized_suffix}"
  resource_group_name    = "rg-dual-voice-${local.normalized_environment}-${local.normalized_suffix}"
  account_name           = "dvoice${substr(local.name_token, 0, 20)}"
  project_name           = "dvoice-${substr(local.name_token, 0, 20)}"
  model_deployment_name  = "agent-${substr(local.name_token, 0, 20)}"
  common_tags = merge(var.tags, {
    application = "dual-channel-voice-agent-pattern"
    environment = local.normalized_environment
    lifecycle   = "ephemeral-validation"
  })
}

resource "azurerm_resource_group" "reference" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_cognitive_account" "reference" {
  name                = local.account_name
  location            = azurerm_resource_group.reference.location
  resource_group_name = azurerm_resource_group.reference.name
  kind                = "AIServices"
  sku_name            = "S0"

  custom_subdomain_name              = local.account_name
  local_auth_enabled                 = false
  project_management_enabled         = true
  public_network_access_enabled      = true
  outbound_network_access_restricted = false

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags
}

resource "azapi_resource" "project" {
  type      = "Microsoft.CognitiveServices/accounts/projects@2026-05-01"
  name      = local.project_name
  parent_id = azurerm_cognitive_account.reference.id
  location  = azurerm_resource_group.reference.location

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      displayName = "Dual-channel voice agent reference"
      description = "Ephemeral project for a bring-your-own reference deployment."
    }
  }

  tags = local.common_tags
}

resource "azurerm_cognitive_deployment" "agent" {
  name                 = local.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.reference.id

  model {
    format  = var.agent_model_format
    name    = var.agent_model_name
    version = var.agent_model_version == "" ? null : var.agent_model_version
  }

  sku {
    name     = var.agent_model_sku
    capacity = var.agent_model_capacity
  }

  version_upgrade_option = "OnceNewDefaultVersionAvailable"
}

resource "azurerm_role_assignment" "operator_voice" {
  scope              = azurerm_cognitive_account.reference.id
  role_definition_id = var.voice_user_role_definition_id
  principal_id       = var.operator_principal_id
  principal_type     = var.operator_principal_type
}

resource "azurerm_role_assignment" "runtime_voice" {
  count = var.runtime_principal_id == var.operator_principal_id ? 0 : 1

  scope              = azurerm_cognitive_account.reference.id
  role_definition_id = var.voice_user_role_definition_id
  principal_id       = var.runtime_principal_id
  principal_type     = var.runtime_principal_type
}

resource "azurerm_role_assignment" "operator_project" {
  scope              = azapi_resource.project.id
  role_definition_id = var.foundry_project_manager_role_definition_id
  principal_id       = var.operator_principal_id
  principal_type     = var.operator_principal_type
}

resource "azurerm_role_assignment" "runtime_project" {
  scope              = azapi_resource.project.id
  role_definition_id = var.foundry_user_role_definition_id
  principal_id       = var.runtime_principal_id
  principal_type     = var.runtime_principal_type
}

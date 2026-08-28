variable "location" {
  description = "Azure region selected after checking current Voice Live, Foundry, policy, and quota support."
  type        = string
}

variable "environment_label" {
  description = "Short lowercase label such as dev or validation."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,11}$", var.environment_label))
    error_message = "Use 2-12 lowercase letters, numbers, or single hyphens."
  }
}

variable "unique_suffix" {
  description = "Lowercase alphanumeric suffix unique to this disposable environment."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6,16}$", var.unique_suffix))
    error_message = "Use 6-16 lowercase letters or numbers."
  }
}

variable "agent_model_name" {
  description = "Foundry catalog model used by the Prompt Agent."
  type        = string
}

variable "agent_model_version" {
  description = "Optional exact model version. Empty selects the service default."
  type        = string
  default     = ""
}

variable "agent_model_format" {
  description = "Model publisher format returned by the account model catalog."
  type        = string
  default     = "OpenAI"
}

variable "agent_model_sku" {
  description = "Deployment SKU verified against current regional quota."
  type        = string
  default     = "GlobalStandard"
}

variable "agent_model_capacity" {
  description = "Model deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 30

  validation {
    condition     = var.agent_model_capacity >= 1
    error_message = "Capacity must be at least one."
  }
}

variable "voice_live_model" {
  description = "Fully managed Voice Live model selected from the current regional support table."
  type        = string
}

variable "operator_principal_id" {
  description = "Object ID of the principal that runs previews, deployment, and agent bootstrap."
  type        = string
  sensitive   = true
}

variable "operator_principal_type" {
  description = "Principal type for operator role assignments."
  type        = string

  validation {
    condition     = contains(["User", "ServicePrincipal"], var.operator_principal_type)
    error_message = "Principal type must be User or ServicePrincipal."
  }
}

variable "runtime_principal_id" {
  description = "Object ID of the principal that runs the local reference application."
  type        = string
  sensitive   = true
}

variable "runtime_principal_type" {
  description = "Principal type for runtime role assignments."
  type        = string

  validation {
    condition     = contains(["User", "ServicePrincipal"], var.runtime_principal_type)
    error_message = "Principal type must be User or ServicePrincipal."
  }
}

variable "voice_user_role_definition_id" {
  description = "Full built-in role definition ID used for keyless Voice Live access."
  type        = string
  sensitive   = true
}

variable "foundry_project_manager_role_definition_id" {
  description = "Full built-in role definition ID used to create and version Prompt Agents."
  type        = string
  sensitive   = true
}

variable "foundry_user_role_definition_id" {
  description = "Full built-in role definition ID used to run Prompt Agents."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Additional non-sensitive tags applied to every supported resource."
  type        = map(string)
  default     = {}
}

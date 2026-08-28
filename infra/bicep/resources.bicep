targetScope = 'resourceGroup'

param location string
param environmentLabel string
param uniqueSuffix string
param agentModelName string
param agentModelVersion string
param agentModelFormat string
param agentModelSku string
param agentModelCapacity int
param voiceLiveModel string
param operatorPrincipalId string
param operatorPrincipalType string
param runtimePrincipalId string
param runtimePrincipalType string
param voiceUserRoleDefinitionId string
param foundryProjectManagerRoleDefinitionId string
param foundryUserRoleDefinitionId string
param tags object

var nameToken = '${replace(environmentLabel, '-', '')}${replace(uniqueSuffix, '-', '')}'
var accountName = 'dvoice${take(nameToken, 20)}'
var projectName = 'dvoice-${take(nameToken, 20)}'
var agentModelDeploymentName = 'agent-${take(nameToken, 20)}'
var agentModel = empty(agentModelVersion)
  ? {
      format: agentModelFormat
      name: agentModelName
    }
  : {
      format: agentModelFormat
      name: agentModelName
      version: agentModelVersion
    }

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    restrictOutboundNetworkAccess: false
  }
  tags: tags
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Dual-channel voice agent reference'
    description: 'Ephemeral project for a bring-your-own reference deployment.'
  }
  tags: tags
}

resource agentModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: agentModelDeploymentName
  properties: {
    model: agentModel
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  sku: {
    name: agentModelSku
    capacity: agentModelCapacity
  }
}

resource operatorVoiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, operatorPrincipalId, voiceUserRoleDefinitionId)
  scope: account
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: voiceUserRoleDefinitionId
  }
}

resource runtimeVoiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (runtimePrincipalId != operatorPrincipalId) {
  name: guid(account.id, runtimePrincipalId, voiceUserRoleDefinitionId)
  scope: account
  properties: {
    principalId: runtimePrincipalId
    principalType: runtimePrincipalType
    roleDefinitionId: voiceUserRoleDefinitionId
  }
}

resource operatorProjectRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, operatorPrincipalId, foundryProjectManagerRoleDefinitionId)
  scope: project
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: foundryProjectManagerRoleDefinitionId
  }
}

resource runtimeProjectRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, runtimePrincipalId, foundryUserRoleDefinitionId)
  scope: project
  properties: {
    principalId: runtimePrincipalId
    principalType: runtimePrincipalType
    roleDefinitionId: foundryUserRoleDefinitionId
  }
}

output accountName string = account.name
output projectName string = project.name
output agentModelDeploymentName string = agentModelDeployment.name
output voiceEndpoint string = account.properties.endpoint
output voiceLiveModel string = voiceLiveModel
output foundryProjectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'

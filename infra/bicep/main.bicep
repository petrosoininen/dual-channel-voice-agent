targetScope = 'subscription'

@description('Azure region selected after checking current Voice Live, Foundry, policy, and quota support.')
param location string

@description('Short lowercase label such as dev or validation.')
@minLength(2)
@maxLength(12)
param environmentLabel string

@description('Lowercase alphanumeric suffix unique to this disposable environment.')
@minLength(6)
@maxLength(16)
param uniqueSuffix string

@description('Foundry catalog model used by the Prompt Agent.')
param agentModelName string

@description('Optional exact model version. Leave empty to let the service select its current default.')
param agentModelVersion string = ''

@description('Model publisher format returned by the account model catalog.')
param agentModelFormat string = 'OpenAI'

@description('Deployment SKU verified against current regional quota.')
param agentModelSku string = 'GlobalStandard'

@description('Model deployment capacity in thousands of tokens per minute.')
@minValue(1)
param agentModelCapacity int = 30

@description('Fully managed Voice Live model selected from the current regional support table.')
param voiceLiveModel string

@description('Object ID of the principal that runs previews, deployment, and agent bootstrap.')
param operatorPrincipalId string

@description('Principal type for the operator role assignments.')
@allowed([
  'User'
  'ServicePrincipal'
])
param operatorPrincipalType string

@description('Object ID of the principal that runs the local reference application.')
param runtimePrincipalId string

@description('Principal type for the runtime role assignments.')
@allowed([
  'User'
  'ServicePrincipal'
])
param runtimePrincipalType string

@description('Full built-in role definition ID used for keyless Voice Live access.')
param voiceUserRoleDefinitionId string

@description('Full built-in role definition ID used to create and version Prompt Agents.')
param foundryProjectManagerRoleDefinitionId string

@description('Full built-in role definition ID used to run Prompt Agents.')
param foundryUserRoleDefinitionId string

@description('Additional non-sensitive tags applied to every supported resource.')
param tags object = {}

var normalizedEnvironment = toLower(environmentLabel)
var normalizedSuffix = toLower(uniqueSuffix)
var resourceGroupName = 'rg-dual-voice-${normalizedEnvironment}-${normalizedSuffix}'
var commonTags = union(tags, {
  application: 'dual-channel-voice-agent-pattern'
  environment: normalizedEnvironment
  lifecycle: 'ephemeral-validation'
})

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: resourceGroupName
  location: location
  tags: commonTags
}

module referenceResources './resources.bicep' = {
  name: 'dual-channel-reference'
  scope: resourceGroup
  params: {
    location: location
    environmentLabel: normalizedEnvironment
    uniqueSuffix: normalizedSuffix
    agentModelName: agentModelName
    agentModelVersion: agentModelVersion
    agentModelFormat: agentModelFormat
    agentModelSku: agentModelSku
    agentModelCapacity: agentModelCapacity
    voiceLiveModel: voiceLiveModel
    operatorPrincipalId: operatorPrincipalId
    operatorPrincipalType: operatorPrincipalType
    runtimePrincipalId: runtimePrincipalId
    runtimePrincipalType: runtimePrincipalType
    voiceUserRoleDefinitionId: voiceUserRoleDefinitionId
    foundryProjectManagerRoleDefinitionId: foundryProjectManagerRoleDefinitionId
    foundryUserRoleDefinitionId: foundryUserRoleDefinitionId
    tags: commonTags
  }
}

output resourceGroupName string = resourceGroup.name
output accountName string = referenceResources.outputs.accountName
output projectName string = referenceResources.outputs.projectName
output agentModelDeploymentName string = referenceResources.outputs.agentModelDeploymentName
output voiceEndpoint string = referenceResources.outputs.voiceEndpoint
output voiceLiveModel string = referenceResources.outputs.voiceLiveModel
output foundryProjectEndpoint string = referenceResources.outputs.foundryProjectEndpoint

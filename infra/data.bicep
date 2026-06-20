// Log Analytics + Microsoft Sentinel for the SOC pipeline.
//
// Scope: resource group (dah-data-rg). Idempotent — re-running this deployment
// with the same parameters is a no-op except for tag updates.
//
//   az group create -n dah-data-rg -l koreacentral
//   az deployment group create -g dah-data-rg -f data.bicep -n data-mvp
//
// The workspace ID is exported so dah-sim-rg (uav-sim-env VM, Azure Monitor
// Agent) and dah-soc-rg (AKS / pollack-ai) can both target it for ingest.

@description('Azure region.')
param location string = 'koreacentral'

@description('Log Analytics workspace name. Must be globally unique within the resource group.')
param workspaceName string = 'dah-data-law'

@description('Days to retain ingested data. 30 = default, 90 = recommended for incident response.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

@description('Daily ingestion cap in GB. Prevents runaway cost. 0 = no cap.')
param dailyQuotaGb int = 1

@description('Enable Microsoft Sentinel on this workspace.')
param enableSentinel bool = true

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    workspaceCapping: dailyQuotaGb > 0 ? { dailyQuotaGb: dailyQuotaGb } : null
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

// Sentinel is added as an OMS Solution applied to the workspace.
resource sentinel 'Microsoft.OperationsManagement/solutions@2015-11-01-preview' = if (enableSentinel) {
  name: 'SecurityInsights(${law.name})'
  location: location
  properties: {
    workspaceResourceId: law.id
  }
  plan: {
    name: 'SecurityInsights(${law.name})'
    product: 'OMSGallery/SecurityInsights'
    publisher: 'Microsoft'
    promotionCode: ''
  }
}

output workspaceId string = law.id
output workspaceName string = law.name
output customerId string = law.properties.customerId

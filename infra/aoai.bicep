// Azure OpenAI account + GPT-4o-mini deployment for the SOC LangGraph agents.
//
// Scope: resource group (dah-soc-rg). Idempotent.
//
//   az deployment group create -g dah-soc-rg -f aoai.bicep -n aoai-mvp
//
// Outputs the endpoint (referenced by kagent ModelProviderConfig). The API key
// is fetched out-of-band via `az cognitiveservices account keys list` so it
// never lands in deployment outputs.

@description('Azure region. Must be in the AOAI-enabled regional catalog (Korea Central is supported).')
param location string = 'koreacentral'

@description('AOAI Cognitive Services account name. Globally unique — defaults to a hash-suffixed value.')
param accountName string = 'dah-aoai-${uniqueString(resourceGroup().id)}'

@description('Model deployment name. This is what kagent ModelConfig.spec.model references.')
param deploymentName string = 'gpt-4o-soc'

@description('Underlying OpenAI model name (must exist in regional catalog).')
param modelName string = 'gpt-4o-mini'

@description('OpenAI model version pinned per AOAI catalog (gpt-4o-mini -> 2024-07-18).')
param modelVersion string = '2024-07-18'

@description('Deployment SKU. Standard = regional data only (preferred for defence work); GlobalStandard uses the global pool.')
@allowed([ 'Standard', 'GlobalStandard', 'DataZoneStandard' ])
param deploymentSkuName string = 'Standard'

@description('Deployment capacity in K-tokens-per-minute units. 30 = 30,000 TPM.')
@minValue(1)
@maxValue(1000)
param capacity int = 30

resource account 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: accountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    // customSubDomainName drives the {sub}.openai.azure.com endpoint. Required
    // when deploying OpenAI models (vs general Cognitive Services usage).
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
    // Disable abuse monitoring? Standard tier already complies; leaving default.
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = {
  parent: account
  name: deploymentName
  sku: {
    name: deploymentSkuName
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

output accountName string = account.name
output endpoint string = account.properties.endpoint
output deploymentName string = deployment.name
output modelName string = modelName
output modelVersion string = modelVersion

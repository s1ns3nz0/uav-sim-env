// AKS managed cluster + Azure Container Registry for the SOC platform.
//
// Scope: resource group (dah-soc-rg). Idempotent.
//
//   az group create -n dah-soc-rg -l koreacentral
//   az deployment group create -g dah-soc-rg -f soc.bicep -n soc-mvp \
//     -p workspaceId="$(az deployment group show -g dah-data-rg -n data-mvp \
//       --query properties.outputs.workspaceId.value -o tsv)"
//
// After deploy, fetch kubeconfig and install kagent:
//   az aks get-credentials -g dah-soc-rg -n dah-soc-aks --overwrite-existing
//   helm install kagent oci://ghcr.io/kagent-dev/kagent --namespace kagent --create-namespace

@description('Azure region.')
param location string = 'koreacentral'

@description('AKS cluster name.')
param clusterName string = 'dah-soc-aks'

@description('ACR name. Must be globally unique. Lower-case letters and numbers only.')
param acrName string = 'dahsocacr${uniqueString(resourceGroup().id)}'

@description('Number of system node pool nodes. 2 = HA, 1 = cheapest.')
@minValue(1)
@maxValue(10)
param systemNodeCount int = 2

@description('VM size for the system node pool. D4s_v5 = balanced for kagent + LangGraph workloads.')
param systemNodeSize string = 'Standard_D4s_v5'

@description('Kubernetes minor version. Empty = AKS regional default (recommended).')
param kubernetesVersion string = ''

@description('Log Analytics workspace resource id to wire AKS container insights into. Output of data.bicep.')
param workspaceId string = ''

@description('DNS prefix for the cluster API server. Defaults to the cluster name.')
param dnsPrefix string = clusterName

var enableMonitoring = !empty(workspaceId)

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-05-01' = {
  name: clusterName
  location: location
  identity: { type: 'SystemAssigned' }
  sku: {
    name: 'Base'
    tier: 'Free'
  }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: dnsPrefix
    enableRBAC: true
    nodeResourceGroup: '${resourceGroup().name}-aks-nodes'
    agentPoolProfiles: [
      {
        name: 'system'
        count: systemNodeCount
        vmSize: systemNodeSize
        mode: 'System'
        osType: 'Linux'
        osDiskType: 'Managed'
        type: 'VirtualMachineScaleSets'
        enableAutoScaling: false
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      loadBalancerSku: 'standard'
    }
    addonProfiles: enableMonitoring ? {
      omsagent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: workspaceId
        }
      }
    } : {}
  }
}

// Grant the AKS kubelet identity AcrPull on the registry so pods can pull
// images without ImagePullSecrets.
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
    // Built-in role: AcrPull (7f951dda-4ed3-4680-a7ca-43fe172d538d)
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output aksName string = aks.name
output aksFqdn string = aks.properties.fqdn
output getCredentialsCommand string = 'az aks get-credentials -g ${resourceGroup().name} -n ${aks.name} --overwrite-existing'

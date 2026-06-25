// AKS cluster for the KUS-FS simulation plane (dah-sim-aks) + ACR.
//
// Scope: resource group (dah-sim-rg). Idempotent.
// Separate cluster from dah-soc-aks (SOC/kagent) — sim ↔ SOC out-of-band 경계.
//
// kind 대비 두 가지 AKS 적응:
//   1) networkPolicy: 'calico'  → air/link/ground/c4i 신뢰경계가 실제 강제됨.
//   2) 3개 노드풀(system/sitl/satcom) + nodeLabels + satcom taint → 기존 매니페스트의
//      nodeSelector(pool=...)·toleration 이 그대로 동작.
//
//   az deployment group create -g dah-sim-rg -f sim.bicep -n sim-aks \
//     -p workspaceId="$(az monitor log-analytics workspace show -g dah-data-rg \
//        -n dah-data-law --query id -o tsv)"
//
// After deploy:
//   az aks get-credentials -g dah-sim-rg -n dah-sim-aks --overwrite-existing

@description('Azure region.')
param location string = 'koreacentral'

@description('AKS cluster name.')
param clusterName string = 'dah-sim-aks'

@description('ACR name. Globally unique, lower-case alphanumeric only.')
param acrName string = 'dahsimacr${uniqueString(resourceGroup().id)}'

@description('System node pool node count.')
@minValue(1)
@maxValue(5)
param systemNodeCount int = 1

@description('SITL node pool node count (SITL = CPU-heavy 편대).')
@minValue(1)
@maxValue(5)
param sitlNodeCount int = 1

@description('SATCOM node pool node count (OpenSAND/satcom 전용, taint).')
@minValue(1)
@maxValue(5)
param satcomNodeCount int = 1

@description('VM size for all node pools.')
param nodeSize string = 'Standard_D4s_v5'

@description('Kubernetes minor version. Empty = AKS regional default (recommended).')
param kubernetesVersion string = ''

@description('Log Analytics workspace resource id for Container Insights (empty = skip).')
param workspaceId string = ''

@description('DNS prefix for the cluster API server.')
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
        vmSize: nodeSize
        mode: 'System'
        osType: 'Linux'
        osDiskType: 'Managed'
        type: 'VirtualMachineScaleSets'
        nodeLabels: { pool: 'system' }
      }
      {
        name: 'sitl'
        count: sitlNodeCount
        vmSize: nodeSize
        mode: 'User'
        osType: 'Linux'
        osDiskType: 'Managed'
        type: 'VirtualMachineScaleSets'
        nodeLabels: { pool: 'sitl' }
      }
      {
        name: 'satcom'
        count: satcomNodeCount
        vmSize: nodeSize
        mode: 'User'
        osType: 'Linux'
        osDiskType: 'Managed'
        type: 'VirtualMachineScaleSets'
        nodeLabels: { pool: 'satcom' }
        nodeTaints: [ 'dedicated=satcom:NoSchedule' ]
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPolicy: 'calico'
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

// AKS kubelet identity → AcrPull, so pods pull from ACR without ImagePullSecrets.
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output aksName string = aks.name
output aksFqdn string = aks.properties.fqdn
output getCredentialsCommand string = 'az aks get-credentials -g ${resourceGroup().name} -n ${aks.name} --overwrite-existing'

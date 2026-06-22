// Attach Azure Monitor Agent to uavsim-vm + associate the UAV DCR.
//
// Scope: resource group (dah-sim-rg, where the VM lives).
// Idempotent.
//
//   DCR_ID=$(az deployment group show -g dah-data-rg -n dcr-mvp \
//     --query properties.outputs.dcrId.value -o tsv)
//   az deployment group create -g dah-sim-rg -f vm-monitoring.bicep \
//     -n vm-mon-mvp -p dcrId="$DCR_ID"
//
// Two resources:
//   1) AzureMonitorLinuxAgent VM extension — actual agent process running on
//      the VM, tailing the file declared in the DCR.
//   2) Data Collection Rule Association (DCRA) — the link between the VM and
//      the DCR. Without this the agent does not know which streams to ship.

@description('Name of the VM. Default matches main.bicep output.')
param vmName string = 'uavsim-vm'

@description('Full resource id of the primary DCR to associate (cross-RG ok).')
param dcrId string

@description('Optional secondary DCR id for overflow streams (empty = skip).')
param dcrIdExtras string = ''

@description('Optional tertiary DCR id for KUS-FS 확장 신규 streams (empty = skip).')
param dcrIdExt2 string = ''

@description('Azure region. Must match the VM.')
param location string = 'koreacentral'

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' existing = {
  name: vmName
}

resource ama 'Microsoft.Compute/virtualMachines/extensions@2024-03-01' = {
  parent: vm
  name: 'AzureMonitorLinuxAgent'
  location: location
  properties: {
    publisher: 'Microsoft.Azure.Monitor'
    type: 'AzureMonitorLinuxAgent'
    typeHandlerVersion: '1.33'
    autoUpgradeMinorVersion: true
    enableAutomaticUpgrade: true
  }
}

resource dcra 'Microsoft.Insights/dataCollectionRuleAssociations@2023-03-11' = {
  name: 'uav-dcr-association'
  scope: vm
  properties: {
    dataCollectionRuleId: dcrId
    description: 'Primary DCR — first 10 NDJSON streams.'
  }
  dependsOn: [ ama ]
}

resource dcraExtras 'Microsoft.Insights/dataCollectionRuleAssociations@2023-03-11' = if (!empty(dcrIdExtras)) {
  name: 'uav-dcr-association-extras'
  scope: vm
  properties: {
    dataCollectionRuleId: dcrIdExtras
    description: 'Secondary DCR — overflow NDJSON streams beyond the 10-logFiles cap.'
  }
  dependsOn: [ ama ]
}

resource dcraExt2 'Microsoft.Insights/dataCollectionRuleAssociations@2023-03-11' = if (!empty(dcrIdExt2)) {
  name: 'uav-dcr-association-ext2'
  scope: vm
  properties: {
    dataCollectionRuleId: dcrIdExt2
    description: 'Tertiary DCR — KUS-FS 확장(편대+SATCOM) 신규 5개 스트림.'
  }
  dependsOn: [ ama ]
}

output extensionName string = ama.name
output associationName string = dcra.name

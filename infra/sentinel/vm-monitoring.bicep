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

@description('Full resource id of the DCR to associate (cross-RG ok).')
param dcrId string

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
    description: 'Ships telemetry.ndjson from uavsim-vm to UAVTelemetry_CL.'
  }
  dependsOn: [ ama ]
}

output extensionName string = ama.name
output associationName string = dcra.name

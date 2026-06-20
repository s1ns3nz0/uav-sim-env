// uav-sim-env Azure VM deployment.
//
// Provisions a single Ubuntu 22.04 VM in Korea Central that boots,
// installs Docker, clones this repo, and brings the Compose stack up.
// Scope: resource group. Deploy with:
//
//   az group create -n <rg> -l koreacentral
//   az deployment group create -g <rg> -f main.bicep \
//     -p adminPublicKey="$(cat ~/.ssh/id_ed25519.pub)" \
//     -p allowedSourceIp="$(curl -s ifconfig.me)/32"

@description('Azure region.')
param location string = 'koreacentral'

@description('Base name used as prefix for every resource.')
param projectName string = 'uavsim'

@description('Linux admin username (used for SSH and the systemd unit).')
param adminUsername string = 'azureuser'

@description('SSH public key to authorise on the VM (string contents of ~/.ssh/id_*.pub).')
@secure()
param adminPublicKey string

@description('CIDR allowed to reach SSH / noVNC / MAVLink / REST endpoints. Example: 1.2.3.4/32.')
param allowedSourceIp string

@description('VM size. D4s_v5 = 4 vCPU / 16 GiB RAM — comfortable for SITL + Gazebo + QGC.')
param vmSize string = 'Standard_D4s_v5'

@description('Git repository to clone on first boot.')
param gitRepoUrl string = 'https://github.com/s1ns3nz0/uav-sim-env.git'

@description('Branch / tag to check out.')
param gitBranch string = 'main'

var vmName = '${projectName}-vm'
var nicName = '${projectName}-nic'
var pipName = '${projectName}-pip'
var nsgName = '${projectName}-nsg'
var vnetName = '${projectName}-vnet'
var subnetName = 'default'
var osDiskName = '${projectName}-os'
var dnsLabel = '${projectName}-${uniqueString(resourceGroup().id)}'

// cloud-init template — values substituted at deploy time so the script knows
// which user to chown to and which repo to clone.
var cloudInit = format(loadTextContent('cloud-init.yaml'), adminUsername, gitRepoUrl, gitBranch)

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: nsgName
  location: location
  properties: {
    securityRules: [
      {
        name: 'ssh'
        properties: {
          priority: 1000
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: allowedSourceIp
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'novnc'
        properties: {
          priority: 1010
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: allowedSourceIp
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8080'
        }
      }
      {
        name: 'mavlink-tcp'
        properties: {
          priority: 1020
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: allowedSourceIp
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '5790'
        }
      }
      {
        name: 'pgse-rest'
        properties: {
          priority: 1030
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: allowedSourceIp
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8000'
        }
      }
      {
        name: 'mavlink-udp'
        properties: {
          priority: 1040
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Udp'
          sourceAddressPrefix: allowedSourceIp
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: [
            '14550'
            '14552'
          ]
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: { addressPrefixes: [ '10.60.0.0/16' ] }
    subnets: [
      {
        name: subnetName
        properties: {
          addressPrefix: '10.60.1.0/24'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource pip 'Microsoft.Network/publicIPAddresses@2024-01-01' = {
  name: pipName
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: { domainNameLabel: dnsLabel }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-01-01' = {
  name: nicName
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipcfg'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: '${vnet.id}/subnets/${subnetName}' }
          publicIPAddress: { id: pip.id }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  identity: {
    // SystemAssigned MSI lets Azure Monitor Agent obtain ingest tokens from
    // IMDS without storing any secrets on disk. The role assignment that
    // grants "Monitoring Metrics Publisher" on the DCR is done out-of-band
    // (vm-monitoring stage) so the identity exists first.
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        name: osDiskName
        createOption: 'FromImage'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
    }
    networkProfile: {
      networkInterfaces: [ { id: nic.id } ]
    }
  }
}

output vmName string = vm.name
output publicIp string = pip.properties.ipAddress
output fqdn string = pip.properties.dnsSettings.fqdn
output sshCommand string = 'ssh ${adminUsername}@${pip.properties.dnsSettings.fqdn}'
output novncUrl string = 'http://${pip.properties.dnsSettings.fqdn}:8080/vnc.html'
output pgseDocsUrl string = 'http://${pip.properties.dnsSettings.fqdn}:8000/docs'

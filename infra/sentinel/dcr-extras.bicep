// Secondary DCR — overflow streams beyond the 10-logFiles per-DCR API limit.
// Same DCE + workspace as the primary DCR.
//
//   az deployment group create -g dah-data-rg -f dcr-extras.bicep -n dcr-extras-mvp \
//     -p workspaceName=dah-data-law

@description('Azure region.')
param location string = 'koreacentral'

@description('Existing Log Analytics workspace name (must match dcr.bicep).')
param workspaceName string

@description('Name prefix used when discovering the existing DCE.')
param namePrefix string = 'dah-data'

@description('Threat intel NDJSON file path (ti-stub).')
param tiLogPath string = '/var/log/uav-sim-env/ti.ndjson'

@description('Operator auth audit NDJSON file path (auth-stub).')
param authLogPath string = '/var/log/uav-sim-env/auth.ndjson'

@description('Failsafe event NDJSON path (telemetry-tap derived).')
param failsafeLogPath string = '/var/log/uav-sim-env/failsafe.ndjson'

@description('MAVSec signing summary NDJSON path (telemetry-tap derived).')
param mavsecLogPath string = '/var/log/uav-sim-env/mavsec.ndjson'

@description('Maintenance NDJSON path (pgse-stub extended).')
param maintLogPath string = '/var/log/uav-sim-env/maintenance.ndjson'

@description('Imagery/payload event NDJSON path (telemetry-tap derived).')
param imageryLogPath string = '/var/log/uav-sim-env/imagery.ndjson'

@description('Config-audit NDJSON path (telemetry-tap derived).')
param configAuditLogPath string = '/var/log/uav-sim-env/config-audit.ndjson'

@description('All-container resource metrics NDJSON (datalink-stats extended).')
param resourceLogPath string = '/var/log/uav-sim-env/resource-metrics.ndjson'

@description('Datalink connection snapshot NDJSON (datalink-stats extended).')
param datalinkConnLogPath string = '/var/log/uav-sim-env/datalink-conn.ndjson'

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr-extras'
var tiStreamName = 'Custom-UAVThreatIntel'
var authStreamName = 'Custom-UAVOpAudit'
var failsafeStreamName = 'Custom-UAVFailsafe'
var mavsecStreamName = 'Custom-UAVMavsec'
var maintStreamName = 'Custom-UAVMaintenance'
var imageryStreamName = 'Custom-UAVImagery'
var configAuditStreamName = 'Custom-UAVConfigAudit'
var resourceStreamName = 'Custom-UAVResourceMetrics'
var datalinkConnStreamName = 'Custom-UAVDatalinkConn'
var tiTableName = 'UAVThreatIntel_CL'
var authTableName = 'UAVOpAudit_CL'
var failsafeTableName = 'UAVFailsafe_CL'
var mavsecTableName = 'UAVMavsec_CL'
var maintTableName = 'UAVMaintenance_CL'
var imageryTableName = 'UAVImagery_CL'
var configAuditTableName = 'UAVConfigAudit_CL'
var resourceTableName = 'UAVResourceMetrics_CL'
var datalinkConnTableName = 'UAVDatalinkConn_CL'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' existing = {
  name: dceName
}

var tiStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'IndicatorType', type: 'string' }
  { name: 'Indicator', type: 'string' }
  { name: 'Severity', type: 'string' }
  { name: 'ConfidencePct', type: 'int' }
  { name: 'Source', type: 'string' }
  { name: 'Description', type: 'string' }
  { name: 'FeedName', type: 'string' }
  { name: 'IndicatorCount', type: 'int' }
  { name: 'Recommendation', type: 'string' }
  { name: 'StatusCode', type: 'int' }
]

var authStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'Operator', type: 'string' }
  { name: 'ClientIp', type: 'string' }
  { name: 'UserAgent', type: 'string' }
  { name: 'SessionId', type: 'string' }
  { name: 'FailReason', type: 'string' }
  { name: 'StatusCode', type: 'int' }
  { name: 'TargetOperator', type: 'string' }
  { name: 'Detail', type: 'string' }
]

var failsafeStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'EventType', type: 'string' }
  { name: 'Severity', type: 'int' }
  { name: 'Text', type: 'string' }
  { name: 'ModeBefore', type: 'int' }
  { name: 'ModeAfter', type: 'int' }
  { name: 'GapSec', type: 'real' }
]

var mavsecStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'EventType', type: 'string' }
  { name: 'SignedCount', type: 'long' }
  { name: 'UnsignedCount', type: 'long' }
  { name: 'FailedCount', type: 'long' }
  { name: 'WindowSec', type: 'int' }
]

var maintStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'UAVId', type: 'string' }
  { name: 'Operator', type: 'string' }
  { name: 'BatteryId', type: 'string' }
  { name: 'CycleCount', type: 'int' }
  { name: 'VoltageMin', type: 'real' }
  { name: 'VoltageMax', type: 'real' }
  { name: 'ComponentName', type: 'string' }
  { name: 'ChecklistId', type: 'string' }
  { name: 'ItemsPassed', type: 'int' }
  { name: 'ItemsTotal', type: 'int' }
  { name: 'Notes', type: 'string' }
  { name: 'StatusCode', type: 'int' }
]

var imageryStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'EventType', type: 'string' }
  { name: 'MsgType', type: 'string' }
]

var configAuditStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'EventType', type: 'string' }
  { name: 'ParamId', type: 'string' }
  { name: 'ParamValueBefore', type: 'real' }
  { name: 'ParamValueAfter', type: 'real' }
  { name: 'Source', type: 'string' }
]

var resourceStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'ContainerName', type: 'string' }
  { name: 'CpuUsagePct', type: 'real' }
  { name: 'MemoryUsageBytes', type: 'long' }
  { name: 'MemoryLimitBytes', type: 'long' }
  { name: 'NetworkRxBytes', type: 'long' }
  { name: 'NetworkTxBytes', type: 'long' }
  { name: 'BlockReadBytes', type: 'long' }
  { name: 'BlockWriteBytes', type: 'long' }
]

var datalinkConnStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'State', type: 'string' }
  { name: 'LocalIp', type: 'string' }
  { name: 'LocalPort', type: 'int' }
  { name: 'PeerIp', type: 'string' }
  { name: 'PeerPort', type: 'int' }
]

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  kind: 'Linux'
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${tiStreamName}': { columns: tiStreamColumns }
      '${authStreamName}': { columns: authStreamColumns }
      '${failsafeStreamName}': { columns: failsafeStreamColumns }
      '${mavsecStreamName}': { columns: mavsecStreamColumns }
      '${maintStreamName}': { columns: maintStreamColumns }
      '${imageryStreamName}': { columns: imageryStreamColumns }
      '${configAuditStreamName}': { columns: configAuditStreamColumns }
      '${resourceStreamName}': { columns: resourceStreamColumns }
      '${datalinkConnStreamName}': { columns: datalinkConnStreamColumns }
    }
    dataSources: {
      logFiles: [
        { name: 'uavTiFile', streams: [ tiStreamName ], filePatterns: [ tiLogPath ], format: 'json' }
        { name: 'uavAuthFile', streams: [ authStreamName ], filePatterns: [ authLogPath ], format: 'json' }
        { name: 'uavFailsafeFile', streams: [ failsafeStreamName ], filePatterns: [ failsafeLogPath ], format: 'json' }
        { name: 'uavMavsecFile', streams: [ mavsecStreamName ], filePatterns: [ mavsecLogPath ], format: 'json' }
        { name: 'uavMaintFile', streams: [ maintStreamName ], filePatterns: [ maintLogPath ], format: 'json' }
        { name: 'uavImageryFile', streams: [ imageryStreamName ], filePatterns: [ imageryLogPath ], format: 'json' }
        { name: 'uavConfigAuditFile', streams: [ configAuditStreamName ], filePatterns: [ configAuditLogPath ], format: 'json' }
        { name: 'uavResourceFile', streams: [ resourceStreamName ], filePatterns: [ resourceLogPath ], format: 'json' }
        { name: 'uavDatalinkConnFile', streams: [ datalinkConnStreamName ], filePatterns: [ datalinkConnLogPath ], format: 'json' }
      ]
    }
    destinations: {
      logAnalytics: [
        { name: 'centralLaw', workspaceResourceId: law.id }
      ]
    }
    dataFlows: [
      { streams: [ tiStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${tiTableName}' }
      { streams: [ authStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${authTableName}' }
      { streams: [ failsafeStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${failsafeTableName}' }
      { streams: [ mavsecStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${mavsecTableName}' }
      { streams: [ maintStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${maintTableName}' }
      { streams: [ imageryStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${imageryTableName}' }
      { streams: [ configAuditStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${configAuditTableName}' }
      { streams: [ resourceStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${resourceTableName}' }
      { streams: [ datalinkConnStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${datalinkConnTableName}' }
    ]
  }
}

output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId

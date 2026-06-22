// Tertiary DCR — KUS-FS 확장(편대 + SATCOM) 신규 5개 스트림.
// primary(dcr.bicep, 10) / extras(dcr-extras.bicep, 9)가 10-logFiles/DCR 한계에
// 가까워 신규 테이블은 이 세 번째 DCR로 분리한다. 동일 DCE + workspace 사용.
//
//   az deployment group create -g dah-data-rg -f dcr-ext2.bicep -n dcr-ext2-mvp \
//     -p workspaceName=dah-data-law

@description('Azure region.')
param location string = 'koreacentral'

@description('Existing Log Analytics workspace name (must match dcr.bicep).')
param workspaceName string

@description('Name prefix used when discovering the existing DCE.')
param namePrefix string = 'dah-data'

@description('SATCOM 위성 링크 NDJSON 경로 (datalink-satcom).')
param satcomLogPath string = '/var/log/uav-sim-env/satcom.ndjson'

@description('SAR 페이로드 프레임 메타 NDJSON 경로 (sar-stub).')
param sarLogPath string = '/var/log/uav-sim-env/sar.ndjson'

@description('GCS 원격접속 감사 NDJSON 경로 (gcs-qgc).')
param gcsAccessLogPath string = '/var/log/uav-sim-env/gcs-access.ndjson'

@description('mavlink-router 내부 통계 NDJSON 경로 (datalink-los).')
param routerStatsLogPath string = '/var/log/uav-sim-env/router-stats.ndjson'

@description('편대 상태 요약 NDJSON 경로 (telemetry-tap 파생).')
param fleetStateLogPath string = '/var/log/uav-sim-env/fleet-state.ndjson'

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr-ext2'

var satcomStreamName = 'Custom-UAVSatcomLink'
var sarStreamName = 'Custom-UAVSarPayload'
var gcsAccessStreamName = 'Custom-UAVGcsAccess'
var routerStatsStreamName = 'Custom-UAVRouterStats'
var fleetStateStreamName = 'Custom-UAVFleetState'

var satcomTableName = 'UAVSatcomLink_CL'
var sarTableName = 'UAVSarPayload_CL'
var gcsAccessTableName = 'UAVGcsAccess_CL'
var routerStatsTableName = 'UAVRouterStats_CL'
var fleetStateTableName = 'UAVFleetState_CL'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' existing = {
  name: dceName
}

var satcomStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'LinkId', type: 'string' }
  { name: 'SessionId', type: 'string' }
  { name: 'Seq', type: 'long' }
  { name: 'IntegrityStatus', type: 'string' }
  { name: 'RttMs', type: 'real' }
  { name: 'JamIndicator', type: 'real' }
  { name: 'SrcAddr', type: 'string' }
  { name: 'DstAddr', type: 'string' }
]

var sarStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'FrameId', type: 'string' }
  { name: 'TargetLat', type: 'real' }
  { name: 'TargetLon', type: 'real' }
  { name: 'Resolution', type: 'string' }
  { name: 'SensorMode', type: 'string' }
  { name: 'SizeBytes', type: 'long' }
]

var gcsAccessStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'ClientIp', type: 'string' }
  { name: 'Transport', type: 'string' }
  { name: 'SessionStart', type: 'datetime' }
  { name: 'SessionEnd', type: 'datetime' }
  { name: 'UserAgent', type: 'string' }
  { name: 'BytesTransferred', type: 'long' }
]

var routerStatsStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EndpointName', type: 'string' }
  { name: 'MsgRx', type: 'long' }
  { name: 'MsgTx', type: 'long' }
  { name: 'MsgDropped', type: 'long' }
  { name: 'CrcErrors', type: 'long' }
]

var fleetStateStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'WindowStart', type: 'datetime' }
  { name: 'FleetId', type: 'string' }
  { name: 'ActiveUAVCount', type: 'int' }
  { name: 'DivergingCount', type: 'int' }
  { name: 'CommonCommand', type: 'string' }
  { name: 'AnomalyScore', type: 'real' }
]

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  kind: 'Linux'
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${satcomStreamName}': { columns: satcomStreamColumns }
      '${sarStreamName}': { columns: sarStreamColumns }
      '${gcsAccessStreamName}': { columns: gcsAccessStreamColumns }
      '${routerStatsStreamName}': { columns: routerStatsStreamColumns }
      '${fleetStateStreamName}': { columns: fleetStateStreamColumns }
    }
    dataSources: {
      logFiles: [
        { name: 'uavSatcomFile', streams: [ satcomStreamName ], filePatterns: [ satcomLogPath ], format: 'json' }
        { name: 'uavSarFile', streams: [ sarStreamName ], filePatterns: [ sarLogPath ], format: 'json' }
        { name: 'uavGcsAccessFile', streams: [ gcsAccessStreamName ], filePatterns: [ gcsAccessLogPath ], format: 'json' }
        { name: 'uavRouterStatsFile', streams: [ routerStatsStreamName ], filePatterns: [ routerStatsLogPath ], format: 'json' }
        { name: 'uavFleetStateFile', streams: [ fleetStateStreamName ], filePatterns: [ fleetStateLogPath ], format: 'json' }
      ]
    }
    destinations: {
      logAnalytics: [
        { name: 'centralLaw', workspaceResourceId: law.id }
      ]
    }
    dataFlows: [
      { streams: [ satcomStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${satcomTableName}' }
      { streams: [ sarStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${sarTableName}' }
      { streams: [ gcsAccessStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${gcsAccessTableName}' }
      { streams: [ routerStatsStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${routerStatsTableName}' }
      { streams: [ fleetStateStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${fleetStateTableName}' }
    ]
  }
}

output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId

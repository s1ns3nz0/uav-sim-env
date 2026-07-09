// Tertiary DCR — KUS-FS 확장(편대 + SATCOM + 카운터-UAS) 5개 스트림.
// primary(dcr.bicep, 10) / extras(dcr-extras.bicep, 9)가 10-logFiles/DCR 한계에
// 가까워 신규 테이블은 이 세 번째 DCR로 분리한다. 동일 DCE + workspace 사용.
// UAVGcsAccess_CL 은 pollack-ai/deploy/sentinel-tables 의 dcr-uav-soc 로 이관(소유권 SOC).
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

// UAVGcsAccess_CL 정의는 pollack-ai/deploy/sentinel-tables (dcr-uav-soc) 가 소유 — 여기서는 빠짐.

@description('mavlink-router 내부 통계 NDJSON 경로 (datalink-los).')
param routerStatsLogPath string = '/var/log/uav-sim-env/router-stats.ndjson'

@description('편대 상태 요약 NDJSON 경로 (telemetry-tap 파생).')
param fleetStateLogPath string = '/var/log/uav-sim-env/fleet-state.ndjson'

@description('카운터-UAS RF 탐지·재밍 교전 NDJSON 경로 (counter-uas).')
param counterUasLogPath string = '/var/log/uav-sim-env/counter-uas.ndjson'

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr-ext2'

var satcomStreamName = 'Custom-UAVSatcomLink'
var sarStreamName = 'Custom-UAVSarPayload'
var routerStatsStreamName = 'Custom-UAVRouterStats'
var fleetStateStreamName = 'Custom-UAVFleetState'
var counterUasStreamName = 'Custom-UAVCounterUas'

var satcomTableName = 'UAVSatcomLink_CL'
var sarTableName = 'UAVSarPayload_CL'
var routerStatsTableName = 'UAVRouterStats_CL'
var fleetStateTableName = 'UAVFleetState_CL'
var counterUasTableName = 'UAVCounterUas_CL'

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
  { name: 'Mode', type: 'string' }
  { name: 'Encoding', type: 'string' }
  { name: 'PayloadEntropy', type: 'real' }
  { name: 'BeaconJitterSec', type: 'real' }
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

var counterUasStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'UAVId', type: 'string' }
  { name: 'Seq', type: 'long' }
  { name: 'TrackId', type: 'string' }
  { name: 'Band', type: 'string' }
  { name: 'CenterFreqMHz', type: 'real' }
  { name: 'Rssi_dBm', type: 'real' }
  { name: 'EstRange_m', type: 'real' }
  { name: 'TrueRange_m', type: 'real' }
  { name: 'Bearing_deg', type: 'real' }
  { name: 'Classification', type: 'string' }
  { name: 'Protocol', type: 'string' }
  { name: 'TargetBand', type: 'string' }
  { name: 'JamFreqMHz', type: 'real' }
  { name: 'JamMode', type: 'string' }
  { name: 'JamEirp_dBm', type: 'real' }
  { name: 'JsRatio_dB', type: 'real' }
  { name: 'Effect', type: 'string' }
  { name: 'Status', type: 'string' }
  { name: 'ReasonCode', type: 'string' }
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
      '${routerStatsStreamName}': { columns: routerStatsStreamColumns }
      '${fleetStateStreamName}': { columns: fleetStateStreamColumns }
      '${counterUasStreamName}': { columns: counterUasStreamColumns }
    }
    dataSources: {
      logFiles: [
        { name: 'uavSatcomFile', streams: [ satcomStreamName ], filePatterns: [ satcomLogPath ], format: 'json' }
        { name: 'uavSarFile', streams: [ sarStreamName ], filePatterns: [ sarLogPath ], format: 'json' }
        { name: 'uavRouterStatsFile', streams: [ routerStatsStreamName ], filePatterns: [ routerStatsLogPath ], format: 'json' }
        { name: 'uavFleetStateFile', streams: [ fleetStateStreamName ], filePatterns: [ fleetStateLogPath ], format: 'json' }
        { name: 'uavCounterUasFile', streams: [ counterUasStreamName ], filePatterns: [ counterUasLogPath ], format: 'json' }
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
      { streams: [ routerStatsStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${routerStatsTableName}' }
      { streams: [ fleetStateStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${fleetStateTableName}' }
      { streams: [ counterUasStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${counterUasTableName}' }
    ]
  }
}

output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId

// Quaternary DCR — grilling 세션 보강분(companion/devops/fleet-infra/ground-truth)
// 4개 스트림. primary(10)/extras(9)/ext2(10) 전부 10-logFiles/DCR 한도 근처거나
// 꽉 차서 이 네 번째 DCR로 분리한다. 동일 DCE + workspace 사용.
//
// VM 은 폐기됨(README "VM 폐기됨" 2026-06-27) — 이 DCR은 AKS fluent-bit(Logs
// Ingestion API push) 경로만 지원한다. 그래서 primary/extras/ext2 와 달리
// `dataSources.logFiles`(AMA 기반 VM 파일 tailing) 블록이 없다 — streamDeclarations
// + dataFlows 만으로 충분(Logs Ingestion API 는 dataSources 없이도 유효한 DCR).
//
//   az deployment group create -g dah-data-rg -f dcr-ext3.bicep -n dcr-ext3-mvp \
//     -p workspaceName=dah-data-law

@description('Azure region.')
param location string = 'koreacentral'

@description('Existing Log Analytics workspace name (must match dcr.bicep).')
param workspaceName string

@description('Name prefix used when discovering the existing DCE.')
param namePrefix string = 'dah-data'

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr-ext3'

var companionStreamName = 'Custom-UAVCompanion'
var devOpsStreamName = 'Custom-UAVDevOps'
var fleetInfraStreamName = 'Custom-UAVFleetInfra'
var groundTruthStreamName = 'Custom-UAVGroundTruth'

var companionTableName = 'UAVCompanion_CL'
var devOpsTableName = 'UAVDevOps_CL'
var fleetInfraTableName = 'UAVFleetInfra_CL'
var groundTruthTableName = 'UAVGroundTruth_CL'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' existing = {
  name: dceName
}

var companionStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'Target', type: 'string' }
  { name: 'ContentSnippet', type: 'string' }
  { name: 'PathTraversalDetected', type: 'boolean' }
  { name: 'InjectionSignatureDetected', type: 'boolean' }
  { name: 'MitmSuspected', type: 'boolean' }
  { name: 'ConfigField', type: 'string' }
  { name: 'ValueBefore', type: 'string' }
  { name: 'ValueAfter', type: 'string' }
  { name: 'ChangedBy', type: 'string' }
  { name: 'Authorized', type: 'boolean' }
  { name: 'Topic', type: 'string' }
  { name: 'Command', type: 'string' }
  { name: 'NtpServer', type: 'string' }
  { name: 'OffsetReportedSec', type: 'real' }
  { name: 'StatusCode', type: 'int' }
]

var devOpsStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'Target', type: 'string' }
  { name: 'Actor', type: 'string' }
  { name: 'DigestMismatch', type: 'boolean' }
  { name: 'UnauthorizedTrigger', type: 'boolean' }
  { name: 'SecretExfilSuspected', type: 'boolean' }
  { name: 'DependencyConfusionSuspected', type: 'boolean' }
  { name: 'UnplannedApply', type: 'boolean' }
  { name: 'ProvenanceMismatch', type: 'boolean' }
  { name: 'ParticipantCount', type: 'int' }
  { name: 'FloodSuspected', type: 'boolean' }
  { name: 'Topic', type: 'string' }
  { name: 'UnauthorizedPublish', type: 'boolean' }
  { name: 'StatusCode', type: 'int' }
]

var fleetInfraStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'FleetId', type: 'string' }
  { name: 'RequesterId', type: 'string' }
  { name: 'TargetId', type: 'string' }
  { name: 'IdorSuspected', type: 'boolean' }
  { name: 'StreamId', type: 'string' }
  { name: 'SessionId', type: 'string' }
  { name: 'ClientIp', type: 'string' }
  { name: 'HijackSuspected', type: 'boolean' }
  { name: 'Rule', type: 'string' }
  { name: 'ValueBefore', type: 'real' }
  { name: 'ValueAfter', type: 'real' }
  { name: 'ChangedBy', type: 'string' }
  { name: 'LinkA', type: 'string' }
  { name: 'LinkB', type: 'string' }
  { name: 'LinkStatus', type: 'string' }
  { name: 'Reason', type: 'string' }
  { name: 'StatusCode', type: 'int' }
]

var groundTruthStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'GroundTruthCustomMode', type: 'int' }
  { name: 'Source', type: 'string' }
]

// kind 미지정(Direct/Logs Ingestion API 전용 DCR). kind:'Linux'는 AMA 대상 DCR
// 전용이라 dataSources 가 non-empty 여야 하는데(Azure 서버측 검증), 이 DCR은
// VM 이 없어 dataSources 자체가 없다 — kind 를 아예 안 주면 이 제약이 안 걸린다.
resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${companionStreamName}': { columns: companionStreamColumns }
      '${devOpsStreamName}': { columns: devOpsStreamColumns }
      '${fleetInfraStreamName}': { columns: fleetInfraStreamColumns }
      '${groundTruthStreamName}': { columns: groundTruthStreamColumns }
    }
    destinations: {
      logAnalytics: [
        { name: 'centralLaw', workspaceResourceId: law.id }
      ]
    }
    dataFlows: [
      { streams: [ companionStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${companionTableName}' }
      { streams: [ devOpsStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${devOpsTableName}' }
      { streams: [ fleetInfraStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${fleetInfraTableName}' }
      { streams: [ groundTruthStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${groundTruthTableName}' }
    ]
  }
}

output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId

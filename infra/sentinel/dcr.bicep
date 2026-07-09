// Primary DCR — first 10 streams (logFiles cap per Azure API is 10).
// Overflow lives in dcr-extras.bicep.
//
//   az deployment group create -g dah-data-rg -f dcr.bicep -n dcr-mvp \
//     -p workspaceName=dah-data-law

@description('Azure region. Must match the workspace and the VM.')
param location string = 'koreacentral'

@description('Name of the existing Log Analytics workspace (output of data.bicep).')
param workspaceName string

@description('Name prefix for the DCE / DCR resources.')
param namePrefix string = 'dah-data'

@description('Telemetry NDJSON file path on the VM (telemetry-tap output).')
param telemetryLogPath string = '/var/log/uav-sim-env/telemetry.ndjson'

@description('PGSE decision NDJSON file path on the VM (pgse-stub output).')
param pgseLogPath string = '/var/log/uav-sim-env/pgse.ndjson'

@description('Operator event NDJSON file path on the VM (telemetry-tap operator filter).')
param operatorLogPath string = '/var/log/uav-sim-env/operator.ndjson'

@description('Mission lifecycle event NDJSON file path on the VM (telemetry-tap mission filter).')
param missionLogPath string = '/var/log/uav-sim-env/mission.ndjson'

@description('Docker engine event NDJSON file path on the VM (service-audit sidecar).')
param serviceAuditLogPath string = '/var/log/uav-sim-env/service-audit.ndjson'

@description('MPS decision NDJSON file path on the VM (mps-stub output).')
param mpsLogPath string = '/var/log/uav-sim-env/mps.ndjson'

@description('Datalink stats NDJSON file path (datalink-stats sidecar).')
param datalinkLogPath string = '/var/log/uav-sim-env/datalink-stats.ndjson'

@description('C4I (ATCIS/MIMS) NDJSON file path (c4i-stub output).')
param c4iLogPath string = '/var/log/uav-sim-env/c4i.ndjson'

@description('Cyber posture NDJSON file path (cyber-posture-stub output).')
param cyberPostureLogPath string = '/var/log/uav-sim-env/cyber-posture.ndjson'

@description('Weapon control plane NDJSON file path (weapon-stub).')
param weaponLogPath string = '/var/log/uav-sim-env/weapon.ndjson'

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr'
var streamName = 'Custom-UAVTelemetry'
var pgseStreamName = 'Custom-UAVPgse'
var operatorStreamName = 'Custom-UAVOperator'
var missionStreamName = 'Custom-UAVMissionEvent'
var serviceAuditStreamName = 'Custom-UAVServiceAudit'
var mpsStreamName = 'Custom-UAVMissionPlan'
var datalinkStreamName = 'Custom-UAVDatalink'
var c4iStreamName = 'Custom-UAVC4I'
var cyberPostureStreamName = 'Custom-UAVCyberPosture'
var weaponStreamName = 'Custom-UAVWeapon'
var tableName = 'UAVTelemetry_CL'
var pgseTableName = 'UAVPgse_CL'
var operatorTableName = 'UAVOperator_CL'
var missionTableName = 'UAVMissionEvent_CL'
var serviceAuditTableName = 'UAVServiceAudit_CL'
var mpsTableName = 'UAVMissionPlan_CL'
var datalinkTableName = 'UAVDatalink_CL'
var c4iTableName = 'UAVC4I_CL'
var cyberPostureTableName = 'UAVCyberPosture_CL'
var weaponTableName = 'UAVWeapon_CL'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: dceName
  location: location
  kind: 'Linux'
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

var streamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'MsgType', type: 'string' }
  { name: 'SystemId', type: 'int' }
  { name: 'ComponentId', type: 'int' }
  { name: 'Lat', type: 'real' }
  { name: 'Lon', type: 'real' }
  { name: 'AltMSL_m', type: 'real' }
  { name: 'AltRel_m', type: 'real' }
  { name: 'VxNorth_cms', type: 'int' }
  { name: 'VyEast_cms', type: 'int' }
  { name: 'VzDown_cms', type: 'int' }
  { name: 'Heading_cdeg', type: 'int' }
  { name: 'X_m', type: 'real' }
  { name: 'Y_m', type: 'real' }
  { name: 'Z_m', type: 'real' }
  { name: 'Vx_ms', type: 'real' }
  { name: 'Vy_ms', type: 'real' }
  { name: 'Vz_ms', type: 'real' }
  { name: 'FixType', type: 'int' }
  { name: 'SatellitesVisible', type: 'int' }
  { name: 'Eph_cm', type: 'int' }
  { name: 'Epv_cm', type: 'int' }
  { name: 'VelGround_cms', type: 'int' }
  { name: 'CourseOverGround_cdeg', type: 'int' }
  { name: 'GpsInputInjected', type: 'boolean' }
  { name: 'Hdop', type: 'real' }
  { name: 'Vdop', type: 'real' }
  { name: 'IgnoreFlags', type: 'int' }
  { name: 'Roll_rad', type: 'real' }
  { name: 'Pitch_rad', type: 'real' }
  { name: 'Yaw_rad', type: 'real' }
  { name: 'RollSpeed_rads', type: 'real' }
  { name: 'PitchSpeed_rads', type: 'real' }
  { name: 'YawSpeed_rads', type: 'real' }
  { name: 'Airspeed_ms', type: 'real' }
  { name: 'Groundspeed_ms', type: 'real' }
  { name: 'Heading_deg', type: 'int' }
  { name: 'Throttle_pct', type: 'int' }
  { name: 'ClimbRate_ms', type: 'real' }
  { name: 'EkfFlags', type: 'int' }
  { name: 'VelocityVariance', type: 'real' }
  { name: 'PosHorizVariance', type: 'real' }
  { name: 'PosVertVariance', type: 'real' }
  { name: 'CompassVariance', type: 'real' }
  { name: 'TerrainAltVariance', type: 'real' }
  { name: 'BatteryVoltage_mV', type: 'int' }
  { name: 'BatteryCurrent_cA', type: 'int' }
  { name: 'BatteryRemaining_pct', type: 'int' }
  { name: 'OnboardCpuLoad_pct', type: 'real' }
  { name: 'ErrorsComm', type: 'int' }
  { name: 'DropRateComm_pct', type: 'real' }
  { name: 'VibrationX', type: 'real' }
  { name: 'VibrationY', type: 'real' }
  { name: 'VibrationZ', type: 'real' }
  { name: 'Clipping0', type: 'int' }
  { name: 'Clipping1', type: 'int' }
  { name: 'Clipping2', type: 'int' }
  { name: 'Command', type: 'int' }
  { name: 'Confirmation', type: 'int' }
  { name: 'Param1', type: 'real' }
  { name: 'Param2', type: 'real' }
  { name: 'Param3', type: 'real' }
  { name: 'Param4', type: 'real' }
  { name: 'TargetSystem', type: 'int' }
  { name: 'TargetComponent', type: 'int' }
  { name: 'Result', type: 'int' }
  { name: 'Seq', type: 'int' }
  { name: 'SystemStatus', type: 'int' }
  { name: 'BaseMode', type: 'int' }
  { name: 'CustomMode', type: 'int' }
  { name: 'MavlinkVersion', type: 'int' }
  { name: 'Severity', type: 'int' }
  { name: 'Text', type: 'string' }
]

var pgseStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'UAVId', type: 'string' }
  { name: 'Operator', type: 'string' }
  { name: 'Serial', type: 'string' }
  { name: 'ImageHashSubmitted', type: 'string' }
  { name: 'ImageHashExpected', type: 'string' }
  { name: 'HashMatch', type: 'boolean' }
  { name: 'SbomForbidden', type: 'string' }
  { name: 'SbomForbiddenCount', type: 'int' }
  { name: 'Passed', type: 'boolean' }
  { name: 'Found', type: 'boolean' }
  { name: 'StatusCode', type: 'int' }
  { name: 'FailReason', type: 'string' }
  { name: 'TokenExpiresAt', type: 'datetime' }
  { name: 'Reason', type: 'string' }
  { name: 'Authorized', type: 'boolean' }
]

var operatorStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'ActionName', type: 'string' }
  { name: 'MsgType', type: 'string' }
  { name: 'SourceSystemId', type: 'int' }
  { name: 'SourceComponentId', type: 'int' }
  { name: 'TargetSystemId', type: 'int' }
  { name: 'TargetComponentId', type: 'int' }
  { name: 'Command', type: 'int' }
  { name: 'Confirmation', type: 'int' }
  { name: 'Param1', type: 'real' }
  { name: 'Param2', type: 'real' }
  { name: 'Param3', type: 'real' }
  { name: 'Param4', type: 'real' }
  { name: 'Result', type: 'int' }
  { name: 'Seq', type: 'int' }
]

var missionStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'UAVId', type: 'string' }
  { name: 'EventName', type: 'string' }
  { name: 'MsgType', type: 'string' }
  { name: 'Command', type: 'int' }
  { name: 'Seq', type: 'int' }
  { name: 'Lat', type: 'real' }
  { name: 'Lon', type: 'real' }
  { name: 'AltMSL_m', type: 'real' }
  { name: 'CustomModeBefore', type: 'int' }
  { name: 'CustomModeAfter', type: 'int' }
]

var serviceAuditStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'Action', type: 'string' }
  { name: 'ActorId', type: 'string' }
  { name: 'ContainerName', type: 'string' }
  { name: 'ImageName', type: 'string' }
  { name: 'ExitCode', type: 'string' }
  { name: 'Signal', type: 'string' }
  { name: 'ServiceLabel', type: 'string' }
  { name: 'ProjectLabel', type: 'string' }
  { name: 'Scope', type: 'string' }
  { name: 'IsDestructiveAction', type: 'boolean' }
  { name: 'LogBearingTargetSuspected', type: 'boolean' }
]

var mpsStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'PlanId', type: 'string' }
  { name: 'UAVId', type: 'string' }
  { name: 'Planner', type: 'string' }
  { name: 'Approver', type: 'string' }
  { name: 'ReleasedBy', type: 'string' }
  { name: 'Callsign', type: 'string' }
  { name: 'Roe', type: 'string' }
  { name: 'PayloadConfig', type: 'string' }
  { name: 'WaypointCount', type: 'int' }
  { name: 'Status', type: 'string' }
  { name: 'Comment', type: 'string' }
  { name: 'FailReason', type: 'string' }
  { name: 'StatusCode', type: 'int' }
  { name: 'RequesterId', type: 'string' }
  { name: 'Found', type: 'boolean' }
]

var datalinkStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'ContainerName', type: 'string' }
  { name: 'InterfaceName', type: 'string' }
  { name: 'RxBytes', type: 'long' }
  { name: 'RxPackets', type: 'long' }
  { name: 'RxErrors', type: 'long' }
  { name: 'RxDropped', type: 'long' }
  { name: 'TxBytes', type: 'long' }
  { name: 'TxPackets', type: 'long' }
  { name: 'TxErrors', type: 'long' }
  { name: 'TxDropped', type: 'long' }
  { name: 'CpuUsagePct', type: 'real' }
  { name: 'MemoryUsageBytes', type: 'long' }
  { name: 'MemoryLimitBytes', type: 'long' }
]

var c4iStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'OrderId', type: 'string' }
  { name: 'Callsign', type: 'string' }
  { name: 'OperationName', type: 'string' }
  { name: 'Objective', type: 'string' }
  { name: 'Roe', type: 'string' }
  { name: 'AreaLat', type: 'real' }
  { name: 'AreaLon', type: 'real' }
  { name: 'AreaRadiusM', type: 'real' }
  { name: 'TargetPriority', type: 'string' }
  { name: 'IssuedBy', type: 'string' }
  { name: 'TargetId', type: 'string' }
  { name: 'Lat', type: 'real' }
  { name: 'Lon', type: 'real' }
  { name: 'AltM', type: 'real' }
  { name: 'Classification', type: 'string' }
  { name: 'ConfidencePct', type: 'int' }
  { name: 'Source', type: 'string' }
  { name: 'ReportedBy', type: 'string' }
  { name: 'UnitCallsign', type: 'string' }
  { name: 'StatusCode', type: 'int' }
  { name: 'ClientIp', type: 'string' }
  { name: 'ResponseBytes', type: 'long' }
]

var cyberPostureStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'PreviousLevel', type: 'string' }
  { name: 'Level', type: 'string' }
  { name: 'ChangedBy', type: 'string' }
  { name: 'Reason', type: 'string' }
  { name: 'Source', type: 'string' }
  { name: 'StatusCode', type: 'int' }
]

var weaponStreamColumns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'EventType', type: 'string' }
  { name: 'WeaponId', type: 'string' }
  { name: 'Operator', type: 'string' }
  { name: 'TargetId', type: 'string' }
  { name: 'SafetyState', type: 'string' }
  { name: 'SafetyStateBefore', type: 'string' }
  { name: 'ArmedBy', type: 'string' }
  { name: 'Status', type: 'string' }
  { name: 'FailReason', type: 'string' }
  { name: 'StatusCode', type: 'int' }
]

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  kind: 'Linux'
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${streamName}': { columns: streamColumns }
      '${pgseStreamName}': { columns: pgseStreamColumns }
      '${operatorStreamName}': { columns: operatorStreamColumns }
      '${missionStreamName}': { columns: missionStreamColumns }
      '${serviceAuditStreamName}': { columns: serviceAuditStreamColumns }
      '${mpsStreamName}': { columns: mpsStreamColumns }
      '${datalinkStreamName}': { columns: datalinkStreamColumns }
      '${c4iStreamName}': { columns: c4iStreamColumns }
      '${cyberPostureStreamName}': { columns: cyberPostureStreamColumns }
      '${weaponStreamName}': { columns: weaponStreamColumns }
    }
    dataSources: {
      logFiles: [
        { name: 'uavTelemetryFile', streams: [ streamName ], filePatterns: [ telemetryLogPath ], format: 'json' }
        { name: 'uavPgseFile', streams: [ pgseStreamName ], filePatterns: [ pgseLogPath ], format: 'json' }
        { name: 'uavOperatorFile', streams: [ operatorStreamName ], filePatterns: [ operatorLogPath ], format: 'json' }
        { name: 'uavMissionFile', streams: [ missionStreamName ], filePatterns: [ missionLogPath ], format: 'json' }
        { name: 'uavServiceAuditFile', streams: [ serviceAuditStreamName ], filePatterns: [ serviceAuditLogPath ], format: 'json' }
        { name: 'uavMpsFile', streams: [ mpsStreamName ], filePatterns: [ mpsLogPath ], format: 'json' }
        { name: 'uavDatalinkFile', streams: [ datalinkStreamName ], filePatterns: [ datalinkLogPath ], format: 'json' }
        { name: 'uavC4iFile', streams: [ c4iStreamName ], filePatterns: [ c4iLogPath ], format: 'json' }
        { name: 'uavCyberPostureFile', streams: [ cyberPostureStreamName ], filePatterns: [ cyberPostureLogPath ], format: 'json' }
        { name: 'uavWeaponFile', streams: [ weaponStreamName ], filePatterns: [ weaponLogPath ], format: 'json' }
      ]
    }
    destinations: {
      logAnalytics: [
        { name: 'centralLaw', workspaceResourceId: law.id }
      ]
    }
    dataFlows: [
      { streams: [ streamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${tableName}' }
      { streams: [ pgseStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${pgseTableName}' }
      { streams: [ operatorStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${operatorTableName}' }
      { streams: [ missionStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${missionTableName}' }
      { streams: [ serviceAuditStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${serviceAuditTableName}' }
      { streams: [ mpsStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${mpsTableName}' }
      { streams: [ datalinkStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${datalinkTableName}' }
      { streams: [ c4iStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${c4iTableName}' }
      { streams: [ cyberPostureStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${cyberPostureTableName}' }
      { streams: [ weaponStreamName ], destinations: [ 'centralLaw' ], transformKql: 'source', outputStream: 'Custom-${weaponTableName}' }
    ]
  }
}

output dceName string = dce.name
output dceId string = dce.id
output dceIngestEndpoint string = dce.properties.logsIngestion.endpoint
output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId

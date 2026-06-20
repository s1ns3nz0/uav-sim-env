// Data Collection Endpoint + Data Collection Rule for UAVTelemetry ingest.
//
// Scope: resource group (dah-data-rg). Idempotent.
//
// Flow:
//   uavsim-vm (Azure Monitor Agent reads /var/log/uav-sim-env/telemetry.ndjson)
//     -> DCE (HTTPS public ingestion endpoint)
//     -> DCR (declares stream schema, transformKql, routes to table)
//     -> UAVTelemetry_CL in Log Analytics
//
// AMA on the VM is configured via DCR association (`Microsoft.Insights/dataCollectionRuleAssociations`),
// added in a separate template once the agent extension is installed.

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

var dceName = '${namePrefix}-dce'
var dcrName = '${namePrefix}-uav-dcr'
var streamName = 'Custom-UAVTelemetry'
var pgseStreamName = 'Custom-UAVPgse'
var operatorStreamName = 'Custom-UAVOperator'
var tableName = 'UAVTelemetry_CL'
var pgseTableName = 'UAVPgse_CL'
var operatorTableName = 'UAVOperator_CL'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

// Data Collection Endpoint — the HTTPS host that ingest traffic hits.
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

// Stream declaration: the columns that the incoming JSON contains. AMA reads
// each NDJSON line, attaches the declared types, and forwards via the DCE.
// The schema must match what telemetry-tap actually emits (tap.py).
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

// Stream declaration for PGSE decision events (low volume, audit-flavoured).
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
]

// Operator-event stream: subset of telemetry containing commands, mode
// changes and mission lifecycle markers.
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

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  kind: 'Linux'
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${streamName}': {
        columns: streamColumns
      }
      '${pgseStreamName}': {
        columns: pgseStreamColumns
      }
      '${operatorStreamName}': {
        columns: operatorStreamColumns
      }
    }
    dataSources: {
      logFiles: [
        {
          name: 'uavTelemetryFile'
          streams: [ streamName ]
          filePatterns: [ telemetryLogPath ]
          format: 'json'
        }
        {
          name: 'uavPgseFile'
          streams: [ pgseStreamName ]
          filePatterns: [ pgseLogPath ]
          format: 'json'
        }
        {
          name: 'uavOperatorFile'
          streams: [ operatorStreamName ]
          filePatterns: [ operatorLogPath ]
          format: 'json'
        }
      ]
    }
    destinations: {
      logAnalytics: [
        {
          name: 'centralLaw'
          workspaceResourceId: law.id
        }
      ]
    }
    dataFlows: [
      {
        streams: [ streamName ]
        destinations: [ 'centralLaw' ]
        transformKql: 'source'
        outputStream: 'Custom-${tableName}'
      }
      {
        streams: [ pgseStreamName ]
        destinations: [ 'centralLaw' ]
        transformKql: 'source'
        outputStream: 'Custom-${pgseTableName}'
      }
      {
        streams: [ operatorStreamName ]
        destinations: [ 'centralLaw' ]
        transformKql: 'source'
        outputStream: 'Custom-${operatorTableName}'
      }
    ]
  }
}

output dceName string = dce.name
output dceId string = dce.id
output dceIngestEndpoint string = dce.properties.logsIngestion.endpoint
output dcrName string = dcr.name
output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId
output telemetryStreamName string = streamName
output pgseStreamName string = pgseStreamName
output operatorStreamName string = operatorStreamName

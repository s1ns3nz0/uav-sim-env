// Custom Log Tables for UAV SOC ingest.
//
// Scope: resource group (dah-data-rg). Idempotent.
//
//   az deployment group create -g dah-data-rg -f sentinel/tables.bicep -n tables-mvp \
//     -p workspaceName=dah-data-law
//
// Tables in this file:
//   UAVTelemetry_CL — MAVLink stream (telemetry-tap NDJSON)
//
// Naming convention: Sentinel custom tables MUST end with "_CL".

@description('Name of the Log Analytics workspace this table lives in.')
param workspaceName string

@description('Days the rows in this table are kept before deletion.')
@minValue(4)
@maxValue(730)
param retentionInDays int = 30

@description('Total days the row is retained including the lower-cost Archive tier. Must be >= retentionInDays.')
@minValue(4)
@maxValue(2555)
param totalRetentionInDays int = 90

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

// Custom Log Table for telemetry-tap MAVLink NDJSON stream.
// Schema is wide on purpose: every MAVLink message type writes the columns it
// has, leaves the rest null. Storage in LA is sparse so unused columns cost
// nothing. KQL rules for any MsgType become single-line filters.
resource uavTelemetry 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVTelemetry_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: retentionInDays
    totalRetentionInDays: totalRetentionInDays
    schema: {
      name: 'UAVTelemetry_CL'
      columns: [
        // Required by Log Analytics — every row needs an ingest timestamp.
        { name: 'TimeGenerated', type: 'datetime' }

        // Identity / routing
        { name: 'UAVId', type: 'string' }
        { name: 'MsgType', type: 'string' }
        { name: 'SystemId', type: 'int' }
        { name: 'ComponentId', type: 'int' }

        // Position / navigation (GLOBAL_POSITION_INT, LOCAL_POSITION_NED)
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

        // GPS (GPS_RAW_INT / GPS2_RAW)
        { name: 'FixType', type: 'int' }
        { name: 'SatellitesVisible', type: 'int' }
        { name: 'Eph_cm', type: 'int' }
        { name: 'Epv_cm', type: 'int' }
        { name: 'VelGround_cms', type: 'int' }
        { name: 'CourseOverGround_cdeg', type: 'int' }

        // Attitude
        { name: 'Roll_rad', type: 'real' }
        { name: 'Pitch_rad', type: 'real' }
        { name: 'Yaw_rad', type: 'real' }
        { name: 'RollSpeed_rads', type: 'real' }
        { name: 'PitchSpeed_rads', type: 'real' }
        { name: 'YawSpeed_rads', type: 'real' }

        // Flight / control (VFR_HUD)
        { name: 'Airspeed_ms', type: 'real' }
        { name: 'Groundspeed_ms', type: 'real' }
        { name: 'Heading_deg', type: 'int' }
        { name: 'Throttle_pct', type: 'int' }
        { name: 'ClimbRate_ms', type: 'real' }

        // EKF status (S1 GNSS spoofing rule core input)
        { name: 'EkfFlags', type: 'int' }
        { name: 'VelocityVariance', type: 'real' }
        { name: 'PosHorizVariance', type: 'real' }
        { name: 'PosVertVariance', type: 'real' }
        { name: 'CompassVariance', type: 'real' }
        { name: 'TerrainAltVariance', type: 'real' }

        // Battery / system health (SYS_STATUS, BATTERY_STATUS)
        { name: 'BatteryVoltage_mV', type: 'int' }
        { name: 'BatteryCurrent_cA', type: 'int' }
        { name: 'BatteryRemaining_pct', type: 'int' }
        { name: 'OnboardCpuLoad_pct', type: 'real' }
        { name: 'ErrorsComm', type: 'int' }
        { name: 'DropRateComm_pct', type: 'real' }

        // Vibration
        { name: 'VibrationX', type: 'real' }
        { name: 'VibrationY', type: 'real' }
        { name: 'VibrationZ', type: 'real' }
        { name: 'Clipping0', type: 'int' }
        { name: 'Clipping1', type: 'int' }
        { name: 'Clipping2', type: 'int' }

        // Command (A4 MAVLink injection rule core input)
        { name: 'Command', type: 'int' }
        { name: 'Confirmation', type: 'int' }
        { name: 'Param1', type: 'real' }
        { name: 'Param2', type: 'real' }
        { name: 'Param3', type: 'real' }
        { name: 'Param4', type: 'real' }
        { name: 'TargetSystem', type: 'int' }
        { name: 'TargetComponent', type: 'int' }
        { name: 'Result', type: 'int' }

        // Mission
        { name: 'Seq', type: 'int' }

        // Heartbeat / status text
        { name: 'SystemStatus', type: 'int' }
        { name: 'BaseMode', type: 'int' }
        { name: 'CustomMode', type: 'int' }
        { name: 'MavlinkVersion', type: 'int' }
        { name: 'Severity', type: 'int' }
        { name: 'Text', type: 'string' }
      ]
    }
  }
}

// Custom Log Table for PGSE decision events (firmware/preflight/launch).
// Volume is low (one row per REST call), so use a longer retention than the
// telemetry stream — these events feed S4 supply-chain rules and may be needed
// for after-action audits.
resource uavPgse 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVPgse_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 365
    schema: {
      name: 'UAVPgse_CL'
      columns: [
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
    }
  }
}

output tableName string = uavTelemetry.name
output tableId string = uavTelemetry.id
output pgseTableName string = uavPgse.name
output pgseTableId string = uavPgse.id

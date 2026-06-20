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

// Custom Log Table for operator-control events (commands, mode changes,
// mission lifecycle). Filtered subset of UAVTelemetry — same retention class
// but separated so insider-threat / forensics rules can scope cheaply.
resource uavOperator 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVOperator_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVOperator_CL'
      columns: [
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
    }
  }
}

// Mission-lifecycle events derived in tap.py (takeoff, waypoint_reached,
// mode_change, roi_set, land, rtl, ...). Carries the geo at the time of the
// event so timelines can be plotted without joining back to UAVTelemetry.
resource uavMissionEvent 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVMissionEvent_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVMissionEvent_CL'
      columns: [
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
    }
  }
}

// Docker engine event audit. Container lifecycle for the SOC ops surface
// ("av-mpd died during mission", "unexpected image pulled").
resource uavServiceAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVServiceAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVServiceAudit_CL'
      columns: [
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
      ]
    }
  }
}

// MPS audit table — primary OSCAL evidence source (who planned, who approved,
// who released). Retention deliberately long for after-action investigations.
resource uavMissionPlan 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVMissionPlan_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 730
    schema: {
      name: 'UAVMissionPlan_CL'
      columns: [
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
      ]
    }
  }
}

// Datalink health snapshot — container-level network counters polled every
// 30 sec by the datalink-stats sidecar. KQL rules compute deltas to detect
// jamming-like packet loss spikes or unauthorised secondary traffic.
resource uavDatalink 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVDatalink_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVDatalink_CL'
      columns: [
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
    }
  }
}

// ATCIS / MIMS C4I integration audit — operational picture changes that the
// SOC + LangGraph agents correlate with UAV behaviour. METT+TC inputs flow
// through this table.
resource uavC4i 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVC4I_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 365
    schema: {
      name: 'UAVC4I_CL'
      columns: [
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
      ]
    }
  }
}

// Cyber threat posture transitions (CT-3 / CT-2 / CT-1). Low-volume but
// long-retention — primary input for OSCAL control evidence ("control
// strength elevated because of CT-2 declaration").
resource uavCyberPosture 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVCyberPosture_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 365
    totalRetentionInDays: 730
    schema: {
      name: 'UAVCyberPosture_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'PreviousLevel', type: 'string' }
        { name: 'Level', type: 'string' }
        { name: 'ChangedBy', type: 'string' }
        { name: 'Reason', type: 'string' }
        { name: 'Source', type: 'string' }
        { name: 'StatusCode', type: 'int' }
      ]
    }
  }
}

output tableName string = uavTelemetry.name
output tableId string = uavTelemetry.id
output pgseTableName string = uavPgse.name
output pgseTableId string = uavPgse.id
output operatorTableName string = uavOperator.name
output operatorTableId string = uavOperator.id
output missionEventTableName string = uavMissionEvent.name
output serviceAuditTableName string = uavServiceAudit.name
output missionPlanTableName string = uavMissionPlan.name
output datalinkTableName string = uavDatalink.name
output c4iTableName string = uavC4i.name
output cyberPostureTableName string = uavCyberPosture.name

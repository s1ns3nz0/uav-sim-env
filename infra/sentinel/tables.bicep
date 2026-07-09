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

        // GPS_INPUT — 외부 주입 API(실 GPS 수신기는 미생성). 존재=스푸핑/주입 신호(S1/S61).
        { name: 'GpsInputInjected', type: 'boolean' }
        { name: 'Hdop', type: 'real' }
        { name: 'Vdop', type: 'real' }
        { name: 'IgnoreFlags', type: 'int' }

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
        // T0800(Activate Firmware Update Mode) — 강제 진입 이벤트.
        { name: 'Reason', type: 'string' }
        { name: 'Authorized', type: 'boolean' }
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
        // S47(anti-forensics/로그삭제)·S66(데이터 파괴) — 기존 Docker 이벤트 파생 지표.
        { name: 'IsDestructiveAction', type: 'boolean' }
        { name: 'LogBearingTargetSuspected', type: 'boolean' }
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
        // T0845(Program/Param Upload — 임무계획 추출) — plan_read 전용.
        { name: 'RequesterId', type: 'string' }
        { name: 'Found', type: 'boolean' }
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
        // T1567(Exfiltration Over Web Service) — /current-operation 읽기 감사.
        { name: 'ClientIp', type: 'string' }
        { name: 'ResponseBytes', type: 'long' }
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

resource uavWeapon 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVWeapon_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 730
    schema: {
      name: 'UAVWeapon_CL'
      columns: [
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
    }
  }
}

resource uavThreatIntel 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVThreatIntel_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 365
    schema: {
      name: 'UAVThreatIntel_CL'
      columns: [
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
    }
  }
}

resource uavOpAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVOpAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 365
    schema: {
      name: 'UAVOpAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'Operator', type: 'string' }
        { name: 'ClientIp', type: 'string' }
        { name: 'UserAgent', type: 'string' }
        { name: 'SessionId', type: 'string' }
        { name: 'FailReason', type: 'string' }
        { name: 'StatusCode', type: 'int' }
        // T1556(Modify Auth Process)/T0859(백도어 계정) — auth_policy_changed/
        // account_created 전용. TargetOperator=대상 필드명 또는 생성된 계정명.
        { name: 'TargetOperator', type: 'string' }
        { name: 'Detail', type: 'string' }
      ]
    }
  }
}

resource uavFailsafe 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVFailsafe_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVFailsafe_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'EventType', type: 'string' }
        { name: 'Severity', type: 'int' }
        { name: 'Text', type: 'string' }
        { name: 'ModeBefore', type: 'int' }
        { name: 'ModeAfter', type: 'int' }
        // T0878(Alarm Suppression) — HEARTBEAT 주기 공백(경보 링크 억제 대리신호).
        { name: 'GapSec', type: 'real' }
      ]
    }
  }
}

resource uavMavsec 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVMavsec_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVMavsec_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'EventType', type: 'string' }
        { name: 'SignedCount', type: 'long' }
        { name: 'UnsignedCount', type: 'long' }
        { name: 'FailedCount', type: 'long' }
        { name: 'WindowSec', type: 'int' }
      ]
    }
  }
}

resource uavMaintenance 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVMaintenance_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 365
    totalRetentionInDays: 730
    schema: {
      name: 'UAVMaintenance_CL'
      columns: [
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
    }
  }
}

resource uavImagery 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVImagery_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVImagery_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'EventType', type: 'string' }
        { name: 'MsgType', type: 'string' }
      ]
    }
  }
}

resource uavConfigAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVConfigAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 730
    schema: {
      name: 'UAVConfigAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'EventType', type: 'string' }
        { name: 'ParamId', type: 'string' }
        { name: 'ParamValueBefore', type: 'real' }
        { name: 'ParamValueAfter', type: 'real' }
        { name: 'Source', type: 'string' }
      ]
    }
  }
}

resource uavResourceMetrics 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVResourceMetrics_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVResourceMetrics_CL'
      columns: [
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
    }
  }
}

resource uavDatalinkConn 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVDatalinkConn_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVDatalinkConn_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'State', type: 'string' }
        { name: 'LocalIp', type: 'string' }
        { name: 'LocalPort', type: 'int' }
        { name: 'PeerIp', type: 'string' }
        { name: 'PeerPort', type: 'int' }
      ]
    }
  }
}

// ───────────────────────────────────────────────────────────────────────────
// 확장(KUS-FS 편대 + SATCOM) 신규 테이블 — schema 문서 §20
// ───────────────────────────────────────────────────────────────────────────

// SATCOM(BLOS) 위성 링크/세션 상태 — datalink-satcom(OpenSAND) satcom.ndjson.
resource uavSatcomLink 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVSatcomLink_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVSatcomLink_CL'
      columns: [
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
        // S65 C2 은닉(터널링/암호화/난독화/인코딩) 지표 — datalink-satcom covert 모드.
        { name: 'Encoding', type: 'string' }
        { name: 'PayloadEntropy', type: 'real' }
        { name: 'BeaconJitterSec', type: 'real' }
        // T1011(Exfiltration Over Other Network Medium) — SATCOM 링크 용량 컬럼.
        { name: 'PayloadBytes', type: 'long' }
      ]
    }
  }
}

// SAR 페이로드 프레임 메타 — sar-stub sar.ndjson.
resource uavSarPayload 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVSarPayload_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVSarPayload_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'FrameId', type: 'string' }
        { name: 'TargetLat', type: 'real' }
        { name: 'TargetLon', type: 'real' }
        { name: 'Resolution', type: 'string' }
        { name: 'SensorMode', type: 'string' }
        { name: 'SizeBytes', type: 'long' }
      ]
    }
  }
}

// UAVGcsAccess_CL 정의는 pollack-ai/deploy/sentinel-tables (dcr-uav-soc) 가 소유 — 여기서는 빠짐.

// mavlink-router 내부 통계 — datalink-los router-stats.ndjson.
resource uavRouterStats 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVRouterStats_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVRouterStats_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EndpointName', type: 'string' }
        { name: 'MsgRx', type: 'long' }
        { name: 'MsgTx', type: 'long' }
        { name: 'MsgDropped', type: 'long' }
        { name: 'CrcErrors', type: 'long' }
        // T1557(텔레메트리 릴레이 MITM) — 알려진 엔드포인트 명단 밖의 이름이면 true.
        { name: 'UnexpectedEndpoint', type: 'boolean' }
      ]
    }
  }
}

// 편대 단위 상태/이상 요약 — telemetry-tap 파생 fleet-state.ndjson.
resource uavFleetState 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVFleetState_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVFleetState_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'WindowStart', type: 'datetime' }
        { name: 'FleetId', type: 'string' }
        { name: 'ActiveUAVCount', type: 'int' }
        { name: 'DivergingCount', type: 'int' }
        { name: 'CommonCommand', type: 'string' }
        { name: 'AnomalyScore', type: 'real' }
        // S103(충돌유도)/S105(Sybil) — grilling 세션 결정, 실 다중차량 데이터 기반.
        { name: 'MinPairDistanceDeg', type: 'real' }
        { name: 'CollisionRiskPair', type: 'string' }
        { name: 'UnknownUavIdDetected', type: 'boolean' }
      ]
    }
  }
}

// 카운터-UAS RF 탐지·재밍 교전 — counter-uas 시뮬(송신 없음).
resource uavCounterUas 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVCounterUas_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVCounterUas_CL'
      columns: [
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
    }
  }
}

// web-stub IT 계층 공격면(S48~S52) — 인증우회/IDOR·웹셸업로드·SUID/GTFOBins·
// 컨테이너escape·cron하이재킹. web.ndjson.
resource uavWebAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVWebAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVWebAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'RequesterId', type: 'string' }
        { name: 'TargetId', type: 'string' }
        { name: 'IdorSuspected', type: 'boolean' }
        { name: 'Filename', type: 'string' }
        { name: 'ContentSnippet', type: 'string' }
        { name: 'WebshellSignatureDetected', type: 'boolean' }
        { name: 'MatchedPattern', type: 'string' }
        { name: 'Binary', type: 'string' }
        { name: 'Args', type: 'string' }
        { name: 'GtfobinsMatch', type: 'boolean' }
        { name: 'PrivilegeBefore', type: 'string' }
        { name: 'PrivilegeAfter', type: 'string' }
        { name: 'EscapeMethod', type: 'string' }
        { name: 'TargetPath', type: 'string' }
        { name: 'CronEntry', type: 'string' }
        { name: 'InstalledBy', type: 'string' }
        { name: 'StatusCode', type: 'int' }
        // T0851(Rootkit — Inhibit Response) — rootkit_install_attempt 전용.
        { name: 'AlarmsInhibited', type: 'boolean' }
      ]
    }
  }
}

// web-stub 아카이브 추출(S53~S55) — Zip Slip·tar 심볼릭링크 탈출·절대경로.
// web-archive.ndjson.
resource uavArchiveAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVArchiveAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVArchiveAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'ArchiveName', type: 'string' }
        { name: 'Mode', type: 'string' }
        { name: 'EntryPath', type: 'string' }
        { name: 'PathTraversalDetected', type: 'boolean' }
        { name: 'AbsolutePathDetected', type: 'boolean' }
        { name: 'SymlinkEscapeDetected', type: 'boolean' }
        { name: 'ExtractedCount', type: 'int' }
        { name: 'BlockedCount', type: 'int' }
        { name: 'StatusCode', type: 'int' }
      ]
    }
  }
}

// 호스트/컨테이너 파일·프로세스 실행 감사 — eBPF/Falco 소스(pollack-ai 설계, 소유권
// uav-sim-env: 테이블+DCR+소스 emit). S47 anti-forensics(로그삭제)·S51/S56 컨테이너
// escape 후속·S57 cron persistence·T0809/T1485 데이터파괴의 파일계층 1차 근거.
// NOTE: 스키마+DCR 스트림만 선등록(UAVFleetState_CL과 동일 패턴) — Falco/eBPF
// 프로듀서는 아직 이 repo에 미구현. 프로듀서 배선 전까지는 미적재 상태.
resource uavFileAudit 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVFileAudit_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVFileAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'ContainerName', type: 'string' }
        { name: 'Pid', type: 'int' }
        { name: 'ProcessName', type: 'string' }
        { name: 'Operation', type: 'string' }
        { name: 'FilePath', type: 'string' }
        { name: 'BytesAccessed', type: 'long' }
        { name: 'User', type: 'string' }
        { name: 'Syscall', type: 'string' }
        // S47 anti-forensics 재사용(UAVServiceAudit_CL과 동일 휴리스틱, 파일 계층).
        { name: 'LogBearingTargetSuspected', type: 'boolean' }
        { name: 'PersistenceTargetSuspected', type: 'boolean' }
      ]
    }
  }
}

// WiFi 텔레메트리 AP + RC 제어링크 공격면(S25~S31) — rc-link-stub rc-link.ndjson.
resource uavRcLink 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVRcLink_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 90
    schema: {
      name: 'UAVRcLink_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'DeviceId', type: 'string' }
        { name: 'UavId', type: 'string' }
        { name: 'Ssid', type: 'string' }
        { name: 'BssidMismatch', type: 'boolean' }
        { name: 'DefaultCredentialUsed', type: 'boolean' }
        { name: 'BindCodeReused', type: 'boolean' }
        { name: 'Channel', type: 'int' }
        { name: 'ChannelValue', type: 'int' }
        { name: 'OverrideAuthorized', type: 'boolean' }
        { name: 'ProtocolRequested', type: 'string' }
        { name: 'ProtocolNegotiated', type: 'string' }
        { name: 'DowngradeDetected', type: 'boolean' }
        { name: 'StatusCode', type: 'int' }
      ]
    }
  }
}

// 아티팩트 서명 우회(T1553, S73) + mTLS 인증서 위조(T1649, S70) —
// supply-chain-stub supply-chain.ndjson.
resource uavSupplyChain 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVSupplyChain_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 180
    totalRetentionInDays: 365
    schema: {
      name: 'UAVSupplyChain_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventType', type: 'string' }
        { name: 'Subject', type: 'string' }
        { name: 'Issuer', type: 'string' }
        { name: 'SignatureValid', type: 'boolean' }
        { name: 'BypassSuspected', type: 'boolean' }
        { name: 'CertSerial', type: 'string' }
        { name: 'CertForgedSuspected', type: 'boolean' }
        { name: 'StatusCode', type: 'int' }
      ]
    }
  }
}

// GCS 애플리케이션 + 컴패니언/ROS 공격면(S41~S47/S50) — companion-stub companion.ndjson.
resource uavCompanion 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVCompanion_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVCompanion_CL'
      columns: [
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
    }
  }
}

// 빌드/배포 파이프라인 + DDS/MQTT 미들웨어 공격면(S67~S76) — devops-stub devops.ndjson.
resource uavDevOps 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVDevOps_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVDevOps_CL'
      columns: [
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
    }
  }
}

// 함대관리 API + RTSP + 스웜조정(S81/S83/S106/S108) — fleet-infra-stub fleet-infra.ndjson.
resource uavFleetInfra 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVFleetInfra_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVFleetInfra_CL'
      columns: [
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
    }
  }
}

// S121 방어 — SITL 직결 진실값(datalink-los 중계 우회). ground-truth-tap.
resource uavGroundTruth 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'UAVGroundTruth_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 90
    totalRetentionInDays: 180
    schema: {
      name: 'UAVGroundTruth_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'UAVId', type: 'string' }
        { name: 'GroundTruthCustomMode', type: 'int' }
        { name: 'Source', type: 'string' }
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
output weaponTableName string = uavWeapon.name
output threatIntelTableName string = uavThreatIntel.name
output opAuditTableName string = uavOpAudit.name
output failsafeTableName string = uavFailsafe.name
output mavsecTableName string = uavMavsec.name
output maintenanceTableName string = uavMaintenance.name
output imageryTableName string = uavImagery.name
output configAuditTableName string = uavConfigAudit.name
output resourceMetricsTableName string = uavResourceMetrics.name
output datalinkConnTableName string = uavDatalinkConn.name
output satcomLinkTableName string = uavSatcomLink.name
output sarPayloadTableName string = uavSarPayload.name
output routerStatsTableName string = uavRouterStats.name
output fleetStateTableName string = uavFleetState.name
output counterUasTableName string = uavCounterUas.name
output counterUasTableId string = uavCounterUas.id
output webAuditTableName string = uavWebAudit.name
output archiveAuditTableName string = uavArchiveAudit.name
output fileAuditTableName string = uavFileAudit.name
output rcLinkTableName string = uavRcLink.name
output supplyChainTableName string = uavSupplyChain.name
output companionTableName string = uavCompanion.name
output devOpsTableName string = uavDevOps.name
output fleetInfraTableName string = uavFleetInfra.name
output groundTruthTableName string = uavGroundTruth.name

(*
  Air-cooled chiller controller: 4 scroll compressors on 4 refrigerant circuits
  IEC 61131-3 Structured Text, runs in OpenPLC (10 Hz task)

  Reusable function blocks:
    FB_Compressor  minimum ON, minimum OFF and start-to-start timers, start counter, run time
    FB_PI          PI loop for cooling with anti-windup (conditional integration)
    FB_Alarm       delayed alarm, latching or self-resetting, reset command
    FB_Hyst        on/off with hysteresis (condenser fans)
    FB_HpCircuit   high-pressure trip with auto reset and lockout after repeated trips

  Field I/O on Modbus TCP remote I/O (the plant simulator):
    %IW100..%IW106  leaving water, return water, ambient (x10 degC), condensing pressure 1..4 (x10 bar)
    %IX100.0        flow switch
    %QX100.0        chilled water pump
    %QX100.1..4     compressors 1..4
    %QX100.5..7, %QX101.0  condenser fans 1..4
    %QX101.1        common alarm relay

  BMS interface (Modbus TCP server of the PLC, holding register = 1024 + word):
    written by the BMS:  %MW0 unit enable, %MW1 setpoint x10 degC, %MW2 alarm reset (PLC clears it)
    read by the BMS:     %MW10.. status, alarms, starts and run time per compressor

  Timers are scaled 1:9 for the simulation (min ON 20 s, min OFF 40 s, start-to-start 60 s
  stand for 3, 6 and 9 minutes on a real unit).
*)

FUNCTION_BLOCK FB_Compressor
  VAR_INPUT
    Request          : BOOL;
    Enable           : BOOL;    (* FALSE = safety trip: stops at once, ignores minimum ON *)
    CycleS               : REAL;    (* task period, s *)
    MinOnS           : REAL;
    MinOffS          : REAL;
    MinStartToStartS : REAL;
  END_VAR
  VAR_OUTPUT
    Run      : BOOL;
    CanStart : BOOL;
    CanStop  : BOOL;
    Starts   : INT;
    RunS     : REAL;            (* accumulated run time, used for rotation *)
  END_VAR
  VAR
    OnS         : REAL := 0.0;
    OffS        : REAL := 10000.0;
    SinceStartS : REAL := 10000.0;
  END_VAR

  IF Run THEN
    OnS := OnS + CycleS;
    RunS := RunS + CycleS;
  ELSE
    OffS := OffS + CycleS;
  END_IF;
  IF SinceStartS < 10000.0 THEN
    SinceStartS := SinceStartS + CycleS;
  END_IF;

  CanStart := NOT Run AND Enable AND OffS >= MinOffS AND SinceStartS >= MinStartToStartS;
  CanStop  := Run AND OnS >= MinOnS;

  IF Run AND NOT Enable THEN
    Run := FALSE;
    OffS := 0.0;
  ELSIF Request AND CanStart THEN
    Run := TRUE;
    OnS := 0.0;
    SinceStartS := 0.0;
    Starts := Starts + 1;
  ELSIF NOT Request AND CanStop THEN
    Run := FALSE;
    OffS := 0.0;
  END_IF;
END_FUNCTION_BLOCK


FUNCTION_BLOCK FB_PI
  VAR_INPUT
    PV     : REAL;
    SP     : REAL;
    Kp     : REAL;      (* % per K *)
    TiS    : REAL;
    CycleS     : REAL;
    Enable : BOOL;
    HoldUp : BOOL;      (* no more capacity available: do not integrate upwards *)
  END_VAR
  VAR_OUTPUT
    Out : REAL;         (* capacity demand 0..100 % *)
  END_VAR
  VAR
    I : REAL := 0.0;
    E : REAL;
    U : REAL;
  END_VAR

  IF NOT Enable THEN
    I := 0.0;
    Out := 0.0;
  ELSE
    E := PV - SP;                                   (* cooling: too warm = more demand *)
    U := Kp * E + I;
    IF NOT ((U >= 100.0 AND E > 0.0) OR (U <= 0.0 AND E < 0.0) OR (HoldUp AND E > 0.0)) THEN
      I := I + Kp * E * CycleS / TiS;
    END_IF;
    Out := LIMIT(0.0, Kp * E + I, 100.0);
  END_IF;
END_FUNCTION_BLOCK


FUNCTION_BLOCK FB_Alarm
  VAR_INPUT
    Cond   : BOOL;
    DelayS : REAL;
    CycleS     : REAL;
    Latch  : BOOL;
    Reset  : BOOL;
  END_VAR
  VAR_OUTPUT
    Active : BOOL;
  END_VAR
  VAR
    T : REAL := 0.0;
  END_VAR

  IF Cond THEN
    T := T + CycleS;
  ELSE
    T := 0.0;
  END_IF;
  IF Cond AND T >= DelayS THEN
    Active := TRUE;
  ELSIF NOT Cond AND (NOT Latch OR Reset) THEN
    Active := FALSE;
  END_IF;
END_FUNCTION_BLOCK


FUNCTION_BLOCK FB_Hyst
  VAR_INPUT
    X        : REAL;
    OnAbove  : REAL;
    OffBelow : REAL;
  END_VAR
  VAR_OUTPUT
    Q : BOOL;
  END_VAR

  IF X >= OnAbove THEN
    Q := TRUE;
  ELSIF X <= OffBelow THEN
    Q := FALSE;
  END_IF;
END_FUNCTION_BLOCK


FUNCTION_BLOCK FB_HpCircuit
  VAR_INPUT
    P        : REAL;    (* condensing pressure, bar *)
    TripBar  : REAL;
    ResetBar : REAL;
    MaxTrips : INT;
    Reset    : BOOL;    (* operator reset, clears the lockout *)
  END_VAR
  VAR_OUTPUT
    Tripped : BOOL;
    Locked  : BOOL;
    Trips   : INT;
  END_VAR

  IF P >= TripBar AND NOT Tripped THEN
    Tripped := TRUE;
    Trips := Trips + 1;
    IF Trips >= MaxTrips THEN
      Locked := TRUE;
    END_IF;
  END_IF;
  IF Tripped AND NOT Locked AND P <= ResetBar THEN
    Tripped := FALSE;                               (* automatic reset *)
  END_IF;
  IF Reset AND P <= ResetBar THEN
    Tripped := FALSE;
    Locked := FALSE;
    Trips := 0;
  END_IF;
END_FUNCTION_BLOCK


PROGRAM Chiller
  VAR
    (* ---- field inputs ---- *)
    T_LW_RAW  AT %IW100 : INT;
    T_RW_RAW  AT %IW101 : INT;
    T_AMB_RAW AT %IW102 : INT;
    P1_RAW    AT %IW103 : INT;
    P2_RAW    AT %IW104 : INT;
    P3_RAW    AT %IW105 : INT;
    P4_RAW    AT %IW106 : INT;
    FLOW_SW   AT %IX100.0 : BOOL;

    (* ---- field outputs ---- *)
    PUMP        AT %QX100.0 : BOOL;
    COMP1       AT %QX100.1 : BOOL;
    COMP2       AT %QX100.2 : BOOL;
    COMP3       AT %QX100.3 : BOOL;
    COMP4       AT %QX100.4 : BOOL;
    FAN1        AT %QX100.5 : BOOL;
    FAN2        AT %QX100.6 : BOOL;
    FAN3        AT %QX100.7 : BOOL;
    FAN4        AT %QX101.0 : BOOL;
    ALARM_RELAY AT %QX101.1 : BOOL;

    (* ---- BMS: commands ---- *)
    BMS_ENABLE AT %MW0 : INT;
    BMS_SP     AT %MW1 : INT;
    BMS_RESET  AT %MW2 : INT;

    (* ---- BMS: status ---- *)
    ST_TLW     AT %MW10 : INT;    (* leaving water x10 *)
    ST_SP      AT %MW11 : INT;    (* active setpoint x10 *)
    ST_DEMAND  AT %MW12 : INT;    (* PI demand % *)
    ST_STAGES  AT %MW13 : INT;    (* compressors running *)
    ST_ALARMS  AT %MW14 : INT;    (* bit 0 flow, 1 freeze, 2 sensor, 3..6 HP trip 1..4, 7..10 lockout 1..4 *)
    ST_STATE   AT %MW15 : INT;    (* 0 off, 1 waiting for flow, 2 running, 3 tripped *)
    ST_STARTS1 AT %MW16 : INT;
    ST_STARTS2 AT %MW17 : INT;
    ST_STARTS3 AT %MW18 : INT;
    ST_STARTS4 AT %MW19 : INT;
    ST_RUN1    AT %MW20 : INT;    (* run time, s *)
    ST_RUN2    AT %MW21 : INT;
    ST_RUN3    AT %MW22 : INT;
    ST_RUN4    AT %MW23 : INT;
  END_VAR

  VAR
    CycleS          : REAL := 0.1;
    MIN_ON_S    : REAL := 20.0;
    MIN_OFF_S   : REAL := 40.0;
    START_S2S_S : REAL := 60.0;
    STAGE_S     : REAL := 15.0;   (* delay between two staging steps *)
    LOW_LW_C    : REAL := 4.0;    (* low leaving water: unload faster *)

    Tlw, Trw, Tamb, Sp : REAL;
    P        : ARRAY[1..4] OF REAL;
    Req      : ARRAY[1..4] OF BOOL;
    Run      : ARRAY[1..4] OF BOOL;
    CanStart : ARRAY[1..4] OF BOOL;
    CanStop  : ARRAY[1..4] OF BOOL;
    RunS     : ARRAY[1..4] OF REAL;
    Tripped  : ARRAY[1..4] OF BOOL;
    Locked   : ARRAY[1..4] OF BOOL;

    Enabled, Permit, ResetCmd, ResetPrev, ResetEdge : BOOL;
    PumpOnS, StageT, Best : REAL;
    Nrun, Navail, k, Pick, Alarms : INT;

    Cmp1 : FB_Compressor;
    Cmp2 : FB_Compressor;
    Cmp3 : FB_Compressor;
    Cmp4 : FB_Compressor;
    Hp1  : FB_HpCircuit;
    Hp2  : FB_HpCircuit;
    Hp3  : FB_HpCircuit;
    Hp4  : FB_HpCircuit;
    FanCtl1 : FB_Hyst;
    FanCtl2 : FB_Hyst;
    FanCtl3 : FB_Hyst;
    FanCtl4 : FB_Hyst;
    Pi                         : FB_PI;
    AlFlow   : FB_Alarm;
    AlFreeze : FB_Alarm;
    AlSensor : FB_Alarm;
  END_VAR

  (* ===================== inputs and BMS commands ===================== *)
  Tlw  := INT_TO_REAL(T_LW_RAW) / 10.0;
  Trw  := INT_TO_REAL(T_RW_RAW) / 10.0;
  Tamb := INT_TO_REAL(T_AMB_RAW) / 10.0;
  P[1] := INT_TO_REAL(P1_RAW) / 10.0;
  P[2] := INT_TO_REAL(P2_RAW) / 10.0;
  P[3] := INT_TO_REAL(P3_RAW) / 10.0;
  P[4] := INT_TO_REAL(P4_RAW) / 10.0;

  Sp := 7.0;                                         (* default when the BMS gives no valid value *)
  IF BMS_SP >= 40 AND BMS_SP <= 150 THEN
    Sp := INT_TO_REAL(BMS_SP) / 10.0;
  END_IF;
  Enabled := BMS_ENABLE <> 0;
  ResetCmd := BMS_RESET <> 0;
  ResetEdge := ResetCmd AND NOT ResetPrev;
  ResetPrev := ResetCmd;
  IF ResetCmd THEN
    BMS_RESET := 0;                                  (* command consumed *)
  END_IF;

  (* ===================== pump, interlocks and alarms ===================== *)
  PUMP := Enabled;
  IF PUMP THEN
    PumpOnS := PumpOnS + CycleS;
  ELSE
    PumpOnS := 0.0;
  END_IF;

  AlFlow(Cond := PUMP AND PumpOnS > 5.0 AND NOT FLOW_SW, DelayS := 2.0, CycleS := CycleS, Latch := TRUE, Reset := ResetEdge);
  AlFreeze(Cond := Tlw < 3.0, DelayS := 0.0, CycleS := CycleS, Latch := TRUE, Reset := ResetEdge);
  AlSensor(Cond := Tlw < -20.0 OR Tlw > 60.0, DelayS := 1.0, CycleS := CycleS, Latch := TRUE, Reset := ResetEdge);

  (* compressors may only run with water flowing and no unit trip *)
  Permit := Enabled AND FLOW_SW AND NOT AlFlow.Active AND NOT AlFreeze.Active AND NOT AlSensor.Active;

  Hp1(P := P[1], TripBar := 41.5, ResetBar := 30.0, MaxTrips := 3, Reset := ResetEdge);
  Hp2(P := P[2], TripBar := 41.5, ResetBar := 30.0, MaxTrips := 3, Reset := ResetEdge);
  Hp3(P := P[3], TripBar := 41.5, ResetBar := 30.0, MaxTrips := 3, Reset := ResetEdge);
  Hp4(P := P[4], TripBar := 41.5, ResetBar := 30.0, MaxTrips := 3, Reset := ResetEdge);
  Tripped[1] := Hp1.Tripped; Tripped[2] := Hp2.Tripped; Tripped[3] := Hp3.Tripped; Tripped[4] := Hp4.Tripped;
  Locked[1] := Hp1.Locked;   Locked[2] := Hp2.Locked;   Locked[3] := Hp3.Locked;   Locked[4] := Hp4.Locked;

  (* ===================== capacity control ===================== *)
  Nrun := 0;
  Navail := 0;
  FOR k := 1 TO 4 DO
    IF Run[k] THEN Nrun := Nrun + 1; END_IF;
    IF NOT Tripped[k] THEN Navail := Navail + 1; END_IF;
    IF Tripped[k] THEN Req[k] := FALSE; END_IF;      (* a tripped circuit drops its request *)
  END_FOR;

  Pi(PV := Tlw, SP := Sp, Kp := 25.0, TiS := 60.0, CycleS := CycleS, Enable := Permit, HoldUp := Nrun >= Navail);

  StageT := StageT + CycleS;
  IF NOT Permit THEN
    FOR k := 1 TO 4 DO Req[k] := FALSE; END_FOR;
    StageT := 0.0;
  ELSIF Tlw < LOW_LW_C AND Nrun > 0 AND StageT >= 3.0 THEN
    (* low leaving water: shed one compressor every 3 s (still after its minimum ON) *)
    Pick := 0; Best := -1.0;
    FOR k := 1 TO 4 DO
      IF Req[k] AND CanStop[k] AND RunS[k] > Best THEN Pick := k; Best := RunS[k]; END_IF;
    END_FOR;
    IF Pick > 0 THEN Req[Pick] := FALSE; StageT := 0.0; END_IF;
  ELSIF StageT >= STAGE_S THEN
    IF Pi.Out > INT_TO_REAL(Nrun) * 25.0 + 5.0 THEN
      (* stage up: start the available compressor with the fewest run hours *)
      Pick := 0; Best := 1.0E9;
      FOR k := 1 TO 4 DO
        IF NOT Req[k] AND CanStart[k] AND RunS[k] < Best THEN Pick := k; Best := RunS[k]; END_IF;
      END_FOR;
      IF Pick > 0 THEN Req[Pick] := TRUE; StageT := 0.0; END_IF;
    ELSIF Nrun > 0 AND (Pi.Out < INT_TO_REAL(Nrun - 1) * 25.0 - 5.0 OR (Nrun = 1 AND Pi.Out <= 0.0)) THEN
      (* stage down: stop the running compressor with the most run hours *)
      Pick := 0; Best := -1.0;
      FOR k := 1 TO 4 DO
        IF Req[k] AND CanStop[k] AND RunS[k] > Best THEN Pick := k; Best := RunS[k]; END_IF;
      END_FOR;
      IF Pick > 0 THEN Req[Pick] := FALSE; StageT := 0.0; END_IF;
    END_IF;
  END_IF;

  Cmp1(Request := Req[1], Enable := Permit AND NOT Tripped[1], CycleS := CycleS, MinOnS := MIN_ON_S, MinOffS := MIN_OFF_S, MinStartToStartS := START_S2S_S);
  Cmp2(Request := Req[2], Enable := Permit AND NOT Tripped[2], CycleS := CycleS, MinOnS := MIN_ON_S, MinOffS := MIN_OFF_S, MinStartToStartS := START_S2S_S);
  Cmp3(Request := Req[3], Enable := Permit AND NOT Tripped[3], CycleS := CycleS, MinOnS := MIN_ON_S, MinOffS := MIN_OFF_S, MinStartToStartS := START_S2S_S);
  Cmp4(Request := Req[4], Enable := Permit AND NOT Tripped[4], CycleS := CycleS, MinOnS := MIN_ON_S, MinOffS := MIN_OFF_S, MinStartToStartS := START_S2S_S);
  Run[1] := Cmp1.Run; Run[2] := Cmp2.Run; Run[3] := Cmp3.Run; Run[4] := Cmp4.Run;
  CanStart[1] := Cmp1.CanStart; CanStart[2] := Cmp2.CanStart; CanStart[3] := Cmp3.CanStart; CanStart[4] := Cmp4.CanStart;
  CanStop[1] := Cmp1.CanStop; CanStop[2] := Cmp2.CanStop; CanStop[3] := Cmp3.CanStop; CanStop[4] := Cmp4.CanStop;
  RunS[1] := Cmp1.RunS; RunS[2] := Cmp2.RunS; RunS[3] := Cmp3.RunS; RunS[4] := Cmp4.RunS;
  COMP1 := Cmp1.Run; COMP2 := Cmp2.Run; COMP3 := Cmp3.Run; COMP4 := Cmp4.Run;

  (* ===================== condenser fans: head pressure control ===================== *)
  FanCtl1(X := P[1], OnAbove := 20.0, OffBelow := 16.0);
  FanCtl2(X := P[2], OnAbove := 20.0, OffBelow := 16.0);
  FanCtl3(X := P[3], OnAbove := 20.0, OffBelow := 16.0);
  FanCtl4(X := P[4], OnAbove := 20.0, OffBelow := 16.0);
  FAN1 := FanCtl1.Q; FAN2 := FanCtl2.Q; FAN3 := FanCtl3.Q; FAN4 := FanCtl4.Q;

  (* ===================== alarms and BMS status ===================== *)
  Alarms := 0;
  IF AlFlow.Active   THEN Alarms := Alarms + 1; END_IF;
  IF AlFreeze.Active THEN Alarms := Alarms + 2; END_IF;
  IF AlSensor.Active THEN Alarms := Alarms + 4; END_IF;
  IF Tripped[1] THEN Alarms := Alarms + 8;   END_IF;
  IF Tripped[2] THEN Alarms := Alarms + 16;  END_IF;
  IF Tripped[3] THEN Alarms := Alarms + 32;  END_IF;
  IF Tripped[4] THEN Alarms := Alarms + 64;  END_IF;
  IF Locked[1]  THEN Alarms := Alarms + 128; END_IF;
  IF Locked[2]  THEN Alarms := Alarms + 256; END_IF;
  IF Locked[3]  THEN Alarms := Alarms + 512; END_IF;
  IF Locked[4]  THEN Alarms := Alarms + 1024; END_IF;
  ALARM_RELAY := Alarms <> 0;

  IF NOT Enabled THEN
    ST_STATE := 0;
  ELSIF AlFlow.Active OR AlFreeze.Active OR AlSensor.Active THEN
    ST_STATE := 3;
  ELSIF NOT FLOW_SW THEN
    ST_STATE := 1;
  ELSE
    ST_STATE := 2;
  END_IF;

  ST_TLW := T_LW_RAW;
  ST_SP := REAL_TO_INT(Sp * 10.0);
  ST_DEMAND := REAL_TO_INT(Pi.Out);
  ST_STAGES := Nrun;
  ST_ALARMS := Alarms;
  ST_STARTS1 := Cmp1.Starts; ST_STARTS2 := Cmp2.Starts; ST_STARTS3 := Cmp3.Starts; ST_STARTS4 := Cmp4.Starts;
  ST_RUN1 := REAL_TO_INT(Cmp1.RunS); ST_RUN2 := REAL_TO_INT(Cmp2.RunS);
  ST_RUN3 := REAL_TO_INT(Cmp3.RunS); ST_RUN4 := REAL_TO_INT(Cmp4.RunS);
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK MainTask(INTERVAL := T#100ms, PRIORITY := 0);
    PROGRAM Inst0 WITH MainTask : Chiller;
  END_RESOURCE
END_CONFIGURATION

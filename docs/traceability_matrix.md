# Requirements Traceability Matrix: chiller controller

Each requirement from the [Functional Specification](functional_specification.md) traced to the code that implements it and the test that verifies it. Test results come from the last software-in-the-loop run ([results/sil_report.md](../results/sil_report.md)). Line numbers refer to `plc/chiller.st`.

| Req | Implemented in | Verified by | Result |
|---|---|---|---|
| FR-01 | `PUMP := Enabled` (l. 297) | SIL scenario t = 0 s: pump starts on BMS enable, flow proven, compressors stage up | Pass (observed in log) |
| FR-02 | Setpoint validation (l. 284 to 287) | SIL check "BMS setpoint change applied" | **Pass** |
| FR-03 | `BMS_RESET := 0` after use (l. 292 to 294) | SIL: three resets in the scenario each clear the latched alarms once | Pass (observed in log) |
| FR-04 | Status words (end of program) | SIL reads %MW10 to %MW23 throughout; duty table in report comes from the PLC | Pass |
| FR-10 | FB_PI (l. 78) + staging (l. 340 to 355) | SIL check "Leaving water held at setpoint (110 to 150 s)" | **Pass**: mean 0.57 K, max 1.58 K |
| FR-11 | as FR-10 | SIL check "Leaving water settles at the new setpoint (555 to 580 s)" | **Pass**: mean 0.31 K, max 0.62 K |
| FR-12 | `StageT >= STAGE_S` (l. 340) | Visible in the stage chart (`results/sil_run.png`) | Not automatically checked: **gap** |
| FR-13 | Low-temperature unloading (l. 333 to 339) | SIL check "No freeze": lowest leaving water 5.72 °C | Pass (unloading not triggered in this run: **gap**) |
| FR-14 | Run-hour selection (l. 345, 352) | Duty table: run times 339 to 495 s across 4 compressors | Pass (no automatic limit: **gap**) |
| FR-20 | FB_Compressor `CanStop` (l. 61) | SIL check "Minimum ON time on every normal stop" | **Pass**: 0 violations |
| FR-21 | FB_Compressor `CanStart` | SIL check "Minimum OFF time before every restart" | **Pass**: 0 violations |
| FR-22 | FB_Compressor `SinceStartS` | SIL check "Start-to-start time" | **Pass**: 0 violations |
| FR-23 | FB_Compressor `IF Run AND NOT Enable` (l. 63) | SIL: 8 safety stops overrode minimum ON | **Pass** |
| SR-01 | `Permit` includes `FLOW_SW` (l. 309) | SIL check "Flow loss stops every compressor": 0.2 s | **Pass** |
| SR-02 | `AlFlow` (l. 304) | SIL check "Flow alarm latched, no restart until reset" | **Pass** |
| SR-03 | `AlFreeze` (l. 305) | Not reached in the scenario (lowest 5.72 °C) | **Gap**: needs a dedicated fault injection test |
| SR-04 | `AlSensor` (l. 306) | SIL check "Sensor failure stops the unit": 0.1 s | **Pass** |
| SR-05 | FB_HpCircuit (l. 157) | SIL check "Fan 3 failure: circuit 3 trips, others keep running" | **Pass** |
| SR-06 | FB_HpCircuit lockout (l. 174 to 184) | SIL checks "Lockout after 3 trips" and "Circuit 3 back in service after reset" | **Pass** |
| SR-07 | Alarm word and relay (l. 376 to 388) | Alarm word read by SIL for every check above | Pass |
| SR-08 | FB_Hyst x4 (l. 369) | Pressure chart; HP trip only when the fan failed | Pass (no automatic check: **gap**) |

## Coverage summary

* 21 requirements, all implemented: 12 verified by an automatic check, 4 by inspection of the log (FR-01, FR-03, FR-04, SR-07), 5 with open gaps.
* **Open gaps:** FR-12, FR-13 (unloading path not exercised), FR-14 (no balance limit), SR-03 (freeze trip never triggered), SR-08. Next step: add fault-injection cases (forced low leaving water, fan cycling) and automatic checks for these, then re-run.

Listing the gaps is deliberate: a matrix that shows only passes hides what has not been tested.

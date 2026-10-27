# Functional Specification: chiller controller

| | |
|---|---|
| Document | FS-CHL-001, revision A |
| System | 4-compressor air-cooled chiller controller, `plc/chiller.st` (IEC 61131-3, OpenPLC) |
| Related | I/O point list and sequence of operation in the [README](../README.md), traceability in [traceability_matrix.md](traceability_matrix.md) |
| Verification | Software-in-the-loop test `sim/run_sil.py`, report [results/sil_report.md](../results/sil_report.md) |

Requirements are written so that each one can be verified by a test. "Shall" marks a requirement. Timers are scaled 1:9 for simulation (see README).

## 1. Operation and interfaces

| ID | Requirement |
|---|---|
| FR-01 | The unit shall start the chilled water pump when the BMS enable word (%MW0) is non-zero, and stop it when it is zero. |
| FR-02 | The controller shall use the BMS setpoint (%MW1, x10 °C) when it is within 4.0 to 15.0 °C, and 7.0 °C otherwise. |
| FR-03 | A BMS alarm reset command (%MW2) shall act once and be cleared by the PLC after use. |
| FR-04 | The PLC shall publish leaving water temperature, active setpoint, demand, stages running, alarm word, unit state, starts and run time per compressor to the BMS (%MW10 to %MW23). |

## 2. Capacity control

| ID | Requirement |
|---|---|
| FR-10 | Leaving water shall be held at setpoint with a mean absolute error below 0.75 K and no deviation beyond one compressor stage (1.25 K) plus 0.5 K under steady load with sufficient capacity. |
| FR-11 | After a setpoint change, the leaving water shall settle to the new setpoint within the same band once capacity allows. |
| FR-12 | At most one compressor shall be staged up or down per 15 s staging interval (except low-temperature unloading, FR-13). |
| FR-13 | Below 4.0 °C leaving water, one running compressor shall be shed every 3 s (after its minimum ON time). |
| FR-14 | The compressor with the fewest run hours shall start first; the one with the most run hours shall stop first. |

## 3. Compressor protection

| ID | Requirement |
|---|---|
| FR-20 | A compressor shall not stop in normal operation before its minimum ON time (20 s scaled). |
| FR-21 | A compressor shall not restart before its minimum OFF time (40 s scaled). |
| FR-22 | Two starts of the same compressor shall be at least 60 s (scaled) apart. |
| FR-23 | A safety trip shall stop a compressor immediately, overriding FR-20. |

## 4. Safety functions and alarms

| ID | Requirement |
|---|---|
| SR-01 | Compressors shall only run with flow proven by the flow switch. |
| SR-02 | Loss of flow for 2 s while the pump runs shall raise a latching flow alarm that stops all compressors until a reset. |
| SR-03 | Leaving water below 3.0 °C shall raise a latching freeze alarm that stops all compressors. |
| SR-04 | A leaving water reading outside -20 to 60 °C for 1 s shall raise a latching sensor alarm that stops all compressors. |
| SR-05 | Condensing pressure at or above 41.5 bar shall trip that circuit only; the other circuits shall keep running. |
| SR-06 | A tripped circuit shall reset automatically below 30 bar, and lock out after 3 trips until an operator reset. |
| SR-07 | Any active alarm shall energize the common alarm relay and be shown as a bit in the BMS alarm word. |
| SR-08 | Each circuit's condenser fan shall run above 20 bar and stop below 16 bar. |

## 5. Out of scope

Hardwired safety devices (high-pressure switch, freeze stat, motor protection) are assumed to exist on a real unit as the first protection layer; this software is the second layer.

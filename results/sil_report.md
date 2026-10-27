# Software-in-the-loop test: chiller controller (OpenPLC runtime + plant model)

| Requirement | Result | Detail |
|---|---|---|
| Minimum ON time (20 s) on every normal stop | PASS | 15 stops, 8 were safety trips (allowed to override), 0 violations |
| Minimum OFF time (40 s) before every restart | PASS | 18 starts, 0 violations |
| Start-to-start time (60 s) | PASS | 0 violations |
| Leaving water held at setpoint (110 to 150 s): mean < 0.75 K, max < one stage step + 0.5 K | PASS | mean error 0.57 K, max 1.58 K (one stage step = 1.25 K) |
| BMS setpoint change applied | PASS | PLC reports 8.0 degC after the write |
| Leaving water settles at the new setpoint (555 to 580 s) | PASS | mean error 0.31 K, max 0.62 K |
| No freeze (leaving water stays above 3.0 degC) | PASS | lowest leaving water 5.72 degC |
| 48 degC ambient: no HP trip with all fans working | PASS | highest condensing pressure 36.7 bar (trip 41.5) |
| Fan 3 failure: circuit 3 trips on high pressure, others keep running | PASS | 3 trips of circuit 3, circuits 1/2/4 running 93 % of the time |
| Lockout after 3 high-pressure trips | PASS | circuit 3 locked out at 387 s |
| Circuit 3 back in service after repair and reset | PASS | compressor 3 restarted after the reset |
| Flow loss stops every compressor | PASS | all compressors off 0.2 s after the pump trip (compressors drop out on the flow permissive at once; the latched flow alarm follows after its 2 s delay) |
| Flow alarm latched, no restart until reset | PASS | alarm held after flow came back; compressors restarted only after the reset |
| Sensor failure stops the unit | PASS | all compressors off 0.1 s after the sensor failed, sensor alarm raised |

## Compressor duty (from the PLC over Modbus)

| Compressor | Starts | Run time (s) |
|---|---|---|
| 1 | 4 | 446 |
| 2 | 4 | 495 |
| 3 | 7 | 339 |
| 4 | 3 | 484 |

## Event log

-    0.0 s: BMS: unit ON, setpoint 7.0 degC
-  150.0 s: load ramps 45 -> 75 kW
-  200.0 s: ambient ramps 35 -> 48 degC
-  270.0 s: FAULT: condenser fan 3 fails
-  420.0 s: fan 3 repaired
-  430.0 s: BMS: alarm reset
-  520.0 s: evening: load -> 25 kW, ambient -> 40 degC
-  540.0 s: BMS: setpoint 8.0 degC
-  580.0 s: FAULT: pump trips (flow lost)
-  600.0 s: pump repaired
-  605.0 s: BMS: alarm reset
-  650.0 s: FAULT: leaving water sensor open circuit
-  660.0 s: sensor replaced
-  665.0 s: BMS: alarm reset

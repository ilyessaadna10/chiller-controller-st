#!/usr/bin/env python3
"""Software-in-the-loop test of plc/chiller.st running in OpenPLC.

  1. starts the chiller plant model and its Modbus TCP remote I/O (port 5021),
  2. acts as the BMS on the PLC's Modbus server (enable, setpoint, alarm reset),
  3. plays a 12 minute scenario: pull-down, load ramp, 48 degC ambient, condenser fan
     failure on circuit 3, setpoint change, low load, flow loss, sensor failure,
  4. logs every signal at 10 Hz and checks the controller against its requirements,
  5. writes results/sil_report.md, results/sil_log.csv and results/sil_run.png.

    python sim/run_sil.py --plc-port 5502
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from pymodbus.client import ModbusTcpClient

sys.path.insert(0, str(Path(__file__).parent))
from plant import CO, HP_TRIP, Plant

ROOT = Path(__file__).resolve().parents[1]
MIN_ON, MIN_OFF, S2S = 20.0, 40.0, 60.0          # must match the PLC constants
TOL = 0.5                                          # s, Modbus polling + logging resolution
HR = 1024                                          # OpenPLC: %MW0 = holding register 1024


def s16(v):
    return v - 65536 if v >= 32768 else v


class BMS:
    def __init__(self, host, port):
        self.c = ModbusTcpClient(host, port=port)

    def connect(self):
        return self.c.connect()

    def write(self, word, value):
        self.c.write_register(HR + word, value)

    def status(self):
        r = self.c.read_holding_registers(HR + 10, count=14)
        if r.isError():
            return None
        v = r.registers
        return dict(tlw=s16(v[0]) / 10, sp=v[1] / 10, demand=v[2], stages=v[3], alarms=v[4], state=v[5],
                    starts=v[6:10], run_s=v[10:14])


def ramp(t, t0, t1, a, b):
    if t <= t0:
        return a
    if t >= t1:
        return b
    return a + (b - a) * (t - t0) / (t1 - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plc", default="127.0.0.1")
    ap.add_argument("--plc-port", type=int, default=5502)
    ap.add_argument("--duration", type=float, default=720)
    ap.add_argument("--analyse-only", action="store_true", help="re-check the last saved run")
    args = ap.parse_args()
    if args.analyse_only:
        return analyse(ROOT / "results")

    plant = Plant()
    plant.serve(5021)
    plant.run()
    bms = BMS(args.plc, args.plc_port)
    t_wait = time.time()
    while True:                                    # PLC up and reading our inputs
        st = bms.status() if bms.connect() else None
        if st and abs(st["tlw"] - plant.t_lw) < 0.2:
            break
        if time.time() - t_wait > 60:
            raise SystemExit("PLC not reachable or not polling the plant on port 5021")
        time.sleep(0.5)
    print(f"PLC online after {time.time() - t_wait:.1f} s")
    bms.write(2, 1); time.sleep(0.5)               # clear anything latched at power up

    events, log = [], []
    def ev(t, msg):
        events.append((t, msg)); print(f"{t:6.1f} s  {msg}")

    script = [
        (0, "BMS: unit ON, setpoint 7.0 degC"), (150, "load ramps 45 -> 75 kW"),
        (200, "ambient ramps 35 -> 48 degC"), (270, "FAULT: condenser fan 3 fails"),
        (420, "fan 3 repaired"), (430, "BMS: alarm reset"),
        (520, "evening: load -> 25 kW, ambient -> 40 degC"), (540, "BMS: setpoint 8.0 degC"), (580, "FAULT: pump trips (flow lost)"),
        (600, "pump repaired"), (605, "BMS: alarm reset"), (650, "FAULT: leaving water sensor open circuit"),
        (660, "sensor replaced"), (665, "BMS: alarm reset"),
    ]
    k = 0
    t0 = time.time()
    next_log = 0.0
    sp_written_t = None
    while True:
        t = time.time() - t0
        if t > args.duration:
            break
        while k < len(script) and t >= script[k][0]:
            at, msg = script[k]; k += 1
            ev(t, msg)
            if at == 0:
                bms.write(1, 70); bms.write(0, 1)
            elif at == 270:
                plant.fan_failed[2] = True
            elif at == 420:
                plant.fan_failed[2] = False
            elif at in (430, 605, 665):
                bms.write(2, 1)
            elif at == 540:
                bms.write(1, 80); sp_written_t = t
            elif at == 580:
                plant.pump_fault = True
            elif at == 600:
                plant.pump_fault = False
            elif at == 650:
                plant.sensor_fault = True
            elif at == 660:
                plant.sensor_fault = False
        with plant.lock:
            plant.load = ramp(t, 150, 180, 45, 75) if t < 520 else ramp(t, 520, 540, 75, 25)
            plant.t_amb = ramp(t, 200, 240, 35, 48) if t < 520 else ramp(t, 520, 540, 48, 40)
        if t >= next_log:
            st = bms.status() or {}
            with plant.lock:
                row = dict(t=t, t_lw=plant.t_lw, t_rw=plant.t_rw, t_amb=plant.t_amb, load=plant.load,
                           q_cool=plant.q_cool, flow=int(plant.flow),
                           **{f"p{i + 1}": plant.p[i] for i in range(4)},
                           **{f"c{i}": int(plant.co[CO[f'C{i}']]) for i in range(1, 5)},
                           **{f"f{i}": int(plant.co[CO[f'F{i}']]) for i in range(1, 5)},
                           pump=int(plant.co[CO["PUMP"]]), alarm_relay=int(plant.co[CO["ALARM"]]),
                           sp=st.get("sp", np.nan), demand=st.get("demand", np.nan),
                           alarms=st.get("alarms", 0), state=st.get("state", -1))
            log.append(row)
            next_log += 0.1
        time.sleep(0.01)
    final = bms.status()
    out = ROOT / "results"; out.mkdir(exist_ok=True)
    with open(out / "sil_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(log[0].keys())); w.writeheader(); w.writerows(log)
    json.dump(dict(events=events, final=final, sp_written_t=sp_written_t), open(out / "sil_meta.json", "w"))
    analyse(out)


def analyse(out):
    """Check the logged run against the controller requirements (re-runnable from the saved files)."""
    with open(out / "sil_log.csv") as f:
        log = [{k: float(v) if v not in ("", "nan") else np.nan for k, v in r.items()} for r in csv.DictReader(f)]
    meta = json.load(open(out / "sil_meta.json"))
    events, final, sp_written_t = meta["events"], meta["final"], meta["sp_written_t"]
    T = np.array([r["t"] for r in log]); col = lambda n: np.array([r[n] for r in log], dtype=float)
    alarms = col("alarms").astype(int)
    unit_trip = (alarms & 0b111) != 0
    checks = []
    def check(name, ok, detail):
        checks.append((name, bool(ok), detail))

    def near(mask, t, before=1.0, after=2.0):
        sel = (T >= t - before) & (T <= t + after)
        return bool(mask[sel].any())

    # compressor timers
    v_on = v_off = v_s2s = 0; n_starts = 0; n_stops = 0; safety_stops = 0
    for i in range(1, 5):
        c = col(f"c{i}").astype(int)
        hp_bit = (alarms >> (2 + i)) & 1
        edges = np.flatnonzero(np.diff(c)) + 1
        last_start = last_stop = None
        for e in edges:
            te = T[e]
            if c[e]:                                   # start
                n_starts += 1
                if last_stop is not None and te - last_stop < MIN_OFF - TOL: v_off += 1
                if last_start is not None and te - last_start < S2S - TOL: v_s2s += 1
                last_start = te
            else:                                      # stop
                n_stops += 1
                if near(unit_trip, te) or near(hp_bit.astype(bool), te):
                    safety_stops += 1
                elif te - last_start < MIN_ON - TOL:
                    v_on += 1
                last_stop = te
    check("Minimum ON time (20 s) on every normal stop", v_on == 0,
          f"{n_stops} stops, {safety_stops} were safety trips (allowed to override), {v_on} violations")
    check("Minimum OFF time (40 s) before every restart", v_off == 0, f"{n_starts} starts, {v_off} violations")
    check("Start-to-start time (60 s)", v_s2s == 0, f"{v_s2s} violations")

    # temperature control
    t_lw = col("t_lw"); sp = col("sp")
    win = (T >= 110) & (T < 150)
    err1 = np.abs(t_lw[win] - 7.0)
    step_k = 25.0 / 20.0                          # one compressor = 25 kW over 20 kW/K water flow
    check(f"Leaving water held at setpoint (110 to 150 s): mean < 0.75 K, max < one stage step + 0.5 K", err1.mean() < 0.75 and err1.max() < step_k + 0.5,
          f"mean error {err1.mean():.2f} K, max {err1.max():.2f} K (one stage step = {step_k:.2f} K)")
    sp_ok = (T > sp_written_t + 1.0) & (T < sp_written_t + 3.0) if sp_written_t else np.zeros_like(T, bool)
    check("BMS setpoint change applied", sp_ok.any() and np.nanmin(sp[sp_ok]) == 8.0, "PLC reports 8.0 degC after the write")
    win2 = (T >= 555) & (T < 580)
    err2 = np.abs(t_lw[win2] - 8.0)
    check("Leaving water settles at the new setpoint (555 to 580 s)", err2.mean() < 0.75 and err2.max() < step_k + 0.5,
          f"mean error {err2.mean():.2f} K, max {err2.max():.2f} K")
    real_min = t_lw[~((T > 648) & (T < 670))].min()
    check("No freeze (leaving water stays above 3.0 degC)", real_min > 3.0, f"lowest leaving water {real_min:.2f} degC")

    # high ambient + fan failure
    p = np.stack([col(f"p{i}") for i in range(1, 5)])
    c = np.stack([col(f"c{i}") for i in range(1, 5)])
    hi_amb = (T >= 240) & (T < 270)
    check("48 degC ambient: no HP trip with all fans working", (alarms[(T >= 200) & (T < 270)] & 0b1111000).sum() == 0,
          f"highest condensing pressure {p[:, hi_amb].max():.1f} bar (trip {HP_TRIP})")
    hp3 = (alarms >> 5) & 1
    lock3 = (alarms >> 9) & 1
    trips3 = int(((np.diff(hp3) == 1)).sum())
    t_lock = T[np.argmax(lock3)] if lock3.any() else None
    others_ran = c[[0, 1, 3]][:, (T > 280) & (T < 420)].mean()
    check("Fan 3 failure: circuit 3 trips on high pressure, others keep running", trips3 >= 1 and others_ran > 0.9,
          f"{trips3} trips of circuit 3, circuits 1/2/4 running {others_ran * 100:.0f} % of the time")
    check("Lockout after 3 high-pressure trips", t_lock is not None and trips3 == 3,
          f"circuit 3 locked out at {t_lock:.0f} s" if t_lock else "no lockout")
    restarted3 = c[2, (T > 432) & (T < 520)].any()
    check("Circuit 3 back in service after repair and reset", restarted3, "compressor 3 restarted after the reset")

    # flow loss
    def all_off_after(t_fault, limit):
        sel = T >= t_fault
        off = c[:, sel].sum(axis=0) == 0
        return (T[sel][np.argmax(off)] - t_fault) if off.any() else None
    dt_flow = all_off_after(580, 20)
    latched = (alarms[(T > 601) & (T < 605)] & 1).all()
    no_restart = c[:, (T > 601) & (T < 605)].sum() == 0
    restart_after = c[:, (T > 606) & (T < 650)].any()
    check("Flow loss stops every compressor", dt_flow is not None and dt_flow < 10,
          f"all compressors off {dt_flow:.1f} s after the pump trip (compressors drop out on the flow permissive at once; the latched flow alarm follows after its 2 s delay)" if dt_flow is not None else "not stopped")
    check("Flow alarm latched, no restart until reset", latched and no_restart and restart_after,
          "alarm held after flow came back; compressors restarted only after the reset")
    dt_sens = all_off_after(650, 10)
    check("Sensor failure stops the unit", dt_sens is not None and dt_sens < 3 and (alarms[(T > 652) & (T < 660)] & 4).all(),
          f"all compressors off {dt_sens:.1f} s after the sensor failed, sensor alarm raised" if dt_sens is not None else "not stopped")

    # rotation
    run_s = final["run_s"] if final else [0] * 4
    starts = final["starts"] if final else [0] * 4

    with open(out / "sil_report.md", "w") as f:
        f.write("# Software-in-the-loop test: chiller controller (OpenPLC runtime + plant model)\n\n")
        f.write("| Requirement | Result | Detail |\n|---|---|---|\n")
        for name, ok, detail in checks:
            f.write(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |\n")
        f.write("\n## Compressor duty (from the PLC over Modbus)\n\n| Compressor | Starts | Run time (s) |\n|---|---|---|\n")
        for i in range(4):
            f.write(f"| {i + 1} | {starts[i]} | {run_s[i]} |\n")
        f.write("\n## Event log\n\n")
        for tt, msg in events:
            f.write(f"- {tt:6.1f} s: {msg}\n")
    print(open(out / "sil_report.md").read())
    plot(T, log, events, out / "sil_run.png")


def plot(T, log, events, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = lambda n: np.array([r[n] for r in log], dtype=float)
    fig, ax = plt.subplots(4, 1, figsize=(13, 11), sharex=True, gridspec_kw=dict(height_ratios=[3, 2, 1.6, 2.4]))
    ax[0].plot(T, col("t_lw"), label="leaving water", lw=1.6)
    ax[0].plot(T, col("t_rw"), label="return water", lw=1, alpha=.7)
    ax[0].plot(T, col("sp"), "k--", label="setpoint (from PLC)", lw=1)
    ax[0].axhline(3.0, color="tab:blue", ls=":", lw=1); ax[0].text(2, 3.1, "freeze limit", color="tab:blue", fontsize=8)
    ax[0].set_ylabel("degC"); ax[0].set_ylim(0, 16); ax[0].legend(loc="upper right", fontsize=8)
    ax[1].plot(T, col("load"), label="cooling load (kW)")
    ax[1].plot(T, col("q_cool"), label="cooling delivered (kW)")
    ax[1].plot(T, col("demand"), label="PI demand (%)", alpha=.8)
    ax[1].legend(loc="upper right", fontsize=8); ax[1].set_ylim(0, 110)
    for i in range(1, 5):
        c = col(f"c{i}")
        ax[2].fill_between(T, i - 0.4, i - 0.4 + 0.8 * c, step="post", color=f"C{i - 1}")
    ax[2].set_yticks([1, 2, 3, 4], ["C1", "C2", "C3", "C4"]); ax[2].set_ylabel("compressors")
    for i in range(1, 5):
        ax[3].plot(T, col(f"p{i}"), lw=1, label=f"circuit {i}")
    ax[3].axhline(HP_TRIP, color="r", ls="--", lw=1); ax[3].text(2, HP_TRIP + 0.4, "HP trip", color="r", fontsize=8)
    a2 = ax[3].twinx(); a2.plot(T, col("t_amb"), "k:", lw=1.2); a2.set_ylabel("ambient degC (dotted)")
    ax[3].set_ylabel("condensing bar"); ax[3].legend(loc="upper left", fontsize=8, ncol=4); ax[3].set_xlabel("time (s)")
    for tt, msg in events:
        if "FAULT" in msg or "BMS" in msg:
            for a in ax:
                a.axvline(tt, color="r" if "FAULT" in msg else "gray", alpha=.35, lw=1)
            ax[0].text(tt + 2, 15.2, msg.replace("FAULT: ", "").replace("BMS: ", ""), fontsize=7, rotation=90, va="top")
    fig.suptitle("Chiller controller in OpenPLC: 12 minute software-in-the-loop run", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()

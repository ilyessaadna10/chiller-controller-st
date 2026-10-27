"""Air-cooled chiller plant + Modbus TCP remote I/O, for software-in-the-loop tests.

The PLC (OpenPLC running plc/chiller.st) polls this module:
  input registers 0..6 -> %IW100..106  leaving water, return water, ambient (x10 degC),
                                        condensing pressure circuits 1..4 (x10 bar)
  discrete input 0     -> %IX100.0     flow switch
  coils 0..9           <- %QX100.0..%QX101.1  pump, compressors 1..4, fans 1..4, alarm relay

Model (deliberately simple, but with the effects the controller has to handle):
  - chilled water loop as one thermal mass; leaving water = return - Q_cool / (m cp)
  - compressor capacity drops as ambient rises (about 1.2 % per K above 35 degC)
  - each circuit has its own condenser fan; condensing temperature = ambient + approach,
    approach 10 K with the fan running, 28 K without; pressure from an R410A saturation fit
  - fault injection: condenser fan failure, pump/flow loss, leaving water sensor failure
"""
import threading
import time

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext  # pymodbus 3.8
from pymodbus.server import StartTcpServer

CO = dict(PUMP=0, C1=1, C2=2, C3=3, C4=4, F1=5, F2=6, F3=7, F4=8, ALARM=9)
C_LOOP = 600.0       # kJ/K, chilled water loop thermal mass
MCP = 20.0           # kW/K, water flow x cp
CAP_NOM = 25.0       # kW per compressor at 35 degC ambient
TAU_P = 4.0          # s, condensing pressure time constant
HP_TRIP = 41.5       # bar, PLC trip setting (for reporting)


def psat_r410a(t_c):
    """Saturation pressure (bar abs) of R410A, quadratic fit through 40/50/60 degC."""
    return 0.006 * t_c ** 2 + 0.11 * t_c + 10.1


class Plant:
    def __init__(self, t_loop=12.0, t_amb=35.0, load=45.0):
        self.lock = threading.Lock()
        self.t_loop, self.t_amb, self.load = t_loop, t_amb, load
        self.co = [False] * 10
        self.p = [psat_r410a(t_amb)] * 4
        self.t_lw = self.t_rw = t_loop
        self.fan_failed = [False] * 4
        self.pump_fault = False
        self.sensor_fault = False
        self.flow = False
        self._flow_t = 0.0
        self.q_cool = 0.0

    def capacity(self):
        return CAP_NOM * max(0.0, 1.0 - 0.012 * (self.t_amb - 35.0))

    def step(self, dt):
        with self.lock:
            co = self.co
            pump_running = co[CO["PUMP"]] and not self.pump_fault
            self._flow_t = self._flow_t + dt if pump_running else 0.0
            self.flow = self._flow_t > 1.5                       # flow switch makes after 1.5 s
            comps = [co[CO[f"C{i}"]] for i in range(1, 5)]
            self.q_cool = self.capacity() * sum(comps) if self.flow else 0.0
            self.t_loop += (self.load - self.q_cool) / C_LOOP * dt
            self.t_rw = self.t_loop
            self.t_lw = self.t_loop - self.q_cool / MCP
            for i in range(4):
                fan_ok = co[CO[f"F{i + 1}"]] and not self.fan_failed[i]
                t_cond = self.t_amb + ((10.0 if fan_ok else 28.0) if comps[i] else 0.0)
                self.p[i] += (psat_r410a(t_cond) - self.p[i]) * dt / TAU_P

    def registers(self):
        t_lw = -50.0 if self.sensor_fault else self.t_lw          # open-circuit sensor reads far out of range
        vals = [t_lw, self.t_rw, self.t_amb] + self.p
        return [int(round(v * 10)) & 0xFFFF for v in vals]

    def serve(self, port=5021):
        dev = ModbusSlaveContext(di=ModbusSequentialDataBlock(0, [0] * 2),
                                 co=ModbusSequentialDataBlock(0, [0] * 11),
                                 ir=ModbusSequentialDataBlock(0, [0] * 8))

        def sync():
            while True:
                with self.lock:
                    dev.setValues(2, 0, [int(self.flow)])
                    dev.setValues(4, 0, self.registers())
                    self.co = [bool(v) for v in dev.getValues(1, 0, 10)]
                time.sleep(0.005)
        threading.Thread(target=sync, daemon=True).start()
        ctx = ModbusServerContext(slaves=dev, single=True)
        threading.Thread(target=lambda: StartTcpServer(context=ctx, address=("0.0.0.0", port)), daemon=True).start()

    def run(self, hz=20):
        def loop():
            last = time.time()
            while True:
                now = time.time(); self.step(now - last); last = now
                time.sleep(1 / hz)
        threading.Thread(target=loop, daemon=True).start()

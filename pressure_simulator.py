# -*- coding: utf-8 -*-
"""
pressure_simulator.py
=====================
Simulates ESP32 serial output to test pressure calibration.

How it works:
  1. Opens a virtual COM port pair using com0com or serial pipe
  2. Sends fake  P:X.XXX,R:1500,I:1,A:0,C:0  packets at 100 Hz
  3. Sweeps pressure from 0 to 1600 BAR and back

Run this FIRST, then connect the app to the virtual port.

If you don't have com0com:
  pip install pyserial
  Use "LOOP://" port — see USAGE below.

USAGE (no extra software needed):
  python pressure_simulator.py --mode loop
    -> Prints what the app WOULD display for each pressure point.
       No COM port needed. Pure Python test.

  python pressure_simulator.py --mode com --port COM5
    -> Sends real serial data on COM5 (needs com0com virtual pair).
"""

import sys
import time
import math
import argparse

# ── Lookup table from diesel_dashboard_FINAL.py ─────────────────────
P_CAL_TABLE = [
    (0.096,    0.0),
    (0.150,    0.0),
    (0.208,    0.0),
    (0.300,    0.0),
    (0.445,  228.6),
    (0.600,  457.1),
    (0.774,  685.7),
    (0.889,  914.3),
    (1.043, 1142.9),
    (1.185, 1371.4),
    (1.340, 1600.0),
]
P_CAL_OFFSET = 0.0

def bar_to_vx4(bar):
    """Convert BAR to VX4 voltage by reverse-interpolating the table."""
    tbl = [(b, v) for v, b in P_CAL_TABLE]   # swap to (bar, vx4)
    tbl.sort()
    if bar <= tbl[0][0]:
        return tbl[0][1]
    if bar >= tbl[-1][0]:
        return tbl[-1][1]
    for i in range(len(tbl) - 1):
        b0, v0 = tbl[i]
        b1, v1 = tbl[i + 1]
        if b0 <= bar <= b1:
            t = (bar - b0) / (b1 - b0) if b1 != b0 else 0
            return v0 + t * (v1 - v0)
    return tbl[0][1]

def vx4_to_bar(vx4):
    """Forward interpolation: VX4 -> BAR."""
    tbl = P_CAL_TABLE
    if vx4 <= tbl[0][0]:
        return 0.0
    if vx4 >= tbl[-1][0]:
        return tbl[-1][1]
    for i in range(len(tbl) - 1):
        x0, y0 = tbl[i]
        x1, y1 = tbl[i + 1]
        if x0 <= vx4 <= x1:
            t = (vx4 - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 0.0

def make_packet(bar, rpm=1500, inj=1, angle=0, cam=0):
    """Build a serial packet like: P:0.3000,R:1500,I:1,A:0,C:0"""
    vx4 = bar_to_vx4(max(0, min(1600, bar)))
    return f"P:{vx4:.4f},R:{rpm},I:{inj},A:{angle},C:{cam}\n"

# ── LOOP mode: pure Python test ──────────────────────────────────────
def run_loop_test():
    print("=" * 60)
    print("  PRESSURE CALIBRATION TEST — Loop Mode")
    print("  (simulates what the app would display)")
    print("=" * 60)
    print(f"\n{'Pressure (BAR)':>16}  {'VX4 sent (V)':>14}  {'App reads (BAR)':>16}  {'Error':>8}")
    print("-" * 62)

    test_points = [0, 100, 200, 400, 600, 800, 1000, 1200, 1400, 1600]
    max_err = 0
    for bar in test_points:
        vx4  = bar_to_vx4(bar)
        got  = vx4_to_bar(vx4) + P_CAL_OFFSET
        err  = got - bar
        flag = " !" if abs(err) > 10 else ""
        print(f"{bar:>16.1f}  {vx4:>14.4f}  {got:>16.1f}  {err:>+7.1f}{flag}")
        max_err = max(max_err, abs(err))

    print("-" * 62)
    print(f"\n  Max error: {max_err:.1f} BAR")
    print(f"  {'PASS OK' if max_err < 20 else 'FAIL - check table'}")
    print()

    print("  Sweep simulation (0 -> 1600 -> 0 BAR):")
    print()
    alpha = 0.15          # same EMA as app
    ema   = 0.0
    prev_bar = -1

    for step in range(200):
        t = step / 199
        # triangle wave: 0->1600->0
        target = 1600 * (1 - abs(2 * t - 1))

        vx4_sent = bar_to_vx4(target)
        ema = alpha * vx4_sent + (1 - alpha) * ema
        display_bar = int(vx4_to_bar(ema) + P_CAL_OFFSET)

        if abs(display_bar - prev_bar) >= 50 or step == 0 or step == 199:
            bar_block = "#" * (display_bar // 50)
            print(f"  {display_bar:5d} BAR  {bar_block}")
            prev_bar = display_bar

        time.sleep(0.01)   # 100 Hz like real hardware

    print("\n  Simulation complete.")

# ── COM mode: real serial output ─────────────────────────────────────
def run_com_mode(port):
    try:
        import serial
    except ImportError:
        print("ERROR: pip install pyserial")
        sys.exit(1)

    print(f"  Opening {port} at 115200 baud...")
    try:
        s = serial.Serial(port, 115200, timeout=1)
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print("  Sending packets — connect app to the OTHER side of the pair")
    print("  Press Ctrl+C to stop.\n")

    step = 0
    try:
        while True:
            t   = (step % 400) / 399
            bar = 1600 * (1 - abs(2 * t - 1))
            pkt = make_packet(bar, rpm=1500, inj=1)
            s.write(pkt.encode())
            step += 1
            time.sleep(0.01)
    except KeyboardInterrupt:
        s.close()
        print("\n  Stopped.")

# ── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pressure simulator")
    parser.add_argument("--mode", choices=["loop", "com"], default="loop",
                        help="loop = pure Python test, com = real serial port")
    parser.add_argument("--port", default="COM5",
                        help="COM port for com mode (e.g. COM5)")
    args = parser.parse_args()

    if args.mode == "loop":
        run_loop_test()
    else:
        run_com_mode(args.port)

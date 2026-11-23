#!/usr/bin/env python3
"""fastsample_rx — host receiver for the on-board 100 Hz CPU-port sampler (scripts/tools/fastsample.c, #186).

- Listens on UDP PORT, appends every datagram with the host receive time to tmp/logs/fastsample.log (flushed per line, so a crash keeps everything received).
- Prints a line whenever a 10 ms sample shows rx > RX_ALERT packets, an rx_dropped / rx_errors / rx_fifo_errors increase, or a gap > GAP_MS between datagrams
  (sw1 stopped sending = crash or hang). Last 30 samples are printed at exit.
- Stops after SECS seconds (default 300) or on Ctrl-C. Usage: python3 scripts/fastsample_rx.py [--port 6677] [--secs 300]
"""
import argparse
import collections
import socket
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/fastsample.log"
RX_ALERT = 200       # packets in one 10 ms sample = 20 kpps; chip-forwarded traffic puts ~0-5 on the CPU port
GAP_MS = 60          # 6 missed samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=6677)
    ap.add_argument("--secs", type=int, default=300)
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 22)
    s.bind(("0.0.0.0", a.port))
    s.settimeout(0.5)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tail = collections.deque(maxlen=30)
    prev, prev_t, n = None, None, 0
    end = time.time() + a.secs
    with LOG.open("a") as fh:
        fh.write(f"# {time.strftime('%Y-%m-%dT%H:%M:%S%z')} start\n")
        while time.time() < end:
            try:
                data, _ = s.recvfrom(512)
            except socket.timeout:
                if prev_t and time.time() - prev_t > 1:
                    print(f"{time.strftime('%H:%M:%S')} NO DATA for {time.time() - prev_t:.1f} s", flush=True)
                    prev_t = time.time() + 3600  # report once
                continue
            now = time.time()
            line = data.decode(errors="replace").strip()
            fh.write(f"{now:.3f} {line}\n")
            fh.flush()
            tail.append(f"{now:.3f} {line}")
            f = line.split()
            if len(f) < 11:
                continue
            v = [int(x) for x in f[1:]]  # t_us rx drop err fifo tx irq0 irq1 r0 r1 (after seq)
            n += 1
            if prev is not None:
                d = [b - a_ for a_, b in zip(prev[1:], v[1:])]
                gap_ms = (now - prev_t) * 1000 if prev_t else 0
                if d[0] > RX_ALERT or d[1] or d[2] or d[3] or gap_ms > GAP_MS:  # rx, drop, err, fifo
                    print(f"{time.strftime('%H:%M:%S')} seq {f[0]} d(rx,drop,err,fifo,tx,irq0,irq1,r0,r1)={d} gap {gap_ms:.0f} ms", flush=True)
            prev, prev_t = v, now
    print(f"{n} samples; last 30:")
    print("\n".join(tail))


if __name__ == "__main__":
    main()

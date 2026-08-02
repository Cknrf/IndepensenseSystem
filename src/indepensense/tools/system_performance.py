"""System performance monitor for the wearable.

Samples CPU (per-core + total), memory, load average, and Pi 5 SoC
temperature at a fixed interval. Runs alongside `app.py` in a separate
SSH session to observe how the wearable uses the Pi's resources
during real operation.

Usage:
    # Print samples to terminal (default 2 s interval)
    python -m indepensense.tools.system_performance

    # Custom interval + CSV logging for thesis data
    python -m indepensense.tools.system_performance --interval 1 --csv perf.csv

    # Also track a specific process (e.g., app.py's PID from `pgrep`)
    python -m indepensense.tools.system_performance --pid 1234

Recommended workflow for thesis evaluation:
    # Terminal 1 — start the wearable
    python -m indepensense.app

    # Terminal 2 — start the monitor with CSV output
    python -m indepensense.tools.system_performance --csv wearable_perf.csv

    # Then perform typical operations: voice commands, walking test,
    # emergency press, etc. Stop with Ctrl-C when done. The CSV is
    # ready for plotting in the thesis evaluation section.

Output columns:
    time      — HH:MM:SS wall clock
    total%    — average CPU utilization across all 4 cores
    c0..c3    — per-core CPU utilization
    mem%      — RAM used percentage
    mem_used  — RAM used in GB
    load1     — 1-minute load average
    temp      — Pi 5 SoC temperature (°C). >80 flagged as throttle risk.
    top_proc  — process using most CPU right now

Prerequisites:
    psutil is required. It is normally installed as a transitive
    dependency of ultralytics; if you get ImportError, install with:
        pip install psutil
"""
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime


def _read_soc_temp_c() -> float:
    """Read Pi SoC temperature via vcgencmd. Returns °C, or -1.0 on failure."""
    try:
        r = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=1.0,
        )
        # Output format: "temp=54.3'C\n"
        return float(r.stdout.strip().split("=")[1].rstrip("'C"))
    except Exception:
        return -1.0


def _find_top_cpu_process(psutil_mod, exclude_names=("system_performance", "htop", "top")):
    """Return (name, cpu%) of the non-excluded process using the most CPU."""
    best_name = ""
    best_cpu = 0.0
    for proc in psutil_mod.process_iter(["name", "cpu_percent"]):
        try:
            name = proc.info["name"] or ""
            if any(x in name.lower() for x in exclude_names):
                continue
            cpu = proc.info["cpu_percent"] or 0.0
            if cpu > best_cpu:
                best_cpu = cpu
                best_name = name
        except Exception:
            continue
    return best_name, best_cpu


def main():
    parser = argparse.ArgumentParser(description="Pi 5 performance monitor")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="sampling interval in seconds (default: 2.0)")
    parser.add_argument("--csv", type=str, default=None,
                        help="also log samples to a CSV file")
    parser.add_argument("--pid", type=int, default=None,
                        help="also track a specific process by PID")
    args = parser.parse_args()

    try:
        import psutil
    except ImportError:
        print("ERROR: psutil is required. Install with:  pip install psutil",
              file=sys.stderr)
        sys.exit(1)

    header = (
        "time     | total  | c0    c1    c2    c3   | mem%  (used)   | load1 | temp   | top_proc"
    )
    print(header)
    print("-" * len(header))

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow([
            "timestamp_iso", "cpu_total_pct",
            "cpu0", "cpu1", "cpu2", "cpu3",
            "mem_pct", "mem_used_gb",
            "load1", "temp_c",
            "top_process_name", "top_process_cpu",
        ])

    tracked_proc = None
    if args.pid:
        try:
            tracked_proc = psutil.Process(args.pid)
            # Prime the CPU counter for this process.
            tracked_proc.cpu_percent(interval=None)
        except psutil.NoSuchProcess:
            print(f"ERROR: PID {args.pid} not found", file=sys.stderr)
            sys.exit(1)

    # Prime the system-wide CPU counter.
    psutil.cpu_percent(percpu=True)
    time.sleep(0.5)

    sample_count = 0
    try:
        while True:
            # `cpu_percent(interval=N)` blocks for N seconds and returns
            # the utilisation over that window — it IS the sampling delay.
            cpu_per_core = psutil.cpu_percent(interval=args.interval, percpu=True)
            cpu_total = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0

            mem = psutil.virtual_memory()
            mem_pct = mem.percent
            mem_used_gb = mem.used / (1024 ** 3)

            load1 = psutil.getloadavg()[0]
            temp = _read_soc_temp_c()

            top_name, top_cpu = _find_top_cpu_process(psutil)

            timestamp = datetime.now()
            ts_short = timestamp.strftime("%H:%M:%S")

            core_str = " ".join(f"{c:5.1f}" for c in cpu_per_core[:4])

            # Base line
            line = (
                f"{ts_short} | {cpu_total:5.1f}% | {core_str} | "
                f"{mem_pct:5.1f}% ({mem_used_gb:4.2f}GB) | "
                f"{load1:5.2f} | "
                f"{temp:5.1f}°C | "
                f"{top_name[:20]:<20s} ({top_cpu:5.1f}%)"
            )
            if temp > 80:
                # Red text + suffix so it's visible in a log stream
                line = f"\033[31m{line}  THERMAL THROTTLE RISK\033[0m"

            print(line)

            if csv_writer:
                csv_writer.writerow([
                    timestamp.isoformat(), f"{cpu_total:.2f}",
                    *(f"{c:.2f}" for c in cpu_per_core[:4]),
                    f"{mem_pct:.2f}", f"{mem_used_gb:.3f}",
                    f"{load1:.2f}", f"{temp:.1f}",
                    top_name, f"{top_cpu:.2f}",
                ])
                csv_file.flush()

            if tracked_proc is not None:
                try:
                    proc_cpu = tracked_proc.cpu_percent(interval=None)
                    proc_mem_mb = tracked_proc.memory_info().rss / (1024 ** 2)
                    threads = tracked_proc.num_threads()
                    print(f"           pid {args.pid}: {proc_cpu:6.1f}% CPU, "
                          f"{proc_mem_mb:6.0f} MB RAM, {threads} threads")
                except psutil.NoSuchProcess:
                    print(f"           pid {args.pid} exited — stopping process trace")
                    tracked_proc = None

            sample_count += 1
    except KeyboardInterrupt:
        print()
        print(f"Stopped after {sample_count} samples.")
        if csv_file:
            csv_file.close()
            print(f"CSV saved: {args.csv}")


if __name__ == "__main__":
    main()

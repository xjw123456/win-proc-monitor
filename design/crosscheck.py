# -*- coding: utf-8 -*-
"""与系统计数器交叉校验：内存工作集 vs Get-Process；CPU% vs Get-Counter \\Process(*)。
输出 design/_crosscheck.txt。
"""
import ctypes
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import winapi, sampler  # noqa: E402

TARGET = sys.argv[1] if len(sys.argv) > 1 else "chrome.exe"
INST = TARGET.replace(".exe", "")
ROUNDS = 8
INTERVAL = 2.0

lines = []


def sh(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def ws_sum():
    out = sh("(Get-Process -Name '%s' -ErrorAction SilentlyContinue | "
             "Measure-Object WorkingSet64 -Sum).Sum" % INST)
    try:
        return float(out) / 1048576.0
    except Exception:
        return None


mon = sampler.Monitor(TARGET, interval=INTERVAL)
mon.start()
time.sleep(INTERVAL * 1.2)

# Get-Counter 的 \Process(inst)\% Processor Time 是「所有核累加」，除以核数才与任务管理器同口径
cores = winapi.system_info()["cores"]
for i in range(ROUNDS):
    s = mon.latest()
    if s is None:
        time.sleep(INTERVAL)
        continue
    ws_ref = ws_sum()
    cpu_raw = sh("(Get-Counter '\\Process(%s)\\%% Processor Time' -MaxSamples 1 "
                 "-ErrorAction SilentlyContinue).CounterSamples[0].CookedValue" % INST)
    try:
        cpu_ref = float(cpu_raw) / cores
    except Exception:
        cpu_ref = None
    lines.append("第 %d 次｜t=%5.1fs  自身 CPU %5.2f%%  参考 %5.2f%%  差 %+5.2f pp | "
                 "私有WS %7.1f MB  工作集 %7.1f MB  参考WS %7.1f MB  差 %+6.1f MB"
                 % (i + 1, s.rel_s, s.cpu_pct or 0.0, cpu_ref if cpu_ref is not None else -1,
                    (s.cpu_pct or 0.0) - (cpu_ref or 0.0), s.priv_mb, s.ws_mb,
                    ws_ref if ws_ref is not None else -1,
                    (s.ws_mb - ws_ref) if ws_ref is not None else 0.0))
    time.sleep(INTERVAL)

mon.stop()
lines.append("")
lines.append("说明：Get-Counter 的 Process(*)\\%% Processor Time 按「全部核累加」，已除以 %d 个逻辑处理器；"
             "工作集参考值取 Get-Process 同一时刻 WorkingSet64 求和（毫秒级不同步，允许 2%% 或 20MB 偏差）。" % cores)

io.open(os.path.join(ROOT, "design", "_crosscheck.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
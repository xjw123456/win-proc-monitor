# -*- coding: utf-8 -*-
"""CPU 口径验证。
A 段：单个 python 进程满载 1 个核（GIL 决定只能吃 1 核），理论 100/核数。
B 段：4 个 powershell 实例各占 1 核，按进程名聚合，理论 400/核数（等于任务管理器对同名实例求和的口径）。
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import winapi, sampler  # noqa: E402

cores = winapi.system_info()["cores"]
lines = ["逻辑处理器 %d，单核满载理论值 %.2f%%，四核满载理论值 %.2f%%"
         % (cores, 100.0 / cores, 400.0 / cores)]

SPIN_PY = ("import time\n"
           "t=time.time()\n"
           "while time.time()-t < 18:\n"
           "    x=0\n"
           "    for i in range(20000): x+=i*i\n")
PS_LOOP = "for($i=0;$i -lt 400000000;$i++){$x=$i*2}"


def run_case(title, spawn, name, pid=None, by_name=True, seconds=16, expect=None):
    lines.append("\n[%s] 目标 %s%s，理论 %.2f%%" % (title, name, "（按名聚合）" if by_name else "",
                                                 expect))
    procs = spawn()
    time.sleep(1.2)
    mon = sampler.Monitor(name, pid=pid, by_name=by_name, interval=2.0)
    mon.start()
    vals = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.5)
        s = mon.latest()
        if s and s.cpu_pct is not None and (not vals or vals[-1][0] != s.seq):
            vals.append((s.seq, s.cpu_pct, s.rel_s, s.instances))
    mon.stop()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    ok = 0
    for seq, pct, rel, inst in vals:
        good = abs(pct - expect) <= 6.0
        ok += 1 if good else 0
        lines.append("  样本 %2d  t=%5.1fs  CPU %6.2f%%  实例 %d  偏差 %+5.2f pp  %s"
                     % (seq, rel, pct, inst, pct - expect, "OK" if good else "偏离"))
    lines.append("  落在 ±6pp 内的样本：%d/%d" % (ok, len(vals)))
    return ok == len(vals) and len(vals) > 0


a = run_case("A 单进程单核", lambda: [subprocess.Popen([sys.executable, "-c", SPIN_PY])],
             "python.exe", expect=100.0 / cores)
b = run_case("B 四实例按名聚合",
             lambda: [subprocess.Popen(["powershell", "-NoProfile", "-Command", PS_LOOP])
                      for _ in range(4)],
             "powershell.exe", expect=400.0 / cores)
lines.append("\n结论：%s" % ("两段均与理论值一致" if a and b else "存在偏差，需检查口径"))
txt = "\n".join(lines)
open(os.path.join(ROOT, "design", "_cpucheck.txt"), "w", encoding="utf-8").write(txt + "\n")
print(txt)
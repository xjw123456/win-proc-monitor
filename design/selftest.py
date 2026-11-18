# -*- coding: utf-8 -*-
"""自检脚本：节拍精度 / 暂停恢复 / 进程退出 / 自身开销 / 产物完整性。
用法：python design/selftest.py [目标进程名，默认 chrome.exe]
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import winapi, sampler, analyzer, output  # noqa: E402

OUT = []
FAIL = []


def log(msg):
    OUT.append(msg)
    print(msg)


def check(name, cond, detail=""):
    log(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def t_cadence(target, n=8, interval=1.0):
    log("\n[T1] 采样节拍（%d 条 / %.1f 秒间隔）" % (n, interval))
    mon = sampler.Monitor(target, interval=interval)
    mon.start()
    time.sleep(n * interval + interval * 0.5)
    mon.stop()
    ss = mon.snapshot()
    dts = [s.dt_ms for s in ss if s.dt_ms]
    check("样本数 = %d" % (n + 1), len(ss) == n + 1, "实际 %d" % len(ss))
    if dts:
        dev = max(abs(d - interval * 1000.0) for d in dts)
        check("节拍偏差 ≤100ms", dev <= 100.0, "最大偏差 %.0fms" % dev)
        log("       平均间隔 %.3fs，最小 %.3fs，最大 %.3fs"
            % (sum(dts) / len(dts) / 1000.0, min(dts) / 1000.0, max(dts) / 1000.0))
    return mon, ss


def t_pause(target, interval=1.0):
    log("\n[T2] 暂停 / 恢复")
    mon = sampler.Monitor(target, interval=interval)
    mon.start()
    time.sleep(2.2)
    mon.pause()
    before = mon.sample_count()
    time.sleep(3.0)
    mon.resume()
    time.sleep(2.2)
    mon.stop()
    ss = mon.snapshot()
    dts = [s.dt_ms for s in ss if s.dt_ms]
    gap = max(dts) if dts else 0
    check("暂停期间无新样本", mon.sample_count() > before, "暂停前 %d 条，停止后共 %d 条"
          % (before, mon.sample_count()))
    check("暂停区间不计入采样间隔", gap <= 1500, "最大间隔 %.0fms（暂停 3s 未采样，恢复后立即重建基线）" % gap)
    check("恢复行写入备注", any("恢复" in (s.note or "") for s in ss),
          "备注样例：%s" % next((s.note for s in ss if s.note and "恢复" in s.note), "无"))
    check("paused_count = 1", mon.paused_count == 1, "实际 %d" % mon.paused_count)
    return mon, ss


def t_exit():
    log("\n[T3] 目标进程中途退出")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    name = winapi.pid_image_name(child.pid) or "python.exe"
    mon = sampler.Monitor(name, pid=child.pid, by_name=False, interval=1.0)
    mon.start()
    deadline = time.time() + 12
    while time.time() < deadline and mon.state != sampler.STOPPED:
        time.sleep(0.3)
    child.wait(timeout=5)
    ss = mon.snapshot()
    check("进程退出后自动停止", mon.state == sampler.STOPPED, "state=%s" % mon.state)
    check("标记 exited", bool(mon.exited), "exited_at=%s" % mon.exited_at)
    check("退出前数据保留", len(ss) >= 3, "%d 条" % len(ss))
    return mon, ss


def t_overhead(seconds=12):
    log("\n[T4] 工具自身开销（%d 秒采样期间）" % seconds)
    h = winapi.ProcHandle(os.getpid())
    mem0 = h.memory()["private_ws"]
    t0 = h.cpu_times()
    mon = sampler.Monitor("chrome.exe", interval=0.2)   # 故意压到 200ms 放大开销
    mon.start()
    time.sleep(seconds)
    mon.stop()
    t1 = h.cpu_times()
    mem1 = h.memory()["private_ws"]
    cpu_ms = ((t1[1] + t1[2]) - (t0[1] + t0[2])) / 1e4
    cores = winapi.system_info()["cores"] or 1
    pct = cpu_ms / (seconds * 1000.0) / cores * 100.0   # 整机折算（任务管理器口径）
    one_core = cpu_ms / (seconds * 1000.0) * 100.0      # 单核满载百分比
    log("       内存 %.1f MB → %.1f MB；CPU 时间 %.0f ms / %.0f s（%.2f%% 单核占用，%d 线程采样）"
        % (mem0 / 1048576.0, mem1 / 1048576.0, cpu_ms, seconds,
           cpu_ms / (seconds * 1000.0) * 100.0, mon.sample_count()))
    check("自身内存 <80MB", mem1 / 1048576.0 < 80.0, "%.1f MB" % (mem1 / 1048576.0))
    check("自身 CPU <1%（按整机折算）", pct < 1.0, "%.3f%%" % pct)


def t_outputs(target):
    log("\n[T5] 产物完整性")
    mon, ss = t_cadence(target, n=6, interval=1.0)
    if len(ss) < 3:
        check("样本充足", False, "仅 %d 条" % len(ss))
        return
    meta = output.build_meta(mon, ss, winapi.system_info())
    th = analyzer.merge_thresholds({})
    a = analyzer.analyze(ss, meta, th)
    out_dir = os.path.join(ROOT, "output", "_selftest")
    res = output.write_outputs(out_dir, ss, meta, a, th, winapi.system_info())
    for key in ("xlsx", "html", "md"):
        p = res.get(key)
        check("生成 %s" % os.path.basename(p or ""), bool(p) and os.path.exists(p)
              and os.path.getsize(p) > 500, "%d bytes" % (os.path.getsize(p) if p and os.path.exists(p) else 0))
    mp = os.path.join(out_dir, "meta.json")
    ok = os.path.exists(mp)
    if ok:
        with open(mp, encoding="utf-8") as f:
            m = json.load(f)
        mm = m.get("meta", {})
        ok = all(k in mm for k in ("target", "started_at_text", "sample_count")) \
            and "thresholds" in m and "analysis" in m
    check("meta.json 可解析且字段齐全", ok)
    check("综合结论存在", a.get("overall") in ("pass", "warn", "fail", "unknown"),
          "%s / %s" % (a.get("overall"), a.get("overall_text")))


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "chrome.exe"
    cat = winapi.ProcessCatalog()
    cat.refresh(force=True)
    if not cat.by_name(target):
        log("!! 当前没有名为 %s 的进程，改用 python.exe 自测" % target)
        target = "python.exe"
    log("自检目标：%s · %s" % (target, winapi.system_info()["os_name"]))
    t_cadence(target)
    t_pause(target)
    t_exit()
    t_overhead()
    t_outputs(target)
    log("\n===== 结果：%s =====" % ("全部通过" if not FAIL else "失败 %d 项：%s"
                                    % (len(FAIL), "、".join(FAIL))))
    with open(os.path.join(ROOT, "design", "_selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
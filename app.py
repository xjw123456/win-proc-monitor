# -*- coding: utf-8 -*-
"""win-proc-monitor 入口。

用法：
    python app.py                       # 启动图形界面
    python app.py --cli chrome.exe -d 12    # 无界面自测：采 12 秒，直接出全部产物
    python app.py --list                # 列出当前所有进程（按实例数分组）
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core import VERSION                      # noqa: E402
from core import analyzer, output, winapi     # noqa: E402
from core.sampler import Monitor              # noqa: E402

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def load_thresholds():
    cfg = {}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
    except Exception:
        cfg = {}
    return analyzer.merge_thresholds((cfg.get("thresholds") or {}))


def _safe_name(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "process"


def cmd_list():
    sysinfo = winapi.system_info()
    print("%s Build %s · %d 逻辑处理器 · %.1f GB 内存 · Python %s" % (
        sysinfo["os_name"], sysinfo["os_build"], sysinfo["cores"],
        sysinfo["total_phys_mb"] / 1024.0, sysinfo["python"]))
    cat = winapi.ProcessCatalog()
    cat.refresh(force=True)
    groups = sorted(cat.grouped().items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    print("%-42s %s" % ("进程名", "实例数"))
    for name, pids in groups:
        print("%-42s %d" % (name, len(pids)))


def cmd_cli(args):
    sysinfo = winapi.system_info()
    interval = max(1.0, float(args.interval))
    if args.pid:
        img = winapi.pid_image_name(args.pid)
        if not img:
            print("[错误] PID %d 不存在或无权限读取。" % args.pid)
            return 2
        mon = Monitor(img, pid=args.pid, by_name=False, interval=interval, sysinfo=sysinfo)
        display = "%s (PID %d)" % (img, args.pid)
    else:
        cat = winapi.ProcessCatalog()
        cat.refresh(force=True)
        if not cat.by_name(args.process):
            print("[错误] 当前没有名为「%s」的进程在运行。" % args.process)
            return 2
        mon = Monitor(args.process, by_name=True, interval=interval, sysinfo=sysinfo)
        display = args.process

    print("[%s] 开始监控 %s，间隔 %.1f 秒，预计采集 %d 秒…"
          % (datetime.now().strftime("%H:%M:%S"), display, interval, args.duration))
    mon.start()

    t0 = time.time()
    last_seq = -1
    while time.time() - t0 < args.duration:
        time.sleep(0.5)
        s = mon.latest()
        if mon.error:
            print("\n[错误] %s" % str(mon.error).strip().splitlines()[-1])
            break
        if s is None:
            if mon.exited:
                print("\n[提示] 目标进程已退出。")
                break
            continue
        if s.seq == last_seq:
            continue
        last_seq = s.seq
        cpu = "  —  " if s.cpu_pct is None else "%5.1f%%" % s.cpu_pct
        sys.stdout.write("\r  %5.1fs  样本 %3d  CPU %s  私有工作集 %7.1f MB  线程 %3d  "
                         % (s.rel_s, len(mon.samples), cpu, s.priv_mb, s.threads))
        sys.stdout.flush()
    print()

    mon.stop()
    samples = mon.snapshot()
    if len(samples) < 3:
        print("[错误] 只采集到 %d 条样本，无法分析。" % len(samples))
        return 3

    meta = output.build_meta(mon, samples, sysinfo)
    th = load_thresholds()
    analysis = analyzer.analyze(samples, meta, th)

    if args.out:
        out_dir = args.out
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(OUTPUT_DIR, "%s_%s" % (_safe_name(mon.name), stamp))

    res = output.write_outputs(out_dir, samples, meta, analysis, th, sysinfo)

    print("-" * 72)
    print("样本 %d 条 · 时长 %s · 间隔 %.2f 秒（实测）"
          % (len(samples), meta["duration_text"],
             (samples[-1].rel_s / max(1, len(samples) - 1)) if len(samples) > 1 else 0))
    print("综合判定：%s" % analysis["overall_text"])
    for key, label in (("cpu", "CPU 占用"), ("mem", "内存占用"), ("release", "内存释放趋势")):
        block = analysis[key]
        print("  %-12s %-4s  %s" % (label, analyzer.LEVEL_TEXT.get(block["verdict"], "—"),
                                    "；".join(block.get("reasons") or [])))
    print("-" * 72)
    print("产物目录：%s" % res["dir"])
    for p in (res["xlsx"], res["html"], res["md"]):
        print("  %8.1f KB  %s" % (os.path.getsize(p) / 1024.0, os.path.basename(p)))
    print("  meta.json")
    return 0


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Windows 进程 CPU/内存监控与性能分析")
    ap.add_argument("--cli", action="store_true", help="无界面自测模式")
    ap.add_argument("--list", action="store_true", help="列出当前进程")
    ap.add_argument("process", nargs="?", default="chrome.exe", help="进程名，如 chrome.exe")
    ap.add_argument("--pid", type=int, default=0, help="按 PID 监控（与进程名二选一）")
    ap.add_argument("-d", "--duration", type=int, default=20, help="CLI 采集秒数（默认 20）")
    ap.add_argument("-i", "--interval", type=float, default=2.0, help="采样间隔秒（默认 2）")
    ap.add_argument("-o", "--out", default="", help="自定义产物目录")
    ap.add_argument("--version", action="version", version="win-proc-monitor %s" % VERSION)
    args = ap.parse_args()

    if args.list:
        cmd_list()
        return 0
    if args.cli:
        return cmd_cli(args)

    from ui.main_window import App
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
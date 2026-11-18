# -*- coding: utf-8 -*-
"""产物落盘：元数据组装 + Excel/HTML/MD/meta.json 一次性写出（GUI 与 CLI 共用）。"""

import json
import os
from datetime import datetime

from . import VERSION, excel_writer, report_writer

MEM_SOURCE_TEXT = {
    "ex2": "PROCESS_MEMORY_COUNTERS_EX2（私有工作集，任务管理器「内存」列同源）",
    "private": "PROCESS_MEMORY_COUNTERS_EX2（私有工作集，任务管理器「内存」列同源）",
    "sysinfo": "系统进程表（NtQuerySystemInformation 私有工作集；句柄无权限时自动回退，"
               "与任务管理器「性能」页汇总同源）",
    "fallback_ws": "工作集（旧系统回退，非任务管理器口径）",
    "mixed": "混合来源（部分实例句柄直读、部分走系统进程表，数值口径一致）",
    "denied": "读取失败（两条通道都不可用）",
}


DEFAULT_NAMES = {"excel": "01_原始数据", "html": "02_性能报告", "md": "03_性能报告摘要"}


def build_meta(monitor, samples, sysinfo):
    """把一次监控会话整理成产物需要的元数据。"""
    started = monitor.started_at or datetime.now()
    finished = monitor.finished_at or datetime.now()
    dur = samples[-1].rel_s if samples else 0.0
    src = getattr(monitor, "mem_source", None) or "private"
    return {
        "target": monitor.name,
        "by_name": bool(monitor.by_name),
        "pids": list(getattr(monitor, "last_pids", None) or
                     ([monitor.pid] if monitor.pid else [])),
        "started_at_text": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at_text": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_s": round(float(dur), 1),
        "duration_text": report_writer.fmt_dur(dur),
        "interval": monitor.interval,
        "sample_count": len(samples),
        "cores": sysinfo.get("cores") or 1,
        "total_phys_mb": sysinfo.get("total_phys_mb") or 0,
        "mem_source": src,
        "mem_source_text": MEM_SOURCE_TEXT.get(src, MEM_SOURCE_TEXT["ex2"]),
        "exited": bool(getattr(monitor, "exited", False)),
        "exited_at_text": (monitor.exited_at.strftime("%Y-%m-%d %H:%M:%S")
                           if getattr(monitor, "exited_at", None) else ""),
        "paused_count": int(getattr(monitor, "paused_count", 0) or 0),
        "tool_version": VERSION,
        "os": "%s Build %s" % (sysinfo.get("os_name"), sysinfo.get("os_build")),
    }


def _brief(analysis):
    def one(block):
        return {"verdict": block.get("verdict"), "label": block.get("label"),
                "reasons": block.get("reasons")}
    return {"overall": analysis.get("overall"),
            "cpu": one(analysis.get("cpu", {})),
            "mem": one(analysis.get("mem", {})),
            "release": one(analysis.get("release", {}))}


def write_outputs(out_dir, samples, meta, analysis, thresholds, sysinfo, names=None):
    names = names or DEFAULT_NAMES
    os.makedirs(out_dir, exist_ok=True)
    xlsx = os.path.join(out_dir, "%s.xlsx" % names["excel"])
    excel_writer.write_workbook(xlsx, samples, meta, analysis, thresholds, sysinfo)
    html_path, md_path = report_writer.write_reports(
        out_dir, samples, meta, analysis, thresholds, sysinfo, names)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "thresholds": thresholds, "analysis": _brief(analysis)},
                  f, ensure_ascii=False, indent=2)
    return {"dir": out_dir, "xlsx": xlsx, "html": html_path, "md": md_path}
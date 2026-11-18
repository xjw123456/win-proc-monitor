# -*- coding: utf-8 -*-
"""Excel 产物：5 个 sheet（说明 / 原始数据 / 统计汇总 / 判定结果 / 图表）。"""

from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import VERSION
from .analyzer import LEVEL_TEXT, mean, stdev

# 配色（与报告/原型一致）
C_DARK = "0F172A"
C_HEAD = "1E3A5F"
C_SUB = "E8EFF7"
C_LINE = "D5DEE8"
C_PASS = "DCFCE7"
C_WARN = "FEF3C7"
C_FAIL = "FEE2E2"

FONT_NAME = "微软雅黑"

# 前三列与任务管理器「进程」页一一对应（时间 / CPU / 内存），
# 其后是补足「占用大小」与精确值的列，最后一列是备注。
COLUMNS = [
    ("序号", 7, "0"),
    ("采样时间", 20, "yyyy-mm-dd hh:mm:ss"),
    ("CPU(%)", 11, "0.00"),
    ("内存(MB)", 13, "0.0"),
    ("相对时间(s)", 12, "0.0"),
    ("CPU占用大小-区间CPU时间(ms)", 22, "0.00"),
    ("累计CPU时间", 13, "[h]:mm:ss"),
    ("等效核数", 10, "0.000"),
    ("私有工作集(MB)", 15, "0.0"),
    ("内存占用率(%)", 13, "0.00"),
    ("工作集(MB)", 12, "0.0"),
    ("提交大小(MB)", 13, "0.0"),
    ("线程数", 8, "0"),
    ("句柄数", 8, "0"),
    ("实例数", 8, "0"),
    ("内存来源", 12, None),
    ("备注", 34, None),
]

# 列号常量（1 起），避免下游按魔法数字误改
C_SEQ, C_TS, C_CPU, C_MEM, C_REL = 1, 2, 3, 4, 5
C_CPU_MS, C_CPU_TOTAL, C_CORES = 6, 7, 8
C_PRIV, C_MEM_PCT, C_WS, C_COMMIT = 9, 10, 11, 12
C_THREADS, C_HANDLES, C_INST, C_SRC, C_NOTE = 13, 14, 15, 16, 17

SRC_TEXT = {
    "ex2": "句柄直读",
    "private": "句柄直读",
    "sysinfo": "系统通道",
    "fallback_ws": "工作集回退",
    "mixed": "混合",
    "denied": "读取失败",
}


def _thin():
    return Side(style="thin", color=C_LINE)


def _border():
    t = _thin()
    return Border(left=t, right=t, top=t, bottom=t)


def _title(ws, text, span=6, sub=None):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    c = ws.cell(row=1, column=1, value=text)
    c.font = Font(name=FONT_NAME, size=15, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=C_DARK)
    c.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    ws.row_dimensions[1].height = 34
    if sub:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
        c2 = ws.cell(row=2, column=1, value=sub)
        c2.font = Font(name=FONT_NAME, size=9, color="475569")
        c2.alignment = Alignment(vertical="center", horizontal="left", indent=1)
        ws.row_dimensions[2].height = 20
        return 3
    return 2


def _kv(ws, row, key, value, key_w=None):
    kc = ws.cell(row=row, column=1, value=key)
    kc.font = Font(name=FONT_NAME, size=10, bold=True, color="334155")
    kc.fill = PatternFill("solid", fgColor=C_SUB)
    kc.alignment = Alignment(vertical="center", indent=1)
    kc.border = _border()
    vc = ws.cell(row=row, column=2, value=value)
    vc.font = Font(name=FONT_NAME, size=10, color="0F172A")
    vc.alignment = Alignment(vertical="center", indent=1, wrap_text=False)
    vc.border = _border()
    ws.row_dimensions[row].height = 21


def _level_fill(level):
    return {"pass": C_PASS, "warn": C_WARN, "fail": C_FAIL}.get(level, "FFFFFF")


# --------------------------------------------------------------------------
def _sheet_readme(wb, meta, analysis, thresholds, sysinfo):
    ws = wb.create_sheet("00_监控说明")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 62

    row = _title(
        ws, "进程性能监控 · 采集说明",
        span=2,
        sub="本页记录本次采集的口径与参数，报告中的所有数字都可由「01_原始数据」复算。",
    )

    row += 1
    ws.cell(row=row, column=1, value="一、监控对象").font = Font(
        name=FONT_NAME, size=11, bold=True, color=C_HEAD)
    row += 1
    items = [
        ("目标进程", meta.get("target", "")),
        ("监控模式", "按进程名聚合（与任务管理器「进程」页一致）" if meta.get("by_name")
         else "指定 PID"),
        ("PID 集合", ", ".join(str(p) for p in (meta.get("pids") or [])) or "—"),
        ("开始时间", meta.get("started_at_text", "—")),
        ("结束时间", meta.get("finished_at_text", "—")),
        ("有效时长", "%s（%.1f 秒）" % (meta.get("duration_text", "—"), meta.get("duration_s", 0))),
        ("采样间隔", "%.0f 秒" % meta.get("interval", 2)),
        ("样本条数", str(meta.get("sample_count", 0))),
    ]
    for k, v in items:
        _kv(ws, row, k, v)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="二、运行环境").font = Font(
        name=FONT_NAME, size=11, bold=True, color=C_HEAD)
    row += 1
    for k, v in [
        ("操作系统", "%s（Build %s）" % (sysinfo.get("os_name"), sysinfo.get("os_build"))),
        ("逻辑处理器", "%d" % sysinfo.get("cores", 0)),
        ("物理内存", "%.1f GB" % (sysinfo.get("total_phys_mb", 0) / 1024.0)),
        ("Python", sysinfo.get("python")),
        ("工具版本", VERSION),
        ("私有工作集来源", meta.get("mem_source_text", "PROCESS_MEMORY_COUNTERS_EX2")),
    ]:
        _kv(ws, row, k, v)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="三、口径说明").font = Font(
        name=FONT_NAME, size=11, bold=True, color=C_HEAD)
    row += 1
    notes = [
        "【与任务管理器逐列对齐】01_原始数据 的前三列 = 时间 / CPU(%) / 内存(MB)，"
        "与「任务管理器 → 进程」页看到的三列一一对应，可直接对号入座比对。",
        "「CPU(%)」= 本区间 CPU 时间 ÷ 本区间实际间隔 ÷ 逻辑处理器数 × 100，"
        "同名多开实例求和，与任务管理器「进程」页 CPU 列同口径。",
        "「内存(MB)」= 私有工作集，即任务管理器「进程」页「内存」列的口径（Win10 1809 起 / Win11）。",
        "「CPU占用大小-区间CPU时间(ms)」= 该采样窗口内进程实际消耗的 CPU 时间（任务管理器无此列，"
        "用于还原「占用大小」）；「等效核数」= 相当于吃满几个核。",
        "「累计CPU时间」= 进程启动至今累计 CPU 时间，与任务管理器「详细信息 → CPU 时间」列一致，"
        "可逐行对照。",
        "「内存占用率(%)」= 私有工作集 ÷ 物理内存总量。任务管理器不提供单进程内存百分比列，"
        "该值按整机占比口径换算，可与「性能」页内存百分比对照。",
        "「内存来源」列：句柄直读 / 系统通道（句柄无权限时自动改用 NtQuerySystemInformation，"
        "普通权限即可读全部进程，数值口径一致）/ 工作集回退。",
        "首行（开始时刻）没有前一帧，CPU 占用率为空；暂停期间不采样，恢复后首行备注中标注暂停时长。",
    ]
    for i, t in enumerate(notes, 1):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        c = ws.cell(row=row, column=1, value="%d. %s" % (i, t))
        c.font = Font(name=FONT_NAME, size=9.5, color="334155")
        c.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
        ws.row_dimensions[row].height = 32
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="四、本次判定标准（快照）").font = Font(
        name=FONT_NAME, size=11, bold=True, color=C_HEAD)
    row += 1
    cpu_th = thresholds["cpu"]
    mem_th = thresholds["mem"]
    rel_th = thresholds["release"]
    std_rows = [
        ("CPU 平均", "≤ %.0f%%（> %.0f%% 不通过）" % (cpu_th["avg"], cpu_th["avg_fail"])),
        ("CPU P95", "≤ %.0f%%（> %.0f%% 不通过）" % (cpu_th["p95"], cpu_th["p95_fail"])),
        ("CPU 峰值", "≤ %.0f%%（> %.0f%% 不通过）" % (cpu_th["peak"], cpu_th["peak_fail"])),
        ("CPU 持续高占用", "≥ %.0f%% 连续不超过 %.0f 秒" % (
            cpu_th["sustained_threshold"], cpu_th["sustained_s"])),
        ("内存峰值占比", "≤ %.0f%%（> %.0f%% 不通过）" % (
            mem_th["peak_percent"], mem_th["peak_percent_fail"])),
        ("内存增长", "期末较基线 ≤ %.0f%%" % mem_th["growth_percent"]),
        ("内存斜率", "≤ %.1f MB/min（> %.1f 且 R²≥0.7 判泄漏）" % (
            rel_th["slope_mb_per_min"], rel_th["leak_slope_mb_per_min"])),
        ("有效释放", "跌幅 ≥ max(%.0f MB, 基线%.0f%%)，且回落到基线+%.0f%% 带内" % (
            rel_th["min_drop_mb"], rel_th["min_drop_percent"], rel_th["recover_band_percent"])),
        ("综合判定", "取 CPU / 内存 / 释放趋势三项中最严的一档"),
    ]
    for k, v in std_rows:
        _kv(ws, row, k, v)
        row += 1

    row += 1
    c = ws.cell(row=row, column=1,
                value="判定结论：%s" % LEVEL_TEXT.get(analysis["overall"], "—"))
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    c.font = Font(name=FONT_NAME, size=12, bold=True, color="0F172A")
    c.fill = PatternFill("solid", fgColor=_level_fill(analysis["overall"]))
    c.alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[row].height = 30


# --------------------------------------------------------------------------
def _sheet_data(wb, samples):
    """原始数据表：前 3 列与任务管理器「进程」页一一对应，其余为补足与精确值列。"""
    ws = wb.create_sheet("01_原始数据")
    n = len(samples)
    HEAD = 3          # 表头所在行（第 1 行是与任务管理器的对齐说明）

    # 对齐引导行：明确告诉使用者「这几列就是任务管理器里的那几列」
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))
    tip = ws.cell(row=1, column=1, value=(
        "对齐说明：『采样时间 / CPU(%) / 内存(MB)』三列与「任务管理器 → 进程」页一一对应，"
        "可直接同秒对比；其后各列为「占用大小」补充与精确值（CPU 时间、等效核数、私有工作集等）。"))
    tip.font = Font(name=FONT_NAME, size=9, color="92400E", bold=True)
    tip.fill = PatternFill("solid", fgColor="FEF3C7")
    tip.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    ws.row_dimensions[1].height = 22

    for idx, (title, width, _fmt) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
        c = ws.cell(row=HEAD, column=idx, value=title)
        c.font = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=C_HEAD)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = _border()
    ws.row_dimensions[HEAD].height = 32

    for i, s in enumerate(samples, start=HEAD + 1):
        src_text = SRC_TEXT.get(getattr(s, "mem_source", None) or "", "")
        vals = [
            s.seq, s.ts, s.cpu_pct, s.priv_mb, s.rel_s,
            s.cpu_ms, (s.cpu_total_s or 0) / 86400.0, s.cores,
            s.priv_mb, s.mem_pct, s.ws_mb, s.commit_mb,
            s.threads, s.handles, s.instances, src_text, s.note or "",
        ]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name=FONT_NAME, size=9.5, color="1E293B")
            c.border = _border()
            if j == C_SEQ:
                c.number_format = "0"
            elif j == C_TS:
                c.number_format = "yyyy-mm-dd hh:mm:ss"
            elif j in (C_CPU, C_MEM, C_MEM_PCT, C_CPU_MS):
                c.number_format = "0.00"
            elif j == C_CPU_TOTAL:
                c.number_format = "[h]:mm:ss"
            elif j == C_CORES:
                c.number_format = "0.000"
            elif j in (C_REL, C_WS, C_COMMIT, C_PRIV):
                c.number_format = "0.0"
            align = "center" if j in (C_TS, C_SRC) else (
                "left" if j == C_NOTE else "right")
            c.alignment = Alignment(horizontal=align, vertical="center",
                                    indent=1 if align == "left" else 0)

    # 前三列与任务管理器对齐，冻结到第 2 行并整表可筛选
    ws.freeze_panes = "A%d" % (HEAD + 1)
    ws.auto_filter.ref = "A%d:%s%d" % (HEAD, get_column_letter(len(COLUMNS)),
                                       max(n + HEAD, HEAD))

    # 两条阈值线：CPU >80% 与内存 >80% 标红（与判定标准一致）
    red = PatternFill("solid", fgColor="FECACA")
    if n:
        ws.conditional_formatting.add(
            "%s%d:%s%d" % (get_column_letter(C_CPU), HEAD + 1,
                           get_column_letter(C_CPU), n + HEAD),
            CellIsRule(operator="greaterThan", formula=["80"], fill=red))
        ws.conditional_formatting.add(
            "%s%d:%s%d" % (get_column_letter(C_MEM_PCT), HEAD + 1,
                           get_column_letter(C_MEM_PCT), n + HEAD),
            CellIsRule(operator="greaterThan", formula=["80"], fill=red))
    return ws


# --------------------------------------------------------------------------
def _sheet_stats(wb, samples, analysis, meta):
    ws = wb.create_sheet("02_统计汇总")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 46

    row = _title(ws, "统计汇总", span=4,
                 sub="与「02_性能报告」中的数字同源；采样质量用于核对 2 秒节拍是否稳定。")

    cpu = analysis["cpu"]
    mem = analysis["mem"]
    rel = analysis["release"]

    def section(title):
        nonlocal row
        row += 1
        c = ws.cell(row=row, column=1, value=title)
        c.font = Font(name=FONT_NAME, size=11, bold=True, color=C_HEAD)
        row += 1
        for j, h in enumerate(["指标", "数值", "单位/说明"], start=1):
            cc = ws.cell(row=row, column=j, value=h)
            cc.font = Font(name=FONT_NAME, size=9.5, bold=True, color="FFFFFF")
            cc.fill = PatternFill("solid", fgColor=C_HEAD)
            cc.alignment = Alignment(horizontal="center", vertical="center")
            cc.border = _border()
        row += 1

    def line(name, value, note=""):
        nonlocal row
        a = ws.cell(row=row, column=1, value=name)
        b = ws.cell(row=row, column=2, value=value)
        c = ws.cell(row=row, column=3, value=note)
        for cell in (a, b, c):
            cell.font = Font(name=FONT_NAME, size=9.5, color="1E293B")
            cell.border = _border()
            cell.alignment = Alignment(vertical="center", indent=1)
        row += 1

    section("CPU")
    line("有效样本数", cpu["count"], "条")
    if cpu["avg"] is not None:
        line("平均占用率", round(cpu["avg"], 2), "%")
        line("中位数（P50）", round(cpu["p50"], 2), "%")
        line("P95 占用率", round(cpu["p95"], 2), "%")
        line("峰值占用率", round(cpu["max"], 2), "%")
        line("峰值出现时间", cpu["max_ts"].strftime("%H:%M:%S") if cpu["max_ts"] else "—", "")
        line("≥80% 累计时长", round(cpu["above_80_total_s"], 1), "秒")
        line("≥80% 最长连续", round(cpu["longest_80_s"], 1), "秒")
        line("平均等效核数", round(cpu["avg"] / 100.0 * max(1, meta["cores"]), 3), "个")

    section("内存（私有工作集）")
    line("有效样本数", mem["count"], "条")
    if mem["baseline_mb"] is not None:
        line("基线", round(mem["baseline_mb"], 1), "MB（前 60s 中位数）")
        line("峰值", round(mem["peak_mb"], 1), "MB")
        line("峰值出现时间", mem["peak_at"].strftime("%H:%M:%S") if mem["peak_at"] else "—", "")
        line("峰值占物理内存", round(mem["peak_pct"], 2), "%")
        line("期末", round(mem["end_mb"], 1), "MB")
        line("期末较基线", "%+.1f%%" % mem["growth_pct"], "（%+.1f MB）" % mem["growth_mb"])
        line("增长斜率", round(mem["slope"], 2), "MB/min")
        line("拟合优度 R²", round(mem["r2"], 3), "越接近 1 越接近线性增长")
        line("波动标准差", round(stdev([s.priv_mb for s in samples]), 1), "MB")

    section("内存释放趋势")
    line("有效释放次数", rel["count"], "次")
    if rel["events"]:
        avg_drop = mean([e["drop_mb"] for e in rel["events"]])
        avg_dur = mean([e["duration_s"] for e in rel["events"]])
        line("平均释放幅度", round(avg_drop, 1), "MB")
        line("平均释放耗时", round(avg_dur, 1), "秒")
        line("最大释放幅度", round(max(e["drop_mb"] for e in rel["events"]), 1), "MB")
    line("趋势判定", rel["label"], "；".join(rel["reasons"]))

    section("采样质量")
    dts = [s.dt_ms for s in samples if s.dt_ms]
    if dts:
        line("平均间隔", round(mean(dts) / 1000.0, 3), "秒（目标 %.0f 秒）" % meta["interval"])
        line("最大间隔", round(max(dts) / 1000.0, 3), "秒")
        line("最小间隔", round(min(dts) / 1000.0, 3), "秒")
        line("节拍偏差（平均）", "%+.0f" % (mean(dts) - meta["interval"] * 1000), "毫秒")
    line("样本条数", len(samples), "条（理论值 %d 条）" % (
        int(round(meta["duration_s"] / float(meta["interval"]))) + 1))


# --------------------------------------------------------------------------
def _sheet_verdict(wb, analysis):
    ws = wb.create_sheet("03_判定结果")
    ws.sheet_view.showGridLines = False
    widths = [30, 34, 40, 12, 50]
    for i, wd in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = wd

    row = _title(ws, "判定结果", span=5,
                 sub="三项主线：CPU 是否超标 / 内存是否超标 / 内存是否有正常释放趋势；综合取最严。")

    # 综合结论
    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    c = ws.cell(row=row, column=1, value="综合结论")
    c.font = Font(name=FONT_NAME, size=11, bold=True, color="0F172A")
    c.alignment = Alignment(vertical="center", indent=1)
    cv = ws.cell(row=row, column=5, value=LEVEL_TEXT.get(analysis["overall"], "—"))
    cv.font = Font(name=FONT_NAME, size=12, bold=True, color="0F172A")
    cv.fill = PatternFill("solid", fgColor=_level_fill(analysis["overall"]))
    cv.alignment = Alignment(horizontal="center", vertical="center")
    for j in range(1, 6):
        ws.cell(row=row, column=j).border = _border()
    row += 2

    header = ["判定项", "标准", "实测", "结论", "说明"]
    for j, h in enumerate(header, 1):
        cc = ws.cell(row=row, column=j, value=h)
        cc.font = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
        cc.fill = PatternFill("solid", fgColor=C_HEAD)
        cc.alignment = Alignment(horizontal="center", vertical="center")
        cc.border = _border()
    row += 1

    groups = [
        ("CPU 占用", analysis["cpu"]),
        ("内存占用", analysis["mem"]),
        ("内存释放趋势", analysis["release"]),
    ]
    for title, block in groups:
        for m in block.get("metrics", []):
            vals = [m["name"], m["standard"], m["actual"],
                    LEVEL_TEXT.get(m["level"], "—"), ""]
            for j, v in enumerate(vals, 1):
                cc = ws.cell(row=row, column=j, value=v)
                cc.font = Font(name=FONT_NAME, size=9.5, color="1E293B")
                cc.border = _border()
                if j == 4:
                    cc.fill = PatternFill("solid", fgColor=_level_fill(m["level"]))
                    cc.alignment = Alignment(horizontal="center", vertical="center")
                elif j in (1,):
                    cc.alignment = Alignment(vertical="center", indent=1)
                else:
                    cc.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
            row += 1

        # 该组小结
        reasons = block.get("reasons") or []
        if reasons:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            cc = ws.cell(row=row, column=1, value="　↳ %s：%s" % (
                title, "；".join(reasons)))
            cc.font = Font(name=FONT_NAME, size=9, italic=True, color="475569")
            cc.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
            ws.row_dimensions[row].height = 26
            row += 1

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    cc = ws.cell(row=row, column=1, value="说明：阈值可在 config.json 中调整；"
                                          "本表的阈值快照见「00_监控说明」第四节。")
    cc.font = Font(name=FONT_NAME, size=9, color="64748B")
    cc.alignment = Alignment(vertical="center", indent=1)


# --------------------------------------------------------------------------
def _sheet_chart(wb, ws_data, count):
    ws = wb.create_sheet("04_图表")
    ws.sheet_view.showGridLines = False
    if count < 2:
        ws["A1"] = "样本不足，无法绘图"
        return ws

    chart = LineChart()
    chart.title = "CPU 占用率 与 私有工作集"
    chart.style = 2
    chart.height = 16
    chart.width = 32
    chart.y_axis.title = "CPU 占用率 (%)"
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 100
    chart.y_axis.majorGridlines = None
    chart.x_axis.title = "相对时间 (s)"
    chart.x_axis.tickLblSkip = max(1, count // 20)

    data_cpu = Reference(ws_data, min_col=5, min_row=1, max_row=count + 1)
    chart.add_data(data_cpu, titles_from_data=True)

    cat = Reference(ws_data, min_col=3, min_row=2, max_row=count + 1)
    chart.set_categories(cat)

    chart2 = LineChart()
    chart2.y_axis.axId = 200
    chart2.y_axis.title = "私有工作集 (MB)"
    chart2.y_axis.scaling.min = 0
    chart2.y_axis.crosses = "max"
    data_mem = Reference(ws_data, min_col=8, min_row=1, max_row=count + 1)
    chart2.add_data(data_mem, titles_from_data=True)
    chart2.set_categories(cat)

    chart += chart2

    # 线条配色
    try:
        s0 = chart.series[0]
        s0.graphicalProperties.line.solidFill = "2563EB"
        s0.graphicalProperties.line.width = 22000
        s1 = chart.series[1]
        s1.graphicalProperties.line.solidFill = "EA580C"
        s1.graphicalProperties.line.width = 22000
    except Exception:
        pass

    ws.add_chart(chart, "A3")
    return ws


# --------------------------------------------------------------------------
def write_workbook(path, samples, meta, analysis, thresholds, sysinfo):
    wb = Workbook()
    wb.remove(wb.active)

    _sheet_readme(wb, meta, analysis, thresholds, sysinfo)
    ws_data = _sheet_data(wb, samples)
    _sheet_stats(wb, samples, analysis, meta)
    _sheet_verdict(wb, analysis)
    _sheet_chart(wb, ws_data, len(samples))

    wb.properties.title = "进程性能监控数据"
    wb.properties.creator = "win-proc-monitor %s" % VERSION
    wb.properties.created = datetime.now()
    wb.save(path)
    return path
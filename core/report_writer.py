# -*- coding: utf-8 -*-
"""报告产物：单文件 HTML（内联样式 + 内联 SVG）+ Markdown 摘要。

不依赖任何外部资源，双击即可打开、可直接 Ctrl+P 存 PDF。
"""

import html
import math
import os
from datetime import datetime

from . import VERSION
from .analyzer import LEVEL_TEXT, UNKNOWN

LEVEL_COLOR = {
    "pass": ("#15803D", "#DCFCE7", "#BBF7D0"),
    "warn": ("#B45309", "#FEF3C7", "#FDE68A"),
    "fail": ("#B91C1C", "#FEE2E2", "#FECACA"),
    "unknown": ("#475569", "#E2E8F0", "#CBD5E1"),
    "info": ("#475569", "#F1F5F9", "#E2E8F0"),
}
LEVEL_TEXT.setdefault("unknown", "样本不足")

CSS = """
*{box-sizing:border-box}
body{margin:0;padding:32px 40px 60px;background:#F1F5F9;color:#0F172A;
 font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;font-size:14px;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto}
.card{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:22px 26px;margin-bottom:18px;
 box-shadow:0 1px 3px rgba(15,23,42,.06)}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:17px;margin:0 0 14px;padding-left:10px;border-left:4px solid #1E3A5F;line-height:1.2}
h3{font-size:14px;margin:18px 0 8px;color:#334155}
.sub{color:#64748B;font-size:13px}
.head{background:linear-gradient(135deg,#0F172A,#1E3A5F);color:#fff;border:none}
.head h1{color:#fff}
.head .sub{color:#CBD5E1}
.meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px 22px;margin-top:18px}
.meta div{font-size:12.5px;color:#CBD5E1}
.meta b{display:block;color:#fff;font-size:14px;font-weight:600;margin-top:2px}
.verdict{display:inline-block;padding:6px 18px;border-radius:999px;font-weight:700;font-size:16px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px}
.vcard{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:18px 20px;border-top-width:5px}
.vcard .t{font-size:13px;color:#64748B}
.vcard .v{font-size:20px;font-weight:700;margin:6px 0 4px}
.vcard .d{font-size:12.5px;color:#475569;min-height:38px}
.vcard .big{font-size:30px;font-weight:800;letter-spacing:-.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1E3A5F;color:#fff;text-align:left;padding:9px 12px;font-weight:600;white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid #E9EEF4;vertical-align:top}
tr:nth-child(even) td{background:#FAFCFE}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
ul.kf{margin:0;padding-left:20px}
ul.kf li{margin:6px 0}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:600;
 background:#E2E8F0;color:#334155;margin-left:6px}
.mono{font-family:"Cascadia Mono",Consolas,monospace;font-size:12px}
.note{background:#F8FAFC;border-left:3px solid #94A3B8;padding:10px 14px;color:#475569;font-size:12.5px;
 border-radius:0 6px 6px 0;margin-top:12px}
.foot{color:#94A3B8;font-size:12px;text-align:center;margin-top:26px}
.chart{margin-top:6px}
@media print{body{background:#fff;padding:0}.card{box-shadow:none;break-inside:avoid}
 .head{background:#0F172A !important;-webkit-print-color-adjust:exact}}
"""


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def fmt_dur(sec):
    sec = float(sec or 0)
    if sec < 60:
        return "%.0f 秒" % sec
    m, s = divmod(int(round(sec)), 60)
    if m < 60:
        return "%d 分 %d 秒" % (m, s)
    h, m = divmod(m, 60)
    return "%d 小时 %d 分" % (h, m)


def fmt_clock(dt):
    return dt.strftime("%H:%M:%S") if dt else "—"


def _fmt(v, nd=1, dash="—"):
    if v is None:
        return dash
    return ("%%.%df" % nd) % v


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def _downsample(samples, max_pts=1200):
    if len(samples) <= max_pts:
        return samples
    step = int(math.ceil(len(samples) / float(max_pts)))
    return samples[::step]


# --------------------------------------------------------------------------
# SVG 折线图
# --------------------------------------------------------------------------
def _xlabel(sec):
    v = int(round(float(sec or 0)))
    if v < 60:
        return "%ds" % v
    m, s = divmod(v, 60)
    if m < 60:
        return "%d:%02d" % (m, s)
    h, m = divmod(m, 60)
    return "%dh%02dm" % (h, m)


def svg_chart(samples, value_of, color, y_title, y_max, width=1100, height=270, y_min=0.0,
              threshold=None, threshold_label=None, ref_line=None, ref_label=None,
              peak_marker=True, fill=True, unit=""):
    """返回一段内联 SVG。x 轴为相对时间（秒）。"""
    pts = []
    for s in _downsample(samples):
        v = value_of(s)
        if v is None:
            continue
        pts.append((float(s.rel_s or 0.0), float(v)))
    if len(pts) < 2:
        return '<div class="note">样本点不足，未生成图表。</div>'

    ml, mr, mt, mb = 66, 26, 18, 40
    pw = width - ml - mr
    ph = height - mt - mb
    x_max = max(p[0] for p in pts) or 1.0
    y_hi = float(y_max) if y_max else math.ceil(max(p[1] for p in pts) / 50.0) * 50 or 100.0
    if y_hi <= 0:
        y_hi = 100.0

    def X(x):
        return ml + (x / x_max) * pw

    lo = float(y_min or 0.0)
    if lo >= y_hi * 0.95:
        lo = 0.0
    span = max(1e-6, y_hi - lo)

    def Y(y):
        y = min(max(y, lo), y_hi)
        return mt + ph - ((y - lo) / span) * ph

    out = ['<svg viewBox="0 0 %d %d" width="100%%" height="%d" class="chart" '
           'xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Microsoft YaHei, sans-serif">'
           % (width, height, height)]

    # 横向网格 + Y 轴刻度
    ticks = 5
    for i in range(ticks + 1):
        yv = lo + span * i / ticks
        yy = Y(yv)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#E2E8F0" stroke-width="1"/>'
                   % (ml, yy, ml + pw, yy))
        out.append('<text x="%d" y="%.1f" font-size="11" fill="#64748B" text-anchor="end">%s</text>'
                   % (ml - 8, yy + 4, _fmt(yv, 0 if y_hi >= 50 else 1)))

    # 面积
    if fill:
        area = ["M%.1f,%.1f" % (X(pts[0][0]), Y(lo))]
        for x, y in pts:
            area.append("L%.1f,%.1f" % (X(x), Y(y)))
        area.append("L%.1f,%.1f" % (X(pts[-1][0]), Y(lo)))
        area.append("Z")
        out.append('<path d="%s" fill="%s" fill-opacity="0.10" stroke="none"/>'
                   % (" ".join(area), color))

    # 参考线 / 阈值线
    if ref_line is not None:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#94A3B8" stroke-width="1.4" '
                   'stroke-dasharray="6 4"/>' % (ml, Y(ref_line), ml + pw, Y(ref_line)))
        if ref_label:
            out.append('<text x="%d" y="%.1f" font-size="11" fill="#64748B">%s</text>'
                       % (ml + 8, Y(ref_line) - 6, _esc(ref_label)))
    if threshold is not None and threshold <= y_max:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#DC2626" stroke-width="1.4" '
                   'stroke-dasharray="7 5"/>' % (ml, Y(threshold), ml + pw, Y(threshold)))
        out.append('<text x="%d" y="%.1f" font-size="11" fill="#DC2626" text-anchor="end">%s</text>'
                   % (ml + pw, Y(threshold) - 6, _esc(threshold_label or "")))

    # 折线
    d = " ".join("%.1f,%.1f" % (X(x), Y(y)) for x, y in pts)
    out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
               'stroke-linejoin="round" stroke-linecap="round"/>' % (d, color))

    # 峰值标记
    if peak_marker:
        px, py = max(pts, key=lambda p: p[1])
        out.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="#fff" stroke="%s" stroke-width="2.5"/>'
                   % (X(px), Y(py), color))
        anchor = "start" if X(px) < ml + pw * 0.75 else "end"
        dx = 8 if anchor == "start" else -8
        out.append('<text x="%.1f" y="%.1f" font-size="11.5" font-weight="700" fill="%s" '
                   'text-anchor="%s">%s%s</text>'
                   % (X(px) + dx, Y(py) - 9, color, anchor, _fmt(py, 1), unit))

    # X 轴刻度
    for i in range(7):
        xv = x_max * i / 6.0
        xx = X(xv)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#CBD5E1" stroke-width="1"/>'
                   % (xx, mt + ph, xx, mt + ph + 4))
        out.append('<text x="%.1f" y="%d" font-size="11" fill="#64748B" text-anchor="middle">%s</text>'
                   % (xx, mt + ph + 18, _xlabel(xv)))

    # 轴名
    out.append('<text x="%d" y="%d" font-size="11.5" fill="#475569" text-anchor="middle">%s</text>'
               % (ml + pw // 2, height - 8, "相对时间"))
    out.append('<text transform="translate(16,%.1f) rotate(-90)" font-size="11.5" fill="#475569" '
               'text-anchor="middle">%s</text>' % (mt + ph / 2.0, _esc(y_title)))
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------
# 关键发现
# --------------------------------------------------------------------------
def _findings(analysis, meta):
    cpu, mem, rel = analysis["cpu"], analysis["mem"], analysis["release"]
    out = []
    cores = max(1, int(meta.get("cores") or 1))

    if cpu.get("avg") is not None:
        out.append("CPU 平均 <b>%.1f%%</b>（约 %.2f 个核持续满载），P95 <b>%.1f%%</b>，峰值 <b>%.1f%%</b>"
                   "（%s），按 %d 逻辑处理器折算。"
                   % (cpu["avg"], cpu["avg"] / 100.0 * cores, cpu["p95"], cpu["max"],
                      fmt_clock(cpu.get("max_ts")), cores))
        if cpu["longest_80_s"] > 0:
            out.append("监控期内有 <b>%s</b> 处于 ≥80%% 高占用，最长连续 <b>%s</b>%s。"
                       % (fmt_dur(cpu["above_80_total_s"]), fmt_dur(cpu["longest_80_s"]),
                          "，已超过持续红线" if cpu["longest_80_s"] > 30 else "，未触及持续红线（30 秒）"))
        else:
            out.append("监控期内 CPU 未出现 ≥80% 的高占用区间。")

    if mem.get("baseline_mb") is not None:
        out.append("私有工作集从基线 <b>%.1f MB</b>（前 60 秒中位数）涨到峰值 <b>%.1f MB</b>"
                   "（%s，占物理内存 %.1f%%），结束时 <b>%.1f MB</b>，较基线 <b>%+.1f%%</b>。"
                   % (mem["baseline_mb"], mem["peak_mb"], fmt_clock(mem.get("peak_at")),
                      mem["peak_pct"], mem["end_mb"], mem["growth_pct"]))
        out.append("内存增长斜率 <b>%+.2f MB/min</b>（线性拟合 R²=%.3f）%s。"
                   % (mem["slope"], mem["r2"],
                      "，接近线性增长，需警惕" if (mem["r2"] >= 0.7 and mem["slope"] > 3) else "，趋势不明显"))

    if rel.get("count"):
        e = rel["events"][0]
        out.append("检出 <b>%d 次</b>有效内存释放，首次从 <b>%.1f MB</b> 回落到 <b>%.1f MB</b>"
                   "（降幅 %.1f MB，历时 %s）。"
                   % (rel["count"], e["peak_mb"], e["trough_mb"], e["drop_mb"], fmt_dur(e["duration_s"])))
    else:
        out.append("监控期内<b>未检出</b>有效内存释放事件（判定门槛：跌幅 ≥ max(%.0f MB, 基线 %.0f%%) 且回落到基线 +%.0f%% 带内）。"
                   % (50, 5, 15))

    dts = [s.dt_ms for s in meta.get("_samples", []) if getattr(s, "dt_ms", None)]
    if dts:
        avg_dt = sum(dts) / len(dts) / 1000.0
        out.append("采样质量：平均间隔 <b>%.2f 秒</b>（目标 %.0f 秒），最大间隔 <b>%.2f 秒</b>，"
                   "共 <b>%d</b> 条样本。" % (avg_dt, meta.get("interval", 2), max(dts) / 1000.0,
                                            len(meta.get("_samples", []))))
    return out


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
def _verdict_cards(a):
    cpu, mem, rel = a["cpu"], a["mem"], a["release"]
    cards = []

    fg, bg, bd = LEVEL_COLOR.get(cpu["verdict"], LEVEL_COLOR["unknown"])
    cards.append((
        "CPU 占用", LEVEL_TEXT.get(cpu["verdict"], "—"), fg, bg, bd,
        "均值 %s%% · P95 %s%% · 峰值 %s%%" % (_fmt(cpu.get("avg"), 1), _fmt(cpu.get("p95"), 1),
                                            _fmt(cpu.get("max"), 1)),
        "标准：均值 ≤50%，P95 ≤70%，峰值 ≤90%，≥80% 连续 ≤30 秒",
    ))

    fg, bg, bd = LEVEL_COLOR.get(mem["verdict"], LEVEL_COLOR["unknown"])
    peak_txt = ("%s MB（%.1f%% 内存）" % (_fmt(mem.get("peak_mb"), 1), mem.get("peak_pct") or 0)
                if mem.get("peak_mb") is not None else "无数据")
    cards.append((
        "内存占用", LEVEL_TEXT.get(mem["verdict"], "—"), fg, bg, bd,
        "峰值 %s · 期末较基线 %s%%" % (peak_txt, _fmt(mem.get("growth_pct"), 1)),
        "标准：峰值 ≤80% 物理内存，期末较基线增长 ≤20%",
    ))

    fg, bg, bd = LEVEL_COLOR.get(rel["verdict"], LEVEL_COLOR["unknown"])
    cards.append((
        "内存释放趋势", LEVEL_TEXT.get(rel["verdict"], "—"), fg, bg, bd,
        rel.get("label") or "—",
        "标准：有效释放 ≥1 次且整体不上移，斜率 ≤3 MB/min",
    ))
    return cards


def write_html(path, samples, meta, analysis, thresholds, sysinfo, names):
    a = analysis
    cpu, mem, rel = a["cpu"], a["mem"], a["release"]
    fg, bg, bd = LEVEL_COLOR.get(a["overall"], LEVEL_COLOR["unknown"])

    parts = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
             "<title>性能监控报告 · %s</title>" % _esc(meta.get("target")),
             "<style>%s</style></head><body><div class=\"wrap\">" % CSS]

    # 头部
    parts.append('<div class="card head"><h1>进程性能监控报告</h1>')
    parts.append('<div class="sub">%s · %s 至 %s</div>'
                 % (_esc(meta.get("target")), _esc(meta.get("started_at_text")),
                    _esc(meta.get("finished_at_text"))))
    parts.append('<div class="meta">')
    for k, v in [
        ("监控时长", meta.get("duration_text")),
        ("样本条数", "%d 条 / 间隔 %.0f 秒" % (meta.get("sample_count", 0), meta.get("interval", 2))),
        ("PID 集合", ", ".join(str(p) for p in (meta.get("pids") or [])) or "—"),
        ("逻辑处理器", "%s 核" % sysinfo.get("cores")),
        ("物理内存", "%.1f GB" % (sysinfo.get("total_phys_mb", 0) / 1024.0)),
        ("操作系统", "%s Build %s" % (sysinfo.get("os_name"), sysinfo.get("os_build"))),
        ("内存口径", "私有工作集" if (meta.get("mem_source") or "private") == "private" else "工作集"),
        ("工具版本", VERSION),
    ]:
        parts.append("<div>%s<b>%s</b></div>" % (_esc(k), _esc(v)))
    parts.append("</div></div>")

    # 综合结论
    parts.append('<div class="card"><h2>综合结论</h2>')
    parts.append('<div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">')
    parts.append('<span class="verdict" style="color:%s;background:%s;border:1px solid %s">%s</span>'
                 % (fg, bg, bd, LEVEL_TEXT.get(a["overall"], "—")))
    parts.append('<span class="sub">综合判定取 CPU、内存占用、内存释放趋势三项中最严的一档</span></div>')
    parts.append('<ul class="kf">')
    for f in _findings(a, dict(meta, _samples=samples)):
        parts.append("<li>%s</li>" % f)
    parts.append("</ul></div>")

    # 三张判定卡
    parts.append('<div class="cards">')
    for title, level_text, c_fg, c_bg, c_bd, detail, std in _verdict_cards(a):
        parts.append('<div class="vcard" style="border-top-color:%s">' % c_fg)
        parts.append('<div class="t">%s</div>' % title)
        parts.append('<div class="v" style="color:%s">%s</div>' % (c_fg, level_text))
        parts.append('<div class="d">%s</div>' % _esc(detail))
        parts.append('<div class="sub" style="font-size:11.5px;margin-top:6px">%s</div>' % _esc(std))
        parts.append("</div>")
    parts.append("</div>")

    # 时序图
    parts.append('<div class="card"><h2>时序趋势</h2>')
    cpu_max = min(100, max(10, int(math.ceil((cpu.get("max") or 0) * 1.15 / 10.0)) * 10))
    parts.append("<h3>CPU 占用率（%%）%s</h3>"
                 % ("" if cpu_max >= 80 else
                    '<span class="sub">纵轴按实测峰值缩放（0–%d%%），80%% 告警线在图上之外</span>'
                    % cpu_max))
    parts.append(svg_chart(samples, lambda s: s.cpu_pct, "#2563EB", "CPU 占用率 (%)",
                           cpu_max, threshold=80.0, threshold_label="告警线 80%"))
    mem_vals = [s.priv_mb for s in samples if s.priv_mb]
    mem_low = min(mem_vals) if mem_vals else 0.0
    mem_peak = mem.get("peak_mb") or 100.0
    mem_top = max(200.0, math.ceil(mem_peak * 1.08 / 100.0) * 100.0)
    # 内存波动往往只有十几 MB：整轴从 0 起会把曲线压成一条贴顶直线。
    # 仅当峰值与最低值之差不足轴长一半时才截掉下方空白，并在标题旁注明起始值。
    mem_floor = 0.0
    if mem_low > 300 and (mem_top - mem_low) < mem_top * 0.5:
        mem_floor = max(0.0, math.floor(mem_low * 0.9 / 100.0) * 100.0)
    parts.append("<h3>私有工作集（MB）%s</h3>"
                 % ("" if not mem_floor else
                    '<span class="sub">纵轴自 %.0f MB 起（为看清波动，非零起点）</span>' % mem_floor))
    parts.append(svg_chart(samples, lambda s: s.priv_mb, "#EA580C", "私有工作集 (MB)",
                           mem_top, y_min=mem_floor, ref_line=mem.get("baseline_mb"),
                           ref_label="基线 %.1f MB" % (mem.get("baseline_mb") or 0),
                           unit=" MB"))
    parts.append('<div class="note">灰线为基线（前 60 秒中位数）；橙色圆点为监控期峰值。'
                 "若曲线在峰值后持续回落至基线附近，说明内存被正常回收；"
                 "若持续上移且斜率与 R² 同时偏高，则应视为疑似泄漏。</div></div>")

    # CPU 明细
    parts.append('<div class="card"><h2>CPU 明细</h2><table><thead><tr>'
                 "<th>指标</th><th>标准</th><th class=\"num\">实测</th><th>结论</th></tr></thead><tbody>")
    for m in cpu.get("metrics", []):
        f2, b2, _ = LEVEL_COLOR.get(m["level"], LEVEL_COLOR["unknown"])
        parts.append("<tr><td>%s</td><td>%s</td><td class=\"num\">%s</td>"
                     "<td style=\"color:%s;font-weight:600\">%s</td></tr>"
                     % (_esc(m["name"]), _esc(m["standard"]), _esc(m["actual"]), f2,
                        LEVEL_TEXT.get(m["level"], "—")))
    parts.append("</tbody></table>")
    parts.append('<div class="note">等效核数 = CPU% ÷ 100 × 逻辑处理器数，用来看「相当于占满几个核」。'
                 "累计 CPU 时间可在任务管理器「详细信息 → CPU 时间」列逐项对照。</div></div>")

    # 内存明细
    parts.append('<div class="card"><h2>内存明细</h2><table><thead><tr>'
                 "<th>指标</th><th>标准</th><th class=\"num\">实测</th><th>结论</th></tr></thead><tbody>")
    for m in mem.get("metrics", []):
        f2, b2, _ = LEVEL_COLOR.get(m["level"], LEVEL_COLOR["unknown"])
        parts.append("<tr><td>%s</td><td>%s</td><td class=\"num\">%s</td>"
                     "<td style=\"color:%s;font-weight:600\">%s</td></tr>"
                     % (_esc(m["name"]), _esc(m["standard"]), _esc(m["actual"]), f2,
                        LEVEL_TEXT.get(m["level"], "—")))
    parts.append("</tbody></table></div>")

    # 释放事件
    parts.append('<div class="card"><h2>内存释放事件</h2>')
    if rel.get("events"):
        parts.append('<table><thead><tr><th>#</th><th>峰值时间</th><th class="num">峰值(MB)</th>'
                     "<th>谷值时间</th><th class=\"num\">谷值(MB)</th><th class=\"num\">降幅(MB)</th>"
                     "<th class=\"num\">跌幅</th><th class=\"num\">历时</th></tr></thead><tbody>")
        for i, e in enumerate(rel["events"], 1):
            parts.append('<tr><td>%d</td><td>%s</td><td class="num">%.1f</td><td>%s</td>'
                         '<td class="num">%.1f</td><td class="num">%.1f</td><td class="num">%.1f%%</td>'
                         '<td class="num">%s</td></tr>'
                         % (i, fmt_clock(e.get("peak_ts")), e["peak_mb"], fmt_clock(e.get("trough_ts")),
                            e["trough_mb"], e["drop_mb"], e.get("drop_pct") or 0,
                            fmt_dur(e.get("duration_s") or 0)))
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="note">本次监控未检出满足门槛的释放事件。'
                     "这不必然等于泄漏——短时监控、缓存持续预热、或进程只在退出时才归还内存，"
                     "都可能表现为「只涨不落」。建议延长监控时长（≥10 分钟）复测。</div>")
    parts.append('<div class="note">趋势判定：<b>%s</b>。' % _esc(rel.get("label")))
    parts.append("；".join(_esc(r) for r in rel.get("reasons") or []) + "</div></div>")

    # 采样质量
    dts = [s.dt_ms for s in samples if getattr(s, "dt_ms", None)]
    if dts:
        parts.append('<div class="card"><h2>采样质量</h2><table><thead><tr>'
                     "<th>项</th><th class=\"num\">值</th></tr></thead><tbody>")
        rows = [
            ("平均采样间隔", "%.3f 秒（目标 %.0f 秒）" % (sum(dts) / len(dts) / 1000.0, meta.get("interval", 2))),
            ("最大采样间隔", "%.3f 秒" % (max(dts) / 1000.0)),
            ("最小采样间隔", "%.3f 秒" % (min(dts) / 1000.0)),
            ("节拍偏差（平均）", "%+.0f 毫秒" % (sum(dts) / len(dts) - meta.get("interval", 2) * 1000)),
            ("样本条数", "%d 条" % len(samples)),
        ]
        for k, v in rows:
            parts.append("<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (k, _esc(v)))
        parts.append("</tbody></table></div>")

    # 附录
    parts.append('<div class="card"><h2>附录：口径与阈值</h2>')
    parts.append('<ul class="kf">')
    for t in [
        "CPU 占用率 = 本区间 CPU 时间 ÷ 本区间实际间隔 ÷ 逻辑处理器数 × 100（与任务管理器同口径）。",
        "首行样本没有前一帧，CPU 占用率记为「—」；暂停期间不采样，恢复后首行备注标注暂停时长。",
        "内存取私有工作集，即任务管理器「内存」列口径（Win10 1809 起 / Win11）。",
        "内存占用率 = 私有工作集 ÷ 物理内存总量；任务管理器不提供单进程内存百分比，按整机占比口径计算。",
        "数值与任务管理器抽检容差：CPU ≤2 个百分点，内存 ≤1% 或 ≤2 MB（10 次抽检 ≥9 次达标）。",
    ]:
        parts.append("<li>%s</li>" % _esc(t))
    parts.append("</ul>")
    th = thresholds
    parts.append('<table style="margin-top:12px"><thead><tr><th>阈值项</th><th>取值</th></tr></thead><tbody>')
    for k, v in [
        ("CPU 均值", "≤ %.0f%%，> %.0f%% 不通过" % (th["cpu"]["avg"], th["cpu"]["avg_fail"])),
        ("CPU P95", "≤ %.0f%%，> %.0f%% 不通过" % (th["cpu"]["p95"], th["cpu"]["p95_fail"])),
        ("CPU 峰值", "≤ %.0f%%，> %.0f%% 不通过" % (th["cpu"]["peak"], th["cpu"]["peak_fail"])),
        ("CPU 持续", "≥ %.0f%% 连续 ≤ %.0f 秒" % (th["cpu"]["sustained_threshold"], th["cpu"]["sustained_s"])),
        ("内存峰值", "≤ %.0f%%，> %.0f%% 不通过" % (th["mem"]["peak_percent"], th["mem"]["peak_percent_fail"])),
        ("内存增长", "期末较基线 ≤ %.0f%%" % th["mem"]["growth_percent"]),
        ("斜率上限", "%.1f MB/min；> %.1f 且 R²≥0.7 判泄漏" % (
            th["release"]["slope_mb_per_min"], th["release"]["leak_slope_mb_per_min"])),
        ("释放门槛", "跌幅 ≥ max(%.0f MB, 基线 %.0f%%)，回落到基线 +%.0f%% 内" % (
            th["release"]["min_drop_mb"], th["release"]["min_drop_percent"],
            th["release"]["recover_band_percent"])),
    ]:
        parts.append("<tr><td>%s</td><td>%s</td></tr>" % (_esc(k), _esc(v)))
    parts.append("</tbody></table>")

    parts.append('<div class="note">产物清单：<span class="mono">%s.xlsx</span>（原始数据与图表）、'
                 '<span class="mono">%s.html</span>（本报告）、<span class="mono">%s.md</span>（摘要）、'
                 '<span class="mono">meta.json</span>（采集元数据）。</div></div>'
                 % (_esc(names["excel"]), _esc(names["html"]), _esc(names["md"])))

    parts.append('<div class="foot">由 win-proc-monitor %s 生成 · %s</div>'
                 % (VERSION, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    parts.append("</div></body></html>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path


# --------------------------------------------------------------------------
# Markdown 摘要
# --------------------------------------------------------------------------
def write_markdown(path, samples, meta, analysis, thresholds, sysinfo, excel_name, html_name):
    a = analysis
    cpu, mem, rel = a["cpu"], a["mem"], a["release"]
    L = []
    L.append("# 性能监控报告 · %s\n" % meta.get("target"))
    L.append("- 监控时间：%s 至 %s（%s）" % (meta.get("started_at_text"), meta.get("finished_at_text"),
                                          meta.get("duration_text")))
    L.append("- 采样：%d 条 / 间隔 %.0f 秒 · PID：%s" % (
        len(samples), meta.get("interval", 2),
        ", ".join(str(p) for p in (meta.get("pids") or [])) or "—"))
    L.append("- 环境：%s Build %s · %s 核 · %.1f GB 内存" % (
        sysinfo.get("os_name"), sysinfo.get("os_build"), sysinfo.get("cores"),
        (sysinfo.get("total_phys_mb") or 0) / 1024.0))
    L.append("\n## 综合结论：**%s**\n" % LEVEL_TEXT.get(a["overall"], "—"))
    L.append("| 判定项 | 结论 | 关键实测 |")
    L.append("|---|---|---|")
    L.append("| CPU 占用 | %s | 均值 %s%%，P95 %s%%，峰值 %s%% |" % (
        LEVEL_TEXT.get(cpu["verdict"], "—"), _fmt(cpu.get("avg")), _fmt(cpu.get("p95")),
        _fmt(cpu.get("max"))))
    L.append("| 内存占用 | %s | 峰值 %s MB（%.1f%%），期末 %s MB（%+.1f%%） |" % (
        LEVEL_TEXT.get(mem["verdict"], "—"), _fmt(mem.get("peak_mb")), mem.get("peak_pct") or 0,
        _fmt(mem.get("end_mb")), mem.get("growth_pct") or 0))
    L.append("| 内存释放趋势 | %s | %s，斜率 %+.2f MB/min，R²=%.2f |" % (
        LEVEL_TEXT.get(rel["verdict"], "—"), rel.get("label"), mem.get("slope") or 0,
        mem.get("r2") or 0))

    L.append("\n## 关键数据\n")
    L.append("**CPU**：≥80%% 累计 %s，最长连续 %s（红线 30 秒）%s。" % (
        fmt_dur(cpu.get("above_80_total_s")), fmt_dur(cpu.get("longest_80_s")),
        "，已超红线" if (cpu.get("longest_80_s") or 0) > 30 else ""))
    if mem.get("baseline_mb") is not None:
        L.append("\n**内存**：基线 %.1f MB → 峰值 %.1f MB（%s）→ 期末 %.1f MB；斜率 %+.2f MB/min，R²=%.3f。"
                 % (mem["baseline_mb"], mem["peak_mb"], fmt_clock(mem.get("peak_at")),
                    mem["end_mb"], mem["slope"], mem["r2"]))
    L.append("\n**释放**：%s。%s" % (rel.get("label"), "；".join(rel.get("reasons") or [])))

    L.append("\n## 判定明细\n")
    L.append("| 判定项 | 标准 | 实测 | 结论 |")
    L.append("|---|---|---|---|")
    for block in (cpu, mem):
        for m in block.get("metrics", []):
            L.append("| %s | %s | %s | %s |" % (m["name"], m["standard"], m["actual"],
                                                LEVEL_TEXT.get(m["level"], "—")))

    if rel.get("events"):
        L.append("\n## 内存释放事件\n")
        L.append("| # | 峰值时间 | 峰值(MB) | 谷值时间 | 谷值(MB) | 降幅(MB) | 历时 |")
        L.append("|---|---|---|---|---|---|---|")
        for i, e in enumerate(rel["events"], 1):
            L.append("| %d | %s | %.1f | %s | %.1f | %.1f | %s |" % (
                i, fmt_clock(e.get("peak_ts")), e["peak_mb"], fmt_clock(e.get("trough_ts")),
                e["trough_mb"], e["drop_mb"], fmt_dur(e.get("duration_s") or 0)))

    L.append("\n## 建议\n")
    advice = []
    if cpu["verdict"] in ("warn", "fail"):
        advice.append("CPU 存在超标项：结合「01_原始数据」中 CPU 占用率最高的时段，"
                      "对照该时段的操作/接口调用定位热点，必要时做采样分析（profiler）。")
    if mem["verdict"] in ("warn", "fail"):
        advice.append("内存占用已接近或超过标准：先确认是否为缓存预热（重启后复测），"
                      "若重启即复现且持续上移，按泄漏方向排查。")
    if rel["verdict"] == "fail":
        advice.append("未观察到有效释放且持续上移：建议把监控时长延长到 ≥10 分钟，"
                      "并做「空闲静置 vs 反复操作」对比，确认是缓存增长还是真实泄漏。")
    if not advice:
        if rel["verdict"] == UNKNOWN:
            advice.append("本次样本量不足以判定内存释放趋势：建议把监控时长延长到 ≥2 分钟"
                          "（间隔 2 秒时约 60 条样本），再复测一次以观察峰值后是否回落。")
        elif rel["verdict"] == "warn":
            advice.append("CPU 与内存占用在标准内，但内存释放趋势为「关注」（%s，斜率 %+.2f MB/min）。"
                          "建议延长到 ≥10 分钟，并做「空闲静置 vs 反复操作」对比，"
                          "确认是缓存自然增长还是真实泄漏。" % (rel.get("label") or "未见有效释放",
                                                                mem.get("slope") or 0.0))
        else:
            label = rel.get("label") or ""
            tail = "内存全程平稳、无增长压力" if ("稳定" in label or "平稳" in label) \
                else "且内存有正常回落"
            advice.append("本次监控未发现异常：CPU 与内存在标准内，%s。"
                          "建议在更长时长（≥30 分钟）与高负载业务路径下复测一次，覆盖更多场景。" % tail)
    for i, t in enumerate(advice, 1):
        L.append("%d. %s" % (i, t))

    L.append("\n## 产物\n")
    L.append("- [%s](%s) — 原始数据（5 个 sheet，含图表）" % (excel_name, excel_name))
    L.append("- [%s](%s) — 完整报告（可直接打印为 PDF）" % (html_name, html_name))
    L.append("- meta.json — 采集元数据与阈值快照")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


# --------------------------------------------------------------------------
def write_reports(out_dir, samples, meta, analysis, thresholds, sysinfo, names=None):
    names = names or {"excel": "01_原始数据", "html": "02_性能报告", "md": "03_性能报告摘要"}
    html_path = os.path.join(out_dir, "%s.html" % names["html"])
    md_path = os.path.join(out_dir, "%s.md" % names["md"])
    write_html(html_path, samples, meta, analysis, thresholds, sysinfo, names)
    write_markdown(md_path, samples, meta, analysis, thresholds, sysinfo,
                   "%s.xlsx" % names["excel"], "%s.html" % names["html"])
    return html_path, md_path
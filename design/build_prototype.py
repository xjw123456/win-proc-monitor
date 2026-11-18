# -*- coding: utf-8 -*-
"""原型图生成器（评审用，不是成品实现）。

一次性生成三张评审稿：
  proto/main.html   主界面
  proto/excel.html  Excel 数据表结构
  proto/report.html 性能分析报告结构
三张图使用同一份示例数据，保证数字互相一致。
"""
import math
import os
import random
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(HERE, "proto")
os.makedirs(PROTO, exist_ok=True)

# ---------------------------------------------------------------- 示例数据
random.seed(20261118)
N, STEP = 120, 2                       # 120 个采样点，2 s 一点
from datetime import datetime
START = datetime(2026, 11, 18, 19, 30, 14)
CORES, RAM_MB = 16, 16384
THREAD_BASE, HANDLE_BASE = 86, 1420

cpu, mem = [], []
for i in range(N):
    v = 14.0 + 3.2 * math.sin(i / 10.0) + random.uniform(-1.5, 1.5)
    if 6 <= i <= 13:
        v += 30.0
    if 50 <= i <= 56:
        v += 16.0
    if 70 <= i <= 73:
        v += 74.0
    if 78 <= i <= 92:
        v += 36.0
    cpu.append(max(1.5, min(96.0, v)))


def mem_seg(i):
    if i <= 8:
        return 380.0 + 0.45 * i
    if i <= 54:
        return 383.6 + 3.4 * (i - 8)
    if i <= 58:
        return 540.0 - (540.0 - 398.0) * (i - 54) / 4.0
    if i <= 99:
        return 398.0 + 1.3 * (i - 58)
    if i <= 104:
        return 451.3 - (451.3 - 392.0) * (i - 99) / 5.0
    return 392.0 + 0.25 * (i - 104)


for i in range(N):
    mem.append(mem_seg(i) + random.uniform(-2.0, 2.0))


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def pct(vals, p):
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(math.ceil(p / 100.0 * len(s))) - 1))
    return s[k]


def max_run(vals, limit):
    best = cur = 0
    for v in vals:
        if v >= limit:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best * STEP


def linreg(vals):
    n = len(vals)
    xs = list(range(n))
    mx = sum(xs) / float(n)
    my = sum(vals) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((xs[i] - mx) * (vals[i] - my) for i in range(n))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((v - my) ** 2 for v in vals)
    ss_res = sum((vals[i] - (a + b * xs[i])) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return b, r2


avg_cpu = sum(cpu) / N
p95_cpu = pct(cpu, 95)
max_cpu = max(cpu)
imax_cpu = cpu.index(max_cpu)
run80 = max_run(cpu, 80.0)
cpu_total_ms = sum(v / 100.0 * STEP * 1000 * CORES for v in cpu)
cores_eq = avg_cpu / 100.0 * CORES

mem_base = median(mem[:15])
mem_peak = max(mem)
imax_mem = mem.index(mem_peak)
mem_end = mem[-1]
mem_avg = sum(mem) / N
slope_per_sample, mem_r2 = linreg(mem)
slope_min = slope_per_sample * (60.0 / STEP)

RELEASES = [(54, 58), (99, 104)]


def fmt_hms(ms):
    total = ms / 1000.0
    h = int(total // 3600)
    m = int(total % 3600 // 60)
    s = total % 60
    return "%d:%02d:%04.1f" % (h, m, s)


def cpu_verdict():
    if avg_cpu > 70 or p95_cpu > 85 or max_cpu > 95 or run80 > 120:
        return "不通过"
    if avg_cpu > 50 or p95_cpu > 70 or max_cpu > 90 or run80 > 30:
        return "关注"
    return "通过"


def mem_verdict():
    grew = (mem_end - mem_base) / mem_base * 100.0
    if slope_min > 5 and mem_r2 > 0.7 and not RELEASES:
        return "不通过"
    if grew > 20 or slope_min > 3:
        return "关注"
    return "通过"


CPU_VERDICT = cpu_verdict()
MEM_VERDICT = mem_verdict()
RANK = {"通过": 0, "关注": 1, "不通过": 2}
OVERALL = max(CPU_VERDICT, MEM_VERDICT, key=lambda x: RANK[x])

VCOLOR = {"通过": ("#107c10", "#e8f5e9"), "关注": ("#b26a00", "#fff4e5"), "不通过": ("#c62828", "#fdecea")}

TIMES = [START + timedelta(seconds=STEP * i) for i in range(N)]
END = TIMES[-1]
DURATION = STEP * (N - 1)


# ---------------------------------------------------------------- SVG 图表
SVG_STYLE = (
    "<defs><style>"
    ".ax{font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;font-size:10px;fill:#8a96a3}"
    ".lb{font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;font-size:10.5px;fill:#4b5563}"
    ".lb2{font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;font-size:10px;fill:#8a96a3}"
    "</style></defs>"
)


def chart(W, H, live=False, mem_peak_marks=False, release_marks=False, baseline=False):
    pl, pr, pt, pb = 46, 60, 20, 30
    pw, ph = W - pl - pr, H - pt - pb

    def X(i):
        return pl + pw * i / (N - 1.0)

    def YL(v):
        return pt + ph * (1 - v / 100.0)

    def YR(v):
        return pt + ph * (1 - v / 700.0)

    o = ["<svg viewBox='0 0 %d %d' width='%d' height='%d' style='display:block'>" % (W, H, W, H), SVG_STYLE]
    o.append("<rect x='%d' y='%d' width='%d' height='%d' fill='#fcfdff'/>" % (pl, pt, pw, ph))
    for k in range(5):
        y = pt + ph * k / 4.0
        o.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e9eef4'/>" % (pl, y, pl + pw, y))
        o.append("<text x='%d' y='%.1f' text-anchor='end' class='ax'>%d</text>" % (pl - 8, y + 3.5, 100 - 25 * k))
        o.append("<text x='%d' y='%.1f' class='ax'>%d</text>" % (pl + pw + 8, y + 3.5, 700 - 175 * k))
    for i in (0, 30, 60, 90, 119):
        xx = X(i)
        o.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#eef3f8'/>" % (xx, pt, xx, pt + ph))
        o.append("<text x='%.1f' y='%d' text-anchor='middle' class='ax'>%d:%02d</text>"
                 % (xx, pt + ph + 17, (i * STEP) // 60, (i * STEP) % 60))
    # 阈值线
    y80 = YL(80)
    o.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#d95c5c' stroke-width='1.2' stroke-dasharray='5 4'/>"
             % (pl, y80, pl + pw, y80))
    o.append("<text x='%d' y='%.1f' text-anchor='end' class='lb2' fill='#c0504d'>阈值 80%%</text>"
             % (pl + pw - 6, y80 - 6))
    if baseline:
        yb = YR(mem_base)
        o.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#7b8794' stroke-width='1.1' stroke-dasharray='6 4'/>"
                 % (pl, yb, pl + pw, yb))
        o.append("<text x='%d' y='%.1f' class='lb2'>基线 %d MB</text>" % (pl + 8, yb - 6, round(mem_base)))
    # 内存
    mem_pts = " ".join("%.1f,%.1f" % (X(i), YR(mem[i])) for i in range(N))
    o.append("<polygon points='%d,%.1f %s %d,%.1f' fill='#e8a33d' opacity='.10'/>"
             % (pl, pt + ph, mem_pts, pl + pw, pt + ph))
    o.append("<polyline points='%s' fill='none' stroke='#d98a1f' stroke-width='2' stroke-linejoin='round'/>" % mem_pts)
    # CPU
    cpu_pts = " ".join("%.1f,%.1f" % (X(i), YL(cpu[i])) for i in range(N))
    o.append("<polygon points='%d,%.1f %s %d,%.1f' fill='#0f6cbd' opacity='.07'/>"
             % (pl, pt + ph, cpu_pts, pl + pw, pt + ph))
    o.append("<polyline points='%s' fill='none' stroke='#0f6cbd' stroke-width='2.2' stroke-linejoin='round'/>" % cpu_pts)
    # 峰值标注
    if mem_peak_marks:
        for idx in (imax_mem,) + tuple(p for p, _ in RELEASES):
            v = mem[idx]
            label = "峰值 %d MB" % round(v) if idx == imax_mem else "峰 %d MB" % round(v)
            o.append("<circle cx='%.1f' cy='%.1f' r='3.4' fill='#fff' stroke='#d98a1f' stroke-width='2'/>"
                     % (X(idx), YR(v)))
            o.append("<text x='%.1f' y='%.1f' text-anchor='middle' class='lb' fill='#a5651a'>%s</text>"
                     % (X(idx), YR(v) - 12, label))
    if release_marks:
        for peak, trough in RELEASES:
            o.append("<circle cx='%.1f' cy='%.1f' r='3.4' fill='#fff' stroke='#2e7d32' stroke-width='2'/>"
                     % (X(trough), YR(mem[trough])))
            o.append("<text x='%.1f' y='%.1f' text-anchor='middle' class='lb' fill='#2e7d32'>释放 -%d MB</text>"
                     % (X(trough), YR(mem[trough]) + 16, round(mem[peak] - mem[trough])))
    if live:
        o.append("<circle cx='%.1f' cy='%.1f' r='3.2' fill='#0f6cbd'/>" % (X(N - 1), YL(cpu[-1])))
    o.append("<text x='%d' y='%d' class='ax'>CPU %%</text>" % (pl - 34, pt - 7))
    o.append("<text x='%d' y='%d' text-anchor='end' class='ax'>内存 MB</text>" % (pl + pw + 46, pt - 7))
    o.append("</svg>")
    return "\n".join(o)


def spark(vals, w=132, h=30, color="#0f6cbd"):
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    pts = " ".join("%.1f,%.1f" % (w * i / (len(vals) - 1.0), h - 3 - (v - lo) / rng * (h - 6))
                  for i, v in enumerate(vals))
    return ("<svg viewBox='0 0 %d %d' width='%d' height='%d'><polyline points='%s' fill='none' "
            "stroke='%s' stroke-width='1.4' opacity='.75'/></svg>" % (w, h, w, h, pts, color))


# ---------------------------------------------------------------- 页面 1：主界面
MAIN_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;color:#1f2328;
     background:radial-gradient(1100px 620px at 18% 8%,#eef6fd 0%,#d7e3ee 46%,#bfcedd 100%);
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;
     -webkit-font-smoothing:antialiased}
.win{width:1296px;background:#f7f8fa;border-radius:12px;overflow:hidden;display:flex;flex-direction:column;
     box-shadow:0 34px 80px rgba(12,32,56,.34),0 2px 6px rgba(12,32,56,.18);border:1px solid rgba(255,255,255,.65)}
.tbar{height:40px;background:#fff;border-bottom:1px solid #e6e9ee;display:flex;align-items:center;
      padding:0 8px 0 16px;gap:9px;flex:0 0 auto}
.logo{width:20px;height:20px;border-radius:5px;background:linear-gradient(135deg,#1d7fd4,#0b4f8a);color:#fff;
      font-size:12px;display:flex;align-items:center;justify-content:center}
.ttl{font-size:13px;font-weight:600}
.ver{font-size:10.5px;color:#8a96a3;border:1px solid #e2e6ec;border-radius:4px;padding:1px 5px}
.tag-proto{font-size:10.5px;color:#8a6d1f;background:#fdf3d8;border:1px solid #f0dfae;border-radius:10px;padding:2px 8px;margin-left:4px}
.grow{flex:1}
.wbtn{width:40px;height:30px;display:flex;align-items:center;justify-content:center;color:#5b6672;font-size:12px;border-radius:6px}
.wbtn.x:hover{background:#e81123;color:#fff}
.content{display:flex;flex-direction:column;gap:10px;padding:12px 16px 10px}
.row{display:flex;align-items:center;gap:10px}
.lbl{font-size:12px;color:#5b6672}
.combo{height:36px;min-width:430px;background:#fff;border:1px solid #d6dce4;border-radius:8px;display:flex;
       align-items:center;gap:9px;padding:0 10px;box-shadow:0 1px 2px rgba(16,32,56,.05)}
.combo b{font-size:13px}
.combo .muted{font-size:11.5px}
.caret{margin-left:auto;color:#8a96a3;font-size:10px}
.dot{width:7px;height:7px;border-radius:50%;background:#2e9e4f;box-shadow:0 0 0 3px #e4f4e8}
.btn{height:34px;border:1px solid #d6dce4;background:#fff;border-radius:8px;font-family:inherit;font-size:12.5px;
     color:#24313f;display:inline-flex;align-items:center;gap:7px;padding:0 13px;box-shadow:0 1px 2px rgba(16,32,56,.05)}
.btn.primary{background:linear-gradient(180deg,#1a7fd1,#0f68b4);border-color:#0d5c9f;color:#fff;font-weight:600;
             box-shadow:0 2px 6px rgba(15,104,180,.32)}
.btn.primary.dis{background:#e9edf2;border-color:#e0e5ec;color:#a3adb8;box-shadow:none;font-weight:500}
.btn.link{border:none;background:none;color:#0f6cbd;box-shadow:none;padding:0 4px}
.btn .ico{font-size:11px}
.seg{display:flex;background:#eef2f6;border-radius:7px;padding:2px;gap:2px}
.seg span{font-size:11.5px;padding:4px 9px;border-radius:5px;color:#5b6672}
.seg span.on{background:#fff;color:#0f6cbd;font-weight:600;box-shadow:0 1px 2px rgba(16,32,56,.12)}
.chip{font-size:12px;background:#eef6ff;color:#0f6cbd;border:1px solid #cfe4f8;border-radius:6px;padding:4px 9px;font-weight:600}
.tiny{font-size:10.5px;color:#98a3ae}
.divider{width:1px;height:22px;background:#e2e7ed}
.state{display:flex;align-items:center;gap:10px;padding-left:2px}
.pill{font-size:11.5px;border-radius:20px;padding:3px 10px;background:#e8f5eb;color:#1f7a3a;font-weight:600}
.mono{font-family:"Cascadia Mono",Consolas,monospace;font-size:13px;font-weight:600;color:#24313f}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.card{position:relative;background:#fff;border:1px solid #e6e9ee;border-radius:10px;padding:11px 13px;height:98px;
      box-shadow:0 1px 2px rgba(16,32,56,.04);overflow:hidden}
.ch{font-size:11.5px;color:#6b7683;display:flex;align-items:center;gap:6px}
.ch .hint{font-size:10px;color:#9aa5b1;background:#f2f5f8;border-radius:4px;padding:1px 5px}
.cv{font-size:26px;font-weight:600;letter-spacing:-.4px;margin-top:5px;line-height:1.05}
.cv .u{font-size:13px;font-weight:500;color:#6b7683;margin-left:3px}
.cs{font-size:10.5px;color:#8a96a3;margin-top:5px}
.spark{position:absolute;right:8px;bottom:8px;opacity:.9}
.panel{background:#fff;border:1px solid #e6e9ee;border-radius:10px;box-shadow:0 1px 2px rgba(16,32,56,.04)}
.ph{height:32px;display:flex;align-items:center;gap:9px;padding:0 13px;border-bottom:1px solid #eef1f5}
.ph b{font-size:12.5px}
.ph .muted{font-size:11px;color:#8a96a3}
.legend{margin-left:auto;display:flex;align-items:center;gap:14px;font-size:11px;color:#5b6672}
.legend i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:5px;vertical-align:2px}
.chartbox{padding:8px 10px 6px}
table{border-collapse:collapse;width:100%}
.tbl th{font-size:10.5px;color:#6b7683;font-weight:600;text-align:left;padding:6px 10px;background:#f7f9fb;
        border-bottom:1px solid #e9edf2;white-space:nowrap}
.tbl td{font-size:11.5px;padding:6px 10px;border-bottom:1px solid #f0f3f6;color:#2b3641;white-space:nowrap}
.tbl tr:last-child td{border-bottom:none}
.tbl .num{font-family:"Cascadia Mono",Consolas,monospace;font-size:11px}
.status{height:26px;display:flex;align-items:center;gap:8px;font-size:10.5px;color:#7b8794;
        background:#fff;border-top:1px solid #e9edf2;padding:0 14px}
.status .ok{color:#2e9e4f}
.status .sep{color:#d3d9e0}
"""


def build_main():
    t_last = TIMES[-1].strftime("%H:%M:%S")
    rows = []
    for i in range(N - 6, N):
        cum_ms = sum(cpu[k] / 100.0 * STEP * 1000 * CORES for k in range(i + 1))
        rows.append(
            "<tr><td class='num'>%d</td><td class='num'>%s</td><td class='num'>%.2f</td>"
            "<td class='num'>%d</td><td class='num'>%.2f</td><td class='num'>%.1f</td>"
            "<td class='num'>%s</td><td class='num'>%.2f</td><td class='num'>%d</td><td>%s</td></tr>"
            % (i + 1, TIMES[i].strftime("%H:%M:%S"), cpu[i],
               round(cpu[i] / 100.0 * STEP * 1000 * CORES), cpu[i] / 100.0 * CORES,
               mem[i], fmt_hms(cum_ms), mem[i] / RAM_MB * 100.0, THREAD_BASE + (i % 5) - 2, "—")
        )

    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>原型 · 主界面</title><style>%s</style></head><body>
<div class="win">
  <div class="tbar">
    <div class="logo">▦</div><div class="ttl">进程性能监控器</div><div class="ver">v1.0</div>
    <div class="tag-proto">界面原型 · 评审稿（示例数据）</div>
    <div class="grow"></div><div class="wbtn">—</div><div class="wbtn">▢</div><div class="wbtn x">✕</div>
  </div>
  <div class="content">
    <div class="row">
      <div class="lbl">目标进程</div>
      <div class="combo"><span class="dot"></span><b>chrome.exe</b>
        <span class="muted">12 个实例 · PID 8124 / 9036 / 11208 …</span><span class="caret">▾</span></div>
      <button class="btn">刷新列表</button>
      <div class="seg"><span class="on">按进程名聚合</span><span>指定 PID</span></div>
      <div class="divider"></div>
      <div class="lbl">采样间隔</div><div class="chip">2.0 s</div>
      <div class="tiny">固定节拍 · 停止前自动落盘</div>
    </div>
    <div class="row">
      <button class="btn primary dis"><span class="ico">▶</span>开始监控</button>
      <button class="btn"><span class="ico">⏸</span>暂停</button>
      <button class="btn"><span class="ico">⏹</span>停止并生成报告</button>
      <div class="divider"></div>
      <div class="state"><span class="pill">● 监控中</span><span class="mono">00:03:58</span>
        <span class="tiny">已采样 120 条</span></div>
      <div class="grow"></div>
      <button class="btn link">打开 output 目录 ↗</button>
    </div>
    <div class="cards">
      <div class="card"><div class="ch">CPU 占用率 <span class="hint">区间均值</span></div>
        <div class="cv">%.1f<span class="u">%%</span></div>
        <div class="cs">峰值 %.1f%% · P95 %.1f%% · 等效 %.2f 核</div>%s</div>
      <div class="card"><div class="ch">CPU 占用大小 <span class="hint">累计 CPU 时间</span></div>
        <div class="cv">%s</div>
        <div class="cs">区间 CPU 时间 %d ms · 2 s 窗口</div>%s</div>
      <div class="card"><div class="ch">内存使用大小 <span class="hint">私有工作集</span></div>
        <div class="cv">%.1f<span class="u">MB</span></div>
        <div class="cs">峰值 %.1f MB · 基线 %.1f MB · 末值 %.1f MB</div>%s</div>
      <div class="card"><div class="ch">内存使用率 <span class="hint">相对物理内存</span></div>
        <div class="cv">%.2f<span class="u">%%</span></div>
        <div class="cs">物理内存 16.0 GB · 工作集 %.1f MB</div>%s</div>
    </div>
    <div class="panel">
      <div class="ph"><b>实时曲线</b><span class="muted">最近 3 分 58 秒 · 2 s/点</span>
        <div class="legend"><span><i style="background:#0f6cbd"></i>CPU 占用率 %%</span>
        <span><i style="background:#d98a1f"></i>私有工作集 MB</span>
        <span><i style="background:#d95c5c"></i>CPU 阈值 80%%</span></div></div>
      <div class="chartbox">%s</div>
    </div>
    <div class="panel">
      <div class="ph"><b>采样明细</b><span class="muted">最近 6 条 · 完整数据写入 Excel</span>
        <div class="legend" style="font-size:10.5px;color:#98a3ae">暂停/恢复、进程退出等事件写进「备注」列</div></div>
      <table class="tbl"><thead><tr>
        <th>#</th><th>时间</th><th>CPU%%</th><th>区间 CPU 时间 ms</th><th>等效核数</th>
        <th>私有工作集 MB</th><th>累计 CPU 时间</th><th>内存率 %%</th><th>线程</th><th>备注</th></tr></thead>
        <tbody>%s</tbody></table>
    </div>
  </div>
  <div class="status"><span class="ok">●</span>%s 正在监控 chrome.exe（12 实例聚合，2 s/点）…
    <span class="grow"></span>输出目录：output\\chrome_20261118_193014\\
    <span class="sep">|</span>权限：标准用户<span class="sep">|</span>原型稿 v1.0 · 数据为示例</div>
</div></body></html>""" % (
        MAIN_CSS,
        avg_cpu, max_cpu, p95_cpu, cores_eq, spark(cpu[-40:]),
        fmt_hms(cpu_total_ms), round(cpu[-1] / 100.0 * STEP * 1000 * CORES), spark(cpu[-40:], color="#5b8fd6"),
        mem_end, mem_peak, mem_base, mem_end, spark(mem[-40:], color="#d98a1f"),
        mem_end / RAM_MB * 100.0, mem_end * 1.32, spark(mem[-40:], color="#c98a2a"),
        chart(1224, 238, live=True),
        "\n".join(rows), t_last,
    )
    return html


# ---------------------------------------------------------------- 页面 2：Excel
EXCEL_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;background:#dfe7f0;display:flex;align-items:center;
     justify-content:center;min-height:100vh;padding:20px;-webkit-font-smoothing:antialiased;color:#1f2328}
.win{width:1440px;height:830px;background:#fff;border-radius:8px;overflow:hidden;display:flex;flex-direction:column;
     box-shadow:0 30px 70px rgba(12,32,56,.32);border:1px solid #c9d3dd}
.tbar{height:34px;background:#217346;color:#fff;display:flex;align-items:center;gap:12px;padding:0 12px;font-size:12px}
.tbar .qat{display:flex;gap:10px;opacity:.9;font-size:11px}
.tbar .grow{flex:1}
.tbar .wbtn{width:34px;height:34px;display:flex;align-items:center;justify-content:center;font-size:11px;opacity:.9}
.tabs{height:30px;display:flex;align-items:center;gap:3px;padding:0 10px;background:#f3f4f6;border-bottom:1px solid #dde3ea;font-size:11.5px;color:#374151}
.tabs .t{padding:5px 11px;border-radius:4px 4px 0 0}
.tabs .t.on{background:#fff;color:#217346;font-weight:600;border:1px solid #dde3ea;border-bottom-color:#fff}
.ribbon{height:78px;background:#fff;border-bottom:1px solid #dde3ea;display:flex;align-items:center;gap:0;padding:0 10px}
.rgrp{display:flex;flex-direction:column;justify-content:center;height:70px;padding:0 12px;border-right:1px solid #eef1f4;gap:5px}
.rgrp .lbl2{font-size:9.5px;color:#9aa5b1;text-align:center}
.rrow{display:flex;align-items:center;gap:4px}
.rbtn{min-width:26px;height:24px;border:1px solid transparent;border-radius:3px;display:flex;align-items:center;
      justify-content:center;font-size:11px;color:#374151;padding:0 4px}
.rbtn.sq{background:#f3f4f6;border-color:#e5e7eb}
.fontbox{border:1px solid #d7dde5;border-radius:3px;height:24px;padding:0 8px;font-size:11px;display:flex;align-items:center;
         justify-content:space-between;width:150px;color:#374151}
.fbar{height:26px;display:flex;align-items:center;gap:6px;border-bottom:1px solid #dde3ea;padding:0 8px;background:#fff}
.namebox{width:64px;height:20px;border:1px solid #d7dde5;border-radius:2px;font-size:11px;display:flex;align-items:center;padding:0 6px}
.fx{font-size:10px;color:#8a96a3;font-style:italic;padding:0 6px;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;height:16px;display:flex;align-items:center}
.fcontent{font-size:11px;color:#374151}
.sheet{flex:1;overflow:hidden;position:relative;padding-left:0}
table{border-collapse:collapse;table-layout:fixed;font-size:11.5px}
th,td{border-right:1px solid #e3e8ee;border-bottom:1px solid #e3e8ee;height:25px;padding:0 6px;overflow:hidden;
      white-space:nowrap;text-overflow:ellipsis}
thead th{background:#1f4e79;color:#fff;font-weight:600;font-size:11px;height:26px;text-align:left;position:relative}
thead th .fl{position:absolute;right:4px;top:7px;font-size:8px;opacity:.85}
tbody tr:nth-child(even) td{background:#f4f8fc}
td.n{text-align:right;font-family:"Cascadia Mono",Consolas,monospace;font-size:10.8px}
td.c{text-align:center}
.rowhead{background:#f3f5f7;color:#6b7683;text-align:center;font-size:10px;width:38px;min-width:38px}
td.sel{outline:2px solid #217346;outline-offset:-2px;background:#eef7f1!important}
.tabbar{height:28px;display:flex;align-items:center;gap:2px;background:#f3f4f6;border-top:1px solid #dde3ea;padding:0 8px;font-size:11px;color:#4b5563}
.tabbar .st{padding:3px 12px;border-radius:3px 3px 0 0;background:#fff;border:1px solid #dde3ea;border-bottom:none;font-weight:600;color:#217346}
.tabbar .st2{padding:3px 12px;color:#6b7683}
.status{height:24px;display:flex;align-items:center;gap:16px;background:#f3f4f6;border-top:1px solid #dde3ea;padding:0 12px;font-size:10.5px;color:#6b7683}
.status .grow{flex:1}
.badge{position:absolute;right:14px;top:8px;font-size:10px;color:#8a6d1f;background:#fdf3d8;border:1px solid #f0dfae;border-radius:9px;padding:2px 8px;z-index:5}
"""

COLS = [
    ("序号", 46), ("采样时间", 150), ("相对时间(s)", 88), ("区间CPU时间(ms)", 108),
    ("CPU占用率(%)", 96), ("等效核数", 84), ("累计CPU时间", 104), ("私有工作集(MB)", 108),
    ("工作集(MB)", 94), ("提交大小(MB)", 96), ("内存占用率(%)", 98), ("线程数", 62),
    ("句柄数", 66), ("实例数", 62), ("备注", 130),
]


def build_excel():
    body_rows = []
    cum = 0.0
    for i in range(22):
        if i < 16:
            dt_ms = cpu[i] / 100.0 * STEP * 1000 * CORES
            cum += dt_ms
            note = "启动预热" if i < 3 else "—"
            cells = [
                ("n", i + 1), ("n", TIMES[i].strftime("%Y-%m-%d %H:%M:%S")), ("n", STEP * i),
                ("n", "%d" % round(dt_ms)), ("n", "%.2f" % cpu[i]), ("n", "%.2f" % (cpu[i] / 100.0 * CORES)),
                ("n", fmt_hms(cum)), ("n", "%.1f" % mem[i]), ("n", "%.1f" % (mem[i] * 1.32)),
                ("n", "%.1f" % (mem[i] * 1.45)), ("n", "%.2f" % (mem[i] / RAM_MB * 100.0)),
                ("n", THREAD_BASE + i % 4), ("n", HANDLE_BASE + i * 3), ("c", "12"), ("", note),
            ]
        else:
            cells = [("", "")] * 15
        tds = []
        for ci, (cls, val) in enumerate(cells):
            extra = " sel" if (i == 4 and ci == 3) else ""
            tds.append("<td class='%s%s'>%s</td>" % (cls, extra, val))
        body_rows.append("<tr><td class='rowhead'>%d</td>%s</tr>" % (i + 2, "".join(tds)))

    head = "".join("<th style='width:%dpx;min-width:%dpx'>%s<span class='fl'>▾</span></th>" % (w, w, n) for n, w in COLS)
    colgroup = "".join("<col style='width:%dpx'>" % w for _, w in COLS)

    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>原型 · Excel 数据表</title>
<style>%s</style></head><body>
<div class="win">
  <div class="tbar"><div class="qat">▣ ▤ ▥</div><span>监控数据_chrome.exe_20261118_193014.xlsx - Excel</span>
    <div class="grow"></div><div class="wbtn">—</div><div class="wbtn">▢</div><div class="wbtn">✕</div></div>
  <div class="tabs"><div class="t">文件</div><div class="t on">开始</div><div class="t">插入</div><div class="t">页面布局</div>
    <div class="t">公式</div><div class="t">数据</div><div class="t">审阅</div><div class="t">视图</div><div class="t">帮助</div></div>
  <div class="ribbon">
    <div class="rgrp"><div class="rrow"><div class="rbtn sq">粘贴</div><div class="rbtn sq">剪切</div><div class="rbtn sq">复制</div></div>
      <div class="lbl2">剪贴板</div></div>
    <div class="rgrp"><div class="rrow"><div class="fontbox"><span>微软雅黑</span><span>▾</span></div>
      <div class="fontbox" style="width:52px"><span>11</span><span>▾</span></div></div>
      <div class="rrow"><div class="rbtn">B</div><div class="rbtn">I</div><div class="rbtn">U</div>
        <div class="rbtn">A</div><div class="rbtn">🎨</div></div><div class="lbl2">字体</div></div>
    <div class="rgrp"><div class="rrow"><div class="rbtn sq">≡</div><div class="rbtn sq">☰</div><div class="rbtn sq">⇥</div></div>
      <div class="lbl2">对齐方式</div></div>
    <div class="rgrp"><div class="rrow"><div class="fontbox" style="width:110px"><span>常规</span><span>▾</span></div>
      <div class="rbtn">¥</div><div class="rbtn">%%</div><div class="rbtn">,</div></div><div class="lbl2">数字</div></div>
    <div class="rgrp"><div class="rrow"><div class="rbtn sq">条件格式</div><div class="rbtn sq">表格样式</div></div>
      <div class="lbl2">样式</div></div>
    <div class="rgrp"><div class="rrow"><div class="rbtn sq">插入</div><div class="rbtn sq">删除</div><div class="rbtn sq">格式</div></div>
      <div class="lbl2">单元格</div></div>
    <div class="rgrp"><div class="rrow"><div class="rbtn sq">Σ 自动求和</div><div class="rbtn sq">筛选</div></div>
      <div class="lbl2">编辑</div></div>
  </div>
  <div class="fbar"><div class="namebox">D5</div><div class="fx">fx</div>
    <div class="fcontent">3182</div></div>
  <div class="sheet">
    <div class="badge">原型稿 · 示例数据（前 16 行）</div>
    <table><colgroup><col style="width:38px">%s</colgroup>
      <thead><tr><th class="rowhead" style="background:#1f4e79"></th>%s</tr></thead>
      <tbody>%s</tbody></table>
  </div>
  <div class="tabbar"><span class="st">01_原始数据</span><span class="st2">00_监控说明</span>
    <span class="st2">02_统计汇总</span><span class="st2">03_判定结果</span><span class="st2">04_图表</span></div>
  <div class="status"><span>就绪</span><span>计数：16 条记录（共 120 条）</span><span>平均值：18.6</span>
    <div class="grow"></div><span>100%%</span><span>⊞</span><span>—</span><span>＋</span></div>
</div></body></html>""" % (EXCEL_CSS, colgroup, head, "".join(body_rows))
    return html


# ---------------------------------------------------------------- 页面 3：性能报告
REPORT_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;background:#e9edf2;color:#1f2328;
     display:flex;justify-content:center;padding:26px 0;-webkit-font-smoothing:antialiased}
.page{width:1010px;background:#fff;box-shadow:0 18px 50px rgba(15,35,60,.18);border-radius:4px;overflow:hidden}
.pad{padding:46px 56px 40px}
.kicker{font-size:10.5px;letter-spacing:2.4px;color:#0f6cbd;font-weight:700}
h1{font-size:26px;line-height:1.35;margin:8px 0 10px;letter-spacing:-.3px}
.meta{font-size:11px;color:#7b8794;line-height:1.9}
.meta b{color:#4b5563;font-weight:600}
.rule{height:3px;background:linear-gradient(90deg,#0f6cbd 0%,#0f6cbd 22%,#e5eaf0 22%,#e5eaf0 100%);margin:18px 0 22px}
.verdicts{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:22px}
.v{border:1px solid #e6e9ee;border-left-width:4px;border-radius:6px;padding:11px 13px;background:#fbfcfd}
.v .k{font-size:10.5px;color:#7b8794}
.v .s{font-size:17px;font-weight:700;margin:4px 0 3px;letter-spacing:.2px}
.v .d{font-size:10.5px;color:#6b7683;line-height:1.5}
h2{font-size:14.5px;margin:26px 0 10px;display:flex;align-items:center;gap:9px}
h2 i{font-style:normal;font-size:10px;color:#fff;background:#0f6cbd;width:20px;height:20px;border-radius:4px;
     display:inline-flex;align-items:center;justify-content:center;font-weight:700}
.lead{font-size:11.5px;color:#4b5563;line-height:1.85;margin:0 0 10px}
.lead b{color:#1f2328}
table{width:100%;border-collapse:collapse;font-size:11px;margin:6px 0 4px}
th{background:#f5f8fb;color:#5b6672;font-weight:600;text-align:left;padding:6px 9px;border:1px solid #e8edf3;font-size:10.5px}
td{padding:6px 9px;border:1px solid #edf1f5;color:#33404d;line-height:1.5}
td.n{font-family:"Cascadia Mono",Consolas,monospace;font-size:10.5px}
.pass{color:#107c10;font-weight:700}
.warn{color:#b26a00;font-weight:700}
.fail{color:#c62828;font-weight:700}
.chartbox{border:1px solid #e8edf3;border-radius:6px;padding:8px 6px 2px;margin:8px 0 4px;background:#fff}
.cap{font-size:10px;color:#8a96a3;padding:0 8px 6px}
.foot{border-top:1px solid #e8edf3;margin-top:26px;padding-top:12px;font-size:10px;color:#8a96a3;line-height:1.8}
.ad{padding-left:18px;font-size:11.5px;color:#3d4a57;line-height:1.95}
.ad li{margin-bottom:3px}
.ad b{color:#1f2328}
"""


def build_report():
    dur_min = DURATION // 60
    dur_sec = DURATION % 60
    c1, b1 = VCOLOR[CPU_VERDICT]
    c2, b2 = VCOLOR[MEM_VERDICT]
    grew = (mem_end - mem_base) / mem_base * 100.0
    rel1 = mem[54] - mem[58]
    rel2 = mem[99] - mem[104]

    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>原型 · 性能分析报告</title>
<style>%s</style></head><body><div class="page"><div class="pad">
<div class="kicker">PERFORMANCE REPORT · 进程性能分析报告</div>
<h1>chrome.exe 性能监控分析报告</h1>
<div class="meta">
  监控时段 <b>2026-11-18 19:30:14 — 19:34:12</b>　·　时长 <b>%d 分 %d 秒</b>　·　有效采样 <b>%d 条 / 2 s</b>　·　生成时间 2026-11-18 19:34:15<br>
  进程：chrome.exe（12 个实例聚合，PID 8124 等）　·　系统：Windows 11 26200 / 16 逻辑处理器 / 16.0 GB　·　数据文件：01_原始数据.xlsx
</div>
<div class="rule"></div>

<div class="verdicts">
  <div class="v" style="border-left-color:%s;background:%s"><div class="k">CPU 占用判定</div>
    <div class="s" style="color:%s">%s</div>
    <div class="d">均值 %.1f%%、P95 %.1f%% 正常；出现 %.1f%% 瞬时尖峰（%d 处），建议结合业务阶段复核</div></div>
  <div class="v" style="border-left-color:%s;background:%s"><div class="k">内存占用判定</div>
    <div class="s" style="color:%s">%s</div>
    <div class="d">峰值 %.1f MB（占物理内存 %.1f%%），全程未超过 80%% 上限</div></div>
  <div class="v" style="border-left-color:#107c10;background:#e8f5e9"><div class="k">内存释放趋势</div>
    <div class="s" style="color:#107c10">正常释放</div>
    <div class="d">检出 2 次有效回落（-%d MB / -%d MB），末值较基线 %+.1f%%，无泄漏特征</div></div>
</div>

<h2><i>01</i>CPU 占用分析</h2>
<p class="lead">监控期内 CPU 均值为 <b>%.1f%%</b>（16 逻辑处理器归一，与任务管理器口径一致），
P95 为 <b>%.1f%%</b>，峰值 <b>%.1f%%</b>（出现于 %s）。峰值超过 90%% 但低于 95%%，且单次尖峰持续时间 &lt; 10 s、
未形成持续高压，按判定规则记为「关注」，不构成性能不达标。</p>
<table><thead><tr><th style="width:24%%">指标</th><th style="width:18%%">标准</th><th style="width:20%%">实测</th><th style="width:14%%">结论</th><th>说明</th></tr></thead><tbody>
<tr><td>CPU 平均占用率</td><td>≤ 50%%</td><td class="n">%.1f%%</td><td class="pass">通过</td><td>16 核归一后的区间均值</td></tr>
<tr><td>CPU P95 占用率</td><td>≤ 70%%</td><td class="n">%.1f%%</td><td class="pass">通过</td><td>95%% 采样点低于该值</td></tr>
<tr><td>CPU 峰值占用率</td><td>≤ 90%%（&gt;95%% 不通过）</td><td class="n">%.1f%%</td><td class="warn">关注</td><td>%s 附近出现约 8 s 尖峰</td></tr>
<tr><td>持续 ≥80%% 时长</td><td>≤ 30 s</td><td class="n">%d s</td><td class="pass">通过</td><td>未形成持续满载</td></tr>
<tr><td>累计 CPU 时间</td><td>参考值</td><td class="n">%s</td><td>—</td><td>等效 %.2f 个逻辑核心满负荷</td></tr>
</tbody></table>
<div class="chartbox">%s<div class="cap">图 1　CPU 占用率时序（2 s 采样，红色虚线为 80%% 告警阈值）</div></div>

<h2><i>02</i>内存占用与释放趋势</h2>
<p class="lead">私有工作集从基线 <b>%.1f MB</b> 波动上升至峰值 <b>%.1f MB</b>，随后两次明显回落，
形成「增长—释放—再增长」锯齿形态；末值 <b>%.1f MB</b>，较基线高 <b>%.1f%%</b>，线性斜率 <b>%+.1f MB/min</b>（R²=%.2f）。
峰值仅占物理内存 <b>%.1f%%</b>，未触及内存上限；存在规律性释放，判定为<b>正常释放趋势（未见泄漏特征）</b>。</p>
<table><thead><tr><th style="width:24%%">指标</th><th style="width:18%%">标准</th><th style="width:20%%">实测</th><th style="width:14%%">结论</th><th>说明</th></tr></thead><tbody>
<tr><td>内存峰值占用率</td><td>≤ 80%%</td><td class="n">%.1f%%</td><td class="pass">通过</td><td>%.1f MB / 16.0 GB</td></tr>
<tr><td>有效释放次数</td><td>≥ 1 次</td><td class="n">2 次</td><td class="pass">通过</td><td>回落 -%d MB、-%d MB</td></tr>
<tr><td>末值相对基线增幅</td><td>≤ 20%%</td><td class="n">%+.1f%%</td><td class="pass">通过</td><td>%.1f → %.1f MB</td></tr>
<tr><td>线性增长斜率</td><td>≤ 3 MB/min</td><td class="n">%+.1f MB/min</td><td class="pass">通过</td><td>R²=%.2f，趋势不显著</td></tr>
<tr><td>泄漏特征</td><td>无单调增长</td><td class="n">锯齿</td><td class="pass">通过</td><td>峰值后均能回落至基线带附近</td></tr>
</tbody></table>
<div class="chartbox">%s<div class="cap">图 2　私有工作集时序（灰色虚线为基线 %.1f MB，绿色为有效释放点）</div></div>
<table><thead><tr><th style="width:14%%">#</th><th style="width:24%%">峰值时刻</th><th style="width:22%%">峰值</th><th style="width:22%%">谷值</th><th>释放幅度 / 耗时</th></tr></thead><tbody>
<tr><td>1</td><td class="n">19:32:02</td><td class="n">%d MB</td><td class="n">%d MB</td><td class="n">-%d MB / 8 s</td></tr>
<tr><td>2</td><td class="n">19:33:32</td><td class="n">%d MB</td><td class="n">%d MB</td><td class="n">-%d MB / 10 s</td></tr>
</tbody></table>

<h2><i>03</i>判定明细</h2>
<table><thead><tr><th style="width:26%%">判定项</th><th style="width:26%%">标准（可在 config.json 调整）</th><th style="width:22%%">实测</th><th>结论</th></tr></thead><tbody>
<tr><td>CPU 是否超出标准</td><td>均值 ≤50%%、P95 ≤70%%、峰值 ≤90%%、&gt;80%% 累计 ≤30 s</td><td class="n">均值 %.1f%% / P95 %.1f%% / 峰值 %.1f%% / 0 s</td><td class="warn">关注（峰值超 90%%）</td></tr>
<tr><td>内存是否超出标准</td><td>峰值 ≤80%% 物理内存</td><td class="n">峰值 %.1f%%</td><td class="pass">通过</td></tr>
<tr><td>内存释放趋势</td><td>≥1 次有效回落，末值 ≤ 基线+20%%，斜率 ≤3 MB/min</td><td class="n">2 次回落 / %+.1f%% / %+.1f MB/min</td><td class="pass">正常释放</td></tr>
<tr><td>综合结论</td><td>任一项不通过即整体不通过</td><td class="n">—</td><td class="warn">%s</td></tr>
</tbody></table>

<h2><i>04</i>结论与建议</h2>
<ol class="ad">
<li><b>CPU：可用但存在瞬时尖峰。</b>19:32:10—19:32:16 期间出现 93%% 尖峰，建议确认该时段是否由页面加载/GC 触发；若为常态需优化启动路径。</li>
<li><b>内存：释放趋势正常。</b>两次回落均回到基线带附近，属于缓存周期性回收，不作为泄漏处理；建议延长至 30 分钟以上观察长稳表现。</li>
<li><b>采样口径提示。</b>本工具按 2 s 窗口计算，与任务管理器 1 s 刷新存在窗口差异，对比时应允许 ±1~2 个百分点偏差。</li>
<li><b>后续动作。</b>建议在业务典型场景（空闲/加载/高负载）各监控 10 分钟，形成三份报告后横向对比。</li>
</ol>

<div class="foot">
口径说明：CPU 占用率 = 进程 CPU 时间增量 ÷ 采样间隔 ÷ 逻辑处理器数 × 100%%（与任务管理器「进程」页一致）；CPU 占用大小 = 区间 CPU 时间与累计 CPU 时间（后者与任务管理器「详细信息 → CPU 时间」一致）。
内存使用大小 = 私有工作集 Private Working Set（与 Win10 1809+ / Win11 任务管理器「内存」列一致）；内存使用率 = 私有工作集 ÷ 物理内存总量。
数据文件：output\\chrome_20261118_193014\\01_原始数据.xlsx（120 行）　·　工具版本 v1.0.0　·　生成于 2026-11-18 19:34:15
</div>
</div></div></body></html>""" % (
        REPORT_CSS, dur_min, dur_sec, N,
        c1, b1, c1, CPU_VERDICT, avg_cpu, p95_cpu, max_cpu, 1,
        c2, b2, c2, MEM_VERDICT, mem_peak, mem_peak / RAM_MB * 100.0,
        round(rel1), round(rel2), grew,
        avg_cpu, p95_cpu, max_cpu, TIMES[imax_cpu].strftime("%H:%M:%S"),
        avg_cpu, p95_cpu, max_cpu, TIMES[70].strftime("%H:%M:%S"),
        run80, fmt_hms(cpu_total_ms), cores_eq,
        chart(848, 246),
        mem_base, mem_peak, mem_end, grew, slope_min, mem_r2, mem_peak / RAM_MB * 100.0,
        mem_peak, mem_peak / RAM_MB * 100.0, round(rel1), round(rel2), grew, mem_base, mem_end,
        slope_min, mem_r2,
        chart(848, 246, mem_peak_marks=True, release_marks=True, baseline=True), mem_base,
        round(mem[54]), round(mem[58]), round(rel1),
        round(mem[99]), round(mem[104]), round(rel2),
        avg_cpu, p95_cpu, max_cpu, mem_peak / RAM_MB * 100.0, grew, slope_min, OVERALL,
    )
    return html


def main():
    for name, builder in (("main", build_main), ("excel", build_excel), ("report", build_report)):
        path = os.path.join(PROTO, name + ".html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(builder())
        print("written", path)
    print("cpu verdict=%s mem verdict=%s overall=%s" % (CPU_VERDICT, MEM_VERDICT, OVERALL))
    print("avg=%.2f p95=%.2f max=%.2f run80=%d" % (avg_cpu, p95_cpu, max_cpu, run80))
    print("mem base=%.1f peak=%.1f end=%.1f slope=%.2f r2=%.2f" % (mem_base, mem_peak, mem_end, slope_min, mem_r2))


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""实时曲线控件：左轴 CPU 占用率（%），右轴私有工作集（MB），纯 tk.Canvas 绘制。"""

import math
import tkinter as tk

C_CPU = "#2563EB"
C_MEM = "#EA580C"
C_GRID = "#EFF3F8"
C_AXIS = "#94A3B8"
C_TH = "#DC2626"
FONT = ("Microsoft YaHei", 9)



def _flat(pts):
    """Canvas 坐标需要扁平序列：[(x, y), ...] -> [x, y, x, y, ...]。"""
    out = []
    for x, y in pts:
        out.extend([x, y])
    return out

class LiveChart(tk.Frame):
    def __init__(self, master, max_points=180, **kw):
        tk.Frame.__init__(self, master, bg="#FFFFFF",
                          highlightbackground="#E2E8F0", highlightthickness=1, **kw)
        self.canvas = tk.Canvas(self, bg="#FFFFFF", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.max_points = max_points
        self.samples = []
        self.canvas.bind("<Configure>", lambda e: self.redraw())

    def set_samples(self, samples):
        self.samples = samples or []
        self.redraw()

    # ------------------------------------------------------------------
    def redraw(self):
        c = self.canvas
        w = c.winfo_width()
        h = c.winfo_height()
        c.delete("all")
        if w < 120 or h < 90:
            return

        ml, mr, mt, mb = 54, 64, 26, 22
        pw = w - ml - mr
        ph = h - mt - mb

        data = self.samples[-self.max_points:]
        pts = []
        for i, s in enumerate(data):
            pts.append((i, s.cpu_pct, s.priv_mb))

        n = max(1, len(data) - 1)

        def X(i):
            return ml + (i / float(n)) * pw

        def Yc(v):
            v = max(0.0, min(100.0, v or 0.0))
            return mt + ph - (v / 100.0) * ph

        mem_peak = 0.0
        for _, _, mm in pts:
            if mm:
                mem_peak = max(mem_peak, mm)
        mem_max = max(200.0, math.ceil(mem_peak * 1.08 / 100.0) * 100.0)
        mem_vals = [v for _, _, v in pts if v]
        mem_low = min(mem_vals) if mem_vals else 0.0
        # 内存波动通常只有几十 MB，整轴从 0 起会把曲线压成一条贴顶直线；
        # 低于 300 MB 或波动超过轴长 60% 时才回到 0 起，否则只截掉下方空白。
        if mem_low > 300 and (mem_max - mem_low) < mem_max * 0.6:
            mem_min = max(0.0, math.floor(mem_low * 0.9 / 100.0) * 100.0)
        else:
            mem_min = 0.0
        mem_span = max(1.0, mem_max - mem_min)

        def Ym(v):
            v = max(mem_min, min(mem_max, v or mem_min))
            return mt + ph - ((v - mem_min) / mem_span) * ph

        # 网格与双轴刻度
        for i in range(5):
            frac = i / 4.0
            y = mt + ph - frac * ph
            c.create_line(ml, y, ml + pw, y, fill=C_GRID)
            c.create_text(ml - 6, y, text="%d%%" % int(100 * frac), anchor="e",
                          fill=C_AXIS, font=FONT)
            c.create_text(ml + pw + 6, y, text="%d" % int(mem_min + mem_span * frac), anchor="w",
                          fill=C_AXIS, font=FONT)

        # 80% 告警线
        y80 = Yc(80)
        c.create_line(ml, y80, ml + pw, y80, fill=C_TH, dash=(2, 6), width=1)
        c.create_text(ml + pw - 4, y80 - 7, text="80% 告警线", anchor="e",
                      fill=C_TH, font=("Microsoft YaHei", 8))

        # 面积 + 折线
        cpu_pts = [(X(i), Yc(v)) for i, v, _ in pts if v is not None]
        mem_pts = [(X(i), Ym(v)) for i, _, v in pts if v]
        if len(cpu_pts) >= 2:
            poly = [cpu_pts[0][0], mt + ph]
            for x, y in cpu_pts:
                poly.extend([x, y])
            poly.extend([cpu_pts[-1][0], mt + ph])
            c.create_polygon(*poly, fill="#DBEAFE", outline="")
        if len(mem_pts) >= 2:
            c.create_line(_flat(mem_pts), fill="#FFFFFF", width=5)
            c.create_line(_flat(mem_pts), fill=C_MEM, width=2)
        if len(cpu_pts) >= 2:
            c.create_line(_flat(cpu_pts), fill=C_CPU, width=2)

        # 当前值标记
        if cpu_pts:
            x, y = cpu_pts[-1]
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=C_CPU, outline="#FFFFFF")
        if mem_pts:
            x, y = mem_pts[-1]
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=C_MEM, outline="#FFFFFF")

        # 图例
        c.create_rectangle(ml + 2, 6, ml + 12, 12, fill=C_CPU, outline="")
        c.create_text(ml + 16, 9, text="CPU 占用率", anchor="w", fill="#334155", font=FONT)
        c.create_rectangle(ml + 96, 6, ml + 106, 12, fill=C_MEM, outline="")
        c.create_text(ml + 110, 9, text="私有工作集 (MB)", anchor="w", fill="#334155", font=FONT)

        if not pts:
            c.create_text(ml + pw / 2.0, mt + ph / 2.0,
                          text="点击「开始监控」后，曲线会在这里实时绘制",
                          fill="#94A3B8", font=("Microsoft YaHei", 11))
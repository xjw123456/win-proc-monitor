# -*- coding: utf-8 -*-
"""主窗口：左侧选进程与采集设置，右侧实时指标 / 曲线 / 日志。"""

import json
import os
import threading
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

from core import APP_NAME, VERSION
from core import analyzer, excel_writer, report_writer, winapi
from core.report_writer import fmt_dur
from core.sampler import Monitor

from .chart_canvas import LiveChart

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

BG = "#F1F5F9"
CARD = "#FFFFFF"
BORDER = "#E2E8F0"
DARK = "#0F172A"
MUTED = "#64748B"
GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"

FONT = "Microsoft YaHei"

NAMES = {"excel": "01_原始数据", "html": "02_性能报告", "md": "03_性能报告摘要"}


def _safe_name(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "process"


class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.title("%s v%s" % (APP_NAME, VERSION))
        self.geometry("1240x820")
        self.minsize(1100, 720)
        self.configure(bg=BG)

        self.sysinfo = winapi.system_info()
        self.catalog = winapi.ProcessCatalog()
        self.thresholds = self._load_thresholds()
        self.monitor = None
        self.generating = False
        self._log_seen = 0
        self._job_done = None
        self._job_error = None
        self._last_out = None

        self.var_filter = tk.StringVar()
        self.var_target = tk.StringVar()
        self.var_mode = tk.StringVar(value="name")
        self.var_interval = tk.StringVar(value="2")

        self._build_style()
        self._build_header()
        self._build_body()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, lambda: self._refresh_process_list())
        self.after(400, self._poll)

    # ------------------------------------------------------------------
    # 配置 / 样式
    # ------------------------------------------------------------------
    def _load_thresholds(self):
        cfg = {}
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
        except Exception:
            cfg = {}
        user = cfg.get("thresholds") if isinstance(cfg, dict) else None
        try:
            return analyzer.merge_thresholds(user or {})
        except Exception:
            return analyzer.merge_thresholds({})

    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=DARK, font=(FONT, 9))
        st.configure("Card.TLabel", background=CARD, foreground=DARK, font=(FONT, 9))
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        st.configure("Title.TLabel", background=CARD, foreground=DARK, font=(FONT, 10, "bold"))
        st.configure("TButton", font=(FONT, 9), padding=(10, 6), borderwidth=0)
        st.configure("Accent.TButton", background=GREEN, foreground="white",
                     font=(FONT, 10, "bold"), padding=(12, 8))
        st.map("Accent.TButton",
               background=[("active", "#15803D"), ("disabled", "#BBF7D0")],
               foreground=[("disabled", "#FFFFFF")])
        st.configure("Warn.TButton", background=AMBER, foreground="white",
                     font=(FONT, 10, "bold"), padding=(12, 8))
        st.map("Warn.TButton",
               background=[("active", "#B45309"), ("disabled", "#FDE68A")],
               foreground=[("disabled", "#FFFFFF")])
        st.configure("Danger.TButton", background=RED, foreground="white",
                     font=(FONT, 10, "bold"), padding=(12, 8))
        st.map("Danger.TButton",
               background=[("active", "#B91C1C"), ("disabled", "#FECACA")],
               foreground=[("disabled", "#FFFFFF")])
        st.configure("Ghost.TButton", background="#E2E8F0", foreground="#334155", padding=(10, 6))
        st.map("Ghost.TButton", background=[("active", "#CBD5E1")])
        st.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=24,
                     font=(FONT, 9), borderwidth=0)
        st.configure("Treeview.Heading", background="#1E3A5F", foreground="white",
                     font=(FONT, 9, "bold"), relief="flat", padding=(4, 5))
        st.map("Treeview.Heading", background=[("active", "#1E3A5F")])
        st.map("Treeview", background=[("selected", "#DBEAFE")],
               foreground=[("selected", DARK)])
        st.configure("TRadiobutton", background=CARD, font=(FONT, 9))

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build_header(self):
        head = tk.Frame(self, bg=DARK, height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="进程性能监控", bg=DARK, fg="white",
                 font=(FONT, 15, "bold")).place(x=20, y=10)
        tk.Label(head, text="CPU / 内存采样 · 2 秒节拍 · 与任务管理器同口径",
                 bg=DARK, fg="#94A3B8", font=(FONT, 9)).place(x=21, y=38)
        self.lbl_state = tk.Label(head, text="待机", bg="#1E293B", fg="#CBD5E1",
                                  font=(FONT, 9, "bold"), padx=14, pady=5)
        self.lbl_state.place(relx=1.0, x=-20, y=20, anchor="ne")

    def _build_body(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        left = tk.Frame(body, bg=BG, width=356)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        self._build_left(left)
        self._build_right(right)

    def _card(self, parent, title, pady=(0, 12)):
        outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        outer.pack(fill="x", pady=pady)
        inner = tk.Frame(outer, bg=CARD, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=CARD, fg=DARK,
                 font=(FONT, 10, "bold")).pack(anchor="w", pady=(0, 8))
        return inner

    def _build_left(self, parent):
        # ---- 1. 选择进程 ----
        box = self._card(parent, "① 选择目标进程")
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="筛选 / 输入进程名", bg=CARD, fg=MUTED,
                 font=(FONT, 8)).pack(anchor="w")
        e = tk.Entry(row, textvariable=self.var_filter, font=(FONT, 9),
                     relief="solid", bd=1, highlightthickness=0)
        e.pack(fill="x", pady=(3, 6))
        e.bind("<KeyRelease>", lambda ev: self._refresh_process_list())

        wrap = tk.Frame(box, bg=CARD)
        wrap.pack(fill="x")
        cols = ("name", "n", "pid")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", height=8,
                                 selectmode="browse")
        self.tree.heading("name", text="进程名")
        self.tree.heading("n", text="实例")
        self.tree.heading("pid", text="PID")
        self.tree.column("name", width=190, anchor="w")
        self.tree.column("n", width=48, anchor="center")
        self.tree.column("pid", width=96, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_pick)
        self.tree.bind("<Double-1>", self._on_pick)

        foot = tk.Frame(box, bg=CARD)
        foot.pack(fill="x", pady=(8, 0))
        self.lbl_count = tk.Label(foot, text="", bg=CARD, fg=MUTED, font=(FONT, 8))
        self.lbl_count.pack(side="left")
        ttk.Button(foot, text="刷新列表", style="Ghost.TButton",
                   command=self._refresh_process_list).pack(side="right")

        sel = tk.Frame(box, bg="#F8FAFC", highlightbackground=BORDER, highlightthickness=1)
        sel.pack(fill="x", pady=(10, 0))
        tk.Label(sel, text="已选目标", bg="#F8FAFC", fg=MUTED,
                 font=(FONT, 8)).pack(side="left", padx=(8, 6), pady=6)
        self.lbl_target = tk.Label(sel, textvariable=self.var_target, bg="#F8FAFC",
                                   fg=DARK, font=(FONT, 9, "bold"))
        self.lbl_target.pack(side="left", pady=6)

        # ---- 2. 采集设置 ----
        box2 = self._card(parent, "② 采集设置")
        r1 = tk.Frame(box2, bg=CARD)
        r1.pack(fill="x")
        tk.Label(r1, text="采样间隔", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left")
        sp = ttk.Spinbox(r1, from_=1, to=60, increment=1, width=5,
                         textvariable=self.var_interval, font=(FONT, 9))
        sp.pack(side="left", padx=(6, 4))
        tk.Label(r1, text="秒 / 次", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left")

        r2 = tk.Frame(box2, bg=CARD)
        r2.pack(fill="x", pady=(8, 0))
        ttk.Radiobutton(r2, text="按进程名聚合", value="name",
                        variable=self.var_mode).pack(side="left")
        ttk.Radiobutton(r2, text="按 PID", value="pid",
                        variable=self.var_mode).pack(side="left", padx=(12, 0))

        tk.Label(box2, text="本机 %d 逻辑处理器 · %.1f GB 物理内存 · %s" % (
            self.sysinfo.get("cores", 0), (self.sysinfo.get("total_phys_mb") or 0) / 1024.0,
            self.sysinfo.get("os_name", "")),
            bg=CARD, fg=MUTED, font=(FONT, 8), wraplength=300,
            justify="left").pack(anchor="w", pady=(8, 0))

        # ---- 3. 控制 ----
        box3 = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        box3.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(box3, bg=CARD, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        self.btn_start = ttk.Button(inner, text="● 开始监控", style="Accent.TButton",
                                    command=self._on_start)
        self.btn_start.pack(fill="x")
        rowb = tk.Frame(inner, bg=CARD)
        rowb.pack(fill="x", pady=(8, 0))
        self.btn_pause = ttk.Button(rowb, text="暂停", style="Warn.TButton",
                                    command=self._on_pause)
        self.btn_pause.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop = ttk.Button(rowb, text="停止并生成", style="Danger.TButton",
                                   command=self._on_stop)
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(inner, text="打开 output 目录", style="Ghost.TButton",
                   command=self._open_output).pack(fill="x", pady=(8, 0))

    def _stat_card(self, parent, title):
        f = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        f.pack(side="left", fill="both", expand=True, padx=(0, 10))
        inner = tk.Frame(f, bg=CARD, padx=14, pady=10)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
        val = tk.Label(inner, text="—", bg=CARD, fg=DARK, font=(FONT, 20, "bold"))
        val.pack(anchor="w")
        sub = tk.Label(inner, text="", bg=CARD, fg=MUTED, font=(FONT, 8))
        sub.pack(anchor="w")
        return val, sub

    def _build_right(self, parent):
        stats = tk.Frame(parent, bg=BG, height=96)
        stats.pack(fill="x")
        stats.pack_propagate(False)
        self.v_cpu, self.s_cpu = self._stat_card(stats, "CPU 占用率")
        self.v_mem, self.s_mem = self._stat_card(stats, "内存（私有工作集）")
        self.v_n, self.s_n = self._stat_card(stats, "样本数")
        self.v_dur, self.s_dur = self._stat_card(stats, "已监控时长")
        tk.Frame(stats, bg=BG, width=2).pack(side="left")

        # 整机实时读数（与任务管理器「性能」页对照）
        self.sysbar = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                               highlightthickness=1)
        self.sysbar.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(self.sysbar, bg=CARD, padx=12, pady=6)
        inner.pack(fill="x")
        tk.Label(inner, text="本机实时", bg=CARD, fg=MUTED,
                 font=(FONT, 8)).pack(side="left", padx=(0, 10))
        self.v_sys_cpu = tk.Label(inner, text="CPU —", bg=CARD, fg="#1E293B",
                                  font=(FONT, 9, "bold"))
        self.v_sys_cpu.pack(side="left", padx=(0, 16))
        self.v_sys_mem = tk.Label(inner, text="内存 —", bg=CARD, fg="#1E293B",
                                  font=(FONT, 9, "bold"))
        self.v_sys_mem.pack(side="left", padx=(0, 16))
        self.v_sys_mem_bar = tk.Canvas(inner, height=8, width=120, bg="#E2E8F0",
                                       highlightthickness=0)
        self.v_sys_mem_bar.pack(side="left")

        self.chart = LiveChart(parent)
        self.chart.pack(fill="both", expand=True, pady=(12, 12))

        logbox = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        logbox.pack(fill="x")
        hdr = tk.Frame(logbox, bg=CARD)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(hdr, text="运行日志", bg=CARD, fg=DARK,
                 font=(FONT, 9, "bold")).pack(side="left")
        self.lbl_out = tk.Label(hdr, text="", bg=CARD, fg=MUTED, font=(FONT, 8))
        self.lbl_out.pack(side="right")
        self.txt_log = tk.Text(logbox, height=5, bg=CARD, fg="#334155", font=("Consolas", 9),
                               relief="flat", wrap="word", state="disabled")
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=(4, 8))

    def _build_statusbar(self):
        bar = tk.Frame(self, bg="#E2E8F0", height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.lbl_status = tk.Label(bar, text="就绪：选择进程后点击「开始监控」", bg="#E2E8F0",
                                   fg="#475569", font=(FONT, 9))
        self.lbl_status.pack(side="left", padx=14)
        tk.Label(bar, text="v%s · 输出目录 output/" % VERSION, bg="#E2E8F0",
                 fg="#94A3B8", font=(FONT, 8)).pack(side="right", padx=14)

    # ------------------------------------------------------------------
    # 进程列表
    # ------------------------------------------------------------------
    def _refresh_process_list(self):
        try:
            self.catalog.refresh(force=True)
            groups = self.catalog.grouped()
        except Exception:
            return
        filt = self.var_filter.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        items = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
        shown = 0
        for name, pids in items:
            if filt and filt not in name.lower():
                continue
            pids = sorted(pids)
            pid_txt = ",".join(str(p) for p in pids[:3]) + ("…" if len(pids) > 3 else "")
            self.tree.insert("", "end", values=(name, len(pids), pid_txt))
            shown += 1
            if shown >= 300:
                break
        self.lbl_count.config(text="共 %d 个进程，显示 %d 个" % (len(groups), shown))

    def _on_pick(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if vals:
            self.var_target.set(vals[0])

    def _interval(self):
        try:
            iv = float(self.var_interval.get())
        except Exception:
            iv = 2.0
        return min(60.0, max(1.0, iv))

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def _on_start(self):
        if self.generating:
            return
        if self.monitor is not None and self.monitor.state in ("running", "paused"):
            return
        target = (self.var_target.get() or self.var_filter.get()).strip()
        if not target:
            messagebox.showwarning("未选择进程", "请先在上方列表选择进程，或直接输入进程名。", parent=self)
            return
        by_name = self.var_mode.get() == "name"
        iv = self._interval()

        if by_name:
            pids = self.catalog.by_name(target)
            if not pids:
                if not messagebox.askyesno(
                        "未找到进程",
                        "当前没有名为「%s」的进程在运行。\n仍开始监控吗？（期间启动该进程也会被统计）" % target,
                        parent=self):
                    return
            mon = Monitor(target, by_name=True, interval=iv, sysinfo=self.sysinfo)
            display = target
        else:
            try:
                pid = int(target)
            except ValueError:
                messagebox.showwarning("PID 无效", "按 PID 模式时，请在筛选框输入数字 PID。", parent=self)
                return
            img = winapi.pid_image_name(pid)
            if not img:
                messagebox.showwarning("PID 不存在", "系统中找不到 PID %d（可能已退出或无权限）。" % pid,
                                       parent=self)
                return
            mon = Monitor(img, pid=pid, by_name=False, interval=iv, sysinfo=self.sysinfo)
            display = "%s (PID %d)" % (img, pid)

        self.monitor = mon
        self._log_seen = 0
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")
        self.lbl_out.config(text="")
        self._log("开始监控 %s，采样间隔 %.0f 秒" % (display, iv))
        ok = mon.start()
        if not ok:
            messagebox.showerror("启动失败", "采样线程未能启动，请重试。", parent=self)
            self.monitor = None
            return
        self._set_state("运行中", GREEN, "#14532D")
        self.lbl_status.config(text="监控中：%s · 每 %.0f 秒采样一次" % (display, iv))

    def _on_pause(self):
        m = self.monitor
        if m is None or self.generating:
            return
        if m.state == "running":
            m.pause()
            self._log("已暂停采样（暂停期间不记录数据）")
            self._set_state("已暂停", AMBER, "#78350F")
            self.btn_pause.config(text="继续")
        elif m.state == "paused":
            m.resume()
            self._log("已恢复采样")
            self._set_state("运行中", GREEN, "#14532D")
            self.btn_pause.config(text="暂停")

    def _on_stop(self):
        m = self.monitor
        if m is None or self.generating:
            return
        m.stop()
        samples = m.snapshot()
        self._set_state("生成中", "#1D4ED8", "#1E3A8A")
        self.btn_start.state(["disabled"])
        self.btn_pause.state(["disabled"])
        self.btn_stop.state(["disabled"])
        self.lbl_status.config(text="正在生成 Excel 与性能报告…")

        if len(samples) < 3:
            self.generating = False
            self._set_state("数据不足", MUTED, "#E2E8F0")
            self.lbl_status.config(text="样本太少，未生成产物（至少需要 3 条样本）")
            messagebox.showinfo("样本不足",
                                "本次只采集到 %d 条样本，不足以分析。\n请至少监控 10 秒后重试。" % len(samples),
                                parent=self)
            self.monitor = None
            self._sync_buttons()
            return

        self.generating = True
        self._job_done = None
        self._job_error = None
        t = threading.Thread(target=self._generate, args=(m, samples), name="report", daemon=True)
        t.start()

    def _on_close(self):
        try:
            if self.monitor is not None and self.monitor.running:
                if not messagebox.askyesno("正在监控", "监控尚未停止，退出将丢弃本次数据。确定退出？",
                                           parent=self):
                    return
                self.monitor.stop(wait=False)
        except Exception:
            pass
        self.destroy()

    def _open_output(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        try:
            os.startfile(OUTPUT_DIR)
        except Exception as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    # ------------------------------------------------------------------
    # 产物生成（后台线程，结果回主线程处理）
    # ------------------------------------------------------------------
    def _build_meta(self, m, samples):
        started = m.started_at or datetime.now()
        finished = m.finished_at or datetime.now()
        dur = samples[-1].rel_s if samples else 0.0
        src = m.mem_source or "private"
        return {
            "target": m.name,
            "by_name": bool(m.by_name),
            "pids": list(m.last_pids) or ([m.pid] if m.pid else []),
            "started_at_text": started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at_text": finished.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": round(dur, 1),
            "duration_text": fmt_dur(dur),
            "interval": m.interval,
            "sample_count": len(samples),
            "cores": self.sysinfo.get("cores") or 1,
            "total_phys_mb": self.sysinfo.get("total_phys_mb") or 0,
            "mem_source": src,
            "mem_source_text": ("PROCESS_MEMORY_COUNTERS_EX2（私有工作集）" if src == "private"
                                else "工作集（旧系统回退，非任务管理器口径）"),
            "exited": bool(m.exited),
            "exited_at_text": (m.exited_at.strftime("%Y-%m-%d %H:%M:%S")
                               if getattr(m, "exited_at", None) else ""),
            "paused_count": getattr(m, "paused_count", 0),
            "tool_version": VERSION,
            "os": "%s Build %s" % (self.sysinfo.get("os_name"), self.sysinfo.get("os_build")),
        }

    def _generate(self, m, samples):
        try:
            meta = self._build_meta(m, samples)
            analysis = analyzer.analyze(samples, meta, self.thresholds)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join(OUTPUT_DIR, "%s_%s" % (_safe_name(m.name), stamp))
            os.makedirs(out_dir, exist_ok=True)

            xlsx = os.path.join(out_dir, "%s.xlsx" % NAMES["excel"])
            excel_writer.write_workbook(xlsx, samples, meta, analysis, self.thresholds,
                                        self.sysinfo)
            html_path, md_path = report_writer.write_reports(
                out_dir, samples, meta, analysis, self.thresholds, self.sysinfo, NAMES)
            with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"meta": meta, "thresholds": self.thresholds,
                           "analysis": self._analysis_brief(analysis)},
                          f, ensure_ascii=False, indent=2)

            self._job_done = {"dir": out_dir, "xlsx": xlsx, "html": html_path,
                              "md": md_path, "analysis": analysis, "meta": meta}
        except Exception:
            self._job_error = traceback.format_exc()

    @staticmethod
    def _analysis_brief(a):
        def brief(block):
            return {"verdict": block.get("verdict"), "label": block.get("label"),
                    "reasons": block.get("reasons")}
        return {"overall": a.get("overall"), "cpu": brief(a.get("cpu", {})),
                "mem": brief(a.get("mem", {})), "release": brief(a.get("release", {}))}

    def _handle_result(self):
        if self._job_error:
            tb = self._job_error
            self._job_error = None
            self.generating = False
            self.monitor = None
            self._set_state("出错", RED, "#7F1D1D")
            self.lbl_status.config(text="生成产物失败，详见日志")
            self._log("生成失败：\n" + tb.strip().splitlines()[-1])
            messagebox.showerror("生成失败", "写入 Excel / 报告时出错：\n\n%s" % tb[-1200:], parent=self)
            self._sync_buttons()
            return

        if not self._job_done:
            return
        r = self._job_done
        self._job_done = None
        self.generating = False
        verdict = r["analysis"].get("overall_text") or "—"
        self._set_state("已完成", "#1D4ED8", "#1E3A8A")
        self.lbl_status.config(text="已生成：%s" % os.path.basename(r["dir"]))
        self.lbl_out.config(text=os.path.basename(r["dir"]))
        self._log("产物已写入：%s" % r["dir"])
        self._log("综合判定：%s" % verdict)
        self.monitor = None
        self._sync_buttons()
        if messagebox.askyesno(
                "完成",
                "采集与判定完成，综合结论：%s\n\n输出目录：\n%s\n\n是否打开该目录？" % (verdict, r["dir"]),
                parent=self):
            try:
                os.startfile(r["dir"])
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 轮询刷新
    # ------------------------------------------------------------------
    def _poll(self):
        try:
            self._refresh_view()
            self._handle_result()
        except Exception as exc:  # 不再静默：刷新异常必须可见
            self.lbl_status.config(text="界面刷新异常：%s" % (exc,))
            if not getattr(self, "_poll_err_logged", False):
                self._poll_err_logged = True
                self._log("界面刷新异常：%r" % (exc,))
                traceback.print_exc()
        self.after(400, self._poll)

    def _refresh_view(self):
        m = self.monitor
        if m is None:
            self._sync_buttons()
            return
        samples = m.snapshot()
        self.chart.set_samples(m.snapshot(240))

        last = samples[-1] if samples else None
        cpu_vals = [s.cpu_pct for s in samples if s.cpu_pct is not None]
        mem_vals = [s.priv_mb for s in samples if s.priv_mb]
        if last is not None:
            cur_cpu = last.cpu_pct
            self.v_cpu.config(text="%.1f%%" % cur_cpu if cur_cpu is not None else "—")
            if cpu_vals:
                self.s_cpu.config(text="平均 %.1f%% · 峰值 %.1f%%" % (
                    sum(cpu_vals) / len(cpu_vals), max(cpu_vals)))
            self.v_mem.config(text="%.1f MB" % last.priv_mb if last.priv_mb else "—")
            if mem_vals:
                self.s_mem.config(text="峰值 %.1f MB · 占物理内存 %.1f%%" % (
                    max(mem_vals), max(mem_vals) / (self.sysinfo.get("total_phys_mb") or 1) * 100))
            self.v_n.config(text="%d" % len(samples))
            self.s_n.config(text="目标 %d 个实例" % len(m.last_pids))
            self.v_dur.config(text=fmt_dur(last.rel_s))
            self.s_dur.config(text="每 %.0f 秒采样" % m.interval)

            # 目标进程内存来源（句柄直读 / 系统通道）
            src = getattr(last, "mem_source", None)
            src_label = {"ex2": "句柄直读", "private": "句柄直读",
                         "sysinfo": "系统通道", "fallback_ws": "工作集回退",
                         "mixed": "混合来源", "denied": "读取失败"}.get(src or "", "")
            if src and self.s_mem.cget("text"):
                self.s_mem.config(text=self.s_mem.cget("text") + " · " + src_label)
            elif src == "denied":
                self.s_mem.config(text="内存读取失败（进程受保护或已退出）")

            # 整机实时读数
            scpu = getattr(last, "sys_cpu_pct", None)
            smem = getattr(last, "sys_mem_pct", None)
            self.v_sys_cpu.config(text="CPU %s" % (
                "%.1f%%" % scpu if scpu is not None else "—"))
            if smem is not None:
                total = self.sysinfo.get("total_phys_mb") or 0
                self.v_sys_mem.config(text="内存 %.1f%%（%.0f / %.0f MB）" % (
                    smem, total * smem / 100.0, total))
                self._draw_mem_bar(smem)
            else:
                self.v_sys_mem.config(text="内存 —")

        # 事件日志
        events = list(m.events)
        for ev in events[self._log_seen:]:
            self._log("%s %s" % (ev[0].strftime("%H:%M:%S"), ev[2]))
        self._log_seen = len(events)

        if m.error and m.state != "stopped":
            self.lbl_status.config(text="错误：%s" % m.error)
        if m.exited and not getattr(self, "_exited_logged", False):
            self._log("目标进程已退出，继续采集将没有数据（可停止并生成报告）")
            self._exited_logged = True
        self._sync_buttons()

    def _draw_mem_bar(self, pct):
        """整机内存占用率小条（与任务管理器「性能」页内存百分比同口径）。"""
        c = self.v_sys_mem_bar
        w = int(c.cget("width"))
        h = int(c.cget("height"))
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill="#E2E8F0", outline="")
        pct = max(0.0, min(100.0, float(pct)))
        fill = "#16A34A" if pct < 70 else ("#D97706" if pct < 90 else "#DC2626")
        c.create_rectangle(0, 0, max(1, w * pct / 100.0), h, fill=fill, outline="")

    def _sync_buttons(self):
        m = self.monitor
        running = m is not None and m.state in ("running", "paused") and not self.generating
        if self.generating:
            self.btn_start.state(["disabled"])
            self.btn_pause.state(["disabled"])
            self.btn_stop.state(["disabled"])
            return
        if running:
            self.btn_start.state(["disabled"])
            self.btn_pause.state(["!disabled"])
            self.btn_stop.state(["!disabled"])
            self.btn_pause.config(text="继续" if m.state == "paused" else "暂停")
        else:
            self.btn_start.state(["!disabled"])
            self.btn_pause.state(["disabled"])
            self.btn_stop.state(["disabled"])
            self.btn_pause.config(text="暂停")

    def _set_state(self, text, bg, fg=None):
        self.lbl_state.config(text=text, bg=bg, fg=fg or "white")

    def _log(self, text):
        try:
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", text + "\n")
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")
        except Exception:
            pass
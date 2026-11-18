# -*- coding: utf-8 -*-
"""采样服务：固定节拍采集目标进程的 CPU / 内存，线程安全。

设计要点：
- 采样线程只做采集与缓冲，不做任何文件 IO；
- 用单调时钟（perf_counter）排节拍，按「实际间隔」计算 CPU%，避免采样抖动污染结果；
- 暂停时完全停止采样，恢复时重建基线（否则暂停区间会被算进 CPU 分母）。
"""

import ctypes
import threading
import time
from datetime import datetime

from . import winapi

# 状态
IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"


class Sample(object):
    __slots__ = (
        "seq", "ts", "rel_s", "dt_ms", "cpu_ms", "cpu_pct", "cores",
        "cpu_total_s", "priv_mb", "ws_mb", "commit_mb", "mem_pct",
        "threads", "handles", "instances", "note", "mem_source",
        "sys_mem_pct", "sys_cpu_pct",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self):
        return dict((k, getattr(self, k)) for k in self.__slots__)


class _Snapshot(object):
    __slots__ = ("t", "pids", "per_pid", "priv", "ws", "commit",
                 "threads", "handles", "mem_ok", "mem_source", "mem_denied_pids")

    def __init__(self):
        self.t = 0.0
        self.pids = []
        self.per_pid = {}      # pid -> (creation, kernel, user)
        self.priv = 0
        self.ws = 0
        self.commit = 0
        self.threads = 0
        self.handles = 0
        self.mem_ok = False
        self.mem_source = None
        self.mem_denied_pids = []


class Monitor(object):
    """一次监控会话。UI 只通过 start/pause/resume/stop 与只读属性交互。"""

    def __init__(self, name, pid=None, by_name=True, interval=2.0, sysinfo=None):
        self.name = name
        self.pid = pid
        self.by_name = bool(by_name)
        self.interval = float(interval) if interval and interval > 0 else 2.0
        self.sysinfo = sysinfo or winapi.system_info()
        self.cores = max(1, int(self.sysinfo.get("cores") or 1))
        self.total_mb = float(self.sysinfo.get("total_phys_mb") or 0.0)

        self.state = IDLE
        self.samples = []
        self.events = []          # [(datetime, kind, text)]
        self.error = None
        self.exited = False
        self.exited_at = None
        self.started_at = None
        self.finished_at = None

        self._lock = threading.RLock()
        self._thread = None
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._start_perf = 0.0
        self._paused_total = 0.0
        self._pending_note = ""

        # 句柄缓存（跨采样复用，避免每 2s 重开全部实例）
        self._handles = {}
        self._catalog = winapi.ProcessCatalog()
        self._mem_warned = False
        self.mem_source = None
        self.last_pids = []         # 最近一次快照命中的 PID 集合
        self.paused_count = 0
        self._prev_sys_total = None    # 整机 CPU 基线（GetSystemTimes）
        self._prev_sys_busy = None

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self.state = RUNNING
        self.started_at = datetime.now()
        self._start_perf = time.perf_counter()
        self._stop_evt.clear()
        self._pause_evt.clear()
        try:
            # 把系统定时器精度提到 1ms，2 秒节拍才能稳在 ±100ms 内
            ctypes.windll.winmm.timeBeginPeriod(1)
            self._timer_tight = True
        except Exception:
            self._timer_tight = False
        self._thread = threading.Thread(target=self._run, name="sampler", daemon=True)
        self._thread.start()
        return True

    def pause(self):
        if self.state != RUNNING:
            return False
        self._pause_evt.set()
        with self._lock:
            self.state = PAUSED
        self.paused_count += 1
        self._event("pause", "暂停采样")
        return True

    def resume(self):
        if self.state != PAUSED:
            return False
        self._pause_evt.clear()
        with self._lock:
            self.state = RUNNING
        return True

    def stop(self, wait=True):
        if self.state == STOPPED:
            return self.samples
        self._stop_evt.set()
        self._pause_evt.clear()
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        with self._lock:
            self.state = STOPPED
            self.finished_at = datetime.now()
            self._close_handles()
        if getattr(self, "_timer_tight", False):
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
            self._timer_tight = False
        self._event("stop", "结束监控")
        return self.samples

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def elapsed(self):
        """有效监控时长（不含暂停）。"""
        if not self._start_perf:
            return 0.0
        end = time.perf_counter()
        paused = self._paused_total
        if self.state == PAUSED and self._pause_started:
            paused += end - self._pause_started
        return max(0.0, end - self._start_perf - paused)

    def sample_count(self):
        with self._lock:
            return len(self.samples)

    def snapshot(self, last_n=None):
        """返回采样列表副本，供 UI 渲染。"""
        with self._lock:
            data = self.samples if last_n is None else self.samples[-last_n:]
            return list(data)

    def latest(self):
        with self._lock:
            return self.samples[-1] if self.samples else None

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    _pause_started = None

    def _event(self, kind, text):
        with self._lock:
            self.events.append((datetime.now(), kind, text))

    def _close_handles(self):
        for h in self._handles.values():
            try:
                h.close()
            except Exception:
                pass
        self._handles.clear()

    def _handle_for(self, pid, creation):
        h = self._handles.get(pid)
        if h is not None and h.valid:
            # PID 复用校验：创建时间变化说明是另一个进程
            times = h.cpu_times()
            if times and creation and times[0] != creation:
                h.close()
                self._handles.pop(pid, None)
                h = None
        if h is None or not h.valid:
            h = winapi.ProcHandle(pid)
            if not h.valid:
                return None
            self._handles[pid] = h
        return h

    def _snapshot(self):
        # 首次取样必须强制刷新，否则缓存未建立时会拿到空名字表
        names = self._catalog.refresh(force=not getattr(self._catalog, "_names", None))
        if self.by_name:
            pids = [p for p, nm in names.items() if nm.lower() == self.name.lower()]
        else:
            pids = [self.pid] if self.pid in names else []

        if not pids:
            return None

        # 清理已退出实例的句柄
        for pid in list(self._handles.keys()):
            if pid not in pids:
                try:
                    self._handles[pid].close()
                except Exception:
                    pass
                del self._handles[pid]

        snap = _Snapshot()
        snap.t = time.perf_counter()
        snap.pids = sorted(pids)
        self.last_pids = list(snap.pids)

        threads = winapi.thread_counts(pids)
        for pid in pids:
            h = self._handle_for(pid, None)
            if h is None:
                continue
            times = h.cpu_times()
            if times is None:
                continue
            snap.per_pid[pid] = times
            # 句柄读不到内存时自动走系统进程表（NtQuerySystemInformation），
            # 这是任务管理器「性能」页汇总所用的同一条通道，普通权限即可读。
            mem = winapi.memory_of(h, pid)
            if mem and mem.get("private_source") != "denied":
                snap.mem_ok = True
                src = mem.get("private_source")
                if snap.mem_source is None:
                    snap.mem_source = src
                    self.mem_source = src
                elif src and src != snap.mem_source:
                    # 多实例来源不一致时标记为 mixed，避免报告误报单一来源
                    if src != "ex2" or snap.mem_source != "ex2":
                        snap.mem_source = "mixed"
                        self.mem_source = "mixed"
                snap.priv += mem["private_ws"]
                snap.ws += mem["working_set"]
                snap.commit += mem["commit"]
            else:
                snap.mem_denied_pids.append(pid)
            hc = h.handle_count()
            if hc:
                snap.handles += hc
            snap.threads += threads.get(pid, 0)

        if not snap.per_pid:
            return None
        return snap

    def _make_sample(self, snap, prev, note=""):
        s = Sample()
        s.seq = len(self.samples) + 1
        s.ts = datetime.now()
        s.rel_s = max(0.0, snap.t - self._start_perf - self._paused_total)
        s.instances = len(snap.pids)
        s.threads = snap.threads
        s.handles = snap.handles
        s.priv_mb = snap.priv / 1048576.0
        s.ws_mb = snap.ws / 1048576.0
        s.commit_mb = snap.commit / 1048576.0
        s.mem_pct = (s.priv_mb / self.total_mb * 100.0) if self.total_mb else 0.0
        s.cpu_total_s = sum((v[1] + v[2]) for v in snap.per_pid.values()) / 1e7
        s.mem_source = snap.mem_source if snap.mem_ok else "denied"

        # 整机读数（界面第 4 区「电脑总体」与任务管理器「性能」页对照用）
        sysmem = winapi.system_memory_status()
        if sysmem:
            s.sys_mem_pct = sysmem["pct"]
        st = winapi.system_times()
        if st and self._prev_sys_busy is not None:
            d_total = st["total"] - self._prev_sys_total
            d_busy = st["busy"] - self._prev_sys_busy
            if d_total > 0:
                s.sys_cpu_pct = max(0.0, min(100.0, d_busy * 100.0 / d_total))
        if st:
            self._prev_sys_total = st["total"]
            self._prev_sys_busy = st["busy"]

        notes = []
        if note:
            notes.append(note)

        if prev is None:
            s.dt_ms = 0.0
            s.cpu_ms = None
            s.cpu_pct = None
            s.cores = None
        else:
            dt = snap.t - prev.t
            s.dt_ms = dt * 1000.0
            delta = 0
            matched = 0
            for pid, (c, k, u) in snap.per_pid.items():
                p = prev.per_pid.get(pid)
                if p and p[0] == c:
                    delta += (k + u) - (p[1] + p[2])
                    matched += 1
            if s.dt_ms > 0 and matched:
                s.cpu_ms = delta / 10000.0
                s.cores = s.cpu_ms / s.dt_ms
                s.cpu_pct = s.cores / self.cores * 100.0
            else:
                s.cpu_ms = None
                s.cpu_pct = None
                s.cores = None

            if len(snap.pids) != len(prev.pids):
                notes.append("实例数 %d→%d" % (len(prev.pids), len(snap.pids)))

        if not snap.mem_ok:
            notes.append("内存不可读（权限不足）")
            if not self._mem_warned:
                self._mem_warned = True
        s.note = "；".join(notes)
        return s

    def _append(self, sample):
        with self._lock:
            self.samples.append(sample)

    def _run(self):
        try:
            snap = self._snapshot()
            if snap is None:
                self.error = "未找到目标进程：%s" % self.name
                self._event("error", self.error)
                with self._lock:
                    self.state = STOPPED
                return

            prev = snap
            self._append(self._make_sample(snap, None, note="开始"))

            next_t = time.perf_counter() + self.interval
            while not self._stop_evt.is_set():
                # 等待到下一个采样点（可被暂停/停止打断）
                while True:
                    if self._stop_evt.is_set():
                        return
                    if self._pause_evt.is_set():
                        break
                    remain = next_t - time.perf_counter()
                    if remain <= 0:
                        break
                    time.sleep(min(0.05, remain))

                if self._stop_evt.is_set():
                    return

                if self._pause_evt.is_set():
                    pause_begin = time.perf_counter()
                    with self._lock:
                        self.state = PAUSED
                    self._pause_started = pause_begin
                    while self._pause_evt.is_set() and not self._stop_evt.is_set():
                        time.sleep(0.05)
                    if self._stop_evt.is_set():
                        return
                    paused_secs = time.perf_counter() - pause_begin
                    self._paused_total += paused_secs
                    self._pause_started = None
                    with self._lock:
                        self.state = RUNNING

                    # 恢复：重建基线，暂停区间不计入 CPU 分母
                    snap = self._snapshot()
                    if snap is None:
                        self._mark_exited()
                        return
                    prev = snap
                    self._pending_note = "恢复（暂停 %.1f 秒）" % paused_secs
                    next_t = time.perf_counter() + self.interval
                    continue

                snap = self._snapshot()
                if snap is None:
                    self._mark_exited()
                    return

                note = self._pending_note
                self._pending_note = ""
                self._append(self._make_sample(snap, prev, note=note))
                prev = snap

                next_t += self.interval
                # 落后超过一个周期就重新对齐，避免"补采样"造成密集点
                if next_t < time.perf_counter() - self.interval:
                    next_t = time.perf_counter()
        except Exception:
            import traceback

            self.error = traceback.format_exc()
            self._event("error", "采样异常：%s" % self.error.splitlines()[-1])
            with self._lock:
                self.state = STOPPED
        finally:
            with self._lock:
                if self.state != STOPPED:
                    self.state = STOPPED
                self.finished_at = self.finished_at or datetime.now()

    def _mark_exited(self):
        self.exited = True
        self.exited_at = datetime.now()
        self._event("exited", "目标进程已退出")
        with self._lock:
            self.state = STOPPED
            self.finished_at = datetime.now()
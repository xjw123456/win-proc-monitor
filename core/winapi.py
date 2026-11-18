# -*- coding: utf-8 -*-
"""Win32 采集层。

只依赖 ctypes，不引入第三方进程库。所有函数都做了 argtypes/restype 声明，
避免 64 位下指针被截断（这是 ctypes 调 Win32 最常见的坑）。

口径说明：
- CPU 时间来自 GetProcessTimes（内核态+用户态，单位 100ns）；
- 私有工作集来自 GetProcessMemoryInfo 的 PROCESS_MEMORY_COUNTERS_EX2.PrivateWorkingSetSize，
  与任务管理器「内存」列同源；旧系统该字段为 0 时回退到工作集并标记来源；
- 打不开进程句柄（权限不足 / 系统/受保护进程）时，改用 NtQuerySystemInformation
  (SystemProcessInformation) 的 WorkingSetPrivateSize，这是任务管理器「性能」页汇总所用的同一条通道，
  普通权限即可读，来源记为 sysinfo。
"""

import ctypes
import ctypes.wintypes as w
import sys

ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

TH32CS_SNAPTHREAD = 0x00000004
SystemProcessInformation = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


# --------------------------------------------------------------------------
# 结构体
# --------------------------------------------------------------------------
class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", w.DWORD), ("dwHighDateTime", w.DWORD)]

    @property
    def value(self):
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class PROCESS_MEMORY_COUNTERS_EX2(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("PageFaultCount", w.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
        ("PrivateWorkingSetSize", ctypes.c_size_t),
        ("SharedCommitUsage", ctypes.c_size_t),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", w.DWORD),
        ("cntUsage", w.DWORD),
        ("th32ThreadID", w.DWORD),
        ("th32OwnerProcessID", w.DWORD),
        ("tpBasePri", w.LONG),
        ("tpDeltaPri", w.LONG),
        ("dwFlags", w.DWORD),
    ]


class FILETIME_IDLE_KERNEL_USER(ctypes.Structure):
    """GetSystemTimes 的三段系统时间（idle / kernel / user），单位 100ns。"""

    _fields_ = [("idle", FILETIME), ("kernel", FILETIME), ("user", FILETIME)]

    @property
    def busy(self):
        # kernel 时间已包含 idle，所以 busy = kernel - idle + user
        return self.kernel.value - self.idle.value + self.user.value

    @property
    def total(self):
        return self.kernel.value + self.user.value


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", w.DWORD),
        ("dwMemoryLoad", w.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


# --------------------------------------------------------------------------
# 原型声明
# --------------------------------------------------------------------------
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE

kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.CloseHandle.restype = w.BOOL

kernel32.GetProcessTimes.argtypes = [
    w.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
]
kernel32.GetProcessTimes.restype = w.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = w.BOOL

kernel32.GetProcessHandleCount.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
kernel32.GetProcessHandleCount.restype = w.BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = w.HANDLE

kernel32.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32First.restype = w.BOOL
kernel32.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32Next.restype = w.BOOL

kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
kernel32.GlobalMemoryStatusEx.restype = w.BOOL

kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME),
                                    ctypes.POINTER(FILETIME),
                                    ctypes.POINTER(FILETIME)]
kernel32.GetSystemTimes.restype = w.BOOL

kernel32.GetActiveProcessorCount.argtypes = [w.WORD]
kernel32.GetActiveProcessorCount.restype = w.DWORD

psapi.EnumProcesses.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD, ctypes.POINTER(w.DWORD)]
psapi.EnumProcesses.restype = w.BOOL

psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
psapi.GetProcessMemoryInfo.restype = w.BOOL

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = w.BOOL

ntdll.NtQuerySystemInformation.argtypes = [w.ULONG, ctypes.c_void_p, w.ULONG,
                                           ctypes.POINTER(w.ULONG)]
ntdll.NtQuerySystemInformation.restype = w.LONG


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def system_info():
    """系统基本信息：逻辑处理器数、物理内存、Windows 版本。"""
    cores = int(kernel32.GetActiveProcessorCount(0xFFFF)) or 1
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    total_bytes = 0
    avail_bytes = 0
    if kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        total_bytes = int(mem.ullTotalPhys)
        avail_bytes = int(mem.ullAvailPhys)

    ver = sys.getwindowsversion()
    build = ver.build
    if build >= 22000:
        os_name = "Windows 11"
    elif build >= 10240:
        os_name = "Windows 10"
    else:
        os_name = "Windows %s" % ver.platform_version

    return {
        "cores": cores,
        "total_phys_bytes": total_bytes,
        "total_phys_mb": total_bytes / 1048576.0,
        "avail_phys_mb": avail_bytes / 1048576.0,
        "os_name": os_name,
        "os_build": build,
        "os_version": "%d.%d.%d" % (ver.major, ver.minor, build),
        "python": "%s (%d-bit)" % (sys.version.split()[0], ctypes.sizeof(ctypes.c_void_p) * 8),
        "is_admin": is_admin(),
        "arch64": ctypes.sizeof(ctypes.c_void_p) == 8,
    }


def system_times():
    """返回整机 CPU 时间快照 {idle, kernel, user, busy, total}（100ns）；失败返回 None。"""
    t = FILETIME_IDLE_KERNEL_USER()
    if not kernel32.GetSystemTimes(ctypes.byref(t.idle), ctypes.byref(t.kernel),
                                  ctypes.byref(t.user)):
        return None
    return {"idle": t.idle.value, "kernel": t.kernel.value, "user": t.user.value,
            "busy": t.busy, "total": t.total}


def system_memory_status():
    """整机内存：返回 {total_mb, avail_mb, used_mb, pct}；失败返回 None。"""
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    total = int(m.ullTotalPhys)
    avail = int(m.ullAvailPhys)
    used = max(0, total - avail)
    return {
        "total_mb": total / 1048576.0,
        "avail_mb": avail / 1048576.0,
        "used_mb": used / 1048576.0,
        "pct": (used / total * 100.0) if total else 0.0,
    }


def enum_pids():
    """枚举所有 PID（不打开句柄，开销极低）。"""
    arr = (w.DWORD * 4096)()
    needed = w.DWORD(0)
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    count = needed.value // ctypes.sizeof(w.DWORD)
    return [arr[i] for i in range(count) if arr[i]]


def pid_image_name(pid):
    """取进程映像基础名（不含路径），无权限时返回 None。"""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        full = buf.value
        return full.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(h)


def pid_full_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(h)


# --------------------------------------------------------------------------
# 进程句柄包装
# --------------------------------------------------------------------------
class ProcHandle(object):
    """一个进程的采集句柄；内存不可读时 limited=True，只提供 CPU 数据。"""

    __slots__ = ("pid", "h", "limited", "mem_denied")

    def __init__(self, pid):
        self.pid = pid
        self.h = None
        self.limited = False
        self.mem_denied = False
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if h:
            self.h = h
        else:
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                self.h = h
                self.limited = True

    @property
    def valid(self):
        return bool(self.h)

    def close(self):
        if self.h:
            kernel32.CloseHandle(self.h)
            self.h = None

    # -- CPU --------------------------------------------------------------
    def cpu_times(self):
        """返回 (creation, kernel, user)，单位 100ns；失败返回 None。"""
        if not self.h:
            return None
        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        ok = kernel32.GetProcessTimes(
            self.h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)
        )
        if not ok:
            return None
        return (c.value, k.value, u.value)

    # -- 内存 -------------------------------------------------------------
    def memory(self):
        """返回字节字典；无权限返回 None。private_source 标明私有工作集来源。"""
        if not self.h or self.limited:
            self.mem_denied = True
            return None
        m = PROCESS_MEMORY_COUNTERS_EX2()
        m.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX2)
        if not psapi.GetProcessMemoryInfo(self.h, ctypes.byref(m), m.cb):
            self.mem_denied = True
            return None
        private_ws = int(m.PrivateWorkingSetSize)
        source = "ex2"
        if private_ws <= 0:
            private_ws = int(m.WorkingSetSize)
            source = "fallback_ws"
        return {
            "working_set": int(m.WorkingSetSize),
            "peak_working_set": int(m.PeakWorkingSetSize),
            "private_ws": private_ws,
            "private_source": source,
            "commit": int(m.PagefileUsage),
            "peak_commit": int(m.PeakPagefileUsage),
            "private_commit": int(m.PrivateUsage),
            "page_faults": int(m.PageFaultCount),
        }

    # -- 句柄数 -----------------------------------------------------------
    def handle_count(self):
        if not self.h:
            return None
        n = w.DWORD(0)
        if kernel32.GetProcessHandleCount(self.h, ctypes.byref(n)):
            return int(n.value)
        return None


# --------------------------------------------------------------------------
# 系统级进程表（权限不足时的内存回退通道）
#
# NtQuerySystemInformation(SystemProcessInformation) 是任务管理器「性能」页
# 汇总进程内存所用的同一条通道，普通权限即可读取任意进程（含系统/受保护进程）的
# 私有工作集。偏移已用 PROCESS_MEMORY_COUNTERS_EX2 逐进程比对验证（误差 0.00 MB）：
#   +0  NextEntryOffset(u32)      +8  WorkingSetPrivateSize(i64)
#   +12 CreateTime                +56 ImageName(UNICODE_STRING: Length u16 / Buffer ptr at +64)
#   +80 UniqueProcessId(u64)
# 注意：与部分 mingw 头文件不同，ImageName 在 +56（不是 +40），PID 在 +80（不是 +16）。
# --------------------------------------------------------------------------
_OFS_NEXT = 0
_OFS_PRIVATE_WS = 8
_OFS_IMAGE_NAME = 56
_OFS_IMAGE_PTR = 64
_OFS_PID = 80


def system_process_table():
    """返回 {pid: {"name": str, "private_ws": int, "working_set": int}}；失败返回 {}。"""
    size = 1 << 20
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        ret = w.ULONG(0)
        st = ntdll.NtQuerySystemInformation(
            SystemProcessInformation, buf, size, ctypes.byref(ret))
        st &= 0xFFFFFFFF
        if st == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, int(ret.value))
            continue
        if st != 0:
            return {}
        break
    else:
        return {}

    base = ctypes.addressof(buf)
    out = {}
    off = 0
    count = 0
    while True:
        count += 1
        if count > 4096:
            break
        pid = ctypes.c_void_p.from_address(base + off + _OFS_PID).value or 0
        priv = ctypes.c_int64.from_address(base + off + _OFS_PRIVATE_WS).value
        length = ctypes.c_uint16.from_address(base + off + _OFS_IMAGE_NAME).value
        ptr = ctypes.c_void_p.from_address(base + off + _OFS_IMAGE_PTR).value
        name = ""
        if ptr and length:
            try:
                name = ctypes.wstring_at(ptr, length // 2)
            except OSError:
                name = ""
        if pid:
            out[int(pid)] = {
                "name": name,
                "private_ws": max(0, int(priv)),
                "working_set": 0,
            }
        nxt = ctypes.c_uint32.from_address(base + off + _OFS_NEXT).value
        if not nxt:
            break
        off += nxt
    return out


_SYSINFO_CACHE = {"ts": 0.0, "data": {}, "failed": False}


def system_memory(pid, max_age=0.0):
    """从系统进程表取某个 PID 的私有工作集（字节）；取不到返回 None。

    max_age>0 时会复用这么多秒内取过的快照，避免同一采样点反复查询。
    """
    import time as _time
    now = _time.monotonic()
    if _SYSINFO_CACHE["failed"]:
        return None
    if max_age > 0 and (now - _SYSINFO_CACHE["ts"]) <= max_age and _SYSINFO_CACHE["data"]:
        data = _SYSINFO_CACHE["data"]
    else:
        data = system_process_table()
        _SYSINFO_CACHE["data"] = data
        _SYSINFO_CACHE["ts"] = now
        if not data:
            # 系统通道不可用时（极老系统 / 调用被拒）记一次失败，停止反复重试
            _SYSINFO_CACHE["failed"] = True
            return None
    row = data.get(int(pid))
    return row["private_ws"] if row else None


def memory_of(handle, pid):
    """取一个进程的内存指标。句柄读不到（权限不足）时走系统进程表回退。

    返回 dict，其中 private_source 取值：
      ex2            —— 句柄 + PROCESS_MEMORY_COUNTERS_EX2（首选，信息最全）
      fallback_ws    —— 旧系统 EX2 私有工作集字段为 0，退回工作集
      sysinfo        —— 权限不足，改用 NtQuerySystemInformation 系统通道
      denied         —— 两条通道都取不到（进程已退出 / 受保护）
    """
    mem = handle.memory() if handle is not None else None
    if mem is not None:
        return mem
    priv = system_memory(pid)
    if priv is None:
        return {"private_ws": 0, "private_source": "denied", "working_set": 0,
                "commit": 0, "page_faults": 0, "peak_working_set": 0}
    return {
        "private_ws": int(priv),
        "private_source": "sysinfo",
        "working_set": 0,
        "peak_working_set": 0,
        "commit": 0,
        "peak_commit": 0,
        "private_commit": 0,
        "page_faults": 0,
    }


# --------------------------------------------------------------------------
# 线程数（一次快照统计全部目标 PID，避免逐进程开销）
# --------------------------------------------------------------------------
def thread_counts(pids):
    """返回 {pid: 线程数}，只包含传入的 pids。"""
    wanted = set(pids)
    result = dict((p, 0) for p in wanted)
    if not wanted:
        return result
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return result
    try:
        te = THREADENTRY32()
        te.dwSize = ctypes.sizeof(THREADENTRY32)
        if not kernel32.Thread32First(snap, ctypes.byref(te)):
            return result
        while True:
            owner = int(te.th32OwnerProcessID)
            if owner in result:
                result[owner] += 1
            te.dwSize = ctypes.sizeof(THREADENTRY32)
            if not kernel32.Thread32Next(snap, ctypes.byref(te)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return result


# --------------------------------------------------------------------------
# 进程目录（带缓存，避免每 2s 都打开全部进程）
# --------------------------------------------------------------------------
class ProcessCatalog(object):
    """PID → 映像名 的缓存目录。

    每次 refresh() 只对「新出现的 PID」查询名字，成本基本恒定；
    每 full_every 次做一次全量重建，避免 PID 复用导致的名字陈旧。
    """

    def __init__(self, full_every=8):
        self._names = {}
        self._tick = 0
        self._full_every = max(1, int(full_every))

    def refresh(self, force=False):
        pids = enum_pids()
        self._tick += 1
        full = force or self._tick % self._full_every == 0
        alive = set(pids)

        if full:
            names = {}
            for pid in pids:
                nm = pid_image_name(pid)
                if nm:
                    names[pid] = nm
            self._names = names
        else:
            # 清理已退出
            for pid in list(self._names.keys()):
                if pid not in alive:
                    del self._names[pid]
            # 只查新 PID
            for pid in pids:
                if pid not in self._names:
                    nm = pid_image_name(pid)
                    if nm:
                        self._names[pid] = nm
        return self._names

    def all_pids(self):
        return list(self._names.keys())

    def by_name(self, name):
        low = name.lower()
        return [pid for pid, nm in self._names.items() if nm.lower() == low]

    def name_of(self, pid):
        return self._names.get(pid)

    def grouped(self):
        """{name: [pid, ...]}，按占用不排序（排序交给调用方）。"""
        out = {}
        for pid, nm in self._names.items():
            out.setdefault(nm, []).append(pid)
        return out


def fmt_seconds(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)


def fmt_cpu_time(seconds):
    """把秒格式化成与任务管理器「CPU 时间」一致的 h:mm:ss。"""
    seconds = max(0.0, float(seconds))
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)
# -*- coding: utf-8 -*-
"""确认 SYSTEM_PROCESS_INFORMATION 两个字段的真实偏移。

已知：ImageName.UNICODE_STRING 在 +56（Buffer 指向缓冲区内），UniqueProcessId 在 +80。
未知：WorkingSetPrivateSize / WorkingSetSize 在哪个偏移。
做法：对同一批 PID 同时用 EX2（已知口径）和候选偏移取私有工作集，比较误差。
"""
import ctypes
import ctypes.wintypes as w
import struct

ntdll = ctypes.WinDLL("ntdll")
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.POINTER(w.ULONG)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_long
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.OpenProcess.restype = w.HANDLE
k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
k32.QueryFullProcessImageNameW.restype = w.BOOL
k32.CloseHandle.argtypes = [w.HANDLE]
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
psapi.GetProcessMemoryInfo.restype = w.BOOL

SYS_PROC = 5
MISMATCH = 0xC0000004


class PMC_EX2(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("PageFaultCount", w.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t), ("PrivateWorkingSetSize", ctypes.c_size_t),
        ("SharedCommitUsage", ctypes.c_size_t),
    ]


def query():
    size = 1 << 20
    for _ in range(14):
        buf = ctypes.create_string_buffer(size)
        rl = w.ULONG(0)
        st = ntdll.NtQuerySystemInformation(SYS_PROC, buf, size, ctypes.byref(rl))
        if st == MISMATCH:
            size = max(size * 2, rl.value)
            continue
        if st < 0:
            raise RuntimeError(hex(st & 0xFFFFFFFF))
        return buf
    raise RuntimeError


def table(buf):
    base = ctypes.addressof(buf)
    off = 0
    out = {}
    while True:
        nxt = ctypes.c_uint32.from_address(base + off).value
        pid = ctypes.c_void_p.from_address(base + off + 80).value or 0
        length = ctypes.c_uint16.from_address(base + off + 56).value
        ptr = ctypes.c_void_p.from_address(base + off + 64).value
        name = ""
        if ptr and length:
            name = ctypes.wstring_at(ptr, length // 2)
        vals = {}
        for cand in (8, 16, 24, 32, 40, 48, 72, 88, 96, 104):
            v = struct.unpack_from("<Q", buf.raw, off + cand)[0]
            if 0 <= v < (1 << 42):
                vals[cand] = v
        out[pid] = (name, vals)
        if not nxt:
            break
        off += nxt
    return out


def ex2(pid):
    h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return None
    try:
        m = PMC_EX2()
        m.cb = ctypes.sizeof(PMC_EX2)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb):
            return None
        return int(m.PrivateWorkingSetSize), int(m.WorkingSetSize)
    finally:
        k32.CloseHandle(h)


buf = query()
t = table(buf)
print("entries:", len(t))

# 用可读进程做对比：看哪个偏移最接近 EX2 私有工作集
samples = []
for pid, (name, vals) in t.items():
    e = ex2(pid)
    if not e or e[0] < 5 * 1048576:
        continue
    samples.append((name, pid, e, vals))
    if len(samples) >= 12:
        break

print("name              pid     EX2_priv(MB) EX2_ws(MB) | " + " ".join("%10s" % ("+" + str(c)) for c in (8, 16, 24, 32, 40, 48, 72, 88, 96, 104)))
for name, pid, (priv, ws), vals in samples:
    row = " ".join("%10.1f" % (vals.get(c, 0) / 1048576.0) for c in (8, 16, 24, 32, 40, 48, 72, 88, 96, 104))
    print("%-17s %-7d %10.1f %10.1f | %s" % (name[:17], pid, priv / 1048576.0, ws / 1048576.0, row))
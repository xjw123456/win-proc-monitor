# -*- coding: utf-8 -*-
"""口径探针2：枚举真实进程，验证 EX2.PrivateWorkingSetSize 是否可靠 + PDH 调试。"""
import ctypes
import ctypes.wintypes as w
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("PageFaultCount", w.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class PMC_EX2(ctypes.Structure):
    _fields_ = PMC._fields_ + [("PrivateWorkingSetSize", ctypes.c_size_t),
                               ("SharedCommitUsage", ctypes.c_size_t)]


def enum_all():
    arr = (w.DWORD * 2048)()
    need = w.DWORD(0)
    if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(need)):
        raise ctypes.WinError(ctypes.get_last_error())
    n = need.value // 4
    return [arr[i] for i in range(n)]


def image_name(pid):
    h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    size = w.DWORD(1024)
    ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    k32.CloseHandle(h)
    if not ok:
        return None
    return buf.value.rsplit("\\", 1)[-1]


def mem(pid):
    for access in (0x1010, 0x1000):
        h = k32.OpenProcess(access, False, pid)
        if h:
            break
    if not h:
        return None
    m = PMC_EX2()
    m.cb = ctypes.sizeof(m)
    ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb)
    k32.CloseHandle(h)
    if not ok:
        return None
    return m


print("sizeof PMC=%d EX2=%d" % (ctypes.sizeof(PMC), ctypes.sizeof(PMC_EX2)))
rows = []
seen = {}
for pid in enum_all():
    if pid == 0:
        continue
    name = image_name(pid)
    if not name:
        continue
    m = mem(pid)
    if not m:
        continue
    seen.setdefault(name.lower(), []).append((pid, m))

print("可读进程数:", sum(len(v) for v in seen.values()), " 不同名称:", len(seen))
targets = ["explorer.exe", "chrome.exe", "msedge.exe", "code.exe", "notepad.exe", "python.exe", "WeChat.exe", "QQ.exe"]
for t in targets:
    v = seen.get(t.lower())
    if not v:
        continue
    tot_priv = sum(m.PrivateWorkingSetSize for _, m in v)
    tot_ws = sum(m.WorkingSetSize for _, m in v)
    tot_commit = sum(m.PrivateUsage for _, m in v)
    print("%-14s 实例=%2d  私有WS=%9.1fMB  工作集=%9.1fMB  提交=%9.1fMB  单例私有=%s" % (
        t, len(v), tot_priv / 1048576, tot_ws / 1048576, tot_commit / 1048576,
        ["%.1f" % (m.PrivateWorkingSetSize / 1048576) for _, m in v][:6]))

# 占比最高的前 5 个进程
flat = sorted([(m.PrivateWorkingSetSize, n, pid) for n, v in seen.items() for pid, m in v], reverse=True)[:8]
print("\n私有WS Top8:")
for sz, n, pid in flat:
    print("  %-24s %8.1f MB  pid=%d" % (n, sz / 1048576, pid))
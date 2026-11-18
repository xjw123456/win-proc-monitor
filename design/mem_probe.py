# -*- coding: utf-8 -*-
"""内存口径探针：对比 EX2 / PDH / PSAPI 三种私有工作集来源。"""
import ctypes
import ctypes.wintypes as w
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
pdh = ctypes.WinDLL("pdh", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010


class PMC(ctypes.Structure):
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
    ]


class PMC_EX2(ctypes.Structure):
    _fields_ = PMC._fields_ + [
        ("PrivateWorkingSetSize", ctypes.c_size_t),
        ("SharedCommitUsage", ctypes.c_size_t),
    ]


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            ("longValue", w.LONG),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_longlong),
            ("AnsiStringValue", ctypes.c_char_p),
            ("WideStringValue", ctypes.c_wchar_p),
        ]

    _fields_ = [("CStatus", w.DWORD), ("u", _U)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", PDH_FMT_COUNTERVALUE)]


PDH_FMT_DOUBLE = 0x00000100
PDH_MORE_DATA = -2147481646  # 0x800007D2
PDH_FMT_NOCAP100 = 0x00008000


def open_proc(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    return h


def mem_pmc(h, struct_cls):
    m = struct_cls()
    m.cb = ctypes.sizeof(struct_cls)
    ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb)
    err = ctypes.get_last_error()
    if not ok:
        return None, err
    return m, 0


def pdh_sum(q):
    """返回 {实例名: 私有工作集字节}"""
    items_ptr = ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W)()
    size = w.DWORD(0)
    count = w.DWORD(0)
    r = pdh.PdhGetFormattedCounterArrayW(
        q, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None
    )
    buf = ctypes.create_string_buffer(size.value)
    items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
    r = pdh.PdhGetFormattedCounterArrayW(
        q, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), items
    )
    out = {}
    for i in range(count.value):
        it = items[i]
        out[it.szName] = (it.FmtValue.CStatus, it.FmtValue.u.doubleValue)
    return out


def main():
    pids = {}
    pids["self"] = (ctypes.windll.kernel32.GetCurrentProcessId(), "python")
    # explorer
    import subprocess

    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/FO", "CSV", "/NH"],
            encoding="mbcs",
        )
        for line in out.strip().splitlines():
            parts = line.replace('"', "").split(",")
            if len(parts) > 1 and parts[1].isdigit():
                pids["explorer"] = (int(parts[1]), "explorer")
                break
    except Exception as e:
        print("tasklist fail", e)

    # PDH 查询
    query = w.HANDLE()
    r = pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))
    print("PdhOpenQuery", r)
    counter = w.HANDLE()
    r = pdh.PdhAddEnglishCounterW(query, r"\Process(*)\Working Set - Private", 0, ctypes.byref(counter))
    print("PdhAddCounter", r)
    pdh.PdhCollectQueryData(query)
    time.sleep(0.6)
    pdh.PdhCollectQueryData(query)
    arr = pdh_sum(counter)
    print("PDH instances:", len(arr))

    for label, (pid, name) in pids.items():
        h = open_proc(pid)
        print("\n===", label, "pid", pid, "h", h)
        if not h:
            print("  open fail", ctypes.get_last_error())
            continue
        m, err = mem_pmc(h, PMC)
        if m:
            print("  PMC    WS=%.1fMB  Private(commit)=%.1fMB" % (
                m.WorkingSetSize / 1048576, m.PrivateUsage / 1048576))
        else:
            print("  PMC fail", err)
        m2, err2 = mem_pmc(h, PMC_EX2)
        if m2:
            print("  EX2    WS=%.1fMB  PrivateWS=%.1fMB  SharedCommit=%.1fMB" % (
                m2.WorkingSetSize / 1048576,
                getattr(m2, "PrivateWorkingSetSize", -1) / 1048576,
                getattr(m2, "SharedCommitUsage", -1) / 1048576))
        else:
            print("  EX2 fail", err2)
        # PDH 同名实例求和
        total = 0.0
        hits = []
        for inst, (st, val) in arr.items():
            base = inst.split("#")[0]
            if base.lower() == name.lower():
                total += val
                hits.append((inst, st, val / 1048576))
        print("  PDH    matches=%s  total=%.1fMB" % (hits, total / 1048576))
        k32.CloseHandle(h)

    # 任务管理器口径参考：PowerShell 独立读一次
    pdh.PdhCloseQuery(query)


main()
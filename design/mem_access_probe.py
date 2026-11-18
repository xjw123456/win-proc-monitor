# -*- coding: utf-8 -*-
"""探针：查清「内存读取无权限」到底是哪些进程、用哪种访问掩码能读到什么。

对比四种打开方式（掩码 + 是否提权），以及三种内存来源：
1) GetProcessMemoryInfo(EX2)  —— 私有工作集，任务管理器「内存」列口径
2) NtQuerySystemInformation(SystemProcessInformation) —— 系统级快照，普通权限可读
3) K32EmptyWorkingSet 等是否需要 PROCESS_SET_QUOTA（仅记录错误码，不实际调用）
"""
import ctypes
import ctypes.wintypes as w
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(w.ULONG)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_long
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_SET_QUOTA = 0x0100

TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SystemProcessInformation = 5


class PROCESS_MEMORY_COUNTERS_EX2(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("PageFaultCount", w.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t), ("PrivateWorkingSetSize", ctypes.c_size_t),
        ("SharedCommitUsage", ctypes.c_size_t),
    ]


k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.OpenProcess.restype = w.HANDLE
k32.CloseHandle.argtypes = [w.HANDLE]
k32.CloseHandle.restype = w.BOOL
k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
k32.QueryFullProcessImageNameW.restype = w.BOOL
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
psapi.GetProcessMemoryInfo.restype = w.BOOL
psapi.EnumProcesses.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD, ctypes.POINTER(w.DWORD)]
psapi.EnumProcesses.restype = w.BOOL


def elevation():
    h = w.HANDLE()
    if not advapi.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h)):
        return "?"
    try:
        val = w.DWORD()
        n = w.DWORD()
        advapi.GetTokenInformation(h, TOKEN_ELEVATION, ctypes.byref(val),
                                   ctypes.sizeof(val), ctypes.byref(n))
        return "elevated" if val.value else "not elevated"
    finally:
        k32.CloseHandle(h)


def try_mask(pid, access):
    h = k32.OpenProcess(access, False, pid)
    if not h:
        return None, ctypes.get_last_error()
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        name = ""
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = buf.value.rsplit("\\", 1)[-1]
        priv = None
        m = PROCESS_MEMORY_COUNTERS_EX2()
        m.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX2)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb):
            priv = int(m.PrivateWorkingSetSize) or int(m.WorkingSetSize)
        return (name, priv), 0
    finally:
        k32.CloseHandle(h)


"""2) NtQuerySystemInformation(SystemProcessInformation) 结构（64 位，按偏移读取）"""
class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", ctypes.c_void_p)]


def sysproc_table():
    """返回 {pid: (image_name, working_set_bytes, private_ws_bytes)}。

    偏移已用 EX2 逐进程比对确认为：+8 WorkingSetPrivateSize、+56 ImageName(UNICODE_STRING)、
    +80 UniqueProcessId（与 mingw 的 SYSTEM_PROCESS_INFORMATION 布局一致）。
    """
    size = 1 << 20
    buf = None
    for _ in range(14):
        buf = ctypes.create_string_buffer(size)
        rl = w.ULONG(0)
        st = ntdll.NtQuerySystemInformation(
            SystemProcessInformation, buf, size, ctypes.byref(rl))
        if st == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, rl.value)
            continue
        if st < 0:
            raise RuntimeError("NtQuerySystemInformation status=0x%08X" % (st & 0xFFFFFFFF))
        break
    base = ctypes.addressof(buf)
    off = 0
    out = {}
    while True:
        nxt = ctypes.c_uint32.from_address(base + off).value
        priv = ctypes.c_int64.from_address(base + off + 8).value
        pid = ctypes.c_void_p.from_address(base + off + 80).value or 0
        length = ctypes.c_uint16.from_address(base + off + 56).value
        ptr = ctypes.c_void_p.from_address(base + off + 64).value
        name = ctypes.wstring_at(ptr, length // 2) if (ptr and length) else ""
        out[int(pid)] = (name, 0, max(0, int(priv)))
        if not nxt:
            break
        off += nxt
    return out


def dump_layout():
    """把第一个条目的关键偏移打印出来，用于人工核对结构体布局。"""
    import struct
    size = 1 << 20
    buf = ctypes.create_string_buffer(size)
    rl = w.ULONG(0)
    st = ntdll.NtQuerySystemInformation(SystemProcessInformation, buf, size, ctypes.byref(rl))
    if st < 0:
        print("NtQuerySystemInformation failed 0x%08X" % (st & 0xFFFFFFFF))
        return
    base = ctypes.addressof(buf)
    pid0 = ctypes.c_void_p.from_address(base + 16).value or 0
    print("entry0: NextEntryOffset=%d NumThreads=%d WsPrivate=%d pid=%d"
          % (ctypes.c_uint32.from_address(base + 0).value,
             ctypes.c_uint32.from_address(base + 4).value,
             ctypes.c_int64.from_address(base + 8).value,
             pid0))
    us = struct.unpack_from("HHI", buf.raw, 40)
    print("unicode@40:", us)
    print("u64@48..96:", struct.unpack_from("<6Q", buf.raw, 48))


def main():
    print("python:", sys.version.split()[0], "| 64bit:", ctypes.sizeof(ctypes.c_void_p) == 8)
    print("elevation:", elevation())

    table = sysproc_table()
    print("SystemProcessInformation 条目:", len(table))

    arr = (w.DWORD * 8192)()
    need = w.DWORD(0)
    psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need))
    pids = [arr[i] for i in range(need.value // 4) if arr[i]]

    stats = {"limited_read": 0, "vmread_read": 0, "denied": 0}
    denied = []
    for pid in pids:
        (_, priv1), err1 = try_mask(pid, PROCESS_QUERY_LIMITED_INFORMATION)
        (info2, err2) = try_mask(
            pid, PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)
        name = table.get(pid, ("", 0, 0))[0] or "?"
        if info2 is not None and info2[0]:
            stats["vmread_read"] += 1
            continue
        if priv1 is not None:
            stats["limited_read"] += 1
            continue
        stats["denied"] += 1
        denied.append((pid, name, err1, err2, table.get(pid, ("", 0, 0))[1],
                       table.get(pid, ("", 0, 0))[2]))

    print("统计:", stats)
    print("\n=== 完全读不到内存的进程（前 15 个）===")
    for pid, name, e1, e2, ws, priv in denied[:15]:
        print("pid=%-6d %-28s err_limited=%-3d err_vmread=%-3d SystemWS=%.1fMB SysPrivate=%.1fMB"
              % (pid, name, e1, e2, ws / 1048576.0, priv / 1048576.0))

    # 能看到多少进程的总内存（任务管理器「内存」列 = PrivateWorkingSet）
    tot_sys = sum(v[2] for v in table.values() if v[2] > 0)
    print("\nSystemProcessInformation 私有工作集合计: %.1f MB" % (tot_sys / 1048576.0))

    # 对比几个真实进程：EX2 与 SystemProcessInformation
    print("\n=== EX2 vs SystemProcessInformation（同名进程抽查）===")
    seen = 0
    for pid in pids:
        (info, _) = try_mask(pid, PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)
        if not info or not info[1]:
            continue
        name, priv = info
        t = table.get(pid)
        if not t:
            continue
        print("%-24s pid=%-6d  EX2=%.2f MB   SysInfo=%.2f MB"
              % (name, pid, priv / 1048576.0, t[2] / 1048576.0))
        seen += 1
        if seen >= 8:
            break


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""在第二个条目上定位 UNICODE_STRING / pid 的真实偏移。"""
import ctypes
import ctypes.wintypes as w
import struct

ntdll = ctypes.WinDLL("ntdll")
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.POINTER(w.ULONG)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_long

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.OpenProcess.restype = w.HANDLE
k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
k32.QueryFullProcessImageNameW.restype = w.BOOL
k32.CloseHandle.argtypes = [w.HANDLE]

SYS_PROC = 5
MISMATCH = 0xC0000004


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
    raise RuntimeError("buf")


def img_name(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        b = ctypes.create_unicode_buffer(512)
        n = w.DWORD(512)
        if k32.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n)):
            return b.value.rsplit("\\", 1)[-1]
        return None
    finally:
        k32.CloseHandle(h)


buf = query()
base = ctypes.addressof(buf)
e1 = ctypes.c_uint32.from_address(base + 0).value
print("entry1 at +%d" % e1)

# 该条目里第一个字段大概率是下一个 NextEntryOffset、NumberOfThreads
print("e1 head:", struct.unpack_from("<IIQ", buf.raw, e1))
print("e1 CreateTime:", struct.unpack_from("<q", buf.raw, e1 + 24)[0])

# 找 UNICODE_STRING：Buffer 必须落在缓冲区内部且指向可解析汉字/ASCII
for off in range(e1, e1 + 300, 4):
    length = struct.unpack_from("<H", buf.raw, off)[0]
    maxlen = struct.unpack_from("<H", buf.raw, off + 2)[0]
    ptr = struct.unpack_from("<Q", buf.raw, off + 8)[0] if off % 8 == 0 else 0
    if off % 8 != 0:
        continue
    if not (0 < length <= maxlen <= 600 and length % 2 == 0):
        continue
    if not (base < ptr < base + len(buf.raw)):
        continue
    try:
        s = ctypes.wstring_at(ptr, length // 2)
    except OSError:
        continue
    if s and all(31 < ord(c) < 0xFFF0 for c in s):
        print("  UNICODE_STRING @e1+%-4d len=%-3d name=%r" % (off - e1, length, s))

# 找 pid：System Idle Process(0)、System(4) 之后的第三个条目一般是 smss.exe
e2 = e1 + ctypes.c_uint32.from_address(base + e1).value
for off in range(e2, e2 + 200, 8):
    v = struct.unpack_from("<Q", buf.raw, off)[0]
    if 0 < v < 100000:
        nm = img_name(v)
        if nm:
            print("  pid-like @e2+%-4d value=%-6d image=%s" % (off - e2, v, nm))
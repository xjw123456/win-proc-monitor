# -*- coding: utf-8 -*-
"""定位 NtQuerySystemInformation 返回缓冲区的真实布局。

不猜偏移：把第一个条目按 8 字节逐格 dump，再在各偏移上尝试解析 UNICODE_STRING，
找到 Buffer 指针落在缓冲区内、内容像进程名的那一处。
"""
import ctypes
import ctypes.wintypes as w
import struct

ntdll = ctypes.WinDLL("ntdll")
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.POINTER(w.ULONG)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_long

SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


def query():
    size = 1 << 20
    for _ in range(14):
        buf = ctypes.create_string_buffer(size)
        rl = w.ULONG(0)
        st = ntdll.NtQuerySystemInformation(SYSTEM_PROCESS_INFORMATION, buf, size, ctypes.byref(rl))
        if st == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, rl.value)
            continue
        if st < 0:
            raise RuntimeError("status 0x%08X" % (st & 0xFFFFFFFF))
        return buf, rl.value
    raise RuntimeError("cannot allocate buffer")


def main():
    buf, used = query()
    base = ctypes.addressof(buf)
    nxt = ctypes.c_uint32.from_address(base + 0).value
    print("buffer used=%d  first NextEntryOffset=%d" % (used, nxt))
    print("\nentry0 前 40 个 8 字节值:")
    for i in range(40):
        v = struct.unpack_from("<Q", buf.raw, i * 8)[0]
        lo32 = v & 0xFFFFFFFF
        hi32 = v >> 32
        print("  +%-4d  0x%016X  (%12d / %12d)" % (i * 8, v, lo32, hi32))

    print("\n在各偏移尝试 UNICODE_STRING(Length, MaximumLength, Buffer):")
    for off in range(0, 200, 4):
        length, maxlen, ptr = struct.unpack_from("<HHI", buf.raw, off)
        if 0 < length <= maxlen <= 520 and length % 2 == 0 and base <= ptr < base + nxt:
            try:
                s = ctypes.wstring_at(ptr, length // 2)
            except OSError:
                continue
            if s.isprintable() and all(32 <= ord(c) < 0xFFF0 for c in s):
                print("  off=%-4d len=%-4d max=%-4d ptr_off=%-6d name=%r"
                      % (off, length, maxlen, ptr - base, s))

    # 同一条目里找 pid（应当等于第 2 条记录的父进程/唯一 id，先用 0/4 号系统进程判定）
    print("\n候选 pid 字段（值形如 0/4/100 等小整数）:")
    for off in range(0, 120, 4):
        v = struct.unpack_from("<I", buf.raw, off)[0]
        if v <= 0xFFFF:
            print("  off=%-4d  u32=%d" % (off, v))


if __name__ == "__main__":
    main()
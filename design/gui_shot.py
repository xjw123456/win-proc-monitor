# -*- coding: utf-8 -*-
"""启动 GUI、定位窗口、截图，然后关闭。用 DSH 自带 Python 3.12（带 Pillow）运行。"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY39 = r"C:\Program Files\Python39\python.exe"
TITLE_KEY = "进程性能监控"

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wt.HWND


def find_window(key):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if key in buf.value and user32.IsWindowVisible(hwnd):
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


proc = subprocess.Popen([PY39, "app.py"], cwd=ROOT)
hwnd = None
try:
    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.6)
        hits = find_window(TITLE_KEY)
        if hits:
            hwnd = hits[0][0]
            break
    if not hwnd:
        print("窗口未出现")
        sys.exit(1)

    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.8)                     # 等进程列表填充与首帧绘制

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    print("rect:", box)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    out = os.path.join(ROOT, "output", "05_运行截图.png")
    img.save(out)
    print("saved:", out, img.size)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
"""等待 _gui_demo.py 就绪后截取主窗口（DSH Python 3.12 + Pillow）。"""
import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import time

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "output", "07_运行中界面.png")
MARK = os.path.join(HERE, "_gui_ready.flag")
PY39 = r"C:\Program Files\Python39\python.exe"

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32

if os.path.exists(MARK):
    os.remove(MARK)

errf = open(os.path.join(HERE, "_gui_demo.err"), "wb")
proc = subprocess.Popen([PY39, os.path.join(HERE, "_gui_demo.py")],
                        cwd=os.path.dirname(HERE), stderr=errf)
deadline = time.time() + 70
while time.time() < deadline and not os.path.exists(MARK):
    time.sleep(0.3)

if not os.path.exists(MARK):
    proc.kill()
    sys.exit("GUI 未就绪")

time.sleep(0.8)
def find_window():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value.startswith("进程性能监控"):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, None)
    return found[0] if found else None


hwnd = find_window()
if not hwnd:
    proc.kill()
    sys.exit("找不到窗口")

rect = ctypes.wintypes.RECT()
ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 9,
                                           ctypes.byref(rect), ctypes.sizeof(rect))
box = (rect.left, rect.top, rect.right, rect.bottom)
img = ImageGrab.grab(bbox=box, all_screens=True)
img.save(OUT)
print("saved", OUT, img.size)

user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
time.sleep(1.5)
if proc.poll() is None:
    proc.kill()
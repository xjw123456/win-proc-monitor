"""演示用：自动选中 chrome.exe 并开始监控，便于外部截图。"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ui.main_window import App  # noqa: E402

MARK = os.path.join(HERE, "_gui_ready.flag")


def main():
    app = App()

    def do_start():
        # 界面自身的 400ms 轮询此时已完成首轮枚举，直接开跑
        try:
            app.var_interval.set("1")
            app.var_target.set("chrome.exe" if app.catalog.by_name("chrome.exe") else "python.exe")
            app._on_start()
        except Exception as exc:
            sys.stderr.write("start failed: %r\n" % (exc,))

    def ready():
        with open(MARK, "w") as fh:
            fh.write(str(time.time()))

    app.after(3000, do_start)
    app.after(40000, ready)
    app.mainloop()


if __name__ == "__main__":
    main()
import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

def main():
    # Ensure offscreen rendering; the environment variable can also be set in shell
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    # Ensure Python path can import project modules without relying on shell PYTHONPATH
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(base_dir, 'src')
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    app = QApplication(sys.argv)
    try:
        from ui.main_window import MainWindow
        mw = MainWindow()
        mw.show()
        # Run the event loop briefly then exit to verify startup
        QTimer.singleShot(2000, app.quit)
        app.exec()
        print("Headless run completed (2s).")
        return 0
    except Exception:
        # 打印完整堆栈并以非零码退出，让自动化冒烟测试能发现启动失败
        print("ERROR during headless run:")
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())

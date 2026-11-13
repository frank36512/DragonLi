import sys
import os
import ctypes
import shutil
import imageio_ffmpeg
import argparse
from datetime import datetime

# 禁用代理，避免本地服务（如 ComfyUI）被系统代理拦截
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

# Add the src directory to the python path so imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from paths import get_app_root, ensure_resources
except ImportError:
    try:
        from src.paths import get_app_root, ensure_resources
    except ImportError:
        print("Warning: Could not import paths module")
        def get_app_root(): return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        def ensure_resources(): pass

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow
from ui.utils import apply_windows_dark_title_bar
from core.utils.log_manager import log_manager, info, debug, warning

def check_ffmpeg():
    # First check system path
    if shutil.which("ffmpeg"):
        return True
        
    # Then check imageio_ffmpeg
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_exe):
            # Add to PATH so other modules can find it
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            if ffmpeg_dir not in os.environ["PATH"]:
                os.environ["PATH"] += os.pathsep + ffmpeg_dir
            return True
    except Exception as e:
        print(f"imageio_ffmpeg check failed: {e}")
        
    print("Warning: FFmpeg not found in PATH. Video synthesis will fail.")
    return False

def parse_args():
    parser = argparse.ArgumentParser(description='狸猫短剧 (Dragonli)')
    parser.add_argument('--cli', action='store_true', help='命令行模式运行')
    parser.add_argument('--api', action='store_true', help='启动 HTTP API 服务')
    parser.add_argument('--port', type=int, default=18790, help='API 服务端口 (默认: 18790)')
    parser.add_argument('--task', type=str, help='CLI 任务类型: create_project, generate_script, generate_video, compose_video, full_pipeline')
    parser.add_argument('--project', type=str, help='项目名称或路径')
    parser.add_argument('--topic', type=str, help='故事主题')
    parser.add_argument('--style', type=str, default='都市', help='短剧风格 (默认: 都市)')
    parser.add_argument('--episodes', type=int, default=1, help='集数 (默认: 1)')
    parser.add_argument('--image-path', type=str, dest='image_path', help='图片路径')
    parser.add_argument('--prompt', type=str, help='视频提示词')
    parser.add_argument('--clips', type=str, help='视频片段路径(逗号分隔)')
    parser.add_argument('--output', type=str, help='输出文件路径')
    return parser.parse_args()

def run_cli(args):
    from cli import CLIRunner
    runner = CLIRunner()
    result = runner.execute(args)
    return result

def run_api(args):
    import uvicorn
    from api.server import app
    print(f"Starting Dragonli API Server on port {args.port}...")
    print(f"API Documentation: http://localhost:{args.port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=args.port)

def run_gui():
    # 初始化日志系统
    try:
        log_dir = os.path.join(get_app_root(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"dragonli_{datetime.now().strftime('%Y%m%d')}.log")
        log_manager.set_log_file(log_file)
        info("应用程序启动")
        debug(f"日志文件: {log_file}")
    except Exception as e:
        print(f"初始化日志系统失败: {e}")

    # Set AppUserModelID for Windows taskbar icon
    try:
        myappid = 'dragonli.shortdrama.1.0' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        info("设置 AppUserModelID 成功")
    except Exception as e:
        warning(f"Failed to set AppUserModelID: {e}")

    # Ensure resources exist next to EXE
    ensure_resources()

    app = QApplication(sys.argv)
    app.setApplicationName("Dragonli")
    app.setApplicationDisplayName("狸猫短剧")

    # Set Application Icon
    icon_path = os.path.join(get_app_root(), "dragonli.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        info(f"加载应用图标: {icon_path}")

    if not check_ffmpeg():
        warning("FFmpeg not found in system PATH")
        QMessageBox.warning(None, "Missing Dependency",
                            "FFmpeg was not found in your system PATH.\n"
                            "Video synthesis features will not work until FFmpeg is installed.")
    else:
        info("FFmpeg 检查通过")

    # Apply Dark Theme 已由 MainWindow 内部的 theme 系统统一接管，
    # 此处不再调用 apply_dark_theme，避免硬编码 QSS 覆盖主题切换。
    window = MainWindow()
    info("主窗口创建完成")

    # Apply Windows Title Bar（跟随主题：dark→深色标题栏，light→浅色）
    apply_windows_dark_title_bar(window, dark=(window._current_theme == "dark"))

    window.show()
    info("应用程序已显示")

    sys.exit(app.exec())

def main():
    args = parse_args()

    if args.cli:
        # CLI 模式用进程退出码反映成败，便于自动化调用方判断
        result = run_cli(args)
        sys.exit(0 if result and result.get("success") else 1)
    elif args.api:
        return run_api(args)
    else:
        return run_gui()

if __name__ == "__main__":
    main()

import logging
import sys
import os
import re
from datetime import datetime
from typing import Optional, Callable
from logging.handlers import RotatingFileHandler
from PyQt6.QtCore import QObject, pyqtSignal


class LogEmitter(QObject):
    log_signal = pyqtSignal(str, str)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m',
    }
    RESET = '\033[0m'

    def __init__(self, use_color=True, **kwargs):
        super().__init__(**kwargs)
        self.use_color = use_color

    def format(self, record):
        color = self.COLORS.get(record.levelname, '') if self.use_color else ''
        reset = self.RESET if self.use_color else ''
        record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)


class LogManager:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LogManager._initialized:
            return

        LogManager._initialized = True
        self.log_emitter = LogEmitter()
        self.log_callbacks = []
        self.max_log_entries = 2000
        self.log_entries = []

        self.logger = logging.getLogger("Dragonli")
        self.logger.setLevel(logging.DEBUG)

        self.formatter = ColoredFormatter(
            '[%(asctime)s] [%(levelname)s] [%(module)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.plain_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(module)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        self.console_handler = logging.StreamHandler(sys.stdout)
        self.console_handler.setLevel(logging.DEBUG)
        self.console_handler.setFormatter(self.formatter)
        self.logger.addHandler(self.console_handler)

        self.file_handler = None

    def set_log_file(self, log_file_path: str):
        if self.file_handler:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()

        try:
            log_dir = os.path.dirname(log_file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self.file_handler = RotatingFileHandler(
                log_file_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
            )
            self.file_handler.setLevel(logging.DEBUG)
            self.file_handler.setFormatter(self.plain_formatter)
            self.logger.addHandler(self.file_handler)
            self.info(f"日志文件已设置: {log_file_path}")
        except Exception as e:
            self.error(f"设置日志文件失败: {e}")

    def _emit_log(self, message: str, level: str):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        self.log_entries.append({
            'timestamp': timestamp,
            'level': level,
            'message': message
        })

        if len(self.log_entries) > self.max_log_entries:
            self.log_entries = self.log_entries[-self.max_log_entries:]

        self.log_emitter.log_signal.emit(message, level)

        for callback in self.log_callbacks:
            try:
                callback(message, level)
            except Exception as e:
                print(f"日志回调函数执行失败: {e}")

    def add_callback(self, callback: Callable[[str, str], None]):
        if callback not in self.log_callbacks:
            self.log_callbacks.append(callback)

    def remove_callback(self, callback: Callable[[str, str], None]):
        if callback in self.log_callbacks:
            self.log_callbacks.remove(callback)

    def debug(self, message: str):
        self.logger.debug(message)
        self._emit_log(message, "DEBUG")

    def info(self, message: str):
        self.logger.info(message)
        self._emit_log(message, "INFO")

    def warning(self, message: str):
        self.logger.warning(message)
        self._emit_log(message, "WARNING")

    def error(self, message: str):
        self.logger.error(message)
        self._emit_log(message, "ERROR")

    def critical(self, message: str):
        self.logger.critical(message)
        self._emit_log(message, "CRITICAL")

    def get_log_entries(self, level: Optional[str] = None, limit: int = 100) -> list:
        entries = self.log_entries
        if level:
            entries = [e for e in entries if e['level'] == level]
        return entries[-limit:]

    def clear_logs(self):
        self.log_entries.clear()
        self.info("日志已清空")

    def export_logs(self, file_path: str):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                for entry in self.log_entries:
                    f.write(f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}\n")
            self.info(f"日志已导出到: {file_path}")
        except Exception as e:
            self.error(f"导出日志失败: {e}")

    def set_level(self, level: str):
        self.logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))


log_manager = LogManager()


def debug(message: str):
    log_manager.debug(message)


def info(message: str):
    log_manager.info(message)


def warning(message: str):
    log_manager.warning(message)


def error(message: str):
    log_manager.error(message)


def critical(message: str):
    log_manager.critical(message)

"""
跨模块协作式取消。

长轮询（视频生成 5-15 分钟）原先只能等到 max_retries 耗尽才能响应取消，
用户点了"取消"仍要干等数分钟。本模块提供进程级取消令牌：
- AutoRunController.cancel() 置位后，所有注册的检查函数返回 True
- 轮询循环用 interruptible_sleep() 代替 time.sleep()，每 0.2 秒检查一次
"""
import time

_checks = []
_aborts = []      # 终止钩子：取消瞬间立即执行（关掉阻塞中的网络连接）
_manual = False   # UI 层直接发起的全局取消（如项目页「停止」按钮）


def register(fn):
    """注册取消检查函数（返回 bool）。重复注册同一函数只保留一份。"""
    if fn not in _checks:
        _checks.append(fn)
    return fn


def unregister(fn):
    try:
        _checks.remove(fn)
    except ValueError:
        pass


def register_abort(fn):
    """注册终止钩子（无参函数）。

    协作式检查只在阻塞点之间的检查位生效——流式请求卡在 socket 读上
    （prefill 期间服务端不发数据）时，光置取消标记要等到首 token 才生效。
    钩子在 request_cancel()/AutoRunController.cancel() 时立即执行，
    用来关闭在途连接把阻塞的线程唤醒（Windows 下实测 0 秒生效）。
    """
    if fn not in _aborts:
        _aborts.append(fn)
    return fn


def unregister_abort(fn):
    try:
        _aborts.remove(fn)
    except ValueError:
        pass


def fire_abort():
    """立即执行所有终止钩子（单个异常不影响其余钩子）。"""
    for fn in list(reversed(_aborts)):
        try:
            fn()
        except Exception:
            continue


def request_cancel():
    """UI 层直接请求全局取消（不依赖控制器注册，进程级生效）。"""
    global _manual
    _manual = True
    fire_abort()   # 先置标记再掐连接：被唤醒的线程立刻能看到取消状态


def reset():
    """新一轮任务开始前清除手动取消标记。"""
    global _manual
    _manual = False


def cancelled():
    """任一注册源请求取消即返回 True。"""
    if _manual:
        return True
    for fn in list(_checks):
        try:
            if fn():
                return True
        except Exception:
            continue
    return False


def interruptible_sleep(seconds, step=0.2):
    """可被取消打断的 sleep。返回 True 表示期间收到了取消请求。"""
    if seconds <= 0:
        return cancelled()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancelled():
            return True
        remaining = deadline - time.monotonic()
        time.sleep(min(step, remaining))
    return cancelled()

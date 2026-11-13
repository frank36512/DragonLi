# -*- coding: utf-8 -*-
"""
全自动短剧生产流水线编排器（纯 Python，不依赖 Qt）。

串起 5 个阶段：剧本 -> 分镜 -> 视频片段 -> 字幕 -> 合成成片。
视频片段按面板的角色/场景/道具参考图配合视频提示词直接生成（分镜图片与独立配音阶段已下线）。
支持：进度回调、检查点暂停/恢复、失败重试、取消、断点续跑（产物校验后跳过）。

线程模型：run() 在调用方线程中执行（GUI 用 QThread 包装 / CLI 直接调 / API 用 threading.Thread），
pause()/resume()/cancel() 可从其他线程调用。
"""
import os
import re
import json
import time
import threading
import traceback

try:
    from core.autorun.params import AutoRunParams
    from core.autorun.state import PipelineState, STAGES, STAGE_LABELS
    from core.script import script_service
    from core.script.script_model import Script
    from core.storyboard import storyboard_builder
    from core.storyboard.storyboard_model import Storyboard
    from core.project.series_manager import SeriesManager
    from core.synthesis.video_composer import VideoComposer
    from core.subtitle.subtitle_generator import SubtitleGenerator
    from core.config.config_manager import ConfigManager
    from ai_engine.image_gen.image_client import ImageGenClient
    from ai_engine.video_gen.video_client import VideoGenClient
    from ai_engine.llm.llm_client import LLMClient
except ImportError:
    from src.core.autorun.params import AutoRunParams
    from src.core.autorun.state import PipelineState, STAGES, STAGE_LABELS
    from src.core.script import script_service
    from src.core.script.script_model import Script
    from src.core.storyboard import storyboard_builder
    from src.core.storyboard.storyboard_model import Storyboard
    from src.core.project.series_manager import SeriesManager
    from src.core.synthesis.video_composer import VideoComposer
    from src.core.subtitle.subtitle_generator import SubtitleGenerator
    from src.core.config.config_manager import ConfigManager
    from src.ai_engine.image_gen.image_client import ImageGenClient
    from src.ai_engine.video_gen.video_client import VideoGenClient
    from src.ai_engine.llm.llm_client import LLMClient

try:
    from ai_engine.utils.cancel import (
        register as _cancel_register,
        unregister as _cancel_unregister,
        reset as _cancel_reset,
        fire_abort as _cancel_fire_abort,
    )
except ImportError:
    try:
        from src.ai_engine.utils.cancel import (
            register as _cancel_register,
            unregister as _cancel_unregister,
            reset as _cancel_reset,
            fire_abort as _cancel_fire_abort,
        )
    except ImportError:
        def _cancel_register(fn): return fn
        def _cancel_unregister(fn): pass
        def _cancel_reset(): pass
        def _cancel_fire_abort(): pass


class PipelineCancelled(Exception):
    """用户取消流水线时抛出，由 run() 捕获转为正常返回。"""


# 图生视频失败里值得重试的瞬时错误（首次加载模型的一次性 interrupt、网络抖动等）
_TRANSIENT_VIDEO_MARKERS = (
    "execution_interrupted", "interrupted", "connection", "refused",
    "reset by peer", "temporarily", "unavailable", "busy",
    "502", "503", "504", "unreachable", "timeout", "timed out",
)
# 确定性失败：重试只会再烧一轮时间（如 20-30 分钟），直接跳过
_NON_RETRYABLE_VIDEO_MARKERS = (
    "超时", "工作流文件不存在", "上传", "节点", "node error", "no video",
)
# 硬件/系统资源类瞬时错误（显存不足、宿主 I/O 资源耗尽）：
# 本质是资源压力而非逻辑错误，清 ComfyUI 缓存后重试通常可恢复。
# 必须优先于 _NON_RETRYABLE 判断——OOM 文本里往往含"节点"字样。
_HARDWARE_TRANSIENT_MARKERS = (
    "allocation on device", "out of memory", "cuda out of memory",
    "hostbuf", "read_file_slice", "getoverlappedresult",
    "error=1450", "no system resources",
)


def _is_hardware_transient(err):
    """错误是否为显存/系统资源类瞬时错误（清缓存后可重试）。"""
    s = (err or "").strip().lower()
    return any(k in s for k in _HARDWARE_TRANSIENT_MARKERS)


# 纯显存溢出：重试同一套分辨率必然原样复现，必须下调 megapixels 才可能成功
_OOM_MARKERS = ("out of memory", "allocation on device", "cuda out of memory")


def _is_oom_error(err):
    """错误是否为显存溢出（可通过降分辨率恢复）。"""
    s = (err or "").strip().lower()
    return any(k in s for k in _OOM_MARKERS)


# OOM 降级：每次把像素预算压到上次的 72%（面积约减半），下限 0.12MP
_OOM_DOWNSCALE_FACTOR = 0.72
_MEGAPIXELS_FLOOR = 0.12


def _video_error_retryable(err):
    """图生视频失败是否值得重试。

    只有明确的瞬时错误才重试；生成超时、工作流缺失、节点报错这类
    确定性失败重试只会再等一整轮（每个片段 20-30 分钟），必须立即跳过。
    硬件资源类错误（OOM/hostbuf）优先级最高：清缓存后重试可恢复。
    """
    s = (err or "").strip().lower()
    if not s:
        return False
    if _is_hardware_transient(s):
        return True
    if any(h in s for h in _NON_RETRYABLE_VIDEO_MARKERS):
        return False
    return any(k in s for k in _TRANSIENT_VIDEO_MARKERS)


def _is_interrupt_error(err):
    """错误是否为「任务被外部中断」（execution_interrupted）。"""
    s = (err or "").strip().lower()
    return "execution_interrupted" in s or "被中断" in s


class AutoRunController:
    """
    用法（GUI）:
        c = AutoRunController(project_dir, config, params,
                              on_progress=cb, on_checkpoint=cb, on_error=cb, on_log=cb)
        c.run()          # 在工作线程中
        c.resume()       # 主线程：检查点/错误后继续
        c.resume(retry=True)  # 重跑当前阶段
        c.cancel()       # 随时取消

    headless（CLI/API）: 不传 on_checkpoint / on_error 即全自动直通（遇错即停）。
    """

    def __init__(self, project_dir, config_manager=None, params=None,
                 on_progress=None, on_checkpoint=None, on_error=None, on_log=None):
        self.project_dir = project_dir
        self.config = config_manager or ConfigManager()
        if params is None:
            params = AutoRunParams(topic="")
        params.validate_checkpoints()
        self.params = params
        self.state = PipelineState(project_dir)

        self.on_progress = on_progress
        self.on_checkpoint = on_checkpoint
        self.on_error = on_error
        self.on_log = on_log

        # 运行控制（跨线程）
        self._resume_event = threading.Event()
        self._cancel_flag = False
        self._retry_requested = False

        self._composer = None  # VideoComposer 懒加载
        self._qa_results = {}  # WB-10: {ep_id: QAResult.to_dict()}

        # 视频生成分辨率预算（megapixels）：None 表示交给 comfyui_service 按 1080P 自动推算。
        # 一旦某片段因显存溢出（OOM）失败，这里会下调并把学到的安全值固定下来，
        # 后续片段直接用安全值，避免每个片段都先撞一次 OOM 白烧 20 分钟。
        self._video_megapixels = self._load_video_megapixels()

    def _load_video_megapixels(self):
        """读取上次学到的安全分辨率（Video 默认 API 配置里的 megapixels）。"""
        try:
            for c in (self.config.get("api_configs") or []):
                if isinstance(c, dict) and str(c.get("type")) == "Video" and c.get("is_default"):
                    v = c.get("megapixels")
                    return float(v) if v else None
        except Exception:
            pass
        return None

    def _persist_video_megapixels(self, mp):
        """把 OOM 后学到的安全分辨率写回 Video 默认配置，下次运行直接使用。"""
        try:
            cfgs = self.config.get("api_configs") or []
            changed = False
            for c in cfgs:
                if isinstance(c, dict) and str(c.get("type")) == "Video" and c.get("is_default"):
                    c["megapixels"] = mp
                    changed = True
            if changed:
                self.config.set("api_configs", cfgs)
                self._log(f"已把安全分辨率 {mp}MP 写回 Video 配置（后续片段与下次运行直接使用）")
        except Exception as e:
            self._log(f"安全分辨率未能写回配置（本次运行内仍生效）：{e}")

    # ================= 对外控制接口 =================
    def pause(self):
        """在当前阶段边界处暂停（不打断正在执行的网络请求）。"""
        self._resume_event.clear()

    def resume(self, retry=False):
        """恢复运行；retry=True 表示重跑刚才失败/被要求重试的阶段。"""
        if retry:
            self._retry_requested = True
        self._resume_event.set()

    def cancel(self):
        self._cancel_flag = True
        self._resume_event.set()  # 唤醒可能正在等待的用户确认
        # 立刻掐断在途 LLM 连接：流式请求阻塞在 socket 读上时，
        # 单靠协作式检查要等首 token 才能看到取消标记（prefill 可长达数分钟）
        try:
            _cancel_fire_abort()
        except Exception:
            pass

    @property
    def cancelled(self):
        return self._cancel_flag

    # ================= 主流程 =================
    def run(self):
        """执行整条流水线（可重复调用以断点续跑）。返回结果 dict。"""
        self._cancel_flag = False
        self._resume_event.set()
        self._retry_requested = False
        try:
            _cancel_reset()   # 清掉上一轮（如项目页「停止」）留下的全局取消标记
        except Exception:
            pass

        # 注册协作式取消：长轮询（视频生成 5-15 分钟）每 0.2s 检查一次，取消秒级生效
        cancel_check = lambda: self._cancel_flag
        _cancel_register(cancel_check)
        try:
            return self._run_inner()
        finally:
            _cancel_unregister(cancel_check)

    def _run_inner(self):
        self.state.data["params"] = self.params.to_dict()
        self.state.save()

        series = SeriesManager(self.project_dir)
        # 集编号必须跨 run() 稳定（断点续跑时续跑同一批集，而不是顺延新建）
        episode_ids = self.state.data.get("episode_ids") or []
        if not episode_ids:
            base = len(series.data.get("episodes", []))
            episode_ids = [base + i + 1 for i in range(self.params.episode_count)]
            self.state.data["episode_ids"] = episode_ids
            self.state.save()
        elif len(episode_ids) != self.params.episode_count:
            # 参数变更：以状态中已登记的集为准续跑，剩余缺口继续补齐
            base = max(episode_ids) if episode_ids else len(series.data.get("episodes", []))
            while len(episode_ids) < self.params.episode_count:
                base += 1
                episode_ids.append(base)
            self.state.data["episode_ids"] = episode_ids
            self.state.save()

        # 集数可能上百，日志里用区间表示，避免刷屏
        ep_desc = (f"{episode_ids[0]}-{episode_ids[-1]}（共 {len(episode_ids)} 集）"
                   if len(episode_ids) > 20 else episode_ids)
        mode = getattr(self.params, "generate_mode", "episode") or "episode"
        mode_label = "逐集生成" if mode == "episode" else "逐类生成"
        self._log(f"全自动流水线启动：项目={os.path.basename(self.project_dir)}，"
                  f"目标集 {ep_desc}，调度模式={mode_label}，"
                  f"视频生成=图生视频（参考图 + 视频提示词）")

        final_outputs = []
        errors = []
        cancelled = False

        try:
            if mode == "category":
                # 逐类生成：按阶段外层、集内层。所有集先跑完同一阶段再进下一阶段。
                # 顺序：所有集剧本+资源+分镜 → 所有集视频片段 → 所有集字幕 → 所有集成片
                for stage in STAGES:
                    if self._cancel_flag:
                        cancelled = True
                        break
                    self._progress(None, stage, "category_start",
                                   f"开始【{STAGE_LABELS[stage]}】阶段（共 {len(episode_ids)} 集）")
                    self._log(f"=== 逐类模式：进入【{STAGE_LABELS[stage]}】阶段 ===")
                    for ep_id in episode_ids:
                        # 先为本阶段所有集建出占位行，使进度表与「共 N 集」一致；
                        # 随后 cached / running / success 会在原行上更新状态。
                        self._progress(ep_id, stage, "pending", "等待执行")
                    for ep_id in episode_ids:
                        if self._cancel_flag:
                            cancelled = True
                            break
                        fn = getattr(self, f"_stage_{stage}")
                        artifacts = self._execute_stage(ep_id, stage, fn)
                        if stage == "compose":
                            compose_arts = artifacts or []
                            if isinstance(compose_arts, str):
                                compose_arts = [compose_arts]
                            if compose_arts:
                                final_outputs.append(compose_arts[-1])
                    self._progress(None, stage, "category_done",
                                   f"【{STAGE_LABELS[stage]}】阶段完成")
                    self._log(f"=== 逐类模式：【{STAGE_LABELS[stage]}】阶段结束 ===")
            else:
                # 逐集生成（默认）：一集跑完所有阶段再进下一集
                for ep_id in episode_ids:
                    if self._cancel_flag:
                        cancelled = True
                        break
                    self._progress(ep_id, None, "episode_start", f"开始第 {ep_id} 集")

                    ep_outputs = {}
                    for stage in STAGES:
                        fn = getattr(self, f"_stage_{stage}")
                        artifacts = self._execute_stage(ep_id, stage, fn)
                        ep_outputs[stage] = artifacts

                    compose_artifacts = ep_outputs.get("compose") or []
                    final_path = compose_artifacts[-1] if compose_artifacts else ""
                    if final_path:
                        final_outputs.append(final_path)
                    self._progress(ep_id, None, "episode_done", f"第 {ep_id} 集完成")
        except PipelineCancelled:
            cancelled = True
            self._log("流水线已被用户取消")
        except Exception as e:
            errors.append(str(e))
            self._log(f"流水线异常终止: {e}")
            traceback.print_exc()

        result = {
            "success": not cancelled and not errors,
            "cancelled": cancelled,
            "final_outputs": final_outputs,
            "errors": errors,
            "state": self.state.summary(),
        }
        # WB-10: QA 结果汇总
        if hasattr(self, '_qa_results') and self._qa_results:
            qa_errors = []
            qa_warnings = []
            for ep_qa in self._qa_results.values():
                for issue in ep_qa.get("issues", []):
                    if issue.get("severity") == "error":
                        qa_errors.append(issue.get("message", ""))
                    elif issue.get("severity") == "warning":
                        qa_warnings.append(issue.get("message", ""))
            result["qa_errors"] = qa_errors
            result["qa_warnings"] = qa_warnings
            # fail_on_qa_error 时 QA error 阻断成功
            if self.params.fail_on_qa_error and qa_errors:
                result["success"] = False
                result["errors"].extend([f"QA: {e}" for e in qa_errors])
        
        self.state.data["final"] = {
            "finished_at": _timestamp(),
            "final_outputs": final_outputs,
            "errors": list(errors),
            "success": result["success"],
            "qa": result.get("qa_errors", []),
        }
        try:
            self.state.save()
        except Exception as e:
            self._log(f"状态落盘失败（结果已保留）: {e}")
        return result

    # ================= 阶段调度（缓存/检查点/重试） =================
    def _execute_stage(self, ep_id, stage, fn):
        """执行单阶段：缓存跳过 -> 执行 -> 状态写盘 -> 检查点/错误控制。"""
        # 消费即清零：防止一次重试导致后续所有阶段/所有集绕过缓存重跑
        retry = self._retry_requested
        self._retry_requested = False
        if retry and not self._retry_matches(ep_id, stage):
            retry = False
        while True:
            self._wait_for_resume()
            if self._cancel_flag:
                raise PipelineCancelled()

            if not retry and self.state.is_done(ep_id, stage):
                # 剧本阶段缓存命中时补一次资源图：旧逻辑里资源图生成失败只写日志、
                # 不改变阶段状态，续跑会带着空参考图直接进视频阶段。
                if stage == "script":
                    self._progress(ep_id, stage, "running",
                                   "正在检查并补齐角色/场景/道具参考图...")
                    _asset = self._generate_resource_images(
                        {},
                        on_item=lambda txt: self._progress(
                            ep_id, stage, "running", f"正在补齐参考图：{txt}"))
                    if _asset.get("ok"):
                        self._log(f"[资源图] 补齐 {_asset['ok']} 张缺失参考图")
                artifacts = self.state.get_artifacts(ep_id, stage)
                self._progress(ep_id, stage, "cached", f"{STAGE_LABELS[stage]}已完成，跳过")
                return artifacts

            self._progress(ep_id, stage, "running", f"正在执行：{STAGE_LABELS[stage]}")
            self.state.mark_running(ep_id, stage)
            # 标记本次是否为用户显式重试（重试剧本阶段要真正重新生成剧本）
            self._current_stage_retry = retry
            try:
                artifacts = fn(ep_id)
                if isinstance(artifacts, str):
                    artifacts = [artifacts]
            except PipelineCancelled:
                raise
            except Exception as e:
                # 已按「终止」→ 直接按取消收尾，别再弹「执行失败，可重试」
                if self._cancel_flag:
                    raise PipelineCancelled()
                self.state.mark_failed(ep_id, stage, str(e))
                self._log(f"[{STAGE_LABELS[stage]}] 失败: {e}")
                traceback.print_exc()
                if not self.on_error:
                    raise  # headless：遇错即停
                # GUI：暂停等待用户决定（继续=跳过？不允许；重试=重跑；取消=终止）
                self._progress(ep_id, stage, "failed", str(e))
                self._retry_requested = False
                self._resume_event.clear()
                try:
                    self.on_error(ep_id, stage, str(e))
                except Exception:
                    traceback.print_exc()
                self._wait_for_resume()
                if self._cancel_flag:
                    raise PipelineCancelled()
                retry = True  # 恢复即重试本阶段
                continue

            self.state.mark_done(ep_id, stage, artifacts)
            self._progress(ep_id, stage, "success", f"{STAGE_LABELS[stage]}完成")

            if stage in self.params.checkpoints and self.on_checkpoint:
                self._retry_requested = False
                self._resume_event.clear()
                self._progress(ep_id, stage, "checkpoint", f"{STAGE_LABELS[stage]}检查点：等待确认")
                try:
                    self.on_checkpoint(ep_id, stage, artifacts)
                except Exception:
                    traceback.print_exc()
                self._wait_for_resume()
                if self._cancel_flag:
                    raise PipelineCancelled()
                if self._retry_requested:
                    self.state.mark_pending(ep_id, stage)
                    retry = True
                    continue
            return artifacts

    def _retry_matches(self, ep_id, stage):
        return True  # 同一时刻只会卡在一个阶段上，恢复即重试该阶段

    def _wait_for_resume(self):
        # 轮询等待，兼顾 cancel 响应；无 on_error/on_checkpoint 时（headless）不应走到这里，
        # 但加 5s 超时兜底防止意外死锁
        while not self._resume_event.wait(timeout=5.0):
            if self._cancel_flag:
                return
            self._log("[等待恢复] 已等待 5s，仍在等待用户操作...")

    # ================= 阶段实现 =================
    def _get_api_config(self, type_):
        # 每次读取前重新加载配置，确保设置页的修改立即生效
        # ConfigManager.get() 已自动感知文件 mtime 变化，无需每次强制 reload
        cfgs = self.config.get("api_configs") or []
        typed = [c for c in cfgs if c.get("type") == type_]
        # 设置页「设为默认」优先：同类型多条配置时必须用默认那条。
        # 此前 next() 取第一条——Image 同时有 z-image 和 moss-image 时，
        # 永远取到先录入的旧配置，设置里勾的默认根本没生效。
        return next((c for c in typed if c.get("is_default")), None) \
            or (typed[0] if typed else {}) or {}

    def _get_embedding_config(self):
        """获取 embedding 独立配置（未单独配置时回退到 LLM 配置）。"""
        try:
            cfg = self.config.get_embedding_config()
            if cfg and cfg.get("api_key"):
                return cfg
        except Exception:
            pass
        # 回退：用 LLM 凭证
        llm = self._get_api_config("LLM")
        cfg = dict(llm)
        cfg.pop("model", None)
        cfg["model"] = self.config.get("embedding_model", "text-embedding-3-small")
        return cfg

    def _script_path(self, ep_id):
        return os.path.join(self.project_dir, "scripts", f"episode_{int(ep_id)}.json")

    def _storyboard_path(self, ep_id):
        return os.path.join(self.project_dir, "storyboards", f"episode_{int(ep_id)}.json")

    def _ep_dir(self, kind, ep_id):
        path = os.path.join(self.project_dir, kind, f"episode_{int(ep_id)}")
        os.makedirs(path, exist_ok=True)
        return path

    def _load_script(self, ep_id):
        with open(self._script_path(ep_id), 'r', encoding='utf-8') as f:
            return Script.from_json(f.read())

    def _load_storyboard(self, ep_id):
        with open(self._storyboard_path(ep_id), 'r', encoding='utf-8') as f:
            return Storyboard.from_json(f.read())

    def _generate_project_outline(self, series, llm_cfg):
        """为项目生成一份与集数一致的故事大纲，返回大纲文本（失败返回 ""）。

        一键成片创建的项目此前只有 premise=主题，没有真正大纲；
        这里在生成剧本前补一次 LLM 调用，产出可直接在项目页「大纲」查看的内容。
        集数必须来自项目元数据，避免只有 1 集却产出多集大纲。
        """
        topic = (self.params.topic or "").strip()
        if not topic:
            return ""
        try:
            total_eps = int(series.data.get("total_episodes") or self.params.episode_count or 1)
        except (TypeError, ValueError):
            total_eps = 1
        total_eps = max(total_eps, 1)

        if total_eps == 1:
            scope_zh = "本剧只有 1 集，严禁出现任何集数范围（如“1-5集”），只描述第 1 集剧情，标题格式为“**第1集：标题**”。"
            scope_en = "This series has only 1 episode: NEVER produce episode ranges. Describe only Episode 1."
        else:
            scope_zh = (f"本剧共 {total_eps} 集，按每 5 集为一段划分（末段可不足 5 集），"
                        f"格式如“**1-5集：标题**”，不得超出 {total_eps} 集。")
            scope_en = (f"This series has {total_eps} episodes: group them by 5 "
                        f"(the last group may be shorter) and never exceed {total_eps}.")

        if self.params.language == "en":
            prompt = (
                f"Write a detailed story outline (Markdown) for a short-drama project.\n"
                f"Theme: {topic}\nGenre: {self.params.style}\nNumber of Episodes: {total_eps}\n\n"
                f"MANDATORY:\n"
                f"1. Output a FULL outline, not just the title; at least 500 words.\n"
                f"2. Include the overall story arc (beginning, rising action, climax, ending).\n"
                f"3. {scope_en}\n"
                f"4. Highlight key conflicts, turning points and climaxes.\n"
                f"5. Use Markdown with blank lines between sections.\n"
                f"6. Never invent more episodes than stated above.\n"
                f"7. {getattr(self.params, 'fidelity_instruction', '')}\n"
            )
            system_prompt = ("You are a professional short-drama screenwriter. Write a complete, detailed "
                             f"outline of at least 500 words. It MUST match {total_eps} episode(s).")
        else:
            prompt = (
                f"请为以下短剧项目写一份详细的故事大纲（Markdown 格式）：\n"
                f"主题：{topic}\n类型：{self.params.style}\n集数：{total_eps}\n\n"
                f"必须遵守：\n"
                f"1. 必须输出完整大纲，禁止只回显标题，不少于 500 字。\n"
                f"2. 必须包含整体故事弧线（开端→发展→高潮→结局）。\n"
                f"3. {scope_zh}\n"
                f"4. 突出关键冲突、转折点和高潮。\n"
                f"5. 使用 Markdown 格式，章节之间空行分隔。\n"
                f"6. 严禁超出上述集数。\n"
                f"7. {getattr(self.params, 'fidelity_instruction', '')}\n"
            )
            system_prompt = ("你是一位专业的短剧编剧。请输出一份完整、详细、不少于 500 字的故事大纲，"
                             f"且必须与项目实际集数（{total_eps} 集）完全一致。")

        client = LLMClient(api_key=llm_cfg.get("api_key"),
                           base_url=llm_cfg.get("base_url"),
                           model=llm_cfg.get("model"))
        return (client.generate_script(prompt, system_prompt=system_prompt) or "").strip()

    # ================= 长篇原作素材处理 =================
    def _prepare_long_source(self, series, llm_cfg):
        """长篇原作预处理：分块 → 逐块摘要 → 全书大纲 → 向量入库。"""
        try:
            from core.script.source_chunker import (
                prepare_long_source, ensure_source_chunks_clean, LongSourceCancelled,
            )
        except ImportError:
            from src.core.script.source_chunker import (
                prepare_long_source, ensure_source_chunks_clean, LongSourceCancelled,
            )
        # 清掉可能存在的旧索引，避免重复入库
        ensure_source_chunks_clean(series.vector_store)
        self._log("检测到长篇原作，正在分块/摘要/建立索引...")
        try:
            result = prepare_long_source(
                self.params.source_text, series, llm_cfg or {},
                embedding_config=self._get_embedding_config(),
                on_progress=lambda step, msg: self._log(msg),
            )
        except LongSourceCancelled:
            # 用户点了「终止」→ 转成流水线取消，而不是报错弹重试
            self._log("长篇素材处理已终止")
            raise PipelineCancelled()
        n = len(result.get("chunks") or [])
        self._log(f"长篇素材处理完成：{n} 块，大纲 {len(result.get('outline') or '')} 字")
        return result

    def _resolve_script_prompt(self, series, ep_id):
        """生成本集实际使用的 prompt：原作上下文 + 改编幅度指令。"""
        prompt = self._build_source_prompt(series, ep_id)
        fid = getattr(self.params, "fidelity_instruction", "") or ""
        if fid:
            prompt = f"{prompt}\n\n{fid}"
        return prompt

    def _build_source_prompt(self, series, ep_id):
        """长篇模式：返回「全书大纲 + 本集对应块摘要 + 检索到的原文块」，
        从而把单次 prompt 控制在上下文窗口内；短篇模式：返回完整主题。
        """
        if not self.params.has_long_source:
            return self.params.full_topic
        try:
            from core.script.source_chunker import build_episode_source_context
        except ImportError:
            from src.core.script.source_chunker import build_episode_source_context
        ctx = build_episode_source_context(
            series, ep_id, self.params.episode_count,
            embedding_config=self._get_embedding_config(),
        )
        if ctx:
            return ctx
        # 回退：大纲 + 截断原文，绝不直接塞全文
        outline = (series.data.get("source_outline") or "").strip()
        if outline:
            return f"{outline}\n\n（原文过长，已按块处理）"
        # 预处理失败时，至少给出截断的原文，而不是只给短标题
        src = (self.params.source_text or "").strip()
        if src:
            return src[:4000]
        return self.params.full_topic[:4000]

    def _stage_script(self, ep_id):
        """剧本生成（含角色/道具/场景资源创建、提示词增强、剧集入库、分镜构建）。

        分镜（storyboard）已并入本阶段：视频片段本来就靠"角色图+场景图+道具图+提示词"
        直接生成，分镜只是把剧本镜头转成带角色ID/提示词/时长的面板，不再单列阶段。
        """
        series = SeriesManager(self.project_dir)
        llm_cfg = self._get_api_config("LLM")

        # 续跑快路径：旧状态里剧本已生成、仅分镜缺失 → 跳过 LLM，只重建分镜
        # 注意：用户显式「重试」本阶段时必须真正重新生成剧本，不能走快路径
        _stage_info = self.state.get_stage(ep_id, "script") or {}
        _extra = _stage_info.get("extra") or {}
        _script_path = self._script_path(ep_id)
        if (_extra.get("script_ready") and not getattr(self, "_current_stage_retry", False)
                and os.path.isfile(_script_path) and os.path.getsize(_script_path) > 0):
            self._log("检测到已有可用剧本，跳过剧本生成，仅重建分镜...")
            try:
                _sb_path = self._stage_storyboard(ep_id)
            except Exception:
                raise
            # 重建成功 → 清掉快路径标记，后续显式重试才会真正重新生成剧本
            try:
                self.state.set_stage_artifact_extra(ep_id, "script", "script_ready", False)
            except Exception:
                pass
            return [_script_path, _sb_path]

        # 确保系列元数据（premise/genre/main_characters/total_episodes）已写入 series.json，
        # 否则后续集生成时 prompt 中这些字段全空，AI 会拒绝生成。
        _series_dirty = False
        # 大纲：仅当缺失或仍等于主题时生成一次（生成失败不阻断流程）
        # 长篇原作模式跳过通用大纲生成，改由分块摘要汇总出全书大纲。
        _topic = (self.params.topic or "").strip()
        _premise = (series.data.get("premise") or "").strip()
        if not self.params.has_long_source and ((not _premise) or (_topic and _premise == _topic)):
            try:
                self._log("正在生成项目大纲...")
                _outline = self._generate_project_outline(series, llm_cfg)
            except Exception as e:
                self._log(f"生成大纲失败（忽略继续）: {e}")
                _outline = ""
            if _outline:
                series.data["premise"] = _outline
                self._log("项目大纲已生成")
            elif not _premise:
                series.data["premise"] = self.params.full_topic
            _series_dirty = True
        if not series.data.get("genre") and self.params.style:
            series.data["genre"] = self.params.style
            _series_dirty = True
        if not series.data.get("total_episodes"):
            series.data["total_episodes"] = max(self.params.episode_count, 1)
            _series_dirty = True
        if not series.data.get("main_characters"):
            try:
                from core.project.series_manager import load_character_references
            except ImportError:
                from src.core.project.series_manager import load_character_references
            chars = load_character_references(self.project_dir)
            if chars:
                series.data["main_characters"] = chars
                _series_dirty = True

        # 长篇原作素材：首次生成前做分块/摘要/大纲/向量化，避免全文塞进 prompt
        if self.params.has_long_source and not series.is_long_source():
            try:
                self._prepare_long_source(series, llm_cfg)
            except PipelineCancelled:
                raise                     # 用户终止：不要降级继续跑
            except Exception as e:
                self._log(f"长篇素材预处理失败（将尝试截断处理）: {e}")
            # 用全书大纲补 premise，供 build_script_prompt 使用
            if not (series.data.get("premise") or "").strip():
                series.data["premise"] = series.data.get("source_outline") or self.params.full_topic
                _series_dirty = True
        if _series_dirty:
            series.save()

        # 1) 取剧本数据：指定剧本文件 > 队列 > LLM/mock
        if self.params.existing_script_path:
            if not os.path.isfile(self.params.existing_script_path):
                raise FileNotFoundError(f"指定的剧本文件不存在: {self.params.existing_script_path}")
            with open(self.params.existing_script_path, 'r', encoding='utf-8') as f:
                script_data = json.load(f)
            self._log(f"使用指定剧本: {os.path.basename(self.params.existing_script_path)}")
        else:
            script_data = self.state.pop_script_queue()
            if script_data is not None:
                self._log("使用此前 LLM 一次返回的多集剧本包中的下一集")
            else:
                # 上下文（RAG/前情摘要）失败不阻断流程
                context_data = {}
                prompt_text = self._resolve_script_prompt(series, ep_id)
                try:
                    self._log("正在获取上下文（前情摘要/角色状态）...")
                    context_data = series.get_full_context_data(
                        prompt_text, embedding_config=self._get_embedding_config(),
                        current_ep_id=ep_id) or {}
                    self._log("上下文获取完成")
                except Exception as e:
                    self._log(f"获取上下文失败（忽略继续）: {e}")
                self._log("正在构建 prompt 并调用 LLM 生成剧本...")
                script_data = script_service.generate_script_data(
                    prompt=prompt_text,
                    api_config=llm_cfg,
                    duration=self.params.duration,
                    style=self.params.style,
                    context_data=context_data,
                    language=self.params.language,
                    allow_mock=self.params.allow_mock,
                    panel_count=self.params.panel_count,
                    shot_duration=self.params.shot_duration or None,
                )
                self._log("LLM 剧本返回，正在解析 JSON...")

        # Handle list response (WB-9: explicit handling)
        if isinstance(script_data, list):
            if len(script_data) == 1 and isinstance(script_data[0], dict):
                script_data = script_data[0]
            else:
                raise RuntimeError(f"LLM 返回顶层为数组（{len(script_data)} 项），应为单个剧本对象")

        # 2) LLM 一次返回多集时的排队处理
        if isinstance(script_data, dict) and isinstance(script_data.get("episodes"), list) \
                and len(script_data["episodes"]) > 1:
            episodes_pkg = [e for e in script_data["episodes"] if isinstance(e, dict)]
            script_data = episodes_pkg.pop(0)
            self.state.push_script_queue(episodes_pkg)
            self._log(f"LLM 返回了 {len(episodes_pkg) + 1} 集剧本包，多余的已排队")

        # 2b) 总时长治理：每集分镜总时长必须 ≥75 秒
        # （覆盖指定剧本/多集剧本包路径；LLM 路径已在 generate_script_data 内治理）
        script_service.ensure_min_total_duration(script_data)

        # 3) 资源创建 + 提示词增强 + 入库
        self._log("正在创建角色/道具/场景资源...")
        created = script_service.create_resources_from_data(script_data, self.project_dir)
        # 3b) 自动生成角色/场景/道具参考图——这是后续分镜一致性的基础
        self._generate_resource_images(created)
        self._log("正在增强视频提示词...")
        script_data = script_service.enhance_video_prompts(script_data)

        # 标题清洗：LLM 可能返回英文/中文占位或空标题，统一转为"第N集"兜底
        raw_title = (script_data.get("title") or "").strip()
        import re as _re
        # 匹配 "Episode 1" / "第1集" / "第3话" / "EP05" 等纯集数占位标题
        _placeholder_re = _re.compile(
            r'(?i)^(?:episode\s*\d+|第\s*[0-9一二三四五六七八九十百]+\s*[集话]|ep\.?\s*\d+|untitled episode|generated episode)$'
        )
        series_title = (series.data.get("title") or "").strip()
        if (not raw_title
                or _placeholder_re.match(raw_title)
                or (series_title and raw_title == series_title)):
            raw_title = f"第{int(ep_id)}集"
        title = raw_title
        self._log(f"正在保存剧集《{title}》...")
        # 重试/重做时该 ep_id 可能已注册在 series 中：必须 update 而非 add，
        # 否则 add 取 max(id)+1 会写成 episode_{n+1}.json，与 _script_path(ep_id) 对不上
        _existing = next((e for e in series.data.get("episodes", [])
                          if e.get("id") == ep_id), None)
        if _existing is not None:
            ok = series.update_episode(ep_id, title,
                                       json.dumps(script_data, ensure_ascii=False),
                                       api_config=llm_cfg or None)
            if not ok:
                raise RuntimeError(f"更新已有剧集失败（ep_id={ep_id}）")
            self._log(f"剧集 ep_id={ep_id} 已存在，按更新覆盖保存（非新增）")
        else:
            series.add_episode(title, json.dumps(script_data, ensure_ascii=False),
                               api_config=llm_cfg or None)

        path = self._script_path(ep_id)
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            raise RuntimeError(f"剧集保存后未找到剧本文件: {path}")
        self._log(f"第 {ep_id} 集剧本《{title}》已保存")

        # 分镜并入本阶段：失败时标记 script_ready，续跑只需重建分镜、不重调 LLM
        try:
            storyboard_path = self._stage_storyboard(ep_id)
        except Exception:
            try:
                self.state.set_stage_artifact_extra(ep_id, "script", "script_ready", True)
            except Exception:
                pass
            raise
        # 成功：清掉快路径标记，后续显式重试才会真正重新生成剧本
        try:
            self.state.set_stage_artifact_extra(ep_id, "script", "script_ready", False)
        except Exception:
            pass
        return [path, storyboard_path]

    def _generate_resource_images(self, created, on_item=None):
        """为新创建及已有但缺图的角色/场景/道具自动生成参考图。
        这些图是后续分镜一致性的基础——角色图用作 IP-Adapter/LoRA 参考，
        场景图用作 ControlNet 参考，缺图时一致性工作流只能退化成纯文生图。"""
        stats = {"ok": 0, "fail": 0, "skip": 0}
        img_cfg = self._get_api_config("Image")
        if not img_cfg:
            self._log("[资源图] 未配置 Image API，跳过资源图生成")
            return stats
        client = ImageGenClient(
            api_key=img_cfg.get("api_key"),
            base_url=img_cfg.get("base_url"),
            model=img_cfg.get("model"),
            provider=img_cfg.get("provider"),
            api_config=img_cfg,
        )

        def _split_prompt(ai_prompt):
            if not ai_prompt:
                return ""
            marker = "[反向提示词]"
            if marker in ai_prompt:
                return ai_prompt[:ai_prompt.index(marker)].strip()
            return ai_prompt.strip()

        def _needs_image(obj, field):
            v = getattr(obj, field, "") or ""
            return not (v and os.path.exists(v))

        def _gen_one(label, obj, img_field, alt_fields, subdir, prefix):
            if not obj:
                return
            # 任一视图字段已有图就跳过
            if not _needs_image(obj, img_field):
                stats["skip"] += 1
                return
            for af in alt_fields:
                if getattr(obj, af, "") and os.path.exists(getattr(obj, af)):
                    stats["skip"] += 1
                    return
            prompt = _split_prompt(getattr(obj, "ai_prompt", "") or getattr(obj, "default_ai_prompt", ""))
            if not prompt:
                stats["skip"] += 1
                return
            out_dir = os.path.join(self.project_dir, subdir)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{prefix}_{obj.id}.png")
            self._log(f"[资源图] 生成{label}图: {obj.name} ...")
            if on_item:
                try:
                    on_item(f"{label} {obj.name}")
                except Exception:
                    pass
            try:
                result = client.generate_image(prompt, out_path)
                if result and os.path.exists(result):
                    setattr(obj, img_field, result)
                    for af in alt_fields:
                        setattr(obj, af, result)
                    obj.save(self.project_dir)
                    stats["ok"] += 1
                    self._log(f"[资源图] {label}图完成: {obj.name}")
                else:
                    stats["fail"] += 1
                    self._log(f"[资源图] {label}图失败: {obj.name}")
            except Exception as e:
                stats["fail"] += 1
                self._log(f"[资源图] {label}图异常 {obj.name}: {e}")

        # ---- 新创建的资源 ----
        # 记录已处理过的 id：下面扫描磁盘时会再遇到同一批资源，
        # 失败项会被重复生成一次（每张图多等一轮），因此统一去重。
        _tried = set()
        for char in created.get("characters", []):
            if getattr(char, "id", None):
                _tried.add(str(char.id))
            _gen_one("角色", char, "front_view", ["avatar_path"], "characters", "char")
        for prop in created.get("props", []):
            if getattr(prop, "id", None):
                _tried.add(str(prop.id))
            _gen_one("道具", prop, "front_view", ["reference_image"], "props", "prop")
        for scene in created.get("scenes", []):
            if getattr(scene, "id", None):
                _tried.add(str(scene.id))
            _gen_one("场景", scene, "reference_image", ["close_view", "wide_view"], "scenes", "scene")

        # ---- 扫描已有但缺图的资源（断点续跑 / 重跑场景）----
        try:
            from core.character.character_model import Character
            from core.prop.prop_model import Prop
            from core.scene.scene_model import Scene
        except ImportError:
            from src.core.character.character_model import Character
            from src.core.prop.prop_model import Prop
            from src.core.scene.scene_model import Scene

        def _load_all(model_cls, subdir):
            d = os.path.join(self.project_dir, subdir)
            if not os.path.isdir(d):
                return []
            objs = []
            for fn in os.listdir(d):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        objs.append(model_cls.from_json(f.read()))
                except Exception:
                    pass
            return objs

        for char in _load_all(Character, "characters"):
            if str(char.id) in _tried:
                continue
            _gen_one("角色", char, "front_view", ["avatar_path"], "characters", "char")
        for prop in _load_all(Prop, "props"):
            if str(prop.id) in _tried:
                continue
            _gen_one("道具", prop, "front_view", ["reference_image"], "props", "prop")
        for scene in _load_all(Scene, "scenes"):
            if str(scene.id) in _tried:
                continue
            _gen_one("场景", scene, "reference_image", ["close_view", "wide_view"], "scenes", "scene")

        return stats

    def _stage_storyboard(self, ep_id):
        """剧本 -> 分镜（纯规则转换，属于「剧本+分镜」阶段的内部步骤）。"""
        self._log(f"正在加载第 {ep_id} 集剧本...")
        script = self._load_script(ep_id)
        self._log("正在加载角色映射...")
        char_map = storyboard_builder.load_character_map(self.project_dir)
        self._log("正在构建一致性锚点表...")
        # 从角色库/场景库实时构建锚点表（此前仅 load 磁盘文件，但从未 save 过，永远为空）
        try:
            try:
                from core.consistency.anchor_model import AnchorTable
            except ImportError:
                from src.core.consistency.anchor_model import AnchorTable
            anchor_table = AnchorTable.from_project(self.project_dir)
            anchor_table.save(self.project_dir)  # 持久化，供 image_client 等读取
        except Exception as e:
            self._log(f"构建锚点表失败（降级纯提示词）: {e}")
            anchor_table = storyboard_builder.load_anchor_table(self.project_dir)
        # 锚点就绪校验：空表则降级为纯提示词模式
        if anchor_table.characters or anchor_table.scenes:
            self._log(f"锚点表就绪：{len(anchor_table.characters)} 角色 / {len(anchor_table.scenes)} 场景")
        else:
            self._log("锚点表为空，将使用纯提示词模式（降级）")
        self._log("正在构建分镜（内部步骤）...")
        storyboard = storyboard_builder.build_storyboard_from_script(
            script, char_map, getattr(script, "title", ""), anchor_table=anchor_table,
            scene_map=storyboard_builder.load_scene_map(self.project_dir),
            prop_map=storyboard_builder.load_prop_map(self.project_dir))
        if not storyboard.panels:
            raise RuntimeError(f"第 {ep_id} 集分镜生成结果为空（0 个分镜）——请检查剧本是否有分场/镜头内容")
        path = self._storyboard_path(ep_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        storyboard.save(path)
        self._log(f"分镜构建完成，共 {len(storyboard.panels)} 个分镜")
        return path

    def _free_gpu_for_video(self):
        """视频生成前卸载本地 LLM，释放显存给 ComfyUI（失败不阻断流程）。"""
        try:
            try:
                from ai_engine.llm.llm_client import unload_model
            except ImportError:
                from src.ai_engine.llm.llm_client import unload_model
        except Exception:
            return
        try:
            llm_cfg = self._get_api_config("LLM") or {}
            base_url = (llm_cfg.get("base_url") or "").strip()
            model = (llm_cfg.get("model") or "").strip()
            if not base_url or not model:
                return
            ok, msg = unload_model(base_url, model)
            if ok:
                self._log(f"[图生视频] {msg}（为视频生成腾出显存）")
        except Exception as e:
            self._log(f"[图生视频] 释放 LLM 显存失败（忽略继续）: {e}")

    def _free_comfyui_memory(self, reason="", unload_models=True):
        """请求 ComfyUI 卸载缓存模型并释放显存（POST /free），失败仅记录不阻断。

        资源图阶段会在 ComfyUI 里留下图像模型缓存，与 20GB 视频模型叠加
        会推高 VRAM/系统资源占用，后半程片段易 OOM/hostbuf 级联失败。
        unload_models=False 时只整理显存碎片，模型保持常驻——避免每个片段
        都重新加载 20GB 模型，那样单个片段会多等数分钟。"""
        video_cfg = self._get_api_config("Video") or {}
        base = (video_cfg.get("base_url") or "").strip()
        if not base:
            return
        try:
            import requests as _req
            r = _req.post(base.rstrip("/") + "/free",
                          json={"unload_models": bool(unload_models),
                                "free_memory": True},
                          timeout=(10, 60), proxies={"http": None, "https": None})
            if r.status_code < 400:
                self._log(f"[图生视频] 已请求 ComfyUI "
                          f"{'卸载模型并' if unload_models else ''}释放显存"
                          f"{'：' + reason if reason else ''}")
            else:
                self._log(f"[图生视频] ComfyUI 释放显存返回 {r.status_code}（忽略）")
        except Exception as _e:
            self._log(f"[图生视频] ComfyUI 释放显存请求失败（忽略）: {type(_e).__name__}")

    @staticmethod
    def _memory_status_mb():
        """返回 (可用物理内存MB, 可用提交内存MB)；非 Windows/失败返回 (None, None)。

        HostBuffer.read_file_slice failed（Windows error 1450）的判定依据是
        提交内存（物理内存+页面文件）耗尽，只看物理内存会漏判，
        因此同时返回两项。"""
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                mb = 1024 * 1024
                return (st.ullAvailPhys // mb, st.ullAvailPageFile // mb)
        except Exception:
            pass
        return (None, None)

    def _prepare_video_submit(self, reason=""):
        """每次提交视频任务前的资源清理：先清显存，内存不足时深度清理。

        用户要求「提交任务时先清理显存和内存」——这里每次提交都做一次轻量
        /free（只整理碎片，模型常驻），仅在提交内存低于 4GB 时才卸载模型
        并等待系统回收，兼顾速度与稳定。"""
        _, commit_mb = self._memory_status_mb()
        threshold = 4096
        if commit_mb is None or commit_mb >= threshold:
            self._free_comfyui_memory(f"{reason}（提交前清理显存）",
                                      unload_models=False)
            return
        self._log(f"[资源清理] 可用提交内存仅 {commit_mb}MB（<{threshold}MB），"
                  f"提交前深度清理：卸载模型 + 释放显存 + 等待系统回收 ...")
        self._free_comfyui_memory(f"{reason}（内存不足，深度清理）",
                                  unload_models=True)
        for _ in range(20):
            if self._cancel_flag:
                raise PipelineCancelled()
            time.sleep(1)
        _, commit2 = self._memory_status_mb()
        if commit2 is not None and commit2 < threshold:
            self._log(f"[资源清理] 等待后可用提交内存 {commit2}MB 仍偏低，"
                      f"继续尝试（如反复失败请增大 Windows 页面文件）")
        else:
            self._log(f"[资源清理] 清理后可用提交内存 {commit2}MB，继续提交")

    @staticmethod
    def _continuity_text(value):
        """把任意字段值收敛为单行文本。

        LLM 返回的 action/continuity_note 可能是 list/dict（JSON 无类型约束），
        直接 .strip() 会抛 'list' object has no attribute 'strip'。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            parts = [AutoRunController._continuity_text(v) for v in value]
            return "；".join(p for p in parts if p)
        if isinstance(value, dict):
            for key in ("action", "pose", "content", "description"):
                if key in value:
                    text = AutoRunController._continuity_text(value[key])
                    if text:
                        return text
            return ""
        return str(value).strip()

    @staticmethod
    def _panel_action_text(panel):
        """提取上一镜面板的动作文本（供接戏注入）。

        Panel 本身没有 action 字段；动作按优先级存放于
        prompt_params['_action']（builder 写入的 scene.action）、
        video_params['action']（合并动作）、prompt_params['_dialogues']。"""
        params = getattr(panel, "prompt_params", None) or {}
        text = AutoRunController._continuity_text(params.get("_action"))
        if text:
            return text
        vparams = getattr(panel, "video_params", None) or {}
        text = AutoRunController._continuity_text(vparams.get("action"))
        if text:
            return text
        dialogues = params.get("_dialogues")
        if isinstance(dialogues, (list, tuple)):
            parts = []
            for d in dialogues:
                if isinstance(d, dict):
                    role = AutoRunController._continuity_text(d.get("role"))
                    action = AutoRunController._continuity_text(d.get("action"))
                    if action:
                        parts.append(f"{role}{action}" if role else action)
            return "；".join(parts)
        return ""

    @staticmethod
    def _panel_state_text(panel, max_chars=3):
        """提取上一镜角色状态摘要（衣着/情绪/姿态），供"状态承接"注入。

        数据来自 builder 写入的 prompt_params['_char_states']
        （= scene.characters_detail 列表）。参考图是干净定妆照，
        不注入状态变化时下一镜会把湿透/受伤等状态重置回去。"""
        states = (getattr(panel, "prompt_params", None) or {}).get("_char_states")
        if not isinstance(states, (list, tuple)):
            return ""
        parts = []
        for c in states:
            if not isinstance(c, dict):
                continue
            name = AutoRunController._continuity_text(c.get("name"))
            if not name:
                continue
            bits = []
            for key, label in (("clothing_note", "衣着"),
                               ("emotional_state", "情绪"),
                               ("pose", "姿态")):
                v = AutoRunController._continuity_text(c.get(key))
                if v:
                    bits.append(f"{label}{v}")
            if bits:
                parts.append(f"{name}（{'、'.join(bits)}）")
            if len(parts) >= max_chars:
                break
        return "；".join(parts)

    @staticmethod
    def _panel_scene_key(panel):
        """提取分镜的场景键（location+time），供换场判定。

        数据来自 builder 写入的 prompt_params['_scene_key']。
        天气不纳入判定：雨雪渐起属同场景正常连续。"""
        sk = (getattr(panel, "prompt_params", None) or {}).get("_scene_key") or {}
        if not isinstance(sk, dict):
            return ("", "")
        return (str(sk.get("location") or "").strip(),
                str(sk.get("time") or "").strip())

    @staticmethod
    def _with_continuity(prompt, panel, prev_panel=None, is_last=False):
        """生成时把分镜衔接信息注入视频提示词（【上一镜衔接】段）。

        分镜层一直在记录 continuity_note（同场景续/场景过渡/时间跳跃），
        但此前没有任何消费者——视频模型不知道上一镜结尾长什么样，
        镜头边界处人物姿态/光线/构图各起各的，观感跳变。
        v2 增强：注入上一镜的收尾动作做动作接戏，并按镜位给出结尾指令
        ——中段镜保持动势直接切出，仅末镜允许淡出。
        v3 增强：注入上一镜角色状态（衣着/情绪/姿态），防止状态重置。
        v4 增强：换场感知——按 _scene_key 区分同场景续与换场过渡；
        跨场景不再要求延续上一镜构图/动作（避免 i2v 把无关场景硬性渐变），
        仅保持剧情时间线与角色状态连续。
        幂等：提示词已含该段（v1/v2）则原样返回。"""
        if not prompt or "【上一镜衔接】" in prompt:
            return prompt
        params = getattr(panel, "prompt_params", None) or {}
        note = AutoRunController._continuity_text(params.get("_continuity"))
        prev_action = ""
        prev_state = ""
        same_scene = True
        if prev_panel is not None:
            prev_action = AutoRunController._panel_action_text(prev_panel)
            prev_state = AutoRunController._panel_state_text(prev_panel)
            cur_key = AutoRunController._panel_scene_key(panel)
            prev_key = AutoRunController._panel_scene_key(prev_panel)
            # 两侧都有场景信息时才判定换场，缺失时默认同场景续（保持既有行为）
            if all(cur_key) and all(prev_key):
                same_scene = (cur_key == prev_key)
        if not note and not prev_action and not prev_state:
            return prompt
        lines = ["", "【上一镜衔接】"]
        if note:
            lines.append(f"- 衔接说明：{note}")
        if same_scene and prev_action:
            lines.append(f"- 上一镜收尾动作：{prev_action}"
                         "（本镜从该动作的下一拍开始，禁止重新起势、重复到达过程）")
        if prev_state:
            lines.append(f"- 状态承接：{prev_state}"
                         "（服装/情绪/姿态与上一镜保持连续，"
                         "禁止湿透后变干爽、受伤后凭空痊愈等状态重置）")
        if prev_panel is not None:
            # 仅存在上一镜时才给场景衔接指令；首镜引用"上一镜"会误导模型
            if same_scene:
                lines.append("- 本镜必须与上一镜在场景、时间、光线、角色姿态上自然连续；"
                              "同场景续时直接延续上一镜的收尾画面，禁止重新起镜、换景或光线突变")
            else:
                lines.append("- 换场过渡：本镜为新场景开场，重新建立空间关系与光线氛围，"
                              "无需延续上一镜的构图与机位（避免跨场景画面渐变变形）；"
                              "仅保持剧情时间线、角色状态与情绪基调连续")
        if is_last:
            lines.append("- 本镜是全片最后一镜：以悬念/余韵收尾，允许停留后淡出")
            lines.append("- 音乐与环境音与上一镜无缝延续，仅结尾允许渐弱淡出"
                         "（忽略时间轴中的独立渐入）")
        else:
            lines.append("- 本镜结尾保持动作进行中直接切入下一镜，"
                         "禁止淡出、黑场或停格")
            lines.append("- 音乐与环境音与上一镜无缝延续，忽略时间轴中"
                         "「背景音乐渐入/音乐渐弱」的独立起收")
        return prompt.rstrip() + "\n\n" + "\n".join(lines)

    def _stage_clips(self, ep_id):
        """生成视频片段：按面板角色/场景/道具取参考图，直接由视频提示词生成视频。

        分镜图片已下线：有参考图的分镜走多参考图图生视频，无参考图的走纯提示词生成。
        片段自带音频（MiniMax H3 / LTX 2.5 等），配音与音频后期在视频编辑器中处理。"""
        storyboard = self._load_storyboard(ep_id)
        composer = self._get_composer()
        out_dir = self._ep_dir("clips", ep_id)
        artifacts = []
        total = len(storyboard.panels)

        # 断点续跑兜底：剧本阶段一旦标记成功，整段（含资源图生成）会被跳过。
        # 若上次是 Image API / ComfyUI 不可达导致角色/场景/道具图缺失，
        # 「继续生成」会直接跑到视频阶段、每镜 0 参考图出片。这里先补齐缺图。
        self._log("正在检查角色/场景/道具参考图...")
        _asset = self._generate_resource_images(
            {},
            on_item=lambda txt: self._progress(
                ep_id, "clips", "running", f"正在补齐参考图：{txt}"))
        if _asset.get("ok") or _asset.get("fail"):
            _note = []
            if _asset.get("ok"):
                _note.append(f"补齐 {_asset['ok']} 张")
            if _asset.get("fail"):
                _note.append(f"仍缺 {_asset['fail']} 个（一致性会下降）")
            self._progress(ep_id, "clips", "running",
                           f"参考图{'、'.join(_note)}，开始生成视频片段")

        # 分镜图片与静态图合成已下线：视频片段始终由图生视频生成，
        # 不再依据 use_video_gen 开关切换路径（旧状态文件里的 False 不再生效）
        video_cfg = self._get_api_config("Video")
        video_client = VideoGenClient(
            api_key=video_cfg.get("api_key"),
            base_url=video_cfg.get("base_url"),
            model=video_cfg.get("model"),
            provider=video_cfg.get("provider", "mock"),
            api_config=video_cfg,
        )
        # 图生视频前先探测服务器可达性并告知用户；预检查不阻断流程，
        # 服务器仅慢响应时不误跳过，真正不可达时逐片段仍会失败
        vbase = (video_cfg.get("base_url") or "").strip()
        if vbase:
            try:
                import requests as _req
                # 与健康哨兵同量级：ComfyUI 忙时可能几分钟不回包，不能把"忙"当"没起来"
                _req.get(vbase.rstrip("/") + "/system_stats",
                         timeout=(15, 300), proxies={"http": None, "https": None})
                self._log(f"[图生视频] 服务器可达: {vbase}")
            except Exception as _e:
                self._log(f"[图生视频] 服务器预检未响应: {vbase}（{type(_e).__name__}）"
                          f"——仍将逐片段尝试图生视频")
        else:
            self._log("[图生视频] 未配置 base_url")

        # 释放显存：本机 GPU 同时跑 LM Studio(LLM) 与 ComfyUI(视频)，
        # 27B 模型常驻会挤掉 MiniMaxH3 需要的显存，导致视频任务 OOM 卡死/被中断。
        self._free_gpu_for_video()
        # 资源图阶段在 ComfyUI 里加载过图像模型：进入片段生成前清一次缓存，
        # 防止 图像模型+视频模型 叠加导致显存/系统资源逐片段累积 → 后半程 OOM
        self._free_comfyui_memory("片段阶段开始前")

        # 单镜时长收敛到 5-10 秒：超长时长会线性放大采样时间且 >10s 会爆显存
        # （旧剧本/手工编辑的 panel.duration 可能是 20-30 秒）
        try:
            from core.script.script_service import clamp_shot_duration as _clamp_dur
        except ImportError:
            from src.core.script.script_service import clamp_shot_duration as _clamp_dur

        # 防字幕/衔接注入日志：让本轮优化在控制台可见
        _extra_neg = (getattr(self.params, "negative_prompt", "") or "").strip()
        self._log("[防字幕] 已启用——每条视频提示词末尾追加双语禁令（首中尾三段起效）"
                  "；工作流含负向条件节点时同步写入禁令词"
                  + (f"；额外负面词：{_extra_neg}" if _extra_neg else ""))

        # 硬件级联失败熔断：连续 N 个片段因 HostBuffer/OOM 失败（各自已清缓存重试 3 次）
        # 说明主机内存/页面文件已耗尽，继续跑只会把每个片段再白烧一整轮——
        # 立即判失败让用户释放资源后续跑（续跑自动补齐缺失片段）
        _hw_fail_streak = 0
        for idx, panel in enumerate(storyboard.panels, start=1):
            if self._cancel_flag:
                raise PipelineCancelled()
            clip_path = os.path.join(out_dir, f"panel_{panel.panel_id}.mp4")
            if self._clip_is_fresh(clip_path, panel):
                artifacts.append(clip_path)
                continue

            # 新方案：从角色/场景/道具库取参考图，配合视频提示词直接生成视频
            ref_detail = self._collect_panel_ref_images(panel)
            ref_images = [d["path"] for d in ref_detail]
            ref_labels = [d["label"] for d in ref_detail]

            duration = float(_clamp_dur(panel.duration or 8.0))
            clip_w, clip_h = self.params.aspect_wh
            clip_done = False
            ref_desc = "；".join(d["label"] for d in ref_detail) or "无"
            self._log(f"[片段 {idx}/{total}] 图生视频 {panel.panel_id}"
                      f"（{duration:.0f}s，参考图 {len(ref_images)} 张: {ref_desc}）...")
            self._progress(ep_id, "clips", "running",
                           f"片段 {idx}/{total} 生成中（{duration:.0f}s，参考图 {len(ref_images)} 张）")
            raw_video = os.path.join(out_dir, f"raw_{panel.panel_id}.mp4")
            # 衔接注入：continuity_note + 上一镜收尾动作 + 镜位化结尾指令
            gen_prompt = self._with_continuity(
                panel.video_prompt or "动画效果，镜头缓慢推进",
                panel,
                prev_panel=storyboard.panels[idx - 2] if idx >= 2 else None,
                is_last=(idx == total))
            # 衔接注入明细：每镜打印注入了哪些段、状态承接具体内容
            _st_line = next((ln for ln in gen_prompt.splitlines()
                             if ln.startswith("- 状态承接：")), "")
            _st_txt = _st_line.split("：", 1)[-1][:100].strip() if _st_line else ""
            _transit = ("换场过渡" if "- 换场过渡：" in gen_prompt
                        else ("同场景续" if "同场景续" in gen_prompt else "无"))
            self._log(f"[片段 {idx}/{total}] 衔接注入明细："
                      f"衔接说明={'有' if '- 衔接说明' in gen_prompt else '无'}、"
                      f"过渡={_transit}、"
                      f"收尾动作={'有' if '上一镜收尾动作' in gen_prompt else '无'}、"
                      f"状态承接={_st_txt or '无'}")
            res = None
            last_err = ""
            # ComfyUI 首次加载大模型可能出现一次性 execution_interrupted，属正常现象，重试即可恢复；
            # 但生成超时/节点报错这类确定性失败绝不再重试——每个片段 20-30 分钟，重试等于白烧时间。
            # 「被外部中断」多半是环境问题（同机其它任务抢占/显存不足），重试 1 次即可，
            # 连重 3 次会把一个片段拖成 40 分钟以上。
            for attempt in (1, 2, 3):
                if self._cancel_flag:
                    raise PipelineCancelled()
                if attempt > 1:
                    # 显存溢出：同一分辨率重试必然复现，先下调像素预算再试。
                    # 下调后的值记到 _video_megapixels，后续片段直接用，避免反复撞 OOM。
                    if _is_oom_error(last_err):
                        _prev_mp = self._video_megapixels
                        if _prev_mp is None:
                            # 首次 OOM：用服务端报告的实际 megapixels 反推
                            _m = re.search(r"megapixels=([0-9.]+)", last_err or "")
                            _prev_mp = float(_m.group(1)) if _m else 0.52
                        _next_mp = max(_MEGAPIXELS_FLOOR,
                                       round(_prev_mp * _OOM_DOWNSCALE_FACTOR, 2))
                        if _next_mp >= float(_prev_mp or 0):
                            self._log(f"[片段 {idx}/{total}] 显存溢出且已到分辨率下限 "
                                      f"（{_prev_mp}MP），不再降级重试")
                            break
                        self._video_megapixels = _next_mp
                        self._persist_video_megapixels(_next_mp)
                        self._log(f"[片段 {idx}/{total}] 显存不足，分辨率下调 "
                                  f"{_prev_mp}MP → {_next_mp}MP 后重试")
                    self._log(f"[片段 {idx}/{total}] 图生视频第 {attempt} 次尝试"
                              f"（上次失败：{(last_err or '')[:120]}）...")
                    if _is_hardware_transient(last_err):
                        # 显存/系统资源类失败：重试前先清 ComfyUI 缓存，
                        # 否则模型缓存还在，OOM/hostbuf 大概率原样复现
                        self._free_comfyui_memory(
                            f"片段 {panel.panel_id} 第 {attempt} 次重试前")
                        # HostBuffer/read_file_slice 本质是主机已提交内存耗尽
                        # （Windows error 1450），OS 回收需要时间，立即重试会原样复现
                        for _wait in range(15):
                            if self._cancel_flag:
                                raise PipelineCancelled()
                            time.sleep(1)
                if attempt > 2 and _is_interrupt_error(last_err):
                    self._log(f"[片段 {idx}/{total}] 图生视频再次被中断"
                              f"（{last_err[:120]}），停止重试（连续中断通常是环境问题："
                              f"ComfyUI 上有其它任务或显存不足）")
                    break
                t_attempt = time.time()
                try:
                    # 提交前先清理显存/内存（用户要求）：内存充足只整理显存碎片，
                    # 提交内存低于阈值才卸载模型并等待回收，从源头压住
                    # HostBuffer.read_file_slice（error 1450）级联失败
                    self._prepare_video_submit(f"片段 {panel.panel_id}")
                    # 种子按 panel 派生：同一分镜可复现，不同分镜互不相同
                    _seed = None
                    try:
                        _seed = abs(hash((str(ep_id), str(panel.panel_id)))) % (2 ** 31)
                    except Exception:
                        _seed = None
                    res = video_client.generate_video(
                        image_path=None,
                        prompt=gen_prompt,
                        output_path=raw_video,
                        aspect_ratio=self.params.aspect_ratio,
                        duration=duration,
                        end_image_path=None,
                        ref_images=ref_images if ref_images else None,
                        ref_labels=ref_labels if ref_labels else None,
                        seed=_seed,
                        negative_prompt=self.params.negative_prompt,
                        megapixels=self._video_megapixels,
                        # 项目参数里的分辨率档（720p / 1080p）决定生成端的像素预算
                        resolution_preset=self.params.resolution
                    )
                    if isinstance(res, tuple):
                        res = res[0] if res else None
                    if res and os.path.isfile(res) and os.path.getsize(res) > 0:
                        if attempt > 1:
                            self._log(f"[片段 {idx}/{total}] 第 {attempt} 次尝试成功"
                                      f"（{time.time()-t_attempt:.0f}s）")
                        break
                    res = None
                    last_err = getattr(video_client, "last_error", "") or "返回为空"
                except PipelineCancelled:
                    raise
                except Exception as attempt_err:
                    res = None
                    last_err = str(attempt_err)
                # 只对瞬时错误重试；确定性失败（超时/节点报错/文件缺失）立即停止
                if not _video_error_retryable(last_err):
                    self._log(f"[片段 {idx}/{total}] 图生视频失败（{last_err}），"
                              f"属确定性错误不再重试（本次耗时 {time.time()-t_attempt:.0f}s）")
                    break
                self._log(f"[片段 {idx}/{total}] 第 {attempt} 次尝试失败"
                          f"（{last_err[:160]}，耗时 {time.time()-t_attempt:.0f}s），将重试")
            if res:
                _hw_fail_streak = 0
                panel.video_path = res
                # 对白清洗日志：让控制台看到喂给 H3 的对白文本质量
                _dialogue_texts = []
                _raw_dialogues = (panel.prompt_params or {}).get("_dialogues") or []
                for _d in _raw_dialogues:
                    if not isinstance(_d, dict):
                        continue
                    _role = str(_d.get("role", "") or "").strip()
                    _content = str(_d.get("content", "") or "").strip()
                    if re.search(r"无(明确)?对白|无台词|无对话|没有台词|没有对白"
                                 r"|（无）|\(无\)", _content):
                        continue
                    if _role in ("旁白", "画外音", "Narrator", "Voiceover", "OS"):
                        continue
                    _clean = re.sub(r'[（(【\[][^)）】\]]*[)）】\]]', '', _content).strip()
                    _clean = re.sub(r'（[^）]*[字标][幕题][：:][^）]*）', '', _clean)
                    _clean = re.sub(r'\([^()]*[字标][幕题][：:][^()]*\)', '', _clean)
                    _clean = _clean.strip()
                    if _clean:
                        _dialogue_texts.append(_clean)
                if _dialogue_texts:
                    _dlog = "。".join(_dialogue_texts)
                    if not _dlog.endswith("。"):
                        _dlog += "。"
                    self._log(f"[片段 {idx}/{total}] H3 对白（{len(_dialogue_texts)} 句，{len(_dlog)}字）："
                              f"“{_dlog[:60]}{'…' if len(_dlog) > 60 else ''}”")
                else:
                    self._log(f"[片段 {idx}/{total}] 无有效对白，H3 只生成画面与环境音")
                # 保留 H3 原生音轨（对白质量通过提示词五要素优化）
                out = composer.create_video_clip(res, None, clip_path, duration=duration,
                                                 width=clip_w, height=clip_h)
                if isinstance(out, tuple):
                    out = out[0]
                clip_done = bool(out)
            else:
                self._log(f"[片段 {idx}/{total}] {panel.panel_id} 图生视频失败（{last_err}），跳过")
                if _is_hardware_transient(last_err):
                    _hw_fail_streak += 1
                    if _hw_fail_streak >= 2:
                        # 连续多个片段在清缓存+重试后仍因系统资源耗尽失败：
                        # 主机已提交内存（RAM+页面文件）耗尽是宿主级问题，
                        # 继续跑后续片段只会同样失败并各白烧 3 次尝试
                        raise RuntimeError(
                            f"连续 {_hw_fail_streak} 个片段因系统资源耗尽"
                            f"（HostBuffer/OOM）失败，清缓存重试无效——"
                            f"主机内存/虚拟内存已耗尽。请先释放资源再续跑："
                            f"1) 增大 Windows 虚拟内存（页面文件，建议 ≥64GB）；"
                            f"2) 关闭其它占用显存/内存的程序；3) 重启 ComfyUI。"
                            f"已成功的片段会自动跳过，仅补齐缺失片段")
                else:
                    _hw_fail_streak = 0

            if not clip_done or not (os.path.isfile(clip_path) and os.path.getsize(clip_path) > 0):
                self._log(f"[片段 {idx}/{total}] {panel.panel_id} 片段生成失败，跳过")
                self._progress(ep_id, "clips", "running",
                               f"片段 {idx}/{total} 失败（已产出 {len(artifacts)}/{total}），继续下一个")
                continue
            artifacts.append(clip_path)
            self._progress(ep_id, "clips", "running",
                           f"片段 {idx}/{total} 完成（已产出 {len(artifacts)}/{total}）")
            if panel.video_path:
                panel.is_animated = True
            storyboard.save(self._storyboard_path(ep_id))

        storyboard.save(self._storyboard_path(ep_id))
        if not artifacts:
            raise RuntimeError("没有任何视频片段产出")
        missing = total - len(artifacts)
        # WB-10: 出 clip 后阶段 QA（先跑，把缺失/时长问题记入 QA 报告）
        try:
            self._run_stage_qa(ep_id, "clips", storyboard=storyboard)
        except Exception as qa_err:
            self._log(f"[QA-clips] 阶段 QA 异常（不阻断）: {qa_err}")
        if missing > 0:
            # 缺片段必须判失败：半集成片（总时长不足 ≥75s）绝不允许标成功。
            # 续跑时已成功的片段被 _clip_is_fresh 跳过，只自动补齐缺失的。
            raise RuntimeError(
                f"{missing}/{total} 个分镜片段缺失（成功 {len(artifacts)}/{total}），"
                f"片段阶段判失败；续跑将自动补齐缺失片段")
        return artifacts

    def _collect_panel_ref_images(self, panel):
        """按面板的 characters/scenes/props 从项目资源库收集参考图明细。

        返回 [{"path","kind","name","label"}]，顺序即视频工作流的参考图槽位顺序
        （角色 → 场景 → 道具）；label 用于把 <Picture i> 与具体参考图对齐，
        避免提示词里泛泛写"角色/场景参考图"导致模型不知道对应哪张图。
        """
        max_refs = 4
        try:
            vcfg = self._get_api_config("Video") or {}
            max_refs = max(1, int(vcfg.get("max_ref_images") or 4))
            include_sp = str(vcfg.get("ref_include_scene_prop", "true")).lower() not in ("false", "0", "no")
        except Exception:
            max_refs = 4
            include_sp = True
        try:
            try:
                from core.storyboard.ref_collector import collect_panel_ref_detail
            except ImportError:
                from src.core.storyboard.ref_collector import collect_panel_ref_detail
        except Exception as e:
            self._log(f"[参考图] 收集器不可用（{e}）")
            return []
        return collect_panel_ref_detail(self.project_dir, panel, max_refs=max_refs,
                                        include_scene_prop=include_sp)

    def _stage_subtitles(self, ep_id):
        """依据分镜面板生成 SRT 字幕。"""
        storyboard = self._load_storyboard(ep_id)
        panels = list(getattr(storyboard, "panels", []) or [])
        if not panels:
            raise RuntimeError(f"第 {ep_id} 集分镜为空（0 个分镜），无法生成字幕；"
                               f"请先修复剧本/分镜后重跑「分镜」阶段")
        srt_path = os.path.join(self.project_dir, "subtitles", f"episode_{int(ep_id)}.srt")
        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        gen = SubtitleGenerator()
        result = gen.generate_srt(storyboard, srt_path)
        size = os.path.getsize(srt_path) if os.path.isfile(srt_path) else 0
        if not result or size <= 0:
            # 有分镜但清洗后没有任何可用文本（对白/描述全为空）→
            # 不再让整个流水线在这里失败，按“无字幕”继续（合成阶段会跳过烧录）
            usable = 0
            for p in panels:
                dialogues = (getattr(p, "prompt_params", None) or {}).get("_dialogues") or []
                text = " ".join(d.get("content", "") for d in dialogues
                                if isinstance(d, dict)) or (getattr(p, "description", "") or "")
                if text.strip():
                    usable += 1
            if usable == 0:
                self._log(f"[SRT字幕] 第 {ep_id} 集 {len(panels)} 个分镜均无台词/描述文本，"
                          f"生成空字幕继续（不阻断成片）")
                return srt_path
            raise RuntimeError(f"SRT 字幕生成失败（{len(panels)} 个分镜中 {usable} 个有文本，"
                               f"但文件为空: {srt_path}）")
        self._log(f"第 {ep_id} 集字幕已生成: {os.path.basename(srt_path)}")
        return srt_path

    def _stage_compose(self, ep_id):
        """拼接全部片段 + 烧录字幕 -> 成片。"""
        storyboard = self._load_storyboard(ep_id)
        clips = []
        for panel in storyboard.panels:
            clip_path = os.path.join(self._ep_dir("clips", ep_id), f"panel_{panel.panel_id}.mp4")
            if os.path.isfile(clip_path) and os.path.getsize(clip_path) > 0:
                clips.append(clip_path)
        if not clips:
            raise RuntimeError("没有可合成的视频片段")

        composer = self._get_composer()
        out_dir = os.path.join(self.project_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        raw_path = os.path.join(out_dir, f"episode_{int(ep_id)}_raw.mp4")
        final_path = os.path.join(out_dir, f"episode_{int(ep_id)}_final.mp4")

        # 导出预设：非 custom 时在拼接后按预设做最终缩放/帧率重采样
        preset_key = getattr(self.params, "export_preset", "custom") or "custom"
        preset_obj = None
        if preset_key and preset_key != "custom":
            try:
                from core.synthesis.export_preset import get_preset as _get_preset
            except ImportError:
                from src.core.synthesis.export_preset import get_preset as _get_preset
            preset_obj = _get_preset(preset_key)
            self._log(f"[合成] 应用导出预设: {preset_obj.name} ({preset_obj.width}x{preset_obj.height}, {preset_obj.fps}fps)")

        self._log(f"[合成] 拼接 {len(clips)} 个片段 ...")
        # 融合偏好：把 blend_mode 映射到 concat_clips 的 transition_duration / transitions
        td = getattr(self.params, "transition_duration", 0.0) or 0.0
        blend = getattr(self.params, "blend_mode", "crossfade") or "crossfade"
        # 仅 crossfade/fade 触发 xfade；hardcut 保持 0
        if blend == "crossfade":
            td = td if td > 0 else 0.5
            transitions = [{"type": "dissolve", "duration": td} for _ in range(len(clips) - 1)]
        elif blend == "fade":
            td = td if td > 0 else 0.3
            transitions = [{"type": "fade", "duration": td} for _ in range(len(clips) - 1)]
        else:
            td = 0.0
            transitions = None
        if td > 0:
            self._log(f"[合成] 融合模式={blend}，转场={td}s（共 {len(transitions or [])} 处）")
        concat_result = composer.concat_clips(
            clips, raw_path,
            bgm_path=self.params.bgm_path,
            transition_duration=td,
            transitions=transitions,
            preset=preset_obj,
        )
        if not concat_result:
            raise RuntimeError("片段拼接失败")

        # 生成端受显存限制，片段分辨率可能低于 1080P（latent 采样放不下）。
        # 成片阶段按项目宽高比一次性 lanczos 放大到目标分辨率，
        # 保证交付物仍是 1080P，且不额外占用显存。
        if preset_obj is None:
            concat_result = self._upscale_final_to_target(
                composer, concat_result, ep_id=ep_id)

        srt_path = os.path.join(self.project_dir, "subtitles", f"episode_{int(ep_id)}.srt")
        final_for_check = concat_result
        # 空字幕文件（0 字节）视同无字幕，跳过烧录（否则 ffmpeg 无 cue 可烧还会报错）
        if os.path.isfile(srt_path) and os.path.getsize(srt_path) > 0:
            self._log("[合成] 烧录字幕 ...")
            burned = composer.burn_subtitles(concat_result, srt_path, final_path)
            if burned and os.path.isfile(burned) and os.path.getsize(burned) > 0:
                self._log(f"第 {ep_id} 集成片完成: {final_path}")
                final_for_check = final_path
            else:
                self._log("[合成] 字幕烧录失败，使用未烧字幕版本作为成片")
        else:
            # 无字幕时把 concat 结果落到 final_path（保持产物路径稳定）
            if concat_result != final_path:
                try:
                    import shutil as _sh
                    _sh.copyfile(concat_result, final_path)
                    final_for_check = final_path
                except Exception:
                    final_for_check = concat_result

        # ---- 成片自检（QA）----
        try:
            self._run_qa(final_for_check, preset_obj, srt_path, ep_id=ep_id)
        except Exception as qa_err:
            self._log(f"[QA] 自检异常（不阻断）: {qa_err}")

        return final_for_check

    def _upscale_final_to_target(self, composer, video_path, ep_id=None):
        """把成片放大到项目目标分辨率（默认 1080P 短边），已在目标分辨率则原样返回。

        生成阶段受显存限制只能出较低分辨率的片段（如 832×1472），
        这里用一次 lanczos 重采样补齐到 1080P，避免交付物分辨率不足。
        """
        try:
            from core.synthesis.export_preset import ExportPreset
        except ImportError:
            from src.core.synthesis.export_preset import ExportPreset
        try:
            target_w, target_h = self.params.aspect_wh
            target_w, target_h = int(target_w or 0), int(target_h or 0)
            if target_w <= 0 or target_h <= 0:
                return video_path
            cur_w, cur_h = composer.get_video_info(video_path)
            if not cur_w or not cur_h:
                return video_path
            if cur_w >= target_w and cur_h >= target_h:
                return video_path
            preset = ExportPreset(
                key="final_target", name="成片目标分辨率",
                width=target_w, height=target_h, fps=0, quality="high")
            out_path = os.path.splitext(video_path)[0] + f"_{target_h}p.mp4"
            self._log(f"[合成] 成片放大 {cur_w}x{cur_h} → {target_w}x{target_h}（lanczos）")
            scaled = composer.apply_preset(video_path, out_path, preset)
            if scaled and os.path.isfile(scaled) and os.path.getsize(scaled) > 0:
                return scaled
            self._log("[合成] 成片放大失败，沿用原分辨率")
            return video_path
        except Exception as e:
            self._log(f"[合成] 成片放大异常（不阻断）: {e}")
            return video_path

    def _run_qa(self, video_path, preset_obj, srt_path, ep_id=None):
        """对成片跑 QA 自检并打印结果到日志。WB-10: 结果存入 _qa_results。"""
        try:
            from core.qa.qa_checker import QAChecker
        except ImportError:
            from src.core.qa.qa_checker import QAChecker
        checker = QAChecker()
        result = checker.check(video_path, preset=preset_obj, srt_path=srt_path)
        self._log(f"[QA] {result.summary()}")
        for issue in result.issues:
            tag = issue.severity.upper()
            line = f"[QA] [{tag}] {issue.category}: {issue.message}"
            if issue.fix_suggestion:
                line += f"  → 修复建议: {issue.fix_suggestion}"
            self._log(line)
        # WB-10: 存储结果
        if ep_id is not None:
            self._qa_results[int(ep_id)] = result.to_dict()
        return result

    def _run_stage_qa(self, ep_id, stage, storyboard=None):
        """WB-10: 阶段级 QA 检查。返回 QAResult 或 None。"""
        try:
            from core.qa.qa_checker import QAChecker
        except ImportError:
            from src.core.qa.qa_checker import QAChecker
        checker = QAChecker()
        result = None
        
        if stage == "clips" and storyboard is not None:
            result = checker.check_clips(storyboard, expected_wh=self.params.aspect_wh)
        
        if result is not None:
            self._log(f"[QA-{stage}] {result.summary()}")
            for issue in result.issues:
                tag = issue.severity.upper()
                self._log(f"[QA-{stage}] [{tag}] {issue.message}")
            # 存储（按 stage 键）
            key = int(ep_id)
            if key not in self._qa_results:
                self._qa_results[key] = {"issues": []}
            self._qa_results[key]["issues"].extend(result.to_dict()["issues"])
        
        return result

    def _get_composer(self):
        if self._composer is None:
            self._composer = VideoComposer()
        return self._composer

    @staticmethod
    def _clip_is_fresh(clip_path, panel):
        """片段是否可复用：存在非空，且其源文件（图/音/图生视频）都不比片段更新。

        单纯按文件存在复用会在“软重置后全新生成”时误用上一版片段，
        故以 mtime 新鲜度保证：源在片段之后被重新生成过就必须重合成。
        """
        try:
            if not (clip_path and os.path.isfile(clip_path) and os.path.getsize(clip_path) > 0):
                return False
            clip_mtime = os.path.getmtime(clip_path)
            for src in (getattr(panel, "image_path", ""),
                        getattr(panel, "audio_path", ""),
                        getattr(panel, "video_path", "")):
                if src and os.path.isfile(src) and os.path.getmtime(src) > clip_mtime:
                    return False
            return True
        except OSError:
            return False

    # ================= 回调封装 =================
    def _progress(self, ep_id, stage, status, message=""):
        if self.on_progress:
            try:
                self.on_progress(ep_id, stage, status, message)
            except Exception:
                traceback.print_exc()

    def _log(self, message):
        print(f"[AutoRun] {message}")
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                traceback.print_exc()


def _timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")

# -*- coding: utf-8 -*-
"""
全自动流水线状态持久化：autorun_state.json 记录每集每阶段的产出物，
支持断点续跑（已完成的阶段校验产物存在且非空后跳过）。
"""
import os
import time

try:
    from core.utils.json_store import atomic_write_json, read_json_file
except ImportError:
    from src.core.utils.json_store import atomic_write_json, read_json_file

# 流水线阶段（按执行顺序）
# 分镜（storyboard）已并入 script 阶段内部完成：
# 剧本 -> 分镜都是"生成脚本/分镜"这一步的产物，UI 不再单列「分镜生成」阶段。
STAGES = ["script", "clips", "subtitles", "compose"]

STAGE_LABELS = {
    "script": "剧本+分镜",
    "clips": "视频片段",
    "subtitles": "SRT字幕",
    "compose": "合成成片",
}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _artifact_ok(path):
    """产物校验：存在且非空（项目铁律：成功判定必须校验产物）。"""
    if not path or not isinstance(path, str):
        return False
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


class PipelineState:
    """以项目目录下的 autorun_state.json 为载体，按 {集ID: {阶段: 状态}} 组织。"""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.path = os.path.join(project_dir, "autorun_state.json")
        self.data = {"version": 1, "params": {}, "episodes": {}, "final": {}, "script_queue": []}
        self.load()

    # ---------- 持久化 ----------
    def load(self):
        loaded = read_json_file(self.path, default=None)
        if isinstance(loaded, dict):
            merged = dict(self.data)
            merged.update(loaded)
            if not isinstance(merged.get("episodes"), dict):
                merged["episodes"] = {}
            if not isinstance(merged.get("script_queue"), list):
                merged["script_queue"] = []
            self.data = merged
            self._migrate_legacy_stages()

    def _migrate_legacy_stages(self):
        """兼容旧状态文件：storyboard 阶段已并入 script。

        - 旧 script 与 storyboard 都成功 → 合并产物到 script，状态视为成功；
        - 旧 storyboard 未成功 → script 标记为待重建，并置 script_ready，
          续跑时只重建分镜、不重调 LLM（省 5-10 分钟）。
        """
        for ep_key, stages in list((self.data.get("episodes") or {}).items()):
            if not isinstance(stages, dict):
                continue
            sb = stages.get("storyboard")
            if not isinstance(sb, dict):
                continue
            stages.pop("storyboard", None)
            sc = dict(stages.get("script") or {})
            sb_status = sb.get("status")
            if sc.get("status") == "success" and sb_status == "success":
                arts = list(sc.get("artifacts") or [])
                for p in (sb.get("artifacts") or []):
                    if p and p not in arts:
                        arts.append(p)
                sc["artifacts"] = arts
            else:
                extra = dict(sc.get("extra") or {})
                extra["script_ready"] = True
                sc["status"] = "failed"
                sc["message"] = "旧分镜未完成，需重建分镜"
                sc["extra"] = extra
            stages["script"] = sc

    def save(self):
        atomic_write_json(self.path, self.data, indent=2)

    def has_unfinished(self):
        """是否存在未完成的任务（供 GUI 提示"继续上次任务"）。"""
        for ep_stages in self.data["episodes"].values():
            for st in STAGES:
                info = ep_stages.get(st) or {}
                if info.get("status") != "success":
                    return True
        return False

    def reset_all(self):
        self.data["episodes"] = {}
        self.data["final"] = {}
        self.data["script_queue"] = []
        self.save()

    # ---------- 阶段状态 ----------
    def _ep_key(self, ep_id):
        return str(int(ep_id))

    def get_stage(self, ep_id, stage):
        return self.data["episodes"].get(self._ep_key(ep_id), {}).get(stage) or {}

    def mark_stage(self, ep_id, stage, status, artifacts=None, message=""):
        ep_key = self._ep_key(ep_id)
        self.data["episodes"].setdefault(ep_key, {})
        # 保留已有的 extra（如 script_ready），避免状态流转时丢失续跑线索
        prev_extra = (self.data["episodes"][ep_key].get(stage) or {}).get("extra")
        entry = {
            "status": status,
            "artifacts": artifacts or [],
            "message": message,
            "updated_at": _now(),
        }
        if prev_extra:
            entry["extra"] = prev_extra
        self.data["episodes"][ep_key][stage] = entry
        self.save()

    def mark_done(self, ep_id, stage, artifacts):
        if isinstance(artifacts, str):
            artifacts = [artifacts]
        self.mark_stage(ep_id, stage, "success", artifacts)

    def mark_running(self, ep_id, stage):
        self.mark_stage(ep_id, stage, "running")

    def mark_failed(self, ep_id, stage, message=""):
        self.mark_stage(ep_id, stage, "failed", message=message)

    def mark_pending(self, ep_id, stage):
        self.mark_stage(ep_id, stage, "pending")

    def is_done(self, ep_id, stage):
        """阶段成功且所有产物文件仍存在且非空。"""
        info = self.get_stage(ep_id, stage)
        if info.get("status") != "success":
            return False
        return all(_artifact_ok(p) for p in info.get("artifacts", []))

    def get_artifacts(self, ep_id, stage):
        return self.get_stage(ep_id, stage).get("artifacts", [])

    def set_stage_artifact_extra(self, ep_id, stage, key, value):
        """在阶段状态里附带额外数据（如脚本队列溢出的集）。"""
        ep_key = self._ep_key(ep_id)
        self.data["episodes"].setdefault(ep_key, {})
        self.data["episodes"][ep_key].setdefault(stage, {})
        self.data["episodes"][ep_key][stage].setdefault("extra", {})
        self.data["episodes"][ep_key][stage]["extra"][key] = value
        self.save()

    # ---------- 多集 LLM 一次返回的排队 ----------
    def pop_script_queue(self):
        if self.data["script_queue"]:
            return self.data["script_queue"].pop(0)
        return None

    def push_script_queue(self, items):
        self.data["script_queue"].extend(items)
        self.save()

    # ---------- 汇总 ----------
    def summary(self):
        """返回精简进度快照，供 CLI/API/GUI 展示。"""
        eps = {}
        for ep_key, stages in self.data["episodes"].items():
            eps[ep_key] = {s: (stages.get(s) or {}).get("status", "pending") for s in STAGES}
        return {"params": self.data.get("params", {}), "episodes": eps, "final": self.data.get("final", {})}

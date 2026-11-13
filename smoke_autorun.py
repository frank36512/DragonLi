# -*- coding: utf-8 -*-
"""全自动流水线冒烟测试：隔离配置（无任何 API key）-> 全 mock 链路跑通 1 集。"""
import os
import sys
import json
import time
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

from core.config.config_manager import ConfigManager
from core.autorun import AutoRunController, AutoRunParams

# 1) 隔离配置：空 api_configs -> LLM 走 mock 剧本 / Image 走占位图 / TTS 走 system / 视频不启用
tmp = tempfile.mkdtemp(prefix="autorun_smoke_cfg_")
cfg_path = os.path.join(tmp, "config.json")
with open(cfg_path, 'w', encoding='utf-8') as f:
    json.dump({"api_configs": []}, f, ensure_ascii=False)
config = ConfigManager(config_path=cfg_path)

# 2) 创建测试项目（写入临时目录，不污染用户项目）
from core.project.project_manager import ProjectManager
pm = ProjectManager(tempfile.mkdtemp(prefix="autorun_smoke_projects_"))
name = f"自动流水线冒烟_{int(time.time())}"
project_path = pm.create_project(name, {
    "theme": "一个关于时间的科幻短剧",
    "genre": "都市",
    "total_episodes": 1,
    "words_per_episode": 300,
})
print(f"[SMOKE] 项目: {project_path}")

params = AutoRunParams(
    topic="一个关于时间旅行者的科幻短剧",
    style="都市",
    episode_count=1,
    use_video_gen=False,
    checkpoints=[],  # 无检查点直通
)


def on_progress(ep, stage, status, msg):
    print(f"[进度] 第{ep}集 [{stage or '-'}] {status} {msg}")


def on_log(msg):
    print(f"[日志] {msg}")


controller = AutoRunController(project_path, config, params,
                               on_progress=on_progress, on_log=on_log)
t0 = time.time()
result = controller.run()
elapsed = time.time() - t0

print(f"[SMOKE] 耗时 {elapsed:.1f}s")
print("[SMOKE] 结果:",
      json.dumps({k: v for k, v in result.items() if k != "state"},
                 ensure_ascii=False, indent=2))

ok = result["success"] and result["final_outputs"]
for p in result.get("final_outputs", []):
    if os.path.isfile(p) and os.path.getsize(p) > 0:
        print(f"[SMOKE] 成片校验 OK: {p} ({os.path.getsize(p)} bytes)")
    else:
        print(f"[SMOKE] 成片缺失: {p}")
        ok = False

# 3) 断点续跑验证：第二次 run() 应全部 cached 跳过
t1 = time.time()
result2 = controller.run()
print(f"[SMOKE] 续跑耗时 {time.time() - t1:.1f}s, success={result2['success']}")
if not result2["success"]:
    ok = False

sys.exit(0 if ok else 1)

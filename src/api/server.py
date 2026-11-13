import os
import sys
import json
import time
import threading
from collections import deque
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.project.project_manager import ProjectManager
from core.config.config_manager import ConfigManager
from ai_engine.llm.llm_client import LLMClient
from ai_engine.video_gen.video_client import VideoGenClient
from core.synthesis.video_composer import VideoComposer

try:
    from core.autorun import AutoRunController, AutoRunParams
except ImportError:
    from src.core.autorun import AutoRunController, AutoRunParams

try:
    from core.utils.json_store import atomic_write_json
except ImportError:
    from src.core.utils.json_store import atomic_write_json

app = FastAPI(
    title="Dragonli API",
    description="狸猫短剧 (Dragonli) HTTP API",
    version="1.0.0"
)

config_manager = ConfigManager()
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
projects_root = os.path.join(base_dir, "resources", "projects")
project_manager = ProjectManager(projects_root)


def resolve_llm_config():
    """
    解析 LLM 配置：优先设置界面维护的 api_configs(type=LLM)，
    其次兼容旧顶层字段 OPENAI_API_KEY，最后回退环境变量。
    """
    api_configs = config_manager.get("api_configs") or []
    llm_cfg = next((c for c in api_configs if c.get("type") == "LLM"), None)
    if llm_cfg:
        return (
            llm_cfg.get("api_key"),
            llm_cfg.get("base_url"),
            llm_cfg.get("model") or config_manager.get("llm_model", "gpt-4o"),
        )
    return (
        config_manager.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        config_manager.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        config_manager.get("llm_model", "gpt-4o"),
    )


def strip_markdown_fence(text):
    """去除 LLM 返回内容可能包裹的 ```json ... ``` 围栏。"""
    if not text:
        return text
    s = text.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        s = s[first_newline + 1:] if first_newline != -1 else s[3:]
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


class CreateProjectRequest(BaseModel):
    name: Optional[str] = None
    theme: Optional[str] = None
    genre: Optional[str] = "都市"
    total_episodes: Optional[int] = 1
    words_per_episode: Optional[int] = 300


class GenerateScriptRequest(BaseModel):
    project_path: str
    topic: str
    style: Optional[str] = "都市"


class GenerateVideoRequest(BaseModel):
    image_path: str
    prompt: Optional[str] = "动画效果，镜头缓慢推进"
    output_path: Optional[str] = None


class ComposeVideoRequest(BaseModel):
    clips: List[str]
    output_path: Optional[str] = None
    bgm_path: Optional[str] = None


class FullPipelineRequest(BaseModel):
    topic: str
    style: Optional[str] = "都市"
    name: Optional[str] = None
    episodes: Optional[int] = 1


class AutoRunRequest(BaseModel):
    """全自动流水线请求：提供 project_path 则断点续跑，否则按 topic 新建项目。"""
    topic: Optional[str] = None
    style: Optional[str] = "都市"
    name: Optional[str] = None
    episodes: Optional[int] = 1
    use_video_gen: Optional[bool] = True
    project_path: Optional[str] = None


class AutoRunActionRequest(BaseModel):
    run_id: str
    action: str  # resume / retry / cancel / rerun


# 全自动流水线运行注册表（内存态）：run_id -> {controller, thread, finished, result, logs}
RUN_REGISTRY = {}
_RUN_LOCK = threading.Lock()
_RUN_SEQ = [0]


@app.get("/")
def root():
    return {"message": "Dragonli API 服务运行中", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/api/project/create")
def create_project(request: CreateProjectRequest):
    # 注意：这些路由使用同步 def。内部是阻塞式 SDK/ffmpeg 调用，
    # FastAPI 会自动把同步路由放到线程池执行，避免阻塞整个事件循环。
    try:
        if not request.name and request.theme:
            name = request.theme[:20].replace("/", "_").replace("\\", "_")
        elif request.name:
            name = request.name
        else:
            name = f"项目_{os.urandom(4).hex()}"

        extra_data = {
            "theme": request.theme or "",
            "genre": request.genre or "都市",
            "total_episodes": request.total_episodes or 1,
            "words_per_episode": request.words_per_episode or 300
        }

        project_path = project_manager.create_project(name, extra_data)

        return {
            "success": True,
            "project_path": project_path,
            "project_name": name,
            "theme": request.theme,
            "style": request.genre,
            "episodes": request.total_episodes
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/list")
def list_projects():
    try:
        projects = project_manager.list_projects()
        return {"success": True, "projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/script/generate")
def generate_script(request: GenerateScriptRequest):
    try:
        if not os.path.exists(request.project_path):
            raise HTTPException(status_code=400, detail=f"项目路径不存在: {request.project_path}")

        api_key, base_url, model = resolve_llm_config()

        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="未配置 LLM API Key，请在应用设置中添加类型为 LLM 的 API 配置"
            )

        llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)

        prompt = f"""请根据以下主题生成一个短剧剧本:
主题: {request.topic}
风格: {request.style}

请生成包含分镜、对话、场景描述的完整剧本，以JSON格式返回。JSON格式如下:
{{
  "title": "剧本标题",
  "scenes": [
    {{
      "scene_number": 1,
      "location": "场景地点",
      "description": "场景描述",
      "characters": ["角色1", "角色2"],
      "dialogues": [
        {{"speaker": "角色1", "line": "台词内容"}}
      ]
    }}
  ]
}}"""

        response = llm_client.generate_script(prompt)

        if response:
            response = strip_markdown_fence(response)

            try:
                script_data = json.loads(response)
            except json.JSONDecodeError:
                script_data = {"raw_content": response, "title": request.topic}

            scripts_dir = os.path.join(request.project_path, "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            script_path = os.path.join(scripts_dir, "current_script.json")

            atomic_write_json(script_path, script_data, indent=2)

            return {
                "success": True,
                "script_path": script_path,
                "title": script_data.get("title", request.topic),
                "scenes_count": len(script_data.get("scenes", []))
            }
        else:
            raise HTTPException(status_code=500, detail="LLM 生成失败，请检查 API Key 配置")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"剧本生成异常: {str(e)}")


@app.post("/api/video/generate")
def generate_video(request: GenerateVideoRequest):
    try:
        if not os.path.exists(request.image_path):
            raise HTTPException(status_code=400, detail=f"图片路径不存在: {request.image_path}")

        api_configs = config_manager.get("api_configs") or []
        video_config = next((c for c in api_configs if c.get("type") == "Video"), {})

        output_path = request.output_path
        if not output_path:
            base_name = os.path.splitext(os.path.basename(request.image_path))[0]
            output_path = f"{base_name}_video.mp4"

        video_client = VideoGenClient(
            api_key=video_config.get("api_key"),
            base_url=video_config.get("base_url"),
            model=video_config.get("model"),
            provider=video_config.get("provider", "mock"),
            api_config=video_config
        )

        video_path = video_client.generate_video(
            image_path=request.image_path,
            prompt=request.prompt or "动画效果",
            output_path=output_path
        )

        if video_path:
            return {
                "success": True,
                "video_path": video_path,
                "duration": "5s"
            }
        else:
            return {
                "success": False,
                "error": "视频生成失败"
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"视频生成异常: {str(e)}")


@app.post("/api/video/compose")
def compose_video(request: ComposeVideoRequest):
    try:
        missing_clips = [c for c in request.clips if not os.path.exists(c)]
        if missing_clips:
            raise HTTPException(status_code=400, detail=f"视频片段不存在: {missing_clips}")

        composer = VideoComposer()

        output_path = request.output_path or "final_output.mp4"

        result_path = composer.concat_clips(
            request.clips,
            output_path,
            bgm_path=request.bgm_path
        )

        if result_path:
            return {
                "success": True,
                "output_path": result_path,
                "clips_count": len(request.clips)
            }
        else:
            return {
                "success": False,
                "error": "视频合成失败"
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"视频合成异常: {str(e)}")


@app.post("/api/pipeline/full")
def full_pipeline(request: FullPipelineRequest):
    try:
        if not request.topic:
            raise HTTPException(status_code=400, detail="请提供故事主题 (topic)")

        create_result = create_project(CreateProjectRequest(
            name=request.name,
            theme=request.topic,
            genre=request.style,
            total_episodes=request.episodes or 1
        ))

        if not create_result.get("success"):
            return create_result

        project_path = create_result["project_path"]

        script_result = generate_script(GenerateScriptRequest(
            project_path=project_path,
            topic=request.topic,
            style=request.style
        ))

        if not script_result.get("success"):
            return script_result

        return {
            "success": True,
            "project_path": project_path,
            "project_name": create_result.get("project_name"),
            "script_path": script_result.get("script_path"),
            "title": script_result.get("title"),
            "scenes_count": script_result.get("scenes_count"),
            "message": "短剧制作流程完成（剧本生成阶段）"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"完整流程异常: {str(e)}")


# ================= 全自动流水线（异步任务） =================

def _start_auto_run_thread(controller, entry):
    """在线程中执行 controller.run()，结束后回写结果（run() 可重复调用以断点续跑）。"""
    def worker():
        try:
            result = controller.run()
        except Exception as e:
            result = {
                "success": False, "cancelled": False,
                "final_outputs": [], "errors": [str(e)],
            }
        entry["result"] = result
        entry["finished"] = True
        entry["finished_at"] = time.time()

    t = threading.Thread(target=worker, daemon=True, name="autorun-api")
    entry["thread"] = t
    t.start()
    return t


def _make_log_sink(entry):
    def on_log(msg):
        entry["logs"].append(f"{time.strftime('%H:%M:%S')} {msg}")

    def on_progress(ep, stage, status, msg):
        entry["logs"].append(f"{time.strftime('%H:%M:%S')} [第{ep}集][{stage or '-'}] {status} {msg}")

    return on_log, on_progress


@app.post("/api/pipeline/auto")
def start_auto_pipeline(request: AutoRunRequest):
    """启动全自动流水线（后台线程执行，返回 run_id 供轮询/控制）。"""
    try:
        if request.project_path:
            project_path = request.project_path
            if not os.path.isdir(project_path):
                raise HTTPException(status_code=400, detail=f"项目路径不存在: {project_path}")
        else:
            if not request.topic:
                raise HTTPException(status_code=400, detail="请提供故事主题 (topic) 或已有项目路径 (project_path)")
            name = request.name or request.topic[:20].replace("/", "_").replace("\\", "_")
            project_path = project_manager.create_project(name, {
                "theme": request.topic,
                "genre": request.style or "都市",
                "total_episodes": request.episodes or 1,
                "words_per_episode": 300,
            })

        params = AutoRunParams(
            topic=request.topic or "",
            style=request.style or "都市",
            episode_count=request.episodes or 1,
            use_video_gen=bool(request.use_video_gen),
            checkpoints=[],  # API 无头运行：清空检查点，全自动直通
        )
        controller = AutoRunController(project_path, config_manager, params)

        entry = {
            "controller": controller, "thread": None,
            "finished": False, "result": None,
            "logs": deque(maxlen=200), "started_at": time.time(),
        }
        on_log, on_progress = _make_log_sink(entry)
        controller.on_log = on_log
        controller.on_progress = on_progress

        with _RUN_LOCK:
            _RUN_SEQ[0] += 1
            run_id = f"run_{_RUN_SEQ[0]}_{int(time.time())}"
            RUN_REGISTRY[run_id] = entry

        _start_auto_run_thread(controller, entry)
        return {"success": True, "run_id": run_id, "project_path": project_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动全自动流水线异常: {str(e)}")


@app.get("/api/pipeline/auto/status")
def auto_pipeline_status(run_id: str):
    """查询运行状态：finished / result / 分阶段进度 / 最近日志。"""
    entry = RUN_REGISTRY.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知 run_id: {run_id}")
    controller = entry["controller"]
    return {
        "run_id": run_id,
        "finished": entry["finished"],
        "project_path": controller.project_dir,
        "params": controller.params.to_dict(),
        "state": controller.state.summary(),
        "running": entry["thread"].is_alive() if entry["thread"] is not None else False,
        "result": entry["result"],
        "logs": list(entry["logs"]),
    }


@app.post("/api/pipeline/auto/resume")
def auto_pipeline_action(request: AutoRunActionRequest):
    """控制运行中的流水线：resume 继续 / retry 重跑当前阶段 / cancel 取消 / rerun 结束后续跑。"""
    entry = RUN_REGISTRY.get(request.run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知 run_id: {request.run_id}")
    controller = entry["controller"]

    try:
        if request.action == "resume":
            if entry["finished"]:
                raise HTTPException(status_code=400, detail="运行已结束，请用 rerun 断点续跑")
            controller.resume()
        elif request.action == "retry":
            if entry["finished"]:
                raise HTTPException(status_code=400, detail="运行已结束，请用 rerun 断点续跑")
            controller.resume(retry=True)
        elif request.action == "cancel":
            controller.cancel()
        elif request.action == "rerun":
            # 结束后再次 run()：已完成阶段按产物缓存跳过，仅补齐缺口
            if entry["thread"] is not None and entry["thread"].is_alive():
                raise HTTPException(status_code=400, detail="流水线仍在运行中")
            entry["finished"] = False
            entry["result"] = None
            _start_auto_run_thread(controller, entry)
        else:
            raise HTTPException(status_code=400, detail=f"未知 action: {request.action}（可选 resume/retry/cancel/rerun）")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"控制流水线异常: {str(e)}")

    return {"success": True, "run_id": request.run_id, "action": request.action}


def run_api_server(port: int = 18790):
    import uvicorn
    print(f"启动 Dragonli API 服务，端口: {port}")
    print(f"API 文档: http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_api_server()

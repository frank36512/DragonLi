import os
import sys
import json
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.project.project_manager import ProjectManager
from core.config.config_manager import ConfigManager
from ai_engine.llm.llm_client import LLMClient
from ai_engine.video_gen.video_client import VideoGenClient
from core.synthesis.video_composer import VideoComposer

try:
    from core.utils.json_store import atomic_write_json
except ImportError:
    from src.core.utils.json_store import atomic_write_json

try:
    from core.autorun import AutoRunController, AutoRunParams
except ImportError:
    from src.core.autorun import AutoRunController, AutoRunParams


def strip_markdown_fence(text):
    """去除 LLM 返回内容可能包裹的 ```json ... ``` 围栏（兼容空白/大写/无语言标注）。"""
    if not text:
        return text
    s = text.strip()
    if s.startswith("```"):
        # 去掉首行围栏（``` / ```json / ```JSON 等）
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1:]
        else:
            s = s[3:]
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


class ExecutionStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class CLIRunner:
    def __init__(self):
        self.config_manager = ConfigManager()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.projects_root = os.path.join(base_dir, "resources", "projects")
        self.project_manager = ProjectManager(self.projects_root)
        self.execution_log = []
        
    def _resolve_llm_config(self):
        """
        解析 LLM 配置：优先设置界面维护的 api_configs(type=LLM)，
        其次兼容旧的 OPENAI_API_KEY/OPENAI_BASE_URL 顶层字段，最后回退环境变量。
        返回 (api_key, base_url, model)。
        """
        api_configs = self.config_manager.get("api_configs") or []
        llm_cfg = next((c for c in api_configs if c.get("type") == "LLM"), None)
        if llm_cfg:
            return (
                llm_cfg.get("api_key"),
                llm_cfg.get("base_url"),
                llm_cfg.get("model") or self.config_manager.get("llm_model", "gpt-4o"),
            )
        return (
            self.config_manager.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            self.config_manager.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
            self.config_manager.get("llm_model", "gpt-4o"),
        )

    def _log_step(self, step_name: str, status: str, message: str = "", data: dict = None):
        log_entry = {
            "step": step_name,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "data": data or {}
        }
        self.execution_log.append(log_entry)
        
    def _build_result(self, success: bool, message: str, data: dict = None, next_steps: list = None, recovery_hints: list = None):
        result = {
            "success": success,
            "status": ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "execution_log": self.execution_log,
            "data": data or {}
        }
        if next_steps:
            result["next_steps"] = next_steps
        if recovery_hints:
            result["recovery_hints"] = recovery_hints
        return result
        
    def execute(self, args):
        self.execution_log = []
        
        task_map = {
            "create_project": self.create_project,
            "generate_script": self.generate_script,
            "generate_video": self.generate_video,
            "compose_video": self.compose_video,
            "full_pipeline": self.full_pipeline,
            "auto_run": self.auto_run
        }

        if args.task in task_map:
            return task_map[args.task](args)
        else:
            result = self._build_result(
                False,
                f"未知任务: {args.task}",
                recovery_hints=["请使用有效的任务类型: create_project, generate_script, generate_video, compose_video, full_pipeline, auto_run"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
    
    def create_project(self, args):
        self._log_step("create_project", ExecutionStatus.RUNNING, "开始创建项目")
        
        topic = getattr(args, 'topic', None)
        style = getattr(args, 'style', '都市')
        episodes = getattr(args, 'episodes', 1)
        
        if args.project:
            project_name = args.project
        elif topic:
            project_name = topic[:20].replace('/', '_').replace('\\', '_')
        else:
            project_name = f"项目_{int(time.time())}"
        
        extra_data = {
            "theme": topic or "",
            "genre": style,
            "total_episodes": episodes,
            "words_per_episode": 300
        }
            
        try:
            project_path = self.project_manager.create_project(project_name, extra_data)
            
            self._log_step("create_project", ExecutionStatus.SUCCESS, f"项目创建成功: {project_name}")
            
            result = self._build_result(
                True,
                f"项目 '{project_name}' 创建成功",
                {
                    "project_path": project_path,
                    "project_name": project_name,
                    "theme": topic,
                    "style": style,
                    "episodes": episodes
                },
                next_steps=[
                    f"生成剧本: --task generate_script --project \"{project_path}\" --topic \"{topic}\"",
                    f"完整流程: --task full_pipeline --topic \"{topic}\" --style \"{style}\""
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        except Exception as e:
            self._log_step("create_project", ExecutionStatus.FAILED, str(e))
            result = self._build_result(
                False,
                f"项目创建失败: {str(e)}",
                recovery_hints=[
                    "检查项目名称是否包含特殊字符",
                    "确认 resources/projects 目录存在且有写入权限",
                    "尝试使用不同的项目名称"
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
    
    def generate_script(self, args):
        self._log_step("generate_script", ExecutionStatus.RUNNING, "开始生成剧本")
        
        project_path = getattr(args, 'project', None)
        topic = getattr(args, 'topic', '一个有趣的故事')
        style = getattr(args, 'style', '都市')
        
        if not project_path:
            result = self._build_result(
                False,
                "缺少项目路径",
                recovery_hints=["请使用 --project 参数指定项目路径"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
            
        if not os.path.exists(project_path):
            result = self._build_result(
                False,
                f"项目路径不存在: {project_path}",
                recovery_hints=[
                    "检查路径是否正确",
                    "先创建项目: --task create_project --topic \"主题\""
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        self._log_step("check_config", ExecutionStatus.RUNNING, "检查配置")
        
        try:
            # 优先使用设置界面配置的 LLM 服务，兼容旧顶层字段与环境变量
            api_key, base_url, model = self._resolve_llm_config()

            if not api_key:
                self._log_step("check_config", ExecutionStatus.FAILED, "API Key 未配置")
                result = self._build_result(
                    False,
                    "未配置 LLM API Key",
                    recovery_hints=[
                        "在应用【设置】中添加类型为 LLM 的 API 配置",
                        "或在 config.json 中设置 OPENAI_API_KEY",
                        "或设置环境变量 OPENAI_API_KEY"
                    ]
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            
            self._log_step("check_config", ExecutionStatus.SUCCESS, f"配置检查通过，模型: {model}")
            self._log_step("llm_generate", ExecutionStatus.RUNNING, "调用 LLM 生成剧本")
            
            llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
            
            prompt = f"""请根据以下主题生成一个短剧剧本:
主题: {topic}
风格: {style}

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
                    script_data = {"raw_content": response, "title": topic}

                scripts_dir = os.path.join(project_path, "scripts")
                os.makedirs(scripts_dir, exist_ok=True)
                script_path = os.path.join(scripts_dir, "current_script.json")

                # 原子写入，避免写一半损坏剧本文件
                atomic_write_json(script_path, script_data, indent=2)
                
                self._log_step("llm_generate", ExecutionStatus.SUCCESS, f"剧本生成完成，共 {len(script_data.get('scenes', []))} 场景")
                
                result = self._build_result(
                    True,
                    f"剧本 '{script_data.get('title', topic)}' 生成成功",
                    {
                        "script_path": script_path,
                        "title": script_data.get("title", topic),
                        "scenes_count": len(script_data.get("scenes", []))
                    },
                    next_steps=[
                        f"查看剧本: cat \"{script_path}\"",
                        f"生成视频: --task generate_video --image-path \"图片路径\""
                    ]
                )
            else:
                self._log_step("llm_generate", ExecutionStatus.FAILED, "LLM 返回为空")
                result = self._build_result(
                    False,
                    "LLM 生成失败",
                    recovery_hints=[
                        "检查 API Key 是否有效",
                        "检查网络连接",
                        "尝试使用其他模型"
                    ]
                )
            
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
            
        except Exception as e:
            self._log_step("generate_script", ExecutionStatus.FAILED, str(e))
            result = self._build_result(
                False,
                f"剧本生成异常: {str(e)}",
                recovery_hints=[
                    "检查 API Key 是否正确",
                    "检查网络连接",
                    "查看详细日志排查问题"
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
    
    def generate_video(self, args):
        self._log_step("generate_video", ExecutionStatus.RUNNING, "开始生成视频")
        
        image_path = getattr(args, 'image_path', None)
        prompt = getattr(args, 'prompt', '动画效果，镜头缓慢推进')
        output = getattr(args, 'output', None)
        
        if not image_path:
            result = self._build_result(
                False,
                "缺少图片路径",
                recovery_hints=["请使用 --image-path 参数指定图片路径"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
            
        if not os.path.exists(image_path):
            result = self._build_result(
                False,
                f"图片路径不存在: {image_path}",
                recovery_hints=["检查图片路径是否正确"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        if not output:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            output = f"{base_name}_video.mp4"
        
        try:
            api_configs = self.config_manager.get("api_configs") or []
            video_config = next((c for c in api_configs if c.get("type") == "Video"), {})
            
            self._log_step("video_generate", ExecutionStatus.RUNNING, f"调用视频生成服务: {video_config.get('provider', 'mock')}")
            
            video_client = VideoGenClient(
                api_key=video_config.get("api_key"),
                base_url=video_config.get("base_url"),
                model=video_config.get("model"),
                provider=video_config.get("provider", "mock"),
                api_config=video_config
            )
            
            video_path = video_client.generate_video(
                image_path=image_path,
                prompt=prompt,
                output_path=output
            )
            
            if video_path:
                self._log_step("video_generate", ExecutionStatus.SUCCESS, f"视频生成完成: {video_path}")
                result = self._build_result(
                    True,
                    "视频生成成功",
                    {
                        "video_path": video_path,
                        "duration": "5s"
                    },
                    next_steps=[
                        f"合成视频: --task compose_video --clips \"{video_path}\""
                    ]
                )
            else:
                self._log_step("video_generate", ExecutionStatus.FAILED, "视频生成返回为空")
                result = self._build_result(
                    False,
                    "视频生成失败",
                    recovery_hints=[
                        "检查视频生成服务配置",
                        "检查图片格式是否支持",
                        "尝试使用其他提示词"
                    ]
                )
            
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
            
        except Exception as e:
            self._log_step("generate_video", ExecutionStatus.FAILED, str(e))
            result = self._build_result(
                False,
                f"视频生成异常: {str(e)}",
                recovery_hints=[
                    "检查视频生成服务配置",
                    "检查网络连接"
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
    
    def compose_video(self, args):
        self._log_step("compose_video", ExecutionStatus.RUNNING, "开始合成视频")
        
        clips_str = getattr(args, 'clips', None)
        output = getattr(args, 'output', None)
        
        if not clips_str:
            result = self._build_result(
                False,
                "缺少视频片段",
                recovery_hints=["请使用 --clips 参数指定视频片段路径（逗号分隔）"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        clips = [c.strip() for c in clips_str.split(",") if c.strip()]
        
        if len(clips) == 0:
            result = self._build_result(
                False,
                "视频片段列表为空",
                recovery_hints=["请提供至少一个视频片段路径"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        missing_clips = [c for c in clips if not os.path.exists(c)]
        if missing_clips:
            result = self._build_result(
                False,
                f"视频片段不存在: {missing_clips}",
                recovery_hints=["检查视频片段路径是否正确"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        if not output:
            output = "final_output.mp4"
        
        try:
            self._log_step("video_compose", ExecutionStatus.RUNNING, f"合成 {len(clips)} 个视频片段")
            
            composer = VideoComposer()
            result_path = composer.concat_clips(clips, output)
            
            if result_path:
                self._log_step("video_compose", ExecutionStatus.SUCCESS, f"视频合成完成: {result_path}")
                result = self._build_result(
                    True,
                    "视频合成成功",
                    {
                        "output_path": result_path,
                        "clips_count": len(clips)
                    }
                )
            else:
                self._log_step("video_compose", ExecutionStatus.FAILED, "视频合成返回为空")
                result = self._build_result(
                    False,
                    "视频合成失败",
                    recovery_hints=[
                        "检查 FFmpeg 是否安装",
                        "检查视频片段格式是否支持"
                    ]
                )
            
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
            
        except Exception as e:
            self._log_step("compose_video", ExecutionStatus.FAILED, str(e))
            result = self._build_result(
                False,
                f"视频合成异常: {str(e)}",
                recovery_hints=[
                    "检查 FFmpeg 是否正确安装",
                    "检查视频片段格式是否一致"
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
    
    def full_pipeline(self, args):
        self._log_step("full_pipeline", ExecutionStatus.RUNNING, "开始完整短剧制作流程")
        
        topic = getattr(args, 'topic', None)
        style = getattr(args, 'style', '都市')
        episodes = getattr(args, 'episodes', 1)
        
        if not topic:
            result = self._build_result(
                False,
                "缺少故事主题",
                recovery_hints=["请使用 --topic 参数指定故事主题"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        print(f"=== 开始完整短剧制作流程 ===")
        print(f"主题: {topic}")
        print(f"风格: {style}")
        print(f"集数: {episodes}")
        print(f"================================")
        
        create_args = argparse.Namespace(
            project=getattr(args, 'project', None),
            topic=topic,
            style=style,
            episodes=episodes
        )
        create_result = self.create_project(create_args)
        
        if not create_result.get("success"):
            return create_result
        
        project_path = create_result["data"]["project_path"]
        
        script_args = argparse.Namespace(
            project=project_path,
            topic=topic,
            style=style
        )
        script_result = self.generate_script(script_args)
        
        if not script_result.get("success"):
            result = self._build_result(
                False,
                "完整流程执行失败（剧本生成阶段）",
                {
                    "project_path": project_path,
                    "failed_stage": "generate_script"
                },
                recovery_hints=[
                    f"项目已创建: {project_path}",
                    "修复剧本生成问题后，可单独执行:",
                    f"  --task generate_script --project \"{project_path}\" --topic \"{topic}\""
                ]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        
        result = self._build_result(
            True,
            "短剧制作流程完成（剧本生成阶段）",
            {
                "project_path": project_path,
                "project_name": create_result["data"].get("project_name"),
                "script_path": script_result["data"].get("script_path"),
                "title": script_result["data"].get("title"),
                "scenes_count": script_result["data"].get("scenes_count")
            },
            next_steps=[
                "生成角色图片和视频",
                "合成最终视频",
                f"查看剧本: cat \"{script_result['data'].get('script_path')}\""
            ]
        )
        
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def auto_run(self, args):
        """一键全自动流水线：创意 -> 剧本 -> 分镜 -> 图片 -> 配音 -> 片段 -> 字幕 -> 成片。

        - 指定 --project 已有项目时自动断点续跑（已完成阶段按产物缓存跳过）
        - 未指定项目时按 --topic 新建项目
        - CLI 无头运行，强制清空检查点，避免无人交互时永久阻塞
        """
        self._log_step("auto_run", ExecutionStatus.RUNNING, "开始全自动流水线")

        topic = getattr(args, 'topic', None)
        style = getattr(args, 'style', '都市')
        episodes = max(1, int(getattr(args, 'episodes', 1) or 1))
        # 分镜图片下线后视频始终由图生视频生成，该开关不再生效（保留参数以兼容旧脚本）
        use_video_gen = True
        project_arg = getattr(args, 'project', None)

        # 项目解析：已有项目 -> 断点续跑；无项目 -> 新建
        project_path = None
        if project_arg:
            candidate = project_arg if os.path.isabs(project_arg) else os.path.join(self.projects_root, project_arg)
            if not os.path.isdir(candidate):
                result = self._build_result(
                    False,
                    f"项目不存在: {candidate}",
                    recovery_hints=["检查 --project 路径是否正确", "去掉 --project 参数改为按主题新建项目"]
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            project_path = candidate
        else:
            if not topic:
                result = self._build_result(
                    False,
                    "缺少故事主题",
                    recovery_hints=["请使用 --topic 参数指定故事主题", "或使用 --project 指定已有项目断点续跑"]
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            create_args = argparse.Namespace(project=None, topic=topic, style=style, episodes=episodes)
            create_result = self.create_project(create_args)
            if not create_result.get("success"):
                print(json.dumps(create_result, ensure_ascii=False, indent=2))
                return create_result
            project_path = create_result["data"]["project_path"]

        params = AutoRunParams(
            topic=topic or "",
            style=style,
            episode_count=episodes,
            use_video_gen=use_video_gen,
            checkpoints=[],  # 无头环境清空检查点
        )

        print("=== 全自动流水线 ===")
        print(f"项目: {project_path}")
        print(f"主题: {topic or '(沿用项目/续跑)'}")
        print(f"风格: {style}")
        print(f"集数: {episodes}")
        print(f"图生视频: 开（分镜图片已下线，始终由图生视频生成）")
        print(f"==================")

        def on_progress(ep, stage, status, msg):
            print(f"[进度] 第{ep}集 [{stage or '-'}] {status} {msg}")

        def on_log(msg):
            print(f"[日志] {msg}")

        def on_error(ep, stage, msg):
            print(f"[错误] 第{ep}集 [{stage}] {msg}")

        try:
            controller = AutoRunController(
                project_path, self.config_manager, params,
                on_progress=on_progress, on_log=on_log, on_error=on_error
            )
            run_result = controller.run()
        except Exception as e:
            self._log_step("auto_run", ExecutionStatus.FAILED, str(e))
            result = self._build_result(
                False,
                f"全自动流水线异常: {str(e)}",
                {"project_path": project_path},
                recovery_hints=["检查 config.json 中 API 配置", "重新执行同一命令可断点续跑"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result

        # 产物校验铁律：成功必须以实际成片文件存在且非空为准
        outputs = [p for p in run_result.get("final_outputs", [])
                   if isinstance(p, str) and os.path.isfile(p) and os.path.getsize(p) > 0]
        success = bool(run_result.get("success")) and len(outputs) > 0 and not run_result.get("cancelled")
        if run_result.get("cancelled"):
            self._log_step("auto_run", ExecutionStatus.PARTIAL, "流水线被取消（进度已保存，可续跑）")
        elif success:
            self._log_step("auto_run", ExecutionStatus.SUCCESS, f"完成，共产出 {len(outputs)} 集成片")
        else:
            self._log_step("auto_run", ExecutionStatus.FAILED, f"失败: {run_result.get('errors')}")

        result = self._build_result(
            success,
            "全自动流水线完成" if success else "全自动流水线未完成（进度已保存，重跑同一命令可续跑）",
            {
                "project_path": project_path,
                "final_outputs": outputs,
                "cancelled": bool(run_result.get("cancelled")),
                "errors": run_result.get("errors", []),
                "summary": run_result.get("state"),
            },
            next_steps=[f"查看成片目录: {os.path.join(project_path, 'output')}"]
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dragonli CLI - 狸猫短剧命令行工具")
    parser.add_argument("--task", required=True, help="任务类型: create_project, generate_script, generate_video, compose_video, full_pipeline, auto_run")
    parser.add_argument("--project", help="项目名称或路径")
    parser.add_argument("--topic", help="故事主题")
    parser.add_argument("--style", default="都市", help="风格 (默认: 都市)")
    parser.add_argument("--episodes", type=int, default=1, help="集数 (默认: 1)")
    parser.add_argument("--image-path", help="图片路径")
    parser.add_argument("--prompt", help="视频提示词")
    parser.add_argument("--clips", help="视频片段路径(逗号分隔)")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--use-video-gen", action="store_true", help="auto_run: 已废弃（分镜图片下线后始终使用图生视频），保留以兼容旧脚本")
    
    args = parser.parse_args()

    runner = CLIRunner()
    result = runner.execute(args)
    # 用退出码反映成败，便于脚本/CI 判断（0 成功，1 失败）
    sys.exit(0 if result and result.get("success") else 1)

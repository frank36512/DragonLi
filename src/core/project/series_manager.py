import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    from core.utils.json_store import atomic_write_json, atomic_write_text, read_json_file
except ImportError:
    from src.core.utils.json_store import atomic_write_json, atomic_write_text, read_json_file

from core.rag.vector_store import SimpleVectorStore
from ai_engine.llm.llm_client import LLMClient, EmbeddingClient
from ai_engine.prompts import (
    UPDATE_CHARACTER_STATE_PROMPT,
    UPDATE_GLOBAL_SUMMARY_PROMPT,
    SUMMARIZE_EPISODE_PROMPT
)

# 摘要/角色状态/全局摘要必须是纯文本：generate_script 不传 system_prompt 时，
# 客户端会套用「JSON 结构」默认 system prompt，导致 summary 被存成 JSON 字符串
# （形如 "{\"global_summary\": ...}"），污染后续集的跨集上下文。
_SUMMARY_SYSTEM_PROMPT = (
    "You are a story-continuity assistant. Reply with PLAIN TEXT only — "
    "a concise paragraph in the same language as the script. "
    "NEVER output JSON, Markdown code fences, or any structured payload."
)


# series.json 必须存在的键及默认值，防止旧版/手改文件缺键导致 KeyError
_SERIES_DEFAULTS = {
    "title": "New Series",
    "premise": "",
    "genre": "",                # 风格类型（都市/古风/科幻…）
    "main_characters": "",       # 主要角色概述
    "total_episodes": 100,      # 计划总集数
    "words_per_episode": 300,   # 每集字数
    "global_summary": "",       # The "Story So Far"
    "character_state": "",      # Dynamic tracking of characters
    "episodes": [],             # List of {id, title, summary, script_path}
    # 长篇原作素材（改编长篇小说时由 source_chunker 写入）
    "is_long_source": False,         # 是否为长篇分块模式
    "source_total_chars": 0,         # 原文总字数
    "source_outline": "",            # 全书大纲
    "source_chunks": [],             # [{index, start, end, title, summary}]
}


def load_character_references(project_dir):
    """Load character references from the characters directory"""
    characters_dir = os.path.join(project_dir, "characters")
    if not os.path.exists(characters_dir):
        return ""

    character_refs = []
    for f in os.listdir(characters_dir):
        if f.endswith(".json"):
            try:
                with open(os.path.join(characters_dir, f), encoding='utf-8') as fp:
                    char_data = json.load(fp)
                name = char_data.get("name", "Unknown")
                gender = char_data.get("gender", "未知")
                age = char_data.get("age", "未知")
                appearance = char_data.get("appearance_features", "")
                style = char_data.get("style_description", "")
                avatar = char_data.get("avatar_path", "") or char_data.get("front_view", "")

                ref = f"【{name}】- 性别: {gender}, 年龄: {age}"
                if appearance:
                    ref += f", 外貌: {appearance}"
                if style:
                    ref += f", 风格: {style}"
                if avatar and os.path.exists(avatar):
                    ref += f", [图片参考: {os.path.basename(avatar)}]"

                character_refs.append(ref)
            except Exception as e:
                print(f"Error loading character {f}: {e}")

    return "\n".join(character_refs)

class SeriesManager:
    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.series_path = os.path.join(project_dir, "series.json")
        self.memory_path = os.path.join(project_dir, "memory.json")

        self.vector_store = SimpleVectorStore(self.memory_path)
        # self.llm_client = LLMClient() # Don't init LLMClient here without config!

        self.data = dict(_SERIES_DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self.series_path):
            loaded = read_json_file(self.series_path, default=None)
            if isinstance(loaded, dict):
                # 合并默认键，旧数据缺字段时用默认值补齐
                merged = dict(_SERIES_DEFAULTS)
                merged.update(loaded)
                if not isinstance(merged.get("episodes"), list):
                    merged["episodes"] = []
                self.data = merged

    def save(self):
        # 原子写入，避免写一半损坏整个 series.json
        atomic_write_json(self.series_path, self.data)

    def update_premise(self, premise, api_config=None):
        self.data["premise"] = premise
        self.save()
        # Embed premise as "World Context"
        # Skip embedding if no config provided, or handle it later
        if api_config:
            client = LLMClient(api_key=api_config.get("api_key"), base_url=api_config.get("base_url"), model=api_config.get("model"))
            emb = client.get_embedding(premise)
            if emb:
                self.vector_store.add_document("premise", premise, emb, {"type": "world_building"})

    def _refresh_summaries(self, api_config, script_content, summary=None,
                           summary_fallback="Summary generation failed.",
                           shared_client=None):
        """剧集保存时刷新 摘要/角色状态/全局总结，分两轮执行。

        第 1 轮：剧集摘要（全局总结的输入，必须先完成）；
        第 2 轮：角色状态 ∥ 全局总结 并行。
        此前 3 次严格串行——「保存剧本很慢」的主因就是本地推理下
        要连等 3 轮 LLM；服务端支持多请求并发（--parallel），并行后
        保存耗时从 3 轮降为 2 轮。返回 (summary, new_state, new_global)。
        """
        def _mk():
            if shared_client is not None:
                return shared_client
            return LLMClient(api_key=api_config.get("api_key"),
                             base_url=api_config.get("base_url"),
                             model=api_config.get("model"))

        def _gen(text):
            try:
                return _mk().generate_script(text,
                                             system_prompt=_SUMMARY_SYSTEM_PROMPT) or ""
            except Exception as e:
                print(f"[摘要] LLM 调用失败（该摘要跳过）: {type(e).__name__}: {e}")
                return ""

        if not summary:
            summary = _gen(SUMMARIZE_EPISODE_PROMPT.format(
                script_content=script_content)) or summary_fallback
        state_prompt = UPDATE_CHARACTER_STATE_PROMPT.format(
            current_state=self.data.get("character_state", "No character state yet."),
            script_content=script_content)
        global_prompt = UPDATE_GLOBAL_SUMMARY_PROMPT.format(
            current_summary=self.data.get("global_summary", ""),
            episode_summary=summary or "")
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_state = ex.submit(_gen, state_prompt)
            fut_global = ex.submit(_gen, global_prompt)
            new_state = fut_state.result()
            new_global = fut_global.result()
        return summary, new_state, new_global

    def add_episode(self, title, script_content, summary=None, api_config=None):
        # 用现有最大 id + 1，避免集数与文件不同步时文件名碰撞覆盖已有剧本
        episodes = self.data["episodes"]
        ep_id = (max((ep.get("id", 0) for ep in episodes), default=0) or 0) + 1
        filename = f"episode_{ep_id}.json"
        script_path = os.path.join(self.project_dir, "scripts", filename)

        os.makedirs(os.path.dirname(script_path), exist_ok=True)

        # 原子保存剧本文件
        atomic_write_text(script_path, script_content)

        # If no API config is provided, we CANNOT generate summaries or update state
        # because we don't know which LLM to use.
        # So we skip the auto-update logic if api_config is missing.
        client = None
        if api_config:
            client = LLMClient(api_key=api_config.get("api_key"), base_url=api_config.get("base_url"), model=api_config.get("model"))
            # 摘要/角色状态/全局总结：2 轮（摘要先行，角色状态 ∥ 全局总结并行）
            summary, new_state, new_global = self._refresh_summaries(
                api_config, script_content, summary=summary, shared_client=client)
            if new_state:
                self.data["character_state"] = new_state
            if new_global:
                self.data["global_summary"] = new_global
        else:
            if not summary:
                summary = "Summary not generated (No API Config)."

        episode_info = {
            "id": ep_id,
            "title": title,
            "summary": summary,
            "script_path": f"scripts/{filename}",
            "created_at": datetime.now().isoformat()
        }

        episodes.append(episode_info)
        self.save()

        # Embed summary into vector store
        if api_config and summary and client is not None:
             emb = client.get_embedding(summary)
             if emb:
                 self.vector_store.add_document(f"episode_{ep_id}", summary, emb, {"type": "episode_summary", "id": ep_id})

    def update_episode(self, ep_id, title, script_content, summary=None, api_config=None):
        # Find episode
        episode = next((e for e in self.data["episodes"] if e.get("id") == ep_id), None)
        if not episode:
            print(f"Episode {ep_id} not found.")
            return False

        # Update file
        rel_path = episode.get("script_path")
        if not rel_path:
             filename = f"episode_{ep_id}.json"
             rel_path = f"scripts/{filename}"
             episode["script_path"] = rel_path

        script_path = os.path.join(self.project_dir, rel_path)
        os.makedirs(os.path.dirname(script_path), exist_ok=True)

        atomic_write_text(script_path, script_content)

        # Update metadata
        episode["title"] = title

        # 重生成剧本时同步刷新跨集上下文（与 add_episode 同款逻辑）：
        # 不刷新会导致后续集的 global_summary/character_state/摘要仍指向旧剧情。
        client = None
        if api_config:
            client = LLMClient(api_key=api_config.get("api_key"),
                               base_url=api_config.get("base_url"),
                               model=api_config.get("model"))
            summary, new_state, new_global = self._refresh_summaries(
                api_config, script_content,
                summary_fallback=summary or "Summary generation failed.",
                shared_client=client)
            if new_state:
                self.data["character_state"] = new_state
            if new_global:
                self.data["global_summary"] = new_global

        if summary:
            episode["summary"] = summary
        episode["updated_at"] = datetime.now().isoformat()

        self.save()

        # 更新 embedding（旧摘要向量保留会污染 RAG 检索；能删则删，删不了就覆盖同 key）
        if client is not None and summary:
            try:
                emb = client.get_embedding(summary)
                if emb:
                    self.vector_store.add_document(f"episode_{ep_id}", summary, emb,
                                                   {"type": "episode_summary", "id": ep_id})
            except Exception as e:
                print(f"Warning: could not update episode embedding: {e}")
        return True

    def delete_episode(self, episode_id):
        """
        Deletes an episode by ID and re-indexes subsequent episodes.
        """
        # Find index
        idx = -1
        for i, ep in enumerate(self.data["episodes"]):
            if ep.get("id") == episode_id:
                idx = i
                break

        if idx == -1:
            return False

        # Remove file（script_path 可能缺失，做容错）
        ep_to_remove = self.data["episodes"][idx]
        rel_to_remove = ep_to_remove.get("script_path")
        if rel_to_remove:
            script_path = os.path.join(self.project_dir, rel_to_remove)
            if os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except Exception as e:
                    print(f"Error deleting file {script_path}: {e}")

        # 先在内存中完成重排，并把需要“改名”的剧本文件以复制方式写到新路径；
        # 只有 series.json 原子保存成功后才删除旧文件，避免重命名中途失败造成 id 与文件永久错位。
        self.data["episodes"].pop(idx)

        pending_cleanup = []
        for i in range(idx, len(self.data["episodes"])):
            ep = self.data["episodes"][i]
            new_id = i + 1
            new_filename = f"episode_{new_id}.json"
            new_rel_path = f"scripts/{new_filename}"
            new_path = os.path.join(self.project_dir, "scripts", new_filename)

            old_rel_path = ep.get("script_path")
            if old_rel_path and old_rel_path != new_rel_path:
                old_path = os.path.join(self.project_dir, old_rel_path)
                if os.path.exists(old_path):
                    try:
                        with open(old_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        atomic_write_text(new_path, content)
                        pending_cleanup.append(old_path)
                    except Exception as e:
                        # 复制失败则中止整个删除：不保存、不改 id，文件与元数据保持一致
                        print(f"Error re-indexing episode file {old_path} -> {new_path}: {e}")
                        return False

            ep["id"] = new_id
            ep["script_path"] = new_rel_path

        self.save()

        # 元数据已落盘，再尽力删除旧剧本文件
        for old_path in pending_cleanup:
            try:
                os.remove(old_path)
            except OSError as e:
                print(f"Warning: could not remove old episode file {old_path}: {e}")

        return True

    def get_full_context_data(self, query_idea, embedding_config=None, current_ep_id=None):
        """
        Returns a dictionary with all context elements needed for generation.

        current_ep_id: 正在（重新）生成的集号。传入时会把该集自身从
        「近 3 集摘要 / 上一集剧本摘录 / RAG 排重 / episode_number」中排除——
        否则重试第 1 集会拿到自己的旧摘要、episode_number 被算成 2，
        prompt 里出现"这是第 2 集、请承接上一集"的错乱指令。
        """
        eps = list(self.data.get("episodes") or [])
        _cur = None
        if current_ep_id is not None:
            try:
                _cur = int(current_ep_id)
                eps = [ep for ep in eps if ep.get("id") != _cur]
            except (TypeError, ValueError):
                _cur = None

        # 1. Recent Episodes Summary (Last 3, 排除本集)
        recent_summaries = []
        for ep in eps[-3:]:
            recent_summaries.append(
                f"Episode {ep.get('id', '?')} '{ep.get('title', '')}': {ep.get('summary', '')}"
            )
        recent_context = "\n".join(recent_summaries)

        # 2. Previous Script Context — 优先取最后 1-2 个分镜的结构化信息（场景/动作/台词/衔接）。
        # 旧逻辑直接读 JSON 文件尾部 800 字会带进大量语法碎片，信息质量差、占用有效上下文。
        prev_excerpt = ""
        if eps:
            last_ep = eps[-1]
            rel_path = last_ep.get("script_path")
            if rel_path:
                full_path = os.path.join(self.project_dir, rel_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        try:
                            data = json.loads(content)
                            shots = (data.get("shots") or data.get("scenes") or [])
                            parts = []
                            for sh in shots[-2:]:
                                if not isinstance(sh, dict):
                                    continue
                                loc = sh.get("scene_location", "") or ""
                                act = sh.get("action", "") or ""
                                dial = sh.get("dialogue", "") or ""
                                if isinstance(dial, list):
                                    dial = " | ".join(
                                        str(d.get("role", "")) + ": " + str(d.get("content", ""))
                                        for d in dial if isinstance(d, dict))
                                note = sh.get("continuity_note", "") or ""
                                # 角色状态（衣着/情绪/姿态变化）：跨集必须延续，
                                # 只给动作时下一集会把湿透/受伤等状态重置
                                cstate_parts = []
                                chars_detail = sh.get("characters_detail") or []
                                if isinstance(chars_detail, list):
                                    for c in chars_detail[:3]:
                                        if not isinstance(c, dict) or not c.get("name"):
                                            continue
                                        bits = []
                                        for key, label in (("clothing_note", "衣着"),
                                                           ("emotional_state", "情绪"),
                                                           ("pose", "姿态")):
                                            v = c.get(key)
                                            if v and str(v).strip():
                                                bits.append(f"{label}{str(v).strip()}")
                                        if bits:
                                            cstate_parts.append(
                                                f"{c['name']}（{'、'.join(bits)}）")
                                cstate = "；".join(cstate_parts)
                                parts.append(f"- 场景:{loc} | 动作:{act} | 台词:{dial}"
                                             f" | 状态:{cstate or '无变化'} | 衔接:{note}")
                            if parts:
                                prev_excerpt = ("上一集结尾的最后镜头（本集必须从这些动作/悬念处自然接续，"
                                                "角色衣着/情绪/状态跨集延续，禁止状态重置；"
                                                "禁止重复开场或回顾）:\n"
                                                + "\n".join(parts))
                            else:
                                prev_excerpt = content[-800:]  # 结构化提取失败时回退旧逻辑
                        except (json.JSONDecodeError, TypeError, AttributeError):
                            prev_excerpt = content[-800:]  # 非标准 JSON 时回退旧逻辑
                    except Exception as e:
                        print(f"Error reading previous script: {e}")

        # 3. RAG Retrieval
        rag_context = ""
        if query_idea:
            emb = None
            try:
                # EmbeddingClient 内部处理配置回退：显式传入 > 全局 embedding 配置 > LLM 配置
                emb = EmbeddingClient(api_config=embedding_config).get_embedding(query_idea)
            except Exception as e:
                print(f"Embedding error: {e}")

            if emb:
                results = self.vector_store.search(emb, top_k=3)
                rag_items = []
                current_ep_num = _cur if _cur is not None else len(self.data["episodes"])
                for score, item in results:
                    if item.get('metadata', {}).get('ep_id') == current_ep_num:
                        continue
                    rag_items.append(item.get('text', ''))
                rag_context = "\n---\n".join(rag_items)

        # 上下文明细日志：让用户在控制台确认跨集状态承接是否生效
        _next_ep = (_cur if _cur is not None
                    else len(self.data.get("episodes") or []) + 1)
        _prev_tag = ("含状态承接" if prev_excerpt.startswith("上一集")
                     else ("结构化（旧格式）" if prev_excerpt else "无（首集）"))
        print(f"[上下文] 生成第 {_next_ep} 集上下文：近3集摘要 {len(recent_context)} 字、"
              f"上一集摘录 {len(prev_excerpt)} 字（{_prev_tag}）、"
              f"RAG {'有' if rag_context else '无'}、"
              f"角色状态 {len(self.data.get('character_state') or '')} 字")
        if prev_excerpt and len(prev_excerpt) <= 900:
            print(f"[上下文] 上一集剧本摘录全文：\n{prev_excerpt}")

        return {
            "premise": self.data.get("premise", ""),
            "genre": self.data.get("genre", ""),
            "total_episodes": self.data.get("total_episodes", 100),
            "words_per_episode": self.data.get("words_per_episode", 300),
            "main_characters": self.data.get("main_characters", ""),
            "global_summary": self.data.get("global_summary", ""),
            "character_state": self.data.get("character_state", ""),
            "recent_episodes_summary": recent_context,
            "previous_script_excerpt": prev_excerpt,
            "rag_context": rag_context,
            "episode_number": (_cur if _cur is not None
                               else len(self.data["episodes"]) + 1)
        }

    def get_context_for_next_episode(self, query_idea):
        # Legacy method wrapper
        data = self.get_full_context_data(query_idea)
        return f"Global Summary: {data['global_summary']}\n\nRecent: {data['recent_episodes_summary']}"

    def get_episodes(self):
        return self.data["episodes"]

    # ------------------------------------------------------------------ 长篇原作素材
    def is_long_source(self):
        """当前项目是否为长篇分块改编模式。"""
        return bool(self.data.get("is_long_source")) and bool(self.data.get("source_chunks"))

    def get_source_chunks(self):
        """返回长篇原文块列表（无则空列表）。"""
        chunks = self.data.get("source_chunks") or []
        return chunks if isinstance(chunks, list) else []

    def get_episode_source_indices(self, episode_id, total_episodes):
        """按集号把原文块均分为 N 段，返回该集对应的块索引集合。

        保证相邻集按故事顺序取块，且所有块都被覆盖（最后一段兜底剩余）。
        """
        chunks = self.get_source_chunks()
        n = len(chunks)
        if n == 0:
            return []
        total = max(1, int(total_episodes or 1))
        ep = max(1, int(episode_id or 1))
        seg = max(1, (n + total - 1) // total)
        start = (ep - 1) * seg
        end = n if ep == total else min(n, start + seg)
        if start >= n:
            start = max(0, n - seg)
            end = n
        return list(range(start, end))

    def get_episode_source_chunks(self, episode_id, total_episodes):
        """返回该集对应的原文块 dict 列表。"""
        idxs = set(self.get_episode_source_indices(episode_id, total_episodes))
        return [c for c in self.get_source_chunks() if c.get("index") in idxs]

    def clear_long_source(self):
        """清除长篇素材缓存（重新改编时调用）。"""
        for key in ("is_long_source", "source_total_chars", "source_outline", "source_chunks"):
            self.data.pop(key, None)
        self.save()

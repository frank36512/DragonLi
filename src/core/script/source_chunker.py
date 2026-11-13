# -*- coding: utf-8 -*-
"""长篇原作素材处理：分块、摘要、全书大纲、向量入库、按集检索。

背景：改编短剧时若导入整本长篇小说（如 50 万字），直接内联进 prompt 会
超出模型上下文窗口。本模块把长篇原文压成「全书大纲 + 分块摘要 + 原文块
向量库」，生成时按集取相关块，从而把单次 prompt 控制在上下文窗口内。

典型用法（一键成片链路，Path B）：
    from core.script.source_chunker import prepare_long_source
    prepare_long_source(text, series, llm_config, embedding_config, on_progress=cb)

生成时按集取上下文：
    from core.script.source_chunker import build_episode_source_context
    ctx = build_episode_source_context(series, ep_id, total_eps, embedding_config)
"""
import os
import re

try:
    from core.rag.vector_store import SimpleVectorStore
    from ai_engine.llm.llm_client import LLMClient, EmbeddingClient
except ImportError:
    from src.core.rag.vector_store import SimpleVectorStore
    from src.ai_engine.llm.llm_client import LLMClient, EmbeddingClient

try:
    from ai_engine.utils.cancel import cancelled as _cancel_requested
except ImportError:
    try:
        from src.ai_engine.utils.cancel import cancelled as _cancel_requested
    except ImportError:
        def _cancel_requested():
            return False


class LongSourceCancelled(Exception):
    """用户在长篇预处理（分块/摘要/大纲/向量化）过程中点了终止。"""


def _ensure_not_cancelled():
    if _cancel_requested():
        raise LongSourceCancelled("长篇素材处理已终止")


# 超过该字数视为长篇，进入分块模式
LONG_SOURCE_THRESHOLD = 20000
# 目标分块字数（中文约 1.5 token/字，4000 字约 6000 token，留足输出空间）
DEFAULT_CHUNK_CHARS = 4000
# 单集 prompt 中原文块总字数上限
MAX_SOURCE_CHARS_PER_EPISODE = 12000
# 每块检索返回的原文块数
RETRIEVE_TOP_K = 6

# 章节标题：第X章/回/节/集、Chapter N、序章/后记等
_CHAPTER_RE = re.compile(
    r'(?m)^\s*(?:'
    r'第\s*[0-9零一二三四五六七八九十百千]+\s*[章回节卷集话篇]'
    r'|chapter\s+[0-9ivxlcdm]+'
    r'|\b(?:prologue|epilogue|序章|楔子|尾声|后记|番外)\b'
    r')\s*[:：]?\s*(.*)$',
    re.IGNORECASE,
)


def is_long_source(text):
    """判断是否属于需要分块处理的长篇原文。"""
    return bool(text) and len(text) >= LONG_SOURCE_THRESHOLD


def chunk_source(text, target_chars=DEFAULT_CHUNK_CHARS):
    """把长篇原文切成带索引的块。

    策略优先级：
    1. 按章节标题切分（若章节数合理）
    2. 按段落（空行）切分
    3. 合并小段落到目标字数；超大段落按固定长度硬切

    Returns:
        list[dict]: [{"index", "start", "end", "title", "text"}]
    """
    text = (text or "").strip()
    if not text:
        return []

    # 1) 尝试按章节切分
    chapters = _split_by_chapter(text)
    if len(chapters) >= 3:
        return _normalize_chunks(chapters, target_chars)

    # 2) 按段落切分
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks = []
    buf = ""
    for para in paragraphs:
        # 单段超长：先冲刷缓冲，再硬切
        if len(para) > target_chars * 1.5:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), target_chars):
                piece = para[i:i + target_chars]
                if piece.strip():
                    chunks.append(piece.strip())
            continue
        if len(buf) + len(para) + 1 > target_chars and buf:
            chunks.append(buf)
            buf = para
        else:
            buf = (buf + "\n\n" + para) if buf else para
    if buf:
        chunks.append(buf)

    return _normalize_chunks(chunks, target_chars)


def _split_by_chapter(text):
    """按章节标题切分，返回 [(title, body), ...]。

    第一个章节标题之前的内容（书名/前言/楔子）也会单独成块，避免丢失开头信息。
    """
    matches = list(_CHAPTER_RE.finditer(text))
    if len(matches) < 3:
        return []
    parts = []
    preamble = text[:matches[0].start()].strip()
    if preamble:
        parts.append(("", preamble))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            parts.append((_clean_chapter_title(m.group(0)), body))
    return parts


def _clean_chapter_title(raw):
    line = (raw or "").strip().splitlines()[0] if raw else ""
    return re.sub(r'\s+', ' ', line).strip(" :：#-")[:40]


def _normalize_chunks(raw_chunks, target_chars):
    """把 (title, body) 或纯文本统一成带索引的 dict 列表。"""
    result = []
    cursor = 0
    for item in raw_chunks:
        if isinstance(item, tuple):
            title, body = item[0], item[1]
        else:
            title, body = "", item
        body = body.strip()
        if not body:
            continue
        # 超大块再硬切
        if len(body) > target_chars * 2:
            sub = [body[i:i + target_chars] for i in range(0, len(body), target_chars)]
        else:
            sub = [body]
        for piece in sub:
            piece = piece.strip()
            if not piece:
                continue
            start = cursor
            end = cursor + len(piece)
            cursor = end
            result.append({
                "index": len(result),
                "start": start,
                "end": end,
                "title": title or "",
                "text": piece,
            })
    return result


def summarize_chunks(chunks, llm_config, on_progress=None):
    """逐块生成摘要，写入 chunk["summary"]。失败时回退原文前 500 字。"""
    if not chunks:
        return chunks
    try:
        client = LLMClient(
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("base_url"),
            model=llm_config.get("model"),
        )
    except Exception:
        client = None

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        _ensure_not_cancelled()          # 172 块逐块跑数小时，终止要能在这里停下来
        if on_progress:
            on_progress(i + 1, total, chunk.get("title", ""))
        text = chunk.get("text", "")
        summary = ""
        if client is not None:
            prompt = (
                "请用 200-300 字概括下面这段小说内容，保留关键人物、事件、转折和结局，"
                "不要评论、不要分点，直接输出概括正文：\n\n" + text[:6000]
            )
            try:
                summary = client.generate_script(prompt) or ""
                summary = summary.strip()
            except Exception:
                summary = ""
            _ensure_not_cancelled()      # 流被中断返回空 → 不再回退写盘，直接停
        if not summary:
            summary = text[:500]
        chunk["summary"] = summary
    return chunks


def build_outline(chunks, llm_config):
    """汇总所有块摘要，生成全书大纲。失败时回退拼接摘要。"""
    if not chunks:
        return ""
    _ensure_not_cancelled()
    joined = "\n".join(
        f"[块{c.get('index', i)}]{c.get('title', '')}\n{c.get('summary', '')}"
        for i, c in enumerate(chunks)
    )
    # 控制输入长度，避免大纲生成阶段再次爆上下文
    joined = joined[:40000]
    try:
        client = LLMClient(
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("base_url"),
            model=llm_config.get("model"),
        )
        prompt = (
            "下面是一部长篇小说的分块摘要。请整理成一份结构化的全书大纲，"
            "按故事发展顺序分幕/分章，标明主要人物、核心冲突、关键转折和结局。"
            "用简洁的中文条目输出，不要逐块复述：\n\n" + joined
        )
        outline = client.generate_script(prompt) or ""
        outline = outline.strip()
        if outline:
            return outline
    except LongSourceCancelled:
        raise
    except Exception:
        pass
    _ensure_not_cancelled()
    # 回退：直接拼接摘要
    return "\n".join(c.get("summary", "") for c in chunks)


def embed_and_store(chunks, embedding_config, vector_store):
    """把块摘要与原文块做 embedding 后入库。失败静默降级（调用方可退回顺序取块）。"""
    if not chunks or vector_store is None:
        return False
    try:
        client = EmbeddingClient(api_config=embedding_config)
    except Exception:
        return False
    if client.client is None:
        return False

    ok = False
    for chunk in chunks:
        _ensure_not_cancelled()          # 172×2 次向量化，终止要能在这里停下来
        idx = chunk.get("index", 0)
        # 摘要向量
        summary = chunk.get("summary", "")
        if summary:
            emb = client.get_embedding(summary)
            if emb:
                vector_store.add_document(
                    f"chunk_{idx}", summary, emb,
                    {"type": "source_chunk", "index": idx, "kind": "summary"},
                )
                ok = True
        # 原文向量（截断到 6000 字，避免 embedding 输入超限）
        body = chunk.get("text", "")[:6000]
        if body:
            emb = client.get_embedding(body)
            if emb:
                vector_store.add_document(
                    f"chunk_{idx}_raw", body, emb,
                    {"type": "source_chunk", "index": idx, "kind": "raw"},
                )
                ok = True
    if ok:
        vector_store.save()
    return ok


def prepare_long_source(text, series, llm_config, embedding_config=None, on_progress=None):
    """编排长篇预处理：分块 → 逐块摘要 → 全书大纲 → 向量入库 → 写 series.json。

    Args:
        text: 原始长篇文本
        series: SeriesManager 实例
        llm_config: LLM 配置（用于摘要/大纲生成）
        embedding_config: embedding 独立配置（用于向量化，可为空则读全局配置）
        on_progress: 可选回调 (step, message)

    Returns:
        dict: {"chunks": [...], "outline": "...", "stored": bool}
    """
    def _prog(step, msg):
        if on_progress:
            on_progress(step, msg)

    _prog("chunk", "正在分块...")
    chunks = chunk_source(text)
    if not chunks:
        return {"chunks": [], "outline": "", "stored": False}
    _ensure_not_cancelled()

    _prog("summary", f"正在生成摘要（共 {len(chunks)} 块）...")
    summarize_chunks(chunks, llm_config,
                     on_progress=lambda i, t, title: _prog(
                         "summary", f"正在生成摘要 {i}/{t} {title}"))

    _prog("outline", "正在汇总全书大纲...")
    outline = build_outline(chunks, llm_config)

    _prog("embed", "正在建立向量索引...")
    stored = False
    try:
        stored = embed_and_store(chunks, embedding_config, series.vector_store)
    except LongSourceCancelled:
        raise                      # 用户终止：不要降级、不要落盘半成品
    except Exception:
        stored = False

    # 落盘到 series.json（不写 project.json 的 theme）
    try:
        series.data["is_long_source"] = True
        series.data["source_total_chars"] = len(text)
        series.data["source_outline"] = outline
        series.data["source_chunks"] = [
            {
                "index": c.get("index"),
                "start": c.get("start"),
                "end": c.get("end"),
                "title": c.get("title", ""),
                "summary": c.get("summary", ""),
            }
            for c in chunks
        ]
        series.save()
    except Exception:
        pass

    _prog("done", "长篇预处理完成")
    return {"chunks": chunks, "outline": outline, "stored": stored}


def build_episode_source_context(series, episode_id, total_episodes, embedding_config=None,
                                 max_chars=MAX_SOURCE_CHARS_PER_EPISODE):
    """为某一集构造原文上下文：全书大纲 + 该集对应块摘要 + RAG 检索的原文片段。

    若项目未开启长文本模式，返回空串，调用方沿用原有全文逻辑。
    输出总长度始终受 max_chars 约束，避免超出模型上下文窗口。

    Args:
        embedding_config: embedding 独立配置（为空则读全局配置；不可用则跳过 RAG）

    Returns:
        str: 可直接拼入 prompt 的上下文文本
    """
    data = getattr(series, "data", {}) or {}
    if not data.get("is_long_source"):
        return ""
    chunks = data.get("source_chunks") or []
    if not chunks:
        return ""
    outline = data.get("source_outline", "") or ""

    total = max(1, int(total_episodes or 1))
    ep = max(1, int(episode_id or 1))
    n = len(chunks)
    seg_size = max(1, (n + total - 1) // total)
    start_idx = (ep - 1) * seg_size
    end_idx = min(n, start_idx + seg_size)
    assigned = [c for c in chunks if start_idx <= int(c.get("index", 0)) < end_idx]
    if not assigned:
        assigned = chunks[start_idx:end_idx] if start_idx < n else chunks[-1:]

    parts = []
    budget = max_chars

    # 1) 全书大纲（截断到 2000 字）
    if outline:
        o = outline[:2000]
        parts.append(f"【全书大纲】\n{o}")
        budget -= len(o) + 8

    # 2) 本集对应块摘要（按预算截断）
    header = f"【本集对应原文摘要（第 {start_idx + 1}-{start_idx + len(assigned)} 块 / 共 {n} 块）】"
    parts.append(header)
    budget -= len(header) + 4
    for c in assigned:
        if budget <= 0:
            break
        label = f"块{c.get('index', 0)} {c.get('title', '')}".strip()
        line = f"- {label}: {c.get('summary', '')}"
        if len(line) > budget:
            line = line[:budget]
        parts.append(line)
        budget -= len(line) + 1

    # 3) 预算有余量时，用 RAG 补充最相关的原文片段
    if budget > 800 and embedding_config is not None:
        try:
            retrieved = _retrieve_chunks(
                series, outline or header, embedding_config,
                exclude_indices={int(c.get("index", 0)) for c in assigned},
                top_k=RETRIEVE_TOP_K)
            if retrieved:
                parts.append("【本集相关原文片段（检索）】")
                budget -= 20
                for text in retrieved:
                    if budget <= 0:
                        break
                    piece = text[:budget]
                    parts.append(piece)
                    budget -= len(piece) + 1
        except Exception:
            pass

    result = "\n\n".join(parts)
    # 最终硬截断，严格保证不超预算（拼接分隔符未计入预算）
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


def _retrieve_chunks(series, query_text, embedding_config, exclude_indices=None, top_k=RETRIEVE_TOP_K):
    """从向量库检索原文块文本。embedding 不可用时返回空列表。"""
    exclude_indices = exclude_indices or set()
    try:
        client = EmbeddingClient(api_config=embedding_config)
        emb = client.get_embedding(query_text[:4000])
    except Exception:
        return []
    if not emb:
        return []
    try:
        results = series.vector_store.search(emb, top_k=top_k * 2)
    except Exception:
        return []

    seen = set()
    texts = []
    for _score, item in results:
        meta = item.get("metadata", {}) or {}
        if meta.get("kind") != "raw":
            continue
        idx = meta.get("index")
        if idx in exclude_indices or idx in seen:
            continue
        seen.add(idx)
        texts.append(item.get("text", ""))
        if len(texts) >= top_k:
            break
    return texts


def clear_long_source(series):
    """清除项目的长篇素材缓存（重新改编时调用）。"""
    try:
        data = series.data
        data.pop("is_long_source", None)
        data.pop("source_total_chars", None)
        data.pop("source_outline", None)
        data.pop("source_chunks", None)
        series.save()
    except Exception:
        pass


def ensure_source_chunks_clean(vector_store):
    """删除向量库中所有 source_chunk 记录（重新预处理前调用）。"""
    try:
        vector_store.data = [
            item for item in (vector_store.data or [])
            if (item.get("metadata", {}) or {}).get("type") != "source_chunk"
        ]
        vector_store.save()
    except Exception:
        pass

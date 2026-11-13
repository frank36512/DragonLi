import json
import os
import threading

try:
    from paths import get_config_path
except ImportError:
    try:
        from src.paths import get_config_path
    except ImportError:
        def get_config_path():
             base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
             return os.path.join(base_dir, "resources", "config", "config.json")

try:
    from core.utils.json_store import atomic_write_json, read_json_file
except ImportError:
    try:
        from src.core.utils.json_store import atomic_write_json, read_json_file
    except ImportError:
        # 兜底：极端导入路径下退化为普通读写
        def atomic_write_json(path, data, *, indent=4, ensure_ascii=False):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)

        def read_json_file(path, default=None, *, quarantine_on_error=True):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {} if default is None else default


class ConfigManager:
    """
    线程安全的单例配置管理器。

    - 全进程共享同一份内存配置，避免每次构造都重读磁盘 + 重解析 JSON
    - get() 自动感知文件 mtime 变化（设置页保存/外部编辑后无需手动 reload）
    - set_many() 批量更新后只做一次原子写盘（原先 settings 保存一次要 fsync 6 次）
    """

    _instances = {}
    _instances_lock = threading.Lock()

    def __new__(cls, config_path=None):
        path = os.path.abspath(config_path) if config_path else os.path.abspath(get_config_path())
        with cls._instances_lock:
            inst = cls._instances.get(path)
            if inst is None:
                inst = super().__new__(cls)
                inst._init_state(path)
                cls._instances[path] = inst
            return inst

    def _init_state(self, path):
        self.config_path = path
        self._lock = threading.RLock()
        self._mtime = None
        self.config = self._load_initial()

    def _load_initial(self):
        config = self.load_config()
        self._mtime = self._file_mtime()
        return config

    def _file_mtime(self):
        try:
            return os.path.getmtime(self.config_path)
        except OSError:
            return None

    def load_config(self):
        # If config.json doesn't exist, create an empty one (don't copy example to avoid bundling sensitive data)
        if not os.path.exists(self.config_path):
            empty_config = {
                "OPENAI_API_KEY": "",
                "ELEVENLABS_API_KEY": "",
                "api_configs": [],
                "default_image_workflow": "",
                "skip_image_gen": True
            }
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                atomic_write_json(self.config_path, empty_config)
                print(f"Created empty config at {self.config_path}")
                return empty_config
            except Exception as e:
                print(f"Failed to create empty config: {e}")
                return {}

        # 损坏的 config 会被隔离为 .corrupt-<时间戳>，而不是静默返回空配置后被下一次保存覆盖
        config = read_json_file(self.config_path, default={})
        if not isinstance(config, dict):
            print(f"[config] 配置文件内容不是 JSON 对象，已忽略: {self.config_path}")
            return {}
        # 分镜图片功能已下线：参考图/纯提示词成为唯一路径，
        # skip_image_gen 恒为 True —— 旧配置缺失该键或残留 false 都统一纠正，
        # 否则 prompt_factory / video_gen_window 会退回已失效的分镜图片分支。
        if config.get("skip_image_gen") is not True:
            config["skip_image_gen"] = True
        return config

    def _refresh_if_changed(self):
        """若磁盘文件 mtime 变化（例如设置页/外部编辑器写入），则重新加载。"""
        mtime = self._file_mtime()
        if mtime != self._mtime:
            self.config = self.load_config()
            self._mtime = self._file_mtime()

    def save_config(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            # 原子写入，避免写一半导致 API Key 等配置全部丢失
            atomic_write_json(self.config_path, self.config)
            self._mtime = self._file_mtime()

    def get(self, key, default=None):
        with self._lock:
            self._refresh_if_changed()
            return self.config.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._refresh_if_changed()
            self.config[key] = value
            self.save_config()

    def set_many(self, mapping):
        """批量更新多个配置项，只写盘一次（减少 fsync 次数）。"""
        if not mapping:
            return
        with self._lock:
            self._refresh_if_changed()
            self.config.update(mapping)
            self.save_config()

    def reload(self):
        """从磁盘重新加载配置（设置页保存后其他模块可调用以获取最新配置）。"""
        with self._lock:
            self.config = self.load_config()
            self._mtime = self._file_mtime()
            return self.config

    def get_embedding_config(self):
        """返回 embedding 独立配置 {api_key, base_url, model}。

        取值优先级：
        1. 「API 配置」里 type=Embedding 的条目（优先 is_default 那条，其次第一条）。
           长篇 RAG 向量化、按集检索都用这份配置。
        2. 设置页 embedding_* 字段：只有填了 API Key 或 Base URL（即启用独立配置）
           时整套覆盖第 1 项；否则不参与——避免字段里的默认
           embedding_model 覆盖掉 API 配置条目里正确的模型名。
        3. 都没有 → 返回空 key/base，由 EmbeddingClient 回退到 LLM 配置。
        """
        with self._lock:
            self._refresh_if_changed()
            emb_cfgs = [c for c in (self.config.get("api_configs") or [])
                        if c.get("type") == "Embedding"]
            emb = (next((c for c in emb_cfgs if c.get("is_default")), None)
                   or (emb_cfgs[0] if emb_cfgs else {}))

            g_key = (self.config.get("embedding_api_key") or "").strip()
            g_base = (self.config.get("embedding_base_url") or "").strip()
            g_model = (self.config.get("embedding_model") or "").strip()

            if g_key or g_base:
                return {"api_key": g_key, "base_url": g_base,
                        "model": g_model or emb.get("model") or "text-embedding-3-small"}
            if emb:
                return {"api_key": emb.get("api_key", ""),
                        "base_url": emb.get("base_url", ""),
                        "model": emb.get("model") or "text-embedding-3-small"}
            return {"api_key": "", "base_url": "",
                    "model": g_model or "text-embedding-3-small"}

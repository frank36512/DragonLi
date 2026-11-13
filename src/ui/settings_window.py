from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QGroupBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QAbstractItemView, QTabWidget,
                             QFormLayout, QLineEdit, QCheckBox, QFileDialog,
                             QSpinBox, QDoubleSpinBox, QComboBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from core.config.config_manager import ConfigManager
from ui.api_config_dialog import ApiConfigDialog
import os
import uuid
from ui import theme as _theme

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.api_configs = self.config_manager.get("api_configs") or []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid """ + _theme.color("panel2") + """; background: """ + _theme.color("panel") + """; }
            QTabBar::tab { background: """ + _theme.color("panel2") + """; color: """ + _theme.color("text_sub") + """; padding: 10px 20px; }
            QTabBar::tab:selected { background: """ + _theme.color("panel") + """; color: """ + _theme.color("warning") + """; border-bottom: 2px solid """ + _theme.color("warning") + """; }
        """)
        layout.addWidget(self.tabs)
        
        # Tab 1: API Settings
        self.api_tab = QWidget()
        self.init_api_tab()
        self.tabs.addTab(self.api_tab, "API 服务配置")
        
        # Tab 2: General Settings
        self.general_tab = QWidget()
        self.init_general_tab()
        self.tabs.addTab(self.general_tab, "通用设置")

        # Tab 3: Path Settings
        self.path_tab = QWidget()
        self.init_path_tab()
        self.tabs.addTab(self.path_tab, "路径设置")

    def init_api_tab(self):
        layout = QVBoxLayout(self.api_tab)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Table
        self.api_table = QTableWidget()
        self.api_table.setColumnCount(5)
        self.api_table.setHorizontalHeaderLabels(["名称", "类型", "提供商", "模型", "ID"])
        
        # Evenly distribute columns
        header = self.api_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        self.api_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.api_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 隐藏内部 ID 列（第 5 列，索引 4）
        self.api_table.hideColumn(4)
        self.api_table.setStyleSheet("background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; gridline-color: " + _theme.color("border_strong") + ";")
        self.api_table.verticalHeader().setVisible(False)
        
        self.refresh_table()
        
        layout.addWidget(self.api_table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ 添加配置")
        add_btn.setStyleSheet("background-color: " + _theme.color("success") + "; color: " + _theme.color("text") + "; padding: 10px 20px; font-size: 14px; font-weight: bold; border-radius: 5px;")
        add_btn.clicked.connect(self.add_config)
        
        edit_btn = QPushButton("✏️ 编辑配置")
        edit_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; padding: 10px 20px; font-size: 14px; font-weight: bold; border-radius: 5px;")
        edit_btn.clicked.connect(self.edit_config)
        
        del_btn = QPushButton("🗑️ 删除配置")
        del_btn.setStyleSheet("background-color: " + _theme.color("danger") + "; color: " + _theme.color("text") + "; padding: 10px 20px; font-size: 14px; font-weight: bold; border-radius: 5px;")
        del_btn.clicked.connect(self.delete_config)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        layout.addLayout(btn_layout)

    def init_general_tab(self):
        self.general_tab.setObjectName("PanelBG")# + "; color: " + _theme.color("text") + ";")
        layout = QFormLayout(self.general_tab)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        lang_lbl = QLabel("简体中文")
        lang_lbl.setStyleSheet("color: " + _theme.color("text") + ";")
        layout.addRow(self.create_label("界面语言:"), lang_lbl)
        
        # ---- Embedding 独立配置（可与 LLM 不同，用于「本地 LLM + 云端 embedding」）----
        _input_style = ("padding: 5px; color: " + _theme.color("text")
                        + "; background-color: " + _theme.color("panel")
                        + "; border: 1px solid " + _theme.color("panel2") + ";")

        self.embed_api_key_edit = QLineEdit()
        self.embed_api_key_edit.setText(self.config_manager.get("embedding_api_key", ""))
        self.embed_api_key_edit.setPlaceholderText("留空则以「API 配置」的 Embedding 条目为准")
        self.embed_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.embed_api_key_edit.setStyleSheet(_input_style)
        self.embed_api_key_edit.setToolTip(
            "填了 API Key 或 Base URL 即启用本页独立配置（覆盖「API 配置」里的 Embedding 条目）；\n"
            "两者都留空则使用「API 配置」中 type=Embedding 的条目。")
        self.embed_api_key_edit.editingFinished.connect(self.save_general_settings)
        layout.addRow(self.create_label("Embedding API Key:"), self.embed_api_key_edit)

        self.embed_base_url_edit = QLineEdit()
        self.embed_base_url_edit.setText(self.config_manager.get("embedding_base_url", ""))
        self.embed_base_url_edit.setPlaceholderText("留空则以「API 配置」的 Embedding 条目为准")
        self.embed_base_url_edit.setStyleSheet(_input_style)
        self.embed_base_url_edit.setToolTip(
            "OpenAI 兼容地址，本地服务可只填到端口（如 http://192.168.2.2:1234），\n"
            "会自动补 /v1；与上面的 Key 同时留空则用「API 配置」的 Embedding 条目。")
        self.embed_base_url_edit.editingFinished.connect(self.save_general_settings)
        layout.addRow(self.create_label("Embedding Base URL:"), self.embed_base_url_edit)

        # Embedding Model Setting
        self.embed_model_edit = QLineEdit()
        self.embed_model_edit.setText(self.config_manager.get("embedding_model", "text-embedding-3-small"))
        self.embed_model_edit.setPlaceholderText("默认: text-embedding-3-small")
        self.embed_model_edit.setStyleSheet(_input_style)
        self.embed_model_edit.setToolTip(
            "仅在启用本页独立配置（填了上面的 Key/地址），\n"
            "或「API 配置」里没有 Embedding 条目时生效。")
        self.embed_model_edit.editingFinished.connect(self.save_general_settings)
        layout.addRow(self.create_label("Embedding 模型:"), self.embed_model_edit)

        embed_test_btn = QPushButton("测试 Embedding 连接")
        embed_test_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; padding: 6px 14px; border-radius: 4px;")
        embed_test_btn.setToolTip("测试流水线实际会使用的 embedding 配置（含「API 配置」里的 Embedding 条目）")
        embed_test_btn.clicked.connect(self.test_embedding_connection)
        layout.addRow("", embed_test_btn)
        
        auto_save = QCheckBox("开启")
        auto_save.setChecked(True)
        auto_save.setStyleSheet("color: " + _theme.color("text") + ";")
        layout.addRow(self.create_label("自动保存:"), auto_save)
        
        theme_lbl = QLabel("深色模式")
        theme_lbl.setStyleSheet("color: " + _theme.color("text") + ";")
        layout.addRow(self.create_label("主题颜色:"), theme_lbl)

        # ---- 扩充偏好项 ----

        # 默认时长
        self.default_duration_spin = QDoubleSpinBox()
        self.default_duration_spin.setRange(8.0, 10.0)
        self.default_duration_spin.setSingleStep(0.5)
        self.default_duration_spin.setSuffix(" 秒")
        self.default_duration_spin.setValue(float(self.config_manager.get("default_duration") or 8.0))
        self.default_duration_spin.setStyleSheet("padding: 5px; color: " + _theme.color("text") + "; background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + ";")
        self.default_duration_spin.editingFinished.connect(self.save_general_settings)
        layout.addRow(self.create_label("默认分镜时长:"), self.default_duration_spin)

        # 默认风格
        self.default_style_combo = QComboBox()
        self.default_style_combo.addItems(["无", "都市", "古风", "科幻", "动漫", "写实", "赛博朋克", "水彩", "油画"])
        cur_style = self.config_manager.get("default_style") or "都市"
        idx = self.default_style_combo.findText(cur_style)
        if idx >= 0:
            self.default_style_combo.setCurrentIndex(idx)
        self.default_style_combo.setStyleSheet("padding: 5px; color: " + _theme.color("text") + "; background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + ";")
        self.default_style_combo.currentIndexChanged.connect(self.save_general_settings)
        layout.addRow(self.create_label("默认画风:"), self.default_style_combo)

        # 自动检查点开关
        self.auto_checkpoint_cb = QCheckBox("开启（每阶段完成后暂停等待确认）")
        self.auto_checkpoint_cb.setChecked(bool(self.config_manager.get("auto_checkpoint", True)))
        self.auto_checkpoint_cb.setStyleSheet("color: " + _theme.color("text") + ";")
        self.auto_checkpoint_cb.stateChanged.connect(self.save_general_settings)
        layout.addRow(self.create_label("自动检查点:"), self.auto_checkpoint_cb)

        # 重试次数
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 5)
        self.retry_count_spin.setValue(int(self.config_manager.get("retry_count", 1)))
        self.retry_count_spin.setStyleSheet("padding: 5px; color: " + _theme.color("text") + "; background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + ";")
        self.retry_count_spin.editingFinished.connect(self.save_general_settings)
        layout.addRow(self.create_label("阶段失败重试次数:"), self.retry_count_spin)

        # 全局图片工作流
        wf_container = QWidget()
        wf_layout = QHBoxLayout(wf_container)
        wf_layout.setContentsMargins(0, 0, 0, 0)
        self.default_wf_edit = QLineEdit()
        self.default_wf_edit.setText(self.config_manager.get("default_image_workflow", ""))
        self.default_wf_edit.setPlaceholderText("resources/workflows/ 下的图片工作流文件名（留空则用 API 配置里选的工作流）")
        self.default_wf_edit.setStyleSheet("padding: 5px; color: " + _theme.color("text") + "; background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + ";")
        self.default_wf_edit.editingFinished.connect(self.save_general_settings)
        wf_layout.addWidget(self.default_wf_edit)
        wf_btn = QPushButton("浏览...")
        wf_btn.setFixedSize(60, 30)
        wf_btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; border-radius: 4px;")
        wf_btn.clicked.connect(self.browse_workflow)
        wf_layout.addWidget(wf_btn)
        layout.addRow(self.create_label("全局图片工作流:"), wf_container)

    def init_path_tab(self):
        self.path_tab.setObjectName("PanelBG")# + "; color: " + _theme.color("text") + ";")
        layout = QFormLayout(self.path_tab)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 路径持久化到 config.json（原先只显示默认值，用户修改不会被保存）
        self.project_path_edit = self.create_path_selector(
            layout, "项目默认路径:",
            self.config_manager.get("default_project_path") or os.path.abspath("projects"),
            "default_project_path")
        self.resource_path_edit = self.create_path_selector(
            layout, "素材库路径:",
            self.config_manager.get("resources_path") or os.path.abspath("resources"),
            "resources_path")
        self.output_path_edit = self.create_path_selector(
            layout, "输出路径:",
            self.config_manager.get("output_path") or os.path.abspath("output"),
            "output_path")

        # 临时目录清理策略
        self.temp_cleanup_combo = QComboBox()
        self.temp_cleanup_combo.addItems(["自动清理（任务完成后删除临时文件）", "手动清理（保留临时文件供调试）", "启动时清理（下次启动时删除旧临时文件）"])
        cur_strategy = self.config_manager.get("temp_cleanup_strategy") or "auto"
        strategy_map = {"auto": 0, "manual": 1, "startup": 2}
        self.temp_cleanup_combo.setCurrentIndex(strategy_map.get(cur_strategy, 0))
        self.temp_cleanup_combo.setStyleSheet("padding: 5px; color: " + _theme.color("text") + "; background-color: " + _theme.color("panel") + "; border: 1px solid " + _theme.color("panel2") + ";")
        self.temp_cleanup_combo.currentIndexChanged.connect(
            lambda: self.config_manager.set("temp_cleanup_strategy",
                                            ["auto", "manual", "startup"][self.temp_cleanup_combo.currentIndex()])
        )
        layout.addRow(self.create_label("临时文件清理:"), self.temp_cleanup_combo)

    def create_path_selector(self, layout, label_text, default_path, config_key):
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(default_path)
        edit.setStyleSheet("padding: 8px; background-color: " + _theme.color("panel2") + "; color: " + _theme.color("text") + "; border: 1px solid " + _theme.color("border_strong") + ";")
        # 手动输入完成后立即保存
        edit.editingFinished.connect(lambda: self.save_path_setting(config_key, edit))
        h_layout.addWidget(edit)

        btn = QPushButton("选择")
        btn.setFixedSize(60, 35)
        btn.setStyleSheet("background-color: " + _theme.color("accent") + "; color: " + _theme.color("text") + "; border-radius: 4px;")
        btn.clicked.connect(lambda: self.browse_path(edit, config_key))
        h_layout.addWidget(btn)

        layout.addRow(self.create_label(label_text), container)
        return edit

    def browse_path(self, line_edit, config_key=None):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", line_edit.text())
        if path:
            line_edit.setText(path)
            if config_key:
                self.save_path_setting(config_key, line_edit)

    def save_path_setting(self, config_key, line_edit):
        path = line_edit.text().strip()
        if path:
            self.config_manager.set(config_key, path)

    def browse_workflow(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        default_dir = os.path.join(project_root, "resources", "workflows")
        if not os.path.isdir(default_dir):
            default_dir = "resources/workflows"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择工作流文件", default_dir,
            "Workflow JSON (*.json);;All Files (*)"
        )
        if path:
            self.default_wf_edit.setText(os.path.basename(path))
            self.save_general_settings()

    def create_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: " + _theme.color("text_sub") + "; font-size: 14px; font-weight: bold;")
        return lbl

    def refresh_table(self):
        self.api_table.setRowCount(0)
        for config in self.api_configs:
            row = self.api_table.rowCount()
            self.api_table.insertRow(row)

            name = config.get("name", "")
            if config.get("is_default"):
                name = f"★ {name} (默认)"

            item_name = QTableWidgetItem(name)
            if config.get("is_default"):
                item_name.setForeground(QColor(_theme.color("accent")))

            self.api_table.setItem(row, 0, item_name)
            self.api_table.setItem(row, 1, QTableWidgetItem(config.get("type", "")))
            self.api_table.setItem(row, 2, QTableWidgetItem(config.get("provider", "")))
            self.api_table.setItem(row, 3, QTableWidgetItem(config.get("model", "")))
            self.api_table.setItem(row, 4, QTableWidgetItem(config.get("id", "")))

    def add_config(self):
        dialog = ApiConfigDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            data["id"] = str(uuid.uuid4())
            
            # Handle default exclusivity
            if data.get("is_default"):
                for config in self.api_configs:
                    if config.get("type") == data.get("type"):
                        config["is_default"] = False
            
            self.api_configs.append(data)
            self.save_configs()
            self.refresh_table()

    def edit_config(self):
        selected_items = self.api_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先选择一项配置")
            return

        row = selected_items[0].row()
        config_id = self.api_table.item(row, 4).text()

        config = next((c for c in self.api_configs if c["id"] == config_id), None)
        if config:
            dialog = ApiConfigDialog(self, config)
            if dialog.exec():
                new_data = dialog.get_data()
                new_data["id"] = config_id # Keep ID
                
                # Handle default exclusivity
                if new_data.get("is_default"):
                    for c in self.api_configs:
                        if c.get("type") == new_data.get("type") and c.get("id") != config_id:
                            c["is_default"] = False
                
                # Update in list
                for i, c in enumerate(self.api_configs):
                    if c["id"] == config_id:
                        self.api_configs[i] = new_data
                        break

                self.save_configs()
                self.refresh_table()

    def delete_config(self):
        selected_items = self.api_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先选择一项配置")
            return

        row = selected_items[0].row()
        config_id = self.api_table.item(row, 4).text()

        confirm = QMessageBox.question(self, "确认", "确定要删除这个配置吗？", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.api_configs = [c for c in self.api_configs if c["id"] != config_id]
            self.save_configs()
            self.refresh_table()

    def save_configs(self):
        self.config_manager.set("api_configs", self.api_configs)

    def save_general_settings(self):
        model = self.embed_model_edit.text().strip()
        if not model:
            model = "text-embedding-3-small"
        updates = {
            "embedding_model": model,
            "embedding_api_key": self.embed_api_key_edit.text().strip(),
            "embedding_base_url": self.embed_base_url_edit.text().strip(),
        }
        # 扩充偏好项
        if hasattr(self, 'default_duration_spin'):
            updates["default_duration"] = self.default_duration_spin.value()
        if hasattr(self, 'default_style_combo'):
            updates["default_style"] = self.default_style_combo.currentText()
        if hasattr(self, 'auto_checkpoint_cb'):
            updates["auto_checkpoint"] = self.auto_checkpoint_cb.isChecked()
        if hasattr(self, 'retry_count_spin'):
            updates["retry_count"] = self.retry_count_spin.value()
        if hasattr(self, 'default_wf_edit'):
            wf = self.default_wf_edit.text().strip()
            if wf:
                updates["default_image_workflow"] = wf
        # 批量更新：一次原子写盘（原先 6 次 set = 6 次全量重写 + fsync）
        self.config_manager.set_many(updates)
        print(f"Saved general settings: duration={self.config_manager.get('default_duration')}, "
              f"style={self.config_manager.get('default_style')}, "
              f"checkpoint={self.config_manager.get('auto_checkpoint')}, "
              f"retry={self.config_manager.get('retry_count')}")

    def test_embedding_connection(self):
        """测试流水线真正会使用的 embedding 配置（含「API 配置」里的 Embedding 条目）。"""
        # 先保存，确保测试用的是最新输入
        self.save_general_settings()
        try:
            from ai_engine.llm.llm_client import EmbeddingClient
            client = EmbeddingClient(self.config_manager.get_embedding_config())
            ok, msg = client.test()
        except Exception as e:
            import traceback
            traceback.print_exc()
            ok, msg = False, f"Embedding 连接失败：{e}"
        if ok:
            QMessageBox.information(self, "连接成功", msg)
        else:
            QMessageBox.warning(self, "连接失败", msg)

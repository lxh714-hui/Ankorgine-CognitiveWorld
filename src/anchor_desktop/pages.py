from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from .widgets import ArchivePanel
from .product_gateway import emit_input_diagnostic


def label(text: str, object_name: str | None = None) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(True)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return widget


def button(text: str, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    return widget


class Page(QWidget):
    navigate = Signal(str, dict)

    def __init__(self, gateway, route, parent=None):
        super().__init__(parent)
        self.gateway, self.route = gateway, route
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 20, 24, 24)
        self.layout.setSpacing(16)
        top = QHBoxLayout()
        back = button("← 返回")
        self.back_button = back
        back.clicked.connect(lambda: self.navigate.emit("__back__", {}))
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        top.addStretch()
        self.layout.addLayout(top)

    def title(self, text: str, subtitle: str | None = None):
        self.layout.addWidget(label(text, "pageTitle"))
        if subtitle:
            self.layout.addWidget(label(subtitle, "muted"))

    def go(self, page: str, **params):
        self.navigate.emit(page, params)


class HomePage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumWidth(0)
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 40, 24, 48)
        column.setSpacing(20)
        column.addStretch(1)
        self.brand_label = label("ANCHOR COGNITIVE WORLD", "muted")
        self.brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_label.setMinimumHeight(self.brand_label.sizeHint().height())
        column.addWidget(self.brand_label)
        self.main_title = label("世界，从一次相遇开始。", "pageTitle")
        self.main_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.main_title)
        self.subtitle = label("桌面客户端 · 世界内容由可信宿主提供", "muted")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.subtitle)
        start = button("查看可用世界", True)
        start.clicked.connect(lambda: self.go("worlds"))
        column.addWidget(start, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(2)
        scroll.setWidget(content)
        self.layout.addWidget(scroll, 1)


class WorldListPage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.title("选择世界", "世界是独立的叙事空间；每个世界可以拥有多个存档和分支。")
        worlds = gateway.list_worlds()
        if not worlds:
            self.layout.addWidget(label(getattr(gateway, "status_message", "当前没有可进入的世界。"), "muted"))
        for world in worlds:
            card = QFrame()
            row = QHBoxLayout(card)
            details = QVBoxLayout()
            details.addWidget(label(world.title, "sectionTitle"))
            details.addWidget(label(world.summary, "muted"))
            row.addLayout(details, 1)
            action = button("查看世界  →")
            action.clicked.connect(lambda checked=False, wid=world.world_id: self.go("world_detail", world_id=wid))
            row.addWidget(action)
            self.layout.addWidget(card)
        self.layout.addStretch()


class WorldDetailPage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        world = gateway.read_world_projection(route.params["world_id"])
        self.title(world.title, world.summary)
        self.layout.addWidget(label("世界须知", "sectionTitle"))
        notice = QFrame()
        note_layout = QVBoxLayout(notice)
        note_layout.addWidget(label(world.notice))
        note_layout.addWidget(label("公开规则", "archiveHeading"))
        for rule in world.public_rules:
            note_layout.addWidget(label(f"· {rule}"))
        self.layout.addWidget(notice)
        actions = QHBoxLayout()
        saves = button("当前无可用存档")
        saves.clicked.connect(lambda: self.go("saves", world_id=world.world_id,
                                              slots=self._verified_saves))
        self.save_button = saves
        self.save_status_label = label("", "muted")
        self._verified_saves = ()
        stage = button("进入运行舞台")
        stage.setEnabled(callable(getattr(gateway, "begin_world", None)))
        stage.setToolTip("开始一个新的、经过内容校验的世界会话。" if stage.isEnabled() else "运行宿主尚未接入。")
        stage.clicked.connect(self.begin_world)
        self.entry_button = stage
        self.entry_status_label = label("", "muted")
        self.layout.addWidget(label(getattr(gateway, "status_message", ""), "muted"))
        actions.addWidget(saves)
        actions.addWidget(stage)
        self.layout.addLayout(actions)
        self.layout.addWidget(self.save_status_label)
        self.layout.addWidget(self.entry_status_label)
        self.layout.addStretch()
        self.refresh_saves()

    def refresh_saves(self):
        """Refresh on page entry/navigation, never on paint or timer ticks."""
        timer = getattr(self, "_save_listing_timer", None)
        if timer is not None:
            timer.stop()
        self._verified_saves = ()
        self.save_button.setEnabled(False)
        if callable(getattr(self.gateway, "begin_save_listing", None)):
            try:
                self._save_listing_id = self.gateway.begin_save_listing(
                    self.route.params["world_id"])
            except Exception:
                self._set_save_unavailable()
                return
            self.save_button.setText("正在核验存档")
            self.save_status_label.setText("")
            self._save_listing_timer = QTimer(self)
            self._save_listing_timer.timeout.connect(self._poll_save_listing)
            self._save_listing_timer.start(80)
            return
        try:
            records = self.gateway.list_saves(self.route.params["world_id"])
        except Exception:
            self._set_save_unavailable()
            return
        self._set_save_records(records)

    def _poll_save_listing(self):
        result = self.gateway.save_listing_status(self._save_listing_id)
        if result.state == "loading":
            return
        self._save_listing_timer.stop()
        if result.state == "ready":
            self._set_save_records(result.slots)
        else:
            self._set_save_unavailable()

    def _set_save_unavailable(self):
        self._verified_saves = ()
        self.save_button.setText("存档暂不可用")
        self.save_button.setEnabled(False)
        self.save_status_label.setText("无法核验本地存档；已有存档未被修改。")

    def _set_save_records(self, records):
        self._verified_saves = tuple(records)
        self.save_status_label.setText("")
        self.save_button.setText("选择存档" if records else "当前无可用存档")
        self.save_button.setEnabled(bool(records))

    def begin_world(self):
        try:
            self.gateway.begin_world(self.route.params["world_id"])
        except Exception:
            self.entry_status_label.setText("当前无法进入世界；没有改变世界状态。")
            return
        self.entry_button.setEnabled(False)
        self.entry_status_label.setText("正在建立世界会话……")
        self._entry_timer = QTimer(self)
        self._entry_timer.timeout.connect(self._poll_entry)
        self._entry_timer.start(80)

    def _poll_entry(self):
        status = self.gateway.entry_status()
        if status.state == "starting":
            return
        self._entry_timer.stop()
        if status.state == "ready":
            self.go("stage", world_id=self.route.params["world_id"])
        else:
            self.entry_status_label.setText("世界会话启动失败；请检查本地运行环境。")
            self.entry_button.setEnabled(True)


class SaveListPage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.world_id = route.params["world_id"]
        world = gateway.read_world_projection(self.world_id)
        self.title(f"{world.title} · 选择存档", "存档与世界分离；每个存档可含多个时间线或分支。")
        unavailable = False
        try:
            self.saves = (route.params["slots"] if "slots" in route.params
                          else gateway.list_saves(self.world_id))
        except Exception:
            self.saves = ()
            unavailable = True
            self.layout.addWidget(label("存档列表暂不可用；已有存档未被修改。请检查本地数据目录后重试。", "muted"))
        if not self.saves and not unavailable:
            self.layout.addWidget(label("当前没有由可信宿主提供的存档。", "muted"))
        self.list = QListWidget()
        for save in self.saves:
            item = QListWidgetItem(f"{save.name}\n最近游玩  {save.updated}   ·   {save.timeline_count} 条时间线/分支")
            item.setData(Qt.ItemDataRole.UserRole, save.id)
            self.list.addItem(item)
        self.layout.addWidget(self.list, 1)
        open_btn = button("载入选中存档", True)
        open_btn.setEnabled(bool(self.saves) and callable(getattr(gateway, "begin_restore", None)))
        open_btn.setToolTip("验证签名存档并恢复原时间线。" if open_btn.isEnabled() else "当前没有可恢复的存档。")
        open_btn.clicked.connect(self.open_selected)
        self.list.itemDoubleClicked.connect(lambda _: self.open_selected())
        self.layout.addWidget(open_btn)
        self.restore_button = open_btn
        self.restore_status_label = label("", "muted")
        self.layout.addWidget(self.restore_status_label)

    def open_selected(self):
        item = self.list.currentItem()
        if item is None or not callable(getattr(self.gateway, "begin_restore", None)):
            return
        self._selected_save_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.gateway.begin_restore(self.world_id, self._selected_save_id)
        except Exception:
            self.restore_status_label.setText("无法开始恢复；当前世界没有改变。")
            return
        self.restore_button.setEnabled(False)
        self.restore_status_label.setText("正在验证存档与历史……")
        self._restore_timer = QTimer(self)
        self._restore_timer.timeout.connect(self._poll_restore)
        self._restore_timer.start(80)

    def _poll_restore(self):
        status = self.gateway.entry_status()
        if status.state == "starting":
            return
        self._restore_timer.stop()
        if status.state == "ready":
            self.go("stage", world_id=self.world_id, save_id=self._selected_save_id)
        else:
            self.restore_status_label.setText("存档验证或恢复失败；未进入该世界。")
            self.restore_button.setEnabled(True)


class StagePage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        if callable(getattr(gateway, "leave_world", None)):
            self.back_button.clicked.disconnect()
            self.back_button.clicked.connect(self.leave_world)
            self.back_button.setToolTip("结束当前会话并返回世界选择。")
        self.world_id, self.save_id = route.params["world_id"], route.params.get("save_id")
        world = gateway.read_world_projection(self.world_id, self.save_id)
        self.world = world
        self.mode = QComboBox()
        self.mode.addItem("人物扮演", "roleplay")
        mode_row = QHBoxLayout()
        mode_row.addWidget(label(world.title, "sectionTitle"))
        mode_row.addStretch()
        mode_row.addWidget(label("运行模式", "muted"))
        mode_row.addWidget(self.mode)
        self.stage_buttons = []
        for text, dest in (("世界状态", "archive"), ("历史记录", "history"), ("时间线 / 回档", "timeline"), ("保存", "save")):
            action_button = button(text)
            if dest in {"history", "timeline"}:
                action_button.setEnabled(False)
                action_button.setToolTip("已授权的历史投影与恢复接口尚未接入。")
            elif dest == "save":
                action_button.setEnabled(callable(getattr(gateway, "begin_save", None)))
                action_button.setToolTip("在后台创建并签名当前世界的存档。" if action_button.isEnabled() else "真实存档接口尚未接入。")
            action_button.clicked.connect(lambda checked=False, d=dest: self.stage_action(d))
            mode_row.addWidget(action_button)
            self.stage_buttons.append(action_button)
        self.layout.addLayout(mode_row)

        history_heading = label("当前交互", "archiveHeading")
        history_heading.setObjectName("actionEffectHeading")
        interaction = QWidget()
        interaction.setObjectName("stageInteraction")
        self.interaction = interaction
        interaction_layout = QVBoxLayout(interaction)
        interaction_layout.setContentsMargins(0, 0, 0, 0)
        interaction_layout.setSpacing(6)
        self.layout.addWidget(history_heading)

        history_scroll = QScrollArea()
        history_scroll.setObjectName("actionEffectScroll")
        history_scroll.setWidgetResizable(True)
        history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        history_scroll.setMinimumHeight(0)
        history_content = QWidget()
        history_content.setMinimumWidth(0)
        self.action_effect_history = QVBoxLayout(history_content)
        self.action_effect_history.setContentsMargins(0, 0, 0, 0)
        self.action_effect_history.setSpacing(2)
        self.action_effect_history.addStretch(1)
        history_scroll.setWidget(history_content)
        self.layout.addWidget(history_scroll, 1)
        self.history_scroll = history_scroll

        self._history_placeholder = label("世界尚未呈现可展示的记录。", "muted")
        self._history_placeholder.setObjectName("actionEffectEmpty")
        self.action_effect_history.insertWidget(0, self._history_placeholder)
        self._unsubscribe_performance = gateway.subscribe_performance(self._on_performance)

        self.target_select = QComboBox()
        self.target_select.addItem("不指定目标", None)
        if not callable(getattr(gateway, "submit_input", None)):
            for target_ref in gateway.available_targets(self.world_id):
                self.target_select.addItem(target_ref, target_ref)
            interaction_layout.addWidget(self.target_select)
        self.response = label("就绪" if callable(getattr(gateway, "submit_input", None)) else "交互尚未接入可信异步宿主。", "muted")
        self.response.setObjectName("stageStatus")
        self.response.setMaximumHeight(30)
        self.layout.addWidget(self.response)
        self.input_area = QTextEdit()
        self.input_area.setPlaceholderText("描述想尝试的方法，并选择已观察目标……")
        self.input_area.setMinimumHeight(72)
        self.input_area.setMaximumHeight(120)
        self.input_area.installEventFilter(self)
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_area, 1)
        self.submit = button("提交", True)
        self.submit.setEnabled(callable(getattr(gateway, "submit_input", None)))
        self.submit.setToolTip("后台执行玩家输入。" if self.submit.isEnabled() else "异步输入尚未接入。")
        self.input_area.setReadOnly(not self.submit.isEnabled())
        self.submit.clicked.connect(self.submit_action)
        input_row.addWidget(self.submit)
        interaction_layout.addLayout(input_row)
        self.retry_display_button = button("重试展示")
        self.retry_display_button.setVisible(False)
        self.retry_display_button.clicked.connect(self.retry_display)
        interaction_layout.addWidget(self.retry_display_button)
        if callable(getattr(gateway, "leave_world", None)):
            leave = button("结束当前会话")
            leave.setToolTip("结束当前会话；未保存的后续变化不会保留。")
            leave.clicked.connect(self.leave_world)
            leave.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            interaction_layout.addWidget(leave)
            self.leave_button = leave
        self.layout.addWidget(interaction, 0)
        self.mode.currentIndexChanged.connect(self.update_mode)
        self.update_mode()
        self._clarification_id = None
        self._append_display()

    def leave_world(self):
        try:
            self.gateway.leave_world()
        except Exception:
            self.response.setText("会话尚未结束；请稍后重试。")
            return
        self.go("__reset_worlds__")

    def _append_display(self):
        reader = getattr(self.gateway, "read_display", None)
        if not callable(reader):
            return ()
        shown = []
        for entry in reader():
            if entry.kind not in {"fact", "dialogue", "clarification", "narrative", "observation", "action_feedback"}:
                continue
            if entry.kind == "clarification":
                self._clarification_id = entry.request_id
            self._append_history_line(entry.text, {
                "fact": "actionEffectEntry", "dialogue": "dialogueEntry",
                "clarification": "clarificationEntry", "narrative": "narrativeEntry",
                "observation": "actionEffectEntry", "action_feedback": "actionEffectEntry",
            }[entry.kind])
            shown.append((entry.kind, getattr(entry, "request_id", None)))
        return tuple(shown)

    def _append_history_line(self, text: str, object_name: str):
        bar = self.history_scroll.verticalScrollBar()
        at_bottom = bar.maximum() - bar.value() <= 16
        if self._history_placeholder:
            self._history_placeholder.hide()
            self._history_placeholder.deleteLater()
            self._history_placeholder = None
        item = label(text)
        item.setObjectName(object_name)
        self.action_effect_history.insertWidget(self.action_effect_history.count() - 1, item)
        if at_bottom:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _on_performance(self, event):
        """Render only an allowlisted action/effect projection, never dialogue."""
        from .models import ActionEffectProjection

        if not isinstance(event, ActionEffectProjection):
            return
        parts = [part for part in (event.subject, event.action, event.effect) if part]
        if not parts:
            return
        if self._history_placeholder:
            self._history_placeholder.hide()
            self._history_placeholder.deleteLater()
            self._history_placeholder = None
        entry = label("  ·  ".join(parts))
        entry.setObjectName("actionEffectEntry")
        self.action_effect_history.insertWidget(self.action_effect_history.count() - 1, entry)

    def update_mode(self):
        self.input_area.setPlaceholderText("描述想尝试的行动；不可确定的输入不会被强行执行。")

    def eventFilter(self, watched, event):
        if (watched is self.input_area and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit_action()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def stage_action(self, dest):
        if dest == "archive":
            self.go("archive", world_id=self.world_id, save_id=self.save_id)
        elif dest == "history":
            self.go("history", world_id=self.world_id, save_id=self.save_id)
        elif dest == "timeline":
            self.go("timeline", world_id=self.world_id, save_id=self.save_id)
        elif dest == "save":
            try:
                self.gateway.begin_save()
            except Exception:
                self.response.setText("当前无法开始保存；世界状态没有改变。")
                return
            self.response.setText("正在后台验证并创建存档……")
            self._save_timer = QTimer(self)
            self._save_timer.timeout.connect(self._poll_save)
            self._save_timer.start(80)

    def _poll_save(self):
        status = self.gateway.save_status()
        if status.state == "saving":
            return
        self._save_timer.stop()
        if status.state == "saved":
            self.response.setText("存档已验证并保存；结束会话后可以从世界页面恢复。")
        else:
            self.response.setText("存档未完成；请稍后重试，当前世界仍在运行。")

    def submit_action(self):
        if not self.submit.isEnabled() and getattr(self, "_pending_request", None) is not None:
            self.response.setText("上一请求仍在处理；请等待结果。")
            return
        if not callable(getattr(self.gateway, "submit_input", None)):
            self.response.setText("玩家输入尚未接入可信异步宿主；未提交行动。")
            return
        raw = self.input_area.toPlainText().strip()
        if not raw:
            self.response.setText("请输入行动或问题后再提交。")
            return
        self.response.setText("正在受理请求……")
        try:
            if self._clarification_id is None:
                request_id = self.gateway.submit_input(raw)
            else:
                request_id = self.gateway.submit_input(raw, clarification_id=self._clarification_id)
        except Exception:
            self.response.setText("输入未受理；请检查会话状态。")
            return
        self._pending_request = request_id
        self._handled_terminal = None
        self._append_history_line(f"你：{raw}", "playerInputEntry")
        self.input_area.clear()
        self.submit.setEnabled(False)
        self.retry_display_button.setVisible(False)
        self.response.setText("已受理，正在理解输入……")
        if not hasattr(self, "_task_timer"):
            self._task_timer = QTimer(self)
            self._task_timer.timeout.connect(self._poll_task)
        self._task_timer.start(80)

    def _poll_task(self):
        request_id = getattr(self, "_pending_request", None)
        if request_id is None or getattr(self, "_handled_terminal", None) == request_id:
            return
        try:
            status = self.gateway.input_status(request_id)
        except Exception:
            self._task_timer.stop()
            self.response.setText("会话已变化；旧请求不再展示。")
            self._handled_terminal = request_id
            self.submit.setEnabled(True)
            return
        if status.request_id != request_id:
            return
        if status.execution.value in {"accepted", "running"}:
            self.response.setText("已受理，正在理解输入……" if status.execution.value == "accepted" else "正在处理输入……")
            return
        if getattr(self, "_retrying_display", False) and status.delivery.value == "pending":
            self.response.setText("正在重新检查并展示已提交结果……")
            return
        self._task_timer.stop()
        self._retrying_display = False
        self._handled_terminal = request_id
        shown = self._append_display()
        has_clarification = ("clarification", request_id) in shown
        has_narrative = ("narrative", request_id) in shown
        if status.outcome_status != "clarification_required" or not has_clarification:
            self._clarification_id = None
        if status.delivery.value == "stale":
            self.response.setText("展示已失效；当前世界事实不因此回滚。")
        elif status.delivery.value == "retryable":
            self.response.setText("行动已提交，展示暂未送达；可以只重试展示。")
            self.retry_display_button.setVisible(True)
        elif status.outcome_status == "reasoning_unavailable":
            reason = {
                "input_provider_unavailable": "输入理解服务未配置；请求未完成。",
                "input_provider_configuration_invalid": "输入理解服务配置无效；请求未完成。",
                "input_provider_timeout": "输入理解服务超时；请求未完成。",
                "input_provider_invalid_response": "输入理解服务响应无效；请求未完成。",
                "input_provider_unreachable": "输入理解服务暂不可达；请求未完成。",
            }.get(status.recovery_code, "输入理解服务暂不可用；请求未完成。")
            self.response.setText(reason)
            self._append_history_line("这次输入未能处理；请稍后重试或检查本地服务。", "statusEntry")
        elif status.outcome_status == "unparseable":
            self.response.setText("没有理解这次输入；请求已结束。")
            if not has_narrative:
                self._append_history_line("没有理解这次输入；请换一种说法。", "statusEntry")
        elif status.outcome_status == "clarification_required":
            self.response.setText("请求已结束：等待补充信息。")
            if not has_clarification:
                self._append_history_line("这次澄清暂不可用；请重新明确描述你的意图。", "statusEntry")
        elif status.outcome_status == "observed":
            self.response.setText("查看已完成。")
        elif status.outcome_status == "target_unavailable":
            self.response.setText("目标当前不可见；请重新描述要查看的对象。")
        elif status.outcome_status == "observation_empty":
            self.response.setText("当前没有可展示的观察结果。")
        elif status.outcome_status == "clarification_expired":
            self.response.setText("之前的问题已失效；请重新提出完整请求。")
        elif status.outcome_status == "clarification_cancelled":
            self.response.setText("已取消之前的请求；世界状态未因此改变。")
        elif status.execution.value in {"cancelled", "expired", "stale"}:
            self.response.setText("请求已取消或世界已变化；没有执行旧请求。")
            self._append_history_line("本次请求没有继续处理。", "statusEntry")
        elif status.execution.value == "failed":
            self.response.setText("请求未完成：处理失败。")
            self._append_history_line("处理暂时失败；请稍后重试。", "statusEntry")
        elif status.outcome_status == "unresolved":
            self.response.setText("请求已结束：行动未能裁定。")
            if not has_narrative:
                self._append_history_line("这次尝试尚无足够依据形成已确认结果。", "statusEntry")
        elif status.outcome_status == "rejected":
            self.response.setText("请求已结束：行动未获准处理。")
            self._append_history_line("这次请求没有进入行动裁定。", "statusEntry")
        elif status.outcome_status == "failed":
            self.response.setText("行动已裁定：未达成预期结果。")
            if not any(kind in {"fact", "dialogue", "action_feedback"} for kind, _ in shown):
                self._append_history_line("这次行动没有达成预期结果。", "statusEntry")
        elif status.outcome_status == "resolved":
            self.response.setText("行动已完成。")
            if not any(kind in {"fact", "dialogue"} for kind, _ in shown):
                self._append_history_line("这次行动已确认，但没有可展示的结果。", "statusEntry")
        elif status.outcome_status == "goal_already_satisfied":
            self.response.setText("请求已结束；结果见历史。")
        elif status.outcome_status == "executed_no_observable_change":
            self.response.setText("请求已结束；结果见历史。")
        else:
            self.response.setText("请求已结束：没有已确认的行动结果。" if status.execution.value == "completed" else "请求未完成。")
            self._append_history_line("这次请求没有产生可展示的行动结果。", "statusEntry")
        try:
            emit_input_diagnostic(request_id, "ui_terminal",
                                  outcome_status=status.outcome_status,
                                  delivery=status.delivery.value,
                                  ui_status=self.response.text(),
                                  display_kinds=sorted({kind for kind, _ in shown}))
        except Exception:
            pass
        self.submit.setEnabled(True)

    def retry_display(self):
        try:
            self.gateway.retry_display(self._pending_request)
        except Exception:
            self.response.setText("当前无法重新展示；世界事实不会因此重做。")
            return
        self.retry_display_button.setVisible(False)
        self.response.setText("正在重新检查并展示已提交结果……")
        self._handled_terminal = None
        self._retrying_display = True
        self._task_timer.start(80)


class ArchivePage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.title("世界状态")
        self.panel = ArchivePanel(gateway, route.params["world_id"])
        self.panel.setMinimumWidth(0)
        self.panel.setMaximumWidth(16777215)
        self.panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout.addWidget(self.panel, 1)


class HistoryPage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.title("历史记录", "授权历史投影尚未接入。")
        world = gateway.read_world_projection(route.params["world_id"], route.params.get("save_id"))
        for event in world.known_events:
            self.layout.addWidget(label(f"◇  {event}"))
        if not world.known_events:
            self.layout.addWidget(label("暂无可展示的已授权历史记录。", "muted"))
        self.layout.addStretch()


class TimelinePage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.world_id, self.save_id = route.params["world_id"], route.params.get("save_id")
        self.title("时间线与回档", "正式分支预览与恢复尚未接入。")
        self.warning = label("此页面不会执行回档，也不会修改世界状态。", "muted")
        self.layout.addWidget(self.warning)
        self.timelines = gateway.list_timelines(self.save_id) if self.save_id else ()
        self.timeline_select = QComboBox()
        for timeline in self.timelines:
            self.timeline_select.addItem(timeline.name, timeline.id)
        self.layout.addWidget(label("原时间线", "archiveHeading"))
        self.layout.addWidget(self.timeline_select)
        self.events = QListWidget()
        self.layout.addWidget(label("回档节点", "archiveHeading"))
        self.layout.addWidget(self.events, 1)
        self.preview = label("选择一个节点以预览分支。", "muted")
        self.layout.addWidget(label("新分支预览", "archiveHeading"))
        self.layout.addWidget(self.preview)
        self.timeline_select.currentIndexChanged.connect(self.populate_events)
        self.events.currentRowChanged.connect(self.update_preview)
        self.populate_events()
        actions = QHBoxLayout()
        cancel = button("取消 / 返回舞台")
        cancel.clicked.connect(lambda: self.navigate.emit("__back__", {}))
        confirm = button("恢复当前节点", True)
        confirm.setEnabled(False)
        confirm.setToolTip("真实恢复接口尚未接入。")
        confirm.clicked.connect(self.confirm_preview)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        self.layout.addLayout(actions)

    def selected_timeline(self):
        index = self.timeline_select.currentIndex()
        return self.timelines[index] if 0 <= index < len(self.timelines) else None

    def populate_events(self):
        self.events.clear()
        timeline = self.selected_timeline()
        if timeline:
            for event in timeline.events:
                item = QListWidgetItem(f"{event.time}  ·  {event.title}\n{event.description}")
                item.setData(Qt.ItemDataRole.UserRole, event.id)
                self.events.addItem(item)
        if self.events.count():
            self.events.setCurrentRow(0)
        self.update_preview()

    def update_preview(self, *_):
        timeline, item = self.selected_timeline(), self.events.currentItem()
        if timeline and item:
            self.preview.setText(f"从「{item.text().splitlines()[0]}」创建待授权分支预览；来源：{timeline.name}。原时间线保持不变。")

    def confirm_preview(self):
        self.warning.setText("真实恢复尚未接入；没有执行回档。")


class SettingsPage(Page):
    def __init__(self, gateway, route, parent=None):
        super().__init__(gateway, route, parent)
        self.title("设置", "Anchor Desktop M0.5")
        host_state = ("可启动经验证的新世界会话" if callable(getattr(gateway, "begin_world", None))
                      else "尚未配置")
        self.layout.addWidget(label("界面：深色低饱和\n组合头像：可替换的稳定渲染适配器\n世界包与运行宿主：" + host_state))
        self.layout.addStretch()


PAGE_TYPES = {
    "home": HomePage, "worlds": WorldListPage, "world_detail": WorldDetailPage,
    "saves": SaveListPage, "stage": StagePage, "archive": ArchivePage,
    "history": HistoryPage, "timeline": TimelinePage, "settings": SettingsPage,
}

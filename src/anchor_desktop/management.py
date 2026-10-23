"""Confirmation-bound host management; no raw paths or Runtime objects reach UI."""
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager, SaveCommittedError
from cognitive_world.content.persistence import scenario_snapshot_codec


@dataclass(frozen=True)
class RemovalPreview:
    token: str
    operation: str
    world_id: str
    target_id: str
    name: str
    removed: str
    retained: str
    consequences: str
    irreversible: bool


@dataclass(frozen=True)
class RemovalStatus:
    state: str
    error_code: str | None = None


class ManagementMixin:
    def _init_management(self, hidden_world_ids, writer):
        self._hidden_packages = set(hidden_world_ids)
        self._visibility_writer = writer
        self._removal_plans = {}
        self._removal = None
        self._removal_token = None

    def _require_no_removal(self):
        if self._removal is not None and not self._removal.done():
            raise RuntimeError("management_operation_in_progress")

    def _management_idle(self):
        if self._closed:
            raise RuntimeError("host_closed")
        if ((self._entry is not None and self._active is None)
                or (self._save is not None and not self._save.done())):
            raise RuntimeError("save_or_restore_in_progress")

    def list_worlds(self):
        return tuple(world for world in super().list_worlds()
                     if world.world_id not in self._hidden_packages)

    def management_worlds(self):
        return tuple(package.projection() for package in self.catalog._packages.values())

    def package_hidden(self, world_id):
        self.catalog.package(world_id)
        return world_id in self._hidden_packages

    def restore_package_visibility(self, world_id):
        with self._lock:
            self._management_idle()
            self._require_no_removal()
            self.catalog.package(world_id)
            hidden = self._hidden_packages - {world_id}
            if self._visibility_writer is not None:
                self._visibility_writer(tuple(sorted(hidden)))
            self._hidden_packages = hidden

    def _management_snapshot(self, world_id):
        package = self.catalog.package(world_id)
        root = self._saves_root / world_id
        records, digest = (), None
        if root.exists():
            # Unlike the normal new-world trust supplier, preview never initializes a key ring.
            from .product_gateway import _local_trust
            trust = (WindowsDpapiPersistenceTrust.open() if self._trust_supplier is _local_trust
                     else self._trust_supplier())
            reader = SaveManager(root, trust=trust, codec=scenario_snapshot_codec(), _read_only=True)
            before = reader.catalog_path.read_bytes()
            records = reader.list_saves()
            if reader.catalog_path.read_bytes() != before:
                raise RuntimeError("catalog_changed")
            digest = sha256(before).hexdigest()
        active = self._active
        binding = None if active is None else (
            active.package.world_id, active.runtime.context.event_history.timeline_id,
            active.runtime.write_fence.session_id, active.runtime.write_fence.restore_generation,
        )
        return (sha256(repr(package).encode()).hexdigest(), world_id in self._hidden_packages, digest, binding), records

    def prepare_removal_async(self, operation, world_id, target_id=None):
        with self._lock:
            self._management_idle()
            self._require_no_removal()
            return self._executor.submit(self.prepare_removal, operation, world_id, target_id)

    def prepare_removal(self, operation, world_id, target_id=None):
        with self._lock:
            self._management_idle()
            self._require_no_removal()
        signature, records = self._management_snapshot(world_id)
        package = self.catalog.package(world_id)
        if operation == "package":
            if not package.listed or signature[1] or (self._active is not None and self._active.package.world_id == world_id):
                raise RuntimeError("package_hidden_or_active")
            target_id, name = world_id, package.title
            removed = "仅从本机新世界目录隐藏此内置包；不删除任何源码文件。"
            retained = f"保留世界定义、运行实例和全部 {len(records)} 个存档及分支。"
            consequences = "管理页仍可恢复存档或恢复显示；没有用户安装包卸载器。"
            irreversible = False
        elif operation == "instance":
            if self._active is None or self._active.package.world_id != world_id:
                raise RuntimeError("no_selected_live_instance")
            actual = self._active.runtime.context.event_history.timeline_id
            if target_id is not None and target_id != actual:
                raise RuntimeError("stale_instance")
            target_id, name = actual, package.title + " · 当前运行实例"
            removed = "结束此运行会话并丢弃未保存进度；取消尚未提交的后台行动并冻结写入。"
            retained = f"保留世界包和全部 {len(records)} 个独立存档及其祖先、分支资源。"
            consequences = "未保存进度不可恢复。此操作不永久抹除存档中的场景实例；已进入提交的行动可先完成。"
            irreversible = True
        elif operation == "save":
            if self._active is not None and self._active.package.world_id == world_id:
                raise RuntimeError("world_is_active")
            selected = next((item for item in records if item.save_id == target_id), None)
            if selected is None:
                raise KeyError("save_not_found")
            reader = SaveManager(self._saves_root / world_id, trust=self._inspection_trust(),
                                 codec=scenario_snapshot_codec(), _read_only=True)
            if reader.manual_deletion_fingerprint(target_id) != signature[2]:
                raise RuntimeError("catalog_changed")
            name = package.title + " · 手动存档"
            removed = "删除所选保存槽；仅回收不再被其他存档、分支或 Runtime 租约引用的资源。"
            retained = f"保留世界包、运行实例以及其他 {len(records)-1} 个存档及其依赖。"
            consequences = "保存槽删除不可撤销；共享祖先或租约保护的资源可能继续保留。"
            irreversible = True
        else:
            raise ValueError("unsupported_removal")
        preview = RemovalPreview(uuid4().hex, operation, world_id, target_id, name,
                                 removed, retained, consequences, irreversible)
        with self._lock:
            self._management_idle()
            self._removal_plans[preview.token] = (preview, signature)
        return preview

    def _inspection_trust(self):
        from .product_gateway import _local_trust
        return (WindowsDpapiPersistenceTrust.open() if self._trust_supplier is _local_trust
                else self._trust_supplier())

    def cancel_removal(self, token):
        with self._lock:
            self._removal_plans.pop(token, None)

    def begin_removal(self, token):
        with self._lock:
            self._management_idle()
            self._require_no_removal()
            preview, expected = self._removal_plans.pop(token)
            def remove():
                try:
                    actual, _ = self._management_snapshot(preview.world_id)
                    with self._lock:
                        self._management_idle()
                        active = self._active
                        current_binding = None if active is None else (
                            active.package.world_id, active.runtime.context.event_history.timeline_id,
                            active.runtime.write_fence.session_id, active.runtime.write_fence.restore_generation,
                        )
                        if actual != expected or current_binding != expected[3]:
                            return RemovalStatus("failed", "selection_or_dependencies_changed")
                        if preview.operation == "package":
                            hidden = self._hidden_packages | {preview.world_id}
                            if self._visibility_writer is not None:
                                self._visibility_writer(tuple(sorted(hidden)))
                            self._hidden_packages = hidden
                        elif preview.operation == "instance":
                            self.leave_world()
                    if preview.operation == "save":
                        manager = self._save_manager(preview.world_id, self._inspection_trust())
                        manager.delete_manual_save(preview.target_id, expected_catalog_sha256=expected[2])
                    return RemovalStatus("completed")
                except SaveCommittedError:
                    return RemovalStatus("completed_cleanup_pending", "maintenance_pending")
                except Exception:
                    return RemovalStatus("failed", "removal_rejected")
            self._removal_token = token
            self._removal = self._executor.submit(remove)

    def removal_status(self, token=None):
        if token is not None and token != self._removal_token:
            return RemovalStatus("failed", "operation_expired")
        future = self._removal
        if future is None:
            return RemovalStatus("not_started")
        if not future.done():
            return RemovalStatus("running")
        if future.cancelled():
            return RemovalStatus("failed", "host_closed")
        return future.result()

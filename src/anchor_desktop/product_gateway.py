"""Qt-free desktop application adapter for a fresh world session."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.player.async_coordinator import PlayerInputTaskHandle, PlayerInputTaskSnapshot
from cognitive_world.player.input_understanding import PlayerInputRequest
from cognitive_world.player.input_diagnostics import emit as emit_input_diagnostic, enabled as input_diagnostics_enabled
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.runtime.save_manager import SaveManager, SaveMetadata

from .engine import BundledWorldCatalogGateway, FeatureUnavailable
from .host import NewWorldSession, start_new_world, resume_saved_world
from .models import SaveSlot, WorldProjection


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryStatus:
    state: str
    error_code: str | None = None


@dataclass(frozen=True)
class DisplayEntry:
    kind: str
    text: str
    request_id: str | None = None


@dataclass(frozen=True)
class SaveStatus:
    state: str
    save_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class SaveListingStatus:
    state: str
    slots: tuple[SaveSlot, ...] = ()


def _local_trust() -> WindowsDpapiPersistenceTrust:
    try:
        return WindowsDpapiPersistenceTrust.open()
    except FileNotFoundError:
        return WindowsDpapiPersistenceTrust.initialize()


def _desktop_clarification(message) -> str:
    """Project an authorized clarification for the Chinese desktop locale.

    The model's free text is not trusted to match the client's language. Known
    missing slots can be expressed without copying model wording or world IDs.
    """
    question = message.question.strip()
    han = sum("\u4e00" <= character <= "\u9fff" for character in question)
    latin = sum(character.isascii() and character.isalpha() for character in question)
    if han >= 2 and han >= latin // 3:
        return question
    slots = set(message.missing_information)
    if "target" in slots:
        return "请说明你指的是哪个对象。"
    if "direction" in slots:
        return "请说明你希望采用的方向。"
    if "method" in slots:
        return "请说明你打算怎样行动。"
    # An unknown model slot cannot safely be turned into a world-specific
    # question. Ask for a new explicit input through the same formal path.
    return "这次请求需要补充关键信息；请重新明确描述你的意图。"


class DesktopProductGateway(BundledWorldCatalogGateway):
    """One active local world; UI sees only narrow status and display values."""

    status_message = "世界内容已验证；进入世界后由正式 Runtime 执行。"

    def __init__(self, directory: Path | None = None, *, trust_supplier=None,
                 input_understanding_provider=None, saves_root: Path | None = None) -> None:
        super().__init__(directory)
        local_appdata = os.environ.get("LOCALAPPDATA")
        if saves_root is None and not local_appdata:
            raise RuntimeError("local application data directory is unavailable")
        self._saves_root = Path(saves_root) if saves_root is not None else Path(local_appdata) / "AnchorCognitiveWorld" / "saves"
        self._trust_supplier = trust_supplier or _local_trust
        self._input_understanding_provider = input_understanding_provider
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="anchor-host")
        self._lock = RLock()
        self._closed = False
        self._entry: Future[NewWorldSession] | None = None
        self._save: Future[SaveMetadata] | None = None
        self._listing: tuple[str, Future[tuple[SaveSlot, ...]]] | None = None
        self._active: NewWorldSession | None = None
        self._handles: dict[str, PlayerInputTaskHandle] = {}
        self._diagnosed_terminal_inputs: dict[str, tuple[str, str, str | None, str | None]] = {}
        self._display_counts = (0, 0, 0, 0, 0)

    def begin_world(self, world_id: str) -> None:
        package = self.catalog.package(world_id)
        with self._lock:
            if self._closed or self._entry is not None or self._active is not None:
                raise FeatureUnavailable("当前世界会话尚未结束。")

            def build() -> NewWorldSession:
                result = start_new_world(
                    package, trust=self._trust_supplier(),
                    input_understanding_provider=self._input_understanding_provider,
                )
                with self._lock:
                    if self._closed:
                        result.close()
                        raise RuntimeError("host_closed")
                return result

            self._entry = self._executor.submit(build)

    def _save_manager(self, world_id: str, trust) -> SaveManager:
        self.catalog.package(world_id)
        return SaveManager(self._saves_root / world_id, trust=trust,
                           codec=scenario_snapshot_codec())

    def list_saves(self, world_id: str) -> tuple[SaveSlot, ...]:
        self.catalog.package(world_id)
        world_saves = self._saves_root / world_id
        if not world_saves.exists():
            return ()
        if not (world_saves / "catalog.json").is_file():
            # A partial directory is not an empty, verified catalog. Listing
            # must not initialize one or mutate recovery evidence.
            raise FileNotFoundError("save catalog is unavailable")
        trust = self._trust_supplier()
        records = SaveManager.inspect_verified_saves(
            world_saves, trust=trust, codec=scenario_snapshot_codec(),
        )
        return tuple(SaveSlot(item.save_id, world_id,
                              "手动存档", item.created_at,
                              1) for item in records)

    def begin_save_listing(self, world_id: str) -> str:
        self.catalog.package(world_id)
        with self._lock:
            if self._closed:
                raise FeatureUnavailable("存档宿主已关闭。")
            request_id = uuid4().hex
            self._listing = (request_id, self._executor.submit(self.list_saves, world_id))
            return request_id

    def save_listing_status(self, request_id: str) -> SaveListingStatus:
        with self._lock:
            listing = self._listing
            if listing is None or listing[0] != request_id:
                return SaveListingStatus("expired")
            pending = listing[1]
        if not pending.done():
            return SaveListingStatus("loading")
        try:
            return SaveListingStatus("ready", pending.result())
        except Exception:
            _LOGGER.warning("Save listing verification failed", exc_info=True)
            return SaveListingStatus("unavailable")

    def read_world_projection(self, world_id: str, save_id: str | None = None) -> WorldProjection:
        package = self.catalog.package(world_id)
        if save_id is not None:
            with self._lock:
                if self._active is None or self._active.package.world_id != world_id:
                    raise FeatureUnavailable("存档尚未通过恢复验证。")
        return package.projection()

    def begin_restore(self, world_id: str, save_id: str) -> None:
        package = self.catalog.package(world_id)
        with self._lock:
            if self._closed or self._entry is not None or self._active is not None:
                raise FeatureUnavailable("请先结束当前世界会话。")
            def build() -> NewWorldSession:
                trust = self._trust_supplier()
                manager = self._save_manager(world_id, trust)
                matches = [item for item in manager.list_saves() if item.save_id == save_id]
                if len(matches) != 1:
                    raise KeyError("save_not_found")
                result = resume_saved_world(
                    package, manager=manager, save_id=save_id,
                    timeline_id=matches[0].timeline_id, trust=trust,
                    input_understanding_provider=self._input_understanding_provider,
                )
                with self._lock:
                    if self._closed:
                        result.close()
                        raise RuntimeError("host_closed")
                return result
            self._entry = self._executor.submit(build)

    def begin_save(self) -> None:
        with self._lock:
            session = self._active
            if self._closed or session is None or (self._save is not None and not self._save.done()):
                raise FeatureUnavailable("当前无法创建存档。")
            def save() -> SaveMetadata:
                trust = self._trust_supplier()
                manager = self._save_manager(session.package.world_id, trust)
                return manager.create_manual_save(
                    runtime=session.runtime, cognition=session.cognition,
                    memory_store=session.memory_store, agent_contexts=session.agent_contexts,
                )
            self._save = self._executor.submit(save)

    def save_status(self) -> SaveStatus:
        with self._lock:
            pending = self._save
        if pending is None:
            return SaveStatus("not_started")
        if not pending.done():
            return SaveStatus("saving")
        try:
            metadata = pending.result()
        except Exception as error:
            return SaveStatus("failed", error_code=type(error).__name__)
        return SaveStatus("saved", save_id=metadata.save_id)

    def entry_status(self) -> EntryStatus:
        with self._lock:
            pending = self._entry
            if self._active is not None:
                return EntryStatus("ready")
        if pending is None:
            return EntryStatus("not_started")
        if not pending.done():
            return EntryStatus("starting")
        try:
            session = pending.result()
        except Exception as exc:
            with self._lock:
                if self._entry is pending:
                    self._entry = None
            return EntryStatus("failed", type(exc).__name__)
        with self._lock:
            if self._closed:
                session.close()
                return EntryStatus("failed", "host_closed")
            self._active = session
        return EntryStatus("ready")

    def submit_input(self, text: str, *, clarification_id: str | None = None,
                     new_request: bool = False) -> str:
        with self._lock:
            session = self._active
            if self._closed or session is None:
                raise FeatureUnavailable("尚未进入运行中的世界。")
            binding = session.runtime.context.player_session
            request = PlayerInputRequest(
                f"desktop:{uuid4().hex}", binding.session_id, session.package.world_id, text,
                clarification_id=clarification_id, new_request=new_request,
            )
            handle = session.player_tasks.submit_input(request)
            self._handles[request.request_id] = handle
            return request.request_id

    def input_status(self, request_id: str) -> PlayerInputTaskSnapshot:
        with self._lock:
            if self._active is None or request_id not in self._handles:
                raise KeyError(request_id)
            status = self._active.player_tasks.get_status(self._handles[request_id])
            if input_diagnostics_enabled() and status.execution.value not in {"accepted", "running"}:
                try:
                    signature = (status.execution.value, status.delivery.value,
                                 status.outcome_status, status.recovery_code)
                    if self._diagnosed_terminal_inputs.get(request_id) != signature:
                        emit_input_diagnostic(request_id, "gateway_terminal",
                                              execution=status.execution.value,
                                              delivery=status.delivery.value,
                                              outcome_status=status.outcome_status,
                                              recovery_code=status.recovery_code)
                        self._diagnosed_terminal_inputs[request_id] = signature
                except Exception:
                    pass
            return status

    def retry_display(self, request_id: str) -> None:
        """Retry delivery without rerunning the completed player action."""
        with self._lock:
            if self._active is None or request_id not in self._handles:
                raise KeyError(request_id)
            self._active.player_tasks.retry_presentation(self._handles[request_id])

    def read_display(self) -> tuple[DisplayEntry, ...]:
        with self._lock:
            session = self._active
            if session is None:
                return ()
            player_id = session.runtime.context.player_session.player_id
            facts = session.output.messages_for(player_id)
            narratives = session.output.narrative_fallbacks_for(player_id)
            clarifications = session.output.clarifications_for(player_id)
            observations = session.output.observation_results_for(player_id)
            action_feedback = session.output.action_feedback_for(player_id)
            (old_facts, old_narratives, old_clarifications,
             old_observations, old_action_feedback) = self._display_counts
            self._display_counts = (len(facts), len(narratives), len(clarifications),
                                    len(observations), len(action_feedback))
            return (
                tuple(DisplayEntry("dialogue" if item.visibility_scope == "dialogue" else "fact",
                                   item.content) for item in facts[old_facts:])
                + tuple(DisplayEntry("narrative", item.content, item.request_id)
                        for item in narratives[old_narratives:])
                + tuple(DisplayEntry("clarification", _desktop_clarification(item), item.request_id)
                        for item in clarifications[old_clarifications:])
                + tuple(DisplayEntry("observation", message.content, result.request_id)
                        for result in observations[old_observations:]
                        for message in result.batch.messages)
                + tuple(DisplayEntry("action_feedback", item.content, item.request_id)
                        for item in action_feedback[old_action_feedback:])
            )

    def available_targets(self, world_id: str) -> tuple[str, ...]:
        with self._lock:
            if self._active is None or self._active.package.world_id != world_id:
                return ()
            return self._active.player_service.available_targets()

    def leave_world(self) -> None:
        """End a fresh in-memory session; no save or restore is implied."""
        with self._lock:
            if self._entry is not None and not self._entry.done():
                raise FeatureUnavailable("世界仍在启动中。")
            if self._save is not None and not self._save.done():
                raise FeatureUnavailable("存档仍在创建中。")
            active = self._active
            if active is not None:
                active.close()
            self._active = None
            self._entry = None
            self._handles.clear()
            self._display_counts = (0, 0, 0, 0, 0)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            active = self._active
            self._active = None
        if active is not None:
            active.close()
        self._executor.shutdown(wait=False, cancel_futures=True)

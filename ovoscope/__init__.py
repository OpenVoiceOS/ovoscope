import dataclasses
import json
import threading
from copy import deepcopy
from time import sleep, time
from typing import Union, List, Dict, Any, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_config.config import Configuration
from ovos_config.models import LocalConf
from ovos_core.intent_services import IntentService
from ovos_core.skill_manager import SkillManager
from ovos_plugin_manager.skills import find_skill_plugins
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessState
from ovos_workshop.skills.ovos import OVOSSkill

SerializedMessage = Dict[str, Union[str, Dict[str, Any]]]
SerializedTest = Dict[str, Union[str, bool, List[str], SerializedMessage]]

DEFAULT_IGNORED = ["ovos.skills.settings_changed"]
GUI_IGNORED = ["gui.clear.namespace",
               "gui.value.set",
               "mycroft.gui.screen.close",
               "gui.page.show"]
DEFAULT_EOF = ["ovos.utterance.handled"]
DEFAULT_ENTRY_POINTS = ["recognizer_loop:utterance"]
DEFAULT_FLIP_POINTS = []
DEFAULT_KEEP_SRC = ["ovos.skills.fallback.ping"]
DEFAULT_ACTIVATION = []
DEFAULT_DEACTIVATION = ["intent.service.skills.deactivate"]

# ---------------------------------------------------------------------------
# Pipeline stage groups — combine as needed for test scenarios
# ---------------------------------------------------------------------------
STOP_PIPELINE = [
    "ovos-stop-pipeline-plugin-high",
    "ovos-stop-pipeline-plugin-medium",
    "ovos-stop-pipeline-plugin-low",
]
CONVERSE_PIPELINE = ["ovos-converse-pipeline-plugin"]
ADAPT_PIPELINE = [
    "ovos-adapt-pipeline-plugin-high",
    "ovos-adapt-pipeline-plugin-medium",
    "ovos-adapt-pipeline-plugin-low",
]
PADATIOUS_PIPELINE = [
    "ovos-padatious-pipeline-plugin-high",
    "ovos-padatious-pipeline-plugin-medium",
    "ovos-padatious-pipeline-plugin-low",
]
# Padacioso is a pure-Python Padatious-compatible engine (no swig/C required).
# It ships as a dependency of ovos-workshop so is always available in any OVOS
# skill test environment.  Use this in place of PADATIOUS_PIPELINE when you
# don't want a swig build dep in CI or when ovos-padatious is not installed.
PADACIOSO_PIPELINE = [
    "ovos-padacioso-pipeline-plugin-high",
    "ovos-padacioso-pipeline-plugin-medium",
    "ovos-padacioso-pipeline-plugin-low",
]
FALLBACK_PIPELINE = [
    "ovos-fallback-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
]
COMMON_QUERY_PIPELINE = ["ovos-common-query-pipeline-plugin"]
PERSONA_PIPELINE = [
    "ovos-persona-pipeline-plugin-high",
    "ovos-persona-pipeline-plugin-low",
]
M2V_PIPELINE = [
    "ovos-m2v-pipeline-high",
    "ovos-m2v-pipeline-medium",
    "ovos-m2v-pipeline-low",
]
# Nebulento — fuzzy intent matching (ConfidenceMatcherPipeline). Single OPM
# entry point; the pipeline manager handles confidence-tier routing.
NEBULENTO_PIPELINE = ["ovos-nebulento-pipeline-plugin"]
# Palavreado — keyword/slot intent parser (ConfidenceMatcherPipeline).
PALAVREADO_PIPELINE = ["palavreado"]

# Standard test pipeline — all standard built-in stages.
# This requires ovos-adapt-pipeline-plugin and ovos-padatious-pipeline-plugin.
# If these are not installed, use LIGHT_TEST_PIPELINE instead.
DEFAULT_TEST_PIPELINE = [
    "ovos-stop-pipeline-plugin-high",
    "ovos-converse-pipeline-plugin",
    "ovos-adapt-pipeline-plugin-high",
    "ovos-padatious-pipeline-plugin-high",
    "ovos-padacioso-pipeline-plugin-high",
    "ovos-adapt-pipeline-plugin-medium",
    "ovos-padatious-pipeline-plugin-medium",
    "ovos-padacioso-pipeline-plugin-medium",
    "ovos-common-query-pipeline-plugin",
    "ovos-adapt-pipeline-plugin-low",
    "ovos-padatious-pipeline-plugin-low",
    "ovos-padacioso-pipeline-plugin-low",
    "ovos-fallback-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
    "ovos-stop-pipeline-plugin-medium",
]

# ---------------------------------------------------------------------------
# Global bus-coverage state (managed by pytest plugin or CLI)
# ---------------------------------------------------------------------------
GLOBAL_BUS_COVERAGE: bool = False
GLOBAL_BUS_COVERAGE_FILE: Optional[str] = None


class GlobalBusCoverageCollector:
    """Accumulates bus events globally across all FakeBus instances."""
    def __init__(self):
        # msg_type -> count
        self.invocations: Dict[str, int] = {}
        # msg_type -> count (total times .on was called for this type)
        self.registrations: Dict[str, int] = {}
        # skill_id -> {msg_type -> count}
        self.skill_registrations: Dict[str, Dict[str, int]] = {}

    def record_invocation(self, msg_type: str):
        self.invocations[msg_type] = self.invocations.get(msg_type, 0) + 1

    def record_registration(self, msg_type: str):
        self.registrations[msg_type] = self.registrations.get(msg_type, 0) + 1

    def record_skill_registration(self, skill_id: str, msg_type: str):
        if not skill_id:
            return
        if skill_id not in self.skill_registrations:
            self.skill_registrations[skill_id] = {}
        self.skill_registrations[skill_id][msg_type] = (
            self.skill_registrations[skill_id].get(msg_type, 0) + 1
        )

    def rename_skill(self, old_id: str, new_id: str):
        """Merge registrations from old_id into new_id."""
        if not old_id or not new_id or old_id == new_id:
            return
        if old_id in self.skill_registrations:
            old_data = self.skill_registrations.pop(old_id)
            if new_id not in self.skill_registrations:
                self.skill_registrations[new_id] = {}
            for mt, count in old_data.items():
                self.skill_registrations[new_id][mt] = (
                    self.skill_registrations[new_id].get(mt, 0) + count
                )


GLOBAL_BUS_COVERAGE_COLLECTOR: Optional[GlobalBusCoverageCollector] = None


def _patch_fakebus():
    """Monkey-patch FakeBus and ovos-workshop classes to track global coverage."""
    from ovos_utils.fakebus import FakeBus
    
    original_on = FakeBus.on
    original_once = getattr(FakeBus, "once", None)
    original_emit = FakeBus.emit

    def patched_on(self, event, handler):
        if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
            GLOBAL_BUS_COVERAGE_COLLECTOR.record_registration(event)
        return original_on(self, event, handler)

    def patched_once(self, event, handler):
        if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
            GLOBAL_BUS_COVERAGE_COLLECTOR.record_registration(event)
        if original_once:
            return original_once(self, event, handler)
        return original_on(self, event, handler)

    def patched_emit(self, message):
        if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
            msg_type = getattr(message, "msg_type", None) or getattr(message, "type", None)
            if msg_type:
                GLOBAL_BUS_COVERAGE_COLLECTOR.record_invocation(msg_type)
        return original_emit(self, message)

    FakeBus.on = patched_on
    FakeBus.once = patched_once
    FakeBus.emit = patched_emit

    # --- Patch ovos-workshop for better attribution ---
    try:
        from ovos_workshop.skills.ovos import OVOSSkill
        original_add_event = OVOSSkill.add_event
        original_bind = OVOSSkill.bind

        def patched_add_event(self, name, handler, *args, **kwargs):
            if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
                # Fallback to .name if skill_id is not yet set
                sid = getattr(self, "skill_id", None) or getattr(self, "name", None)
                if sid:
                    GLOBAL_BUS_COVERAGE_COLLECTOR.record_skill_registration(sid, name)
            return original_add_event(self, name, handler, *args, **kwargs)

        def patched_bind(self, bus):
            if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
                old_id = getattr(self, "skill_id", None) or getattr(self, "name", None)
                res = original_bind(self, bus)
                new_id = getattr(self, "skill_id", None)
                if old_id and new_id and old_id != new_id:
                    GLOBAL_BUS_COVERAGE_COLLECTOR.rename_skill(old_id, new_id)
                return res
            return original_bind(self, bus)

        OVOSSkill.add_event = patched_add_event
        OVOSSkill.bind = patched_bind
    except ImportError:
        pass

    try:
        from ovos_utils.events import EventContainer
        original_container_add = EventContainer.add

        def patched_container_add(self, name, handler, once=False):
            if GLOBAL_BUS_COVERAGE and GLOBAL_BUS_COVERAGE_COLLECTOR:
                # EventContainer usually belongs to a skill, but we don't have easy
                # access to skill_id here without more complex patching.
                # However, many skills call self.add_event which we already patched.
                pass
            return original_container_add(self, name, handler, once)
        # EventContainer.add = patched_container_add
    except ImportError:
        pass


# Apply the patch immediately when ovoscope is imported
_patch_fakebus()

# Lightweight test pipeline — no C extensions (swig) required.
# Uses only pure-Python stages that are dependencies of ovos-core/workshop.
# Use this when you want fast CI without building Padatious or Adapt.
LIGHT_TEST_PIPELINE = [
    "ovos-stop-pipeline-plugin-high",
    "ovos-converse-pipeline-plugin",
    "ovos-padacioso-pipeline-plugin-high",
    "ovos-padacioso-pipeline-plugin-medium",
    "ovos-padacioso-pipeline-plugin-low",
    "ovos-fallback-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
    "ovos-stop-pipeline-plugin-medium",
]

DEFAULT_PIPELINE_UNSET = object()


def is_pipeline_available(pipeline: List[str]) -> bool:
    """Return True if all pipeline stages in *pipeline* are currently installed.

    Uses ``importlib.metadata`` to check entry points — no FakeBus or IntentService
    is created, so this is cheap to call at class setup time.

    Example::

        import unittest
        from ovoscope import is_pipeline_available, M2V_PIPELINE

        class TestM2V(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                if not is_pipeline_available(M2V_PIPELINE):
                    raise unittest.SkipTest("ovos-m2v-pipeline not installed")
    """
    import importlib.metadata
    installed_bases: set = set()
    try:
        # Python 3.10+ entry_points API
        for ep in importlib.metadata.entry_points(group="opm.pipeline"):
            installed_bases.add(ep.name)
    except TypeError:
        # Fallback for older metadata API if needed
        for ep in importlib.metadata.entry_points().get("opm.pipeline", []):
            installed_bases.add(ep.name)

    for stage in pipeline:
        base = stage
        for suffix in ("-high", "-medium", "-low"):
            if stage.endswith(suffix):
                base = stage[: -len(suffix)]
                break
        if base not in installed_bases:
            return False
    return True


class MiniCroft(SkillManager):
    def __init__(self, skill_ids,
                 enable_installer=False,
                 enable_intent_service=True,
                 enable_event_scheduler=False,
                 enable_file_watcher=False,
                 enable_skill_api=True,
                 extra_skills: Optional[Dict[str, OVOSSkill]] = None,
                 isolate_config: bool = True,
                 default_pipeline: Optional[List[str]] = DEFAULT_PIPELINE_UNSET,
                 lang: Optional[str] = None,
                 secondary_langs: Optional[List[str]] = None,
                 pipeline_config: Optional[Dict[str, Dict]] = None,
                 modernize: bool = True,
                 emit_legacy: bool = True,
                 *args, **kwargs):
        # Namespace-migration flags forwarded to the harness FakeBus so callers
        # can choose which bus namespace(s) to exercise:
        #   modernize=True   emitting a legacy topic ALSO emits the ovos.* spec
        #                    topic (legacy producer -> spec listener)
        #   emit_legacy=True emitting an ovos.* spec topic ALSO emits the legacy
        #                    topic (spec producer -> legacy listener)
        # Both default on (mirrors MessageBusClient). Set BOTH False to isolate a
        # single namespace and assert no cross-namespace bridging occurs.
        self._modernize = modernize
        self._emit_legacy = emit_legacy
        self._isolated_config = isolate_config
        self._original_xdg_configs: Optional[List[LocalConf]] = None

        if default_pipeline is DEFAULT_PIPELINE_UNSET:
            if is_pipeline_available(DEFAULT_TEST_PIPELINE):
                self._default_pipeline = DEFAULT_TEST_PIPELINE
            else:
                self._default_pipeline = LIGHT_TEST_PIPELINE
        else:
            self._default_pipeline = default_pipeline

        self._original_pipeline: Optional[List[str]] = None
        self._original_cfg_pipeline: Optional[List[str]] = None
        self._had_cfg_pipeline: bool = False
        self._original_blacklisted_skills: Optional[List[str]] = None
        self._had_blacklisted_skills: bool = False
        self._original_blacklisted_intents: Optional[List[str]] = None
        self._had_blacklisted_intents: bool = False
        self._lang = lang
        self._secondary_langs = secondary_langs
        self._original_lang: Optional[str] = None
        self._original_cfg_lang: Optional[str] = None
        self._had_lang: bool = False
        self._original_secondary_langs: Optional[List[str]] = None
        self._had_secondary_langs: bool = False
        self._pipeline_config: Optional[Dict[str, Dict]] = pipeline_config
        self._original_pipeline_configs: Dict[str, Optional[Dict]] = {}
        self._had_pipeline_configs: Dict[str, bool] = {}

        if isolate_config:
            # Replace user XDG configs (e.g. ~/.config/mycroft/mycroft.conf) with
            # an empty list so the user's installed pipeline, locale, and other
            # preferences do not affect test results.  System config
            # (/etc/mycroft/mycroft.conf) and built-in defaults are still used.
            # Note: LocalConf(None) cannot be used here — its reload() calls
            # os.stat(None) and raises TypeError.  An empty list is safe.
            self._original_xdg_configs = Configuration.xdg_configs[:]
            Configuration.xdg_configs = []
            Configuration.reload()
            LOG.debug("ovoscope: user config isolated (xdg_configs cleared)")

        # Patch lang / secondary_langs BEFORE super().__init__() because
        # IntentService (and thus Adapt/Padatious) reads Configuration()
        # during construction and creates per-language engines at that time.
        if self._lang is not None or self._secondary_langs is not None:
            cfg = Configuration()
            if self._lang is not None:
                self._had_lang = "lang" in cfg
                self._original_cfg_lang = cfg.get("lang")
                cfg["lang"] = self._lang
                LOG.debug(f"ovoscope: lang set to '{self._lang}' "
                          f"(was '{self._original_cfg_lang}')")
            if self._secondary_langs is not None:
                self._had_secondary_langs = "secondary_langs" in cfg
                self._original_secondary_langs = cfg.get("secondary_langs")
                cfg["secondary_langs"] = self._secondary_langs
                LOG.debug(f"ovoscope: secondary_langs set to "
                          f"{self._secondary_langs}")

        # Patch per-pipeline config BEFORE super().__init__() so that pipeline
        # plugins read the overridden values during their __init__.
        # pipeline_config is a dict keyed by pipeline plugin config key
        # (the key used under Configuration()["intents"]), e.g.:
        #   {"ovos_m2v_pipeline": {"model": "Jarbas/ovos-model2vec-..."}}
        if self._pipeline_config:
            cfg = Configuration()
            intents_cfg = cfg.setdefault("intents", {})
            for plugin_key, plugin_cfg in self._pipeline_config.items():
                self._had_pipeline_configs[plugin_key] = plugin_key in intents_cfg
                self._original_pipeline_configs[plugin_key] = intents_cfg.get(plugin_key)
                intents_cfg[plugin_key] = plugin_cfg
                LOG.debug(f"ovoscope: pipeline_config patched '{plugin_key}'")

        self.boot_messages: List[Message] = []
        bus = FakeBus(modernize=self._modernize,
                      emit_legacy=self._emit_legacy)
        bus.on("message", self.handle_boot_message)
        self.skill_ids = skill_ids
        self.extra_skills = extra_skills or {}

        try:
            super().__init__(bus, enable_installer=enable_installer,
                             enable_skill_api=enable_skill_api,
                             enable_file_watcher=enable_file_watcher,
                             enable_intent_service=enable_intent_service,
                             enable_event_scheduler=enable_event_scheduler,
                             *args, **kwargs)
        except Exception:
            # If super().__init__ fails (e.g. plugin construction error),
            # ensure global Configuration() is restored.
            self.stop()
            raise

    @property
    def pipeline(self) -> List[str]:
        """Return the current active pipeline stages for this instance.

        Returns:
            List of stage IDs.
        """
        return self._default_pipeline

    def handle_boot_message(self, message: str):
        self.boot_messages.append(Message.deserialize(message))

    def load_metadata_transformers(self, cfg):
        self.intent_service.metadata_plugins.config = cfg
        self.intent_service.metadata_plugins.load_plugins()

    def load_plugin_skills(self):
        LOG.info("loading skill plugins")
        plugins = find_skill_plugins()
        for skill_id, plug in plugins.items():
            LOG.debug(f"Found skill: {skill_id}")
            if skill_id not in self.skill_ids:
                continue
            if skill_id not in self.plugin_skills:
                self._load_plugin_skill(skill_id, plug)
                LOG.info(f"Loaded skill: {skill_id}")

        for skill_id, plug in self.extra_skills.items():
            LOG.debug(f"Injected test skill: {skill_id}")
            if skill_id not in self.plugin_skills:
                self._load_plugin_skill(skill_id, plug)
                LOG.info(f"Loaded test skill: {skill_id}")

        self.bus.emit(Message("mycroft.skills.train"))  # tell any pipeline plugins to train loaded intents

    def _check_pipeline_available(self, pipeline: List[str]) -> bool:
        """Check if all stages in *pipeline* can be served by IntentService.

        Returns:
            bool: True if all stages are available, False if any are missing.
        """
        available = set(self.intents.pipeline_plugins.keys())
        missing = []
        for stage in pipeline:
            # Strip priority suffix to get the base plugin ID
            base = stage
            for suffix in ("-high", "-medium", "-low"):
                if stage.endswith(suffix):
                    base = stage[: -len(suffix)]
                    break
            if base not in available:
                missing.append(stage)
        if missing:
            LOG.warning(
                f"ovoscope: Pipeline stage(s) not installed: {missing}\n"
                f"Installed pipeline plugins: {sorted(available)}\n"
                f"Missing package(s) suggested:\n"
                f"  ADAPT_PIPELINE  → pip install ovos-adapt-pipeline-plugin\n"
                f"  PADATIOUS_PIPELINE → pip install ovos-padatious-pipeline-plugin\n"
                f"  PADACIOSO_PIPELINE → already bundled with ovos-workshop\n"
            )
            return False
        return True

    def run(self):
        """Load skills and mark core as ready to start tests"""
        self.status.set_alive()
        self.load_plugin_skills()
        if self._default_pipeline is not None:
            if not self._check_pipeline_available(self._default_pipeline):
                if self._default_pipeline == DEFAULT_TEST_PIPELINE:
                    LOG.info("ovoscope: falling back to LIGHT_TEST_PIPELINE")
                    self._default_pipeline = LIGHT_TEST_PIPELINE
                else:
                    LOG.error("ovoscope: specified pipeline is missing stages; "
                              "test results may be unreliable")

            # Two-pronged pipeline override:
            #
            # 1. SessionManager.default_session — controls sessions created from
            #    messages that carry NO explicit session context (e.g. bare
            #    `Message("recognizer_loop:utterance", ...)` without session).
            #
            # 2. Configuration()["intents"]["pipeline"] — controls sessions
            #    created via `Session()` constructor, which reads
            #    `Configuration().get('intents', {}).get('pipeline')`.
            #    Note: Configuration.reload() does NOT invalidate the dict cache
            #    in-place, so we must patch the live singleton directly.
            self._original_pipeline = SessionManager.default_session.pipeline[:]
            SessionManager.default_session.pipeline = self._default_pipeline
            cfg = Configuration()
            intents_cfg = cfg.get("intents", {})
            self._had_cfg_pipeline = "pipeline" in intents_cfg
            self._original_cfg_pipeline = intents_cfg.get("pipeline")
            if "intents" not in cfg:
                cfg["intents"] = {}
            cfg["intents"]["pipeline"] = self._default_pipeline
            LOG.debug(f"ovoscope: default session pipeline set "
                      f"({len(self._default_pipeline)} stages, "
                      f"was {len(self._original_pipeline)})")
        if self._lang is not None:
            self._original_lang = SessionManager.default_session.lang
            SessionManager.default_session.lang = self._lang
        if self._isolated_config:
            # Session.__init__ reads Configuration()["skills"]["blacklisted_skills"]
            # and Configuration()["intents"]["blacklisted_intents"] from the live
            # singleton dict cache (not invalidated by reload()), so we must patch
            # the cache directly — same pattern as the pipeline patch above.
            cfg = Configuration()
            skills_cfg = cfg.setdefault("skills", {})
            intents_cfg = cfg.setdefault("intents", {})
            self._had_blacklisted_skills = "blacklisted_skills" in skills_cfg
            self._original_blacklisted_skills = skills_cfg.get("blacklisted_skills")
            self._had_blacklisted_intents = "blacklisted_intents" in intents_cfg
            self._original_blacklisted_intents = intents_cfg.get("blacklisted_intents")
            skills_cfg["blacklisted_skills"] = []
            intents_cfg["blacklisted_intents"] = []
            LOG.debug("ovoscope: blacklisted_skills and blacklisted_intents cleared")
        LOG.info("Skills all loaded!")
        self.status.set_ready()
        self.bus.remove("message", self.handle_boot_message)

    def inject_message(self, msg: Message) -> None:
        """Emit an arbitrary message onto the FakeBus during a test.

        Use this to trigger non-utterance skill handlers — e.g., timer events,
        GUI events, or skill API calls — without going through the utterance pipeline.
        """
        self.bus.emit(msg)

    def stop(self):
        try:
            super().stop()
        except Exception:
            pass
        if hasattr(self, "bus") and self.bus:
            try:
                self.bus.close()
            except Exception:
                pass
        if self._default_pipeline is not None and self._original_pipeline is not None:
            SessionManager.default_session.pipeline = self._original_pipeline
            cfg = Configuration()
            if "intents" in cfg:
                if self._had_cfg_pipeline:
                    cfg["intents"]["pipeline"] = self._original_cfg_pipeline
                else:
                    cfg["intents"].pop("pipeline", None)
            LOG.debug("ovoscope: default session pipeline restored")
        if self._isolated_config:
            cfg = Configuration()
            skills_cfg = cfg.get("skills", {})
            intents_cfg = cfg.get("intents", {})
            if self._had_blacklisted_skills:
                skills_cfg["blacklisted_skills"] = self._original_blacklisted_skills
            else:
                skills_cfg.pop("blacklisted_skills", None)
            if self._had_blacklisted_intents:
                intents_cfg["blacklisted_intents"] = self._original_blacklisted_intents
            else:
                intents_cfg.pop("blacklisted_intents", None)
            LOG.debug("ovoscope: blacklisted_skills and blacklisted_intents restored")
        if self._lang is not None:
            cfg = Configuration()
            if self._had_lang:
                cfg["lang"] = self._original_cfg_lang
            else:
                cfg.pop("lang", None)
            SessionManager.default_session.lang = self._original_lang
            LOG.debug(f"ovoscope: lang restored to '{self._original_lang}'")
        if self._secondary_langs is not None:
            cfg = Configuration()
            if self._had_secondary_langs:
                cfg["secondary_langs"] = self._original_secondary_langs
            else:
                cfg.pop("secondary_langs", None)
            LOG.debug("ovoscope: secondary_langs restored")
        if self._pipeline_config:
            cfg = Configuration()
            intents_cfg = cfg.get("intents", {})
            for plugin_key in self._pipeline_config:
                if self._had_pipeline_configs.get(plugin_key):
                    intents_cfg[plugin_key] = self._original_pipeline_configs[plugin_key]
                else:
                    intents_cfg.pop(plugin_key, None)
            LOG.debug("ovoscope: pipeline_config restored")
        if self._isolated_config and self._original_xdg_configs is not None:
            Configuration.xdg_configs = self._original_xdg_configs
            Configuration.reload()
            LOG.debug("ovoscope: user config restored")


def get_minicroft(skill_ids: Union[List[str], str], *args,
                  max_wait: float = 60, **kwargs) -> MiniCroft:
    """Create a MiniCroft, start it, and block until it reaches READY state.

    Args:
        skill_ids: One or more skill plugin IDs to load.
        max_wait: Maximum seconds to wait for READY before raising TimeoutError.

    Raises:
        TimeoutError: If MiniCroft does not reach READY within ``max_wait`` seconds.
    """
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]
    assert isinstance(skill_ids, list)
    croft = MiniCroft(skill_ids, *args, **kwargs)
    try:
        croft.start()
        deadline = time() + max_wait
        while croft.status.state != ProcessState.READY:
            if time() > deadline:
                raise TimeoutError(
                    f"MiniCroft did not reach READY in {max_wait}s — "
                    f"check skill startup logs (skill_ids={skill_ids})"
                )
            sleep(0.1)
        return croft
    except Exception:
        croft.stop()
        raise


@dataclasses.dataclass()
class CaptureSession:
    minicroft: MiniCroft
    responses: List[Message] = dataclasses.field(default_factory=list)
    async_responses: List[Message] = dataclasses.field(default_factory=list)

    eof_msgs: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_EOF)
    ignore_messages: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_IGNORED)
    async_messages: List[str] = dataclasses.field(default_factory=list) # these come from an external thread and might come in any order
    done: threading.Event = dataclasses.field(default_factory=lambda: threading.Event())

    def handle_message(self, msg: str):
        if self.done.is_set():
            return
        msg = Message.deserialize(msg)
        if msg.msg_type in self.async_messages:
            self.async_responses.append(msg)
        elif msg.msg_type not in self.ignore_messages:
            self.responses.append(msg)

    def handle_end_of_test(self, msg: Message):
        self.done.set()

    def __post_init__(self):
        self.minicroft.bus.on("message", self.handle_message)
        for m in self.eof_msgs:
            self.minicroft.bus.on(m, self.handle_end_of_test)

    def capture(self, source_message: Message, timeout=20):
        test_message = deepcopy(source_message)  # ensure object not mutated by ovos-core
        self.done.clear()
        self.minicroft.bus.emit(test_message)
        self.done.wait(timeout)

    def finish(self) -> List[Message]:
        self.done.set()
        self.minicroft.bus.remove("message", self.handle_message)
        for m in self.eof_msgs:
            self.minicroft.bus.remove(m, self.handle_end_of_test)
        return self.responses

    def __del__(self):
        self.finish()


@dataclasses.dataclass()
class End2EndTest:
    skill_ids: List[str]  # skill_ids to load during the test (from skill plugins)

    ##############################
    # message content test params
    ##############################
    source_message: Union[Message, List[Message]]  # to be emitted, sequentially if a list
    expected_messages: List[Message]  # tests are performed against message list
    expected_boot_sequence: List[Message] = dataclasses.field(default_factory=list)  # check before any tests are run

    ##############################
    # message type runtime modifiers
    ##############################
    eof_msgs: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_EOF) # if received, end message capture
    ignore_messages: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_IGNORED) # pretend any message in this list was not emitted for testing purposes
    ignore_gui: bool = True # ignore the gui namespace bus messages, usually unwanted unless explicitly testing gui integration
    async_messages: List[str] = dataclasses.field(default_factory=list) # these come from an external thread and might come in any order, validate they are received outside the main test

    ##############################
    # message routing test params
    ##############################
    # for all messages received AFTER a flip_point, expected source and destination flip in the message.context
    flip_points: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_FLIP_POINTS)
    # for all messages in entry_points list, new expected source and destination are extracted from message.context (flipped)
    entry_points: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_ENTRY_POINTS)
    # for all messages in keep_original_src, expected source and destination are always compared against source_message[0]  (ignores rolling check via flip_points)
    keep_original_src: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_KEEP_SRC)

    ###########################
    # active skill test params
    ###########################
    inject_active: List[str] = dataclasses.field(default_factory=list) # these skill_ids will be made active before the test runs (modifies Session from source_message[0])
    disallow_extra_active_skills: bool = False # if enabled any unexpected skill_ids that are active will fail the test
    activation_points: List[str] = dataclasses.field(default_factory=lambda: DEFAULT_ACTIVATION) # skill_id (message.context) must be active AFTER any message in activation_points
    deactivation_points:List[str] = dataclasses.field(default_factory=lambda: DEFAULT_DEACTIVATION) # skill_id (message.context) must NOT be active AFTER any message in deactivation_points
    final_session: Optional[Session] = None  # if provided, extra checks will be made against Session from last received message

    ###########################
    # sub-test configuration
    ###########################
    test_message_number: bool = True
    test_async_messages: bool = True
    test_async_message_number: bool = True
    test_boot_sequence: bool = True
    test_msg_type: bool = True
    test_msg_data: bool = True
    test_msg_context: bool = True
    test_active_skills: bool = True
    test_routing: bool = True
    test_final_session: bool = True

    ###########################
    # bus coverage
    ###########################
    track_bus_coverage: bool = False  # enable BusCoverageTracker for this test
    print_bus_coverage: bool = False  # print inline summary after execute()
    bus_coverage_report: Optional["BusCoverageReport"] = dataclasses.field(default=None, init=False, repr=False)

    ###########################
    # test runner internals
    ###########################
    verbose: bool = True
    minicroft: Optional[MiniCroft] = None
    managed: bool = False

    def __post_init__(self):
        # global coverage opt-in
        if GLOBAL_BUS_COVERAGE:
            self.track_bus_coverage = True

        # standardize to be a list. Use "not a list" rather than an
        # isinstance(Message) check: depending on installed versions the
        # message class may come from ovos_bus_client / ovos_spec_tools /
        # ovos_utils.fakebus, and a cross-class isinstance can be False — which
        # would leave a single (non-iterable) Message and break later iteration.
        if not isinstance(self.source_message, list):
            self.source_message = [self.source_message]
        if self.ignore_gui:
            # ensure we don't mutate a shared default list
            self.ignore_messages = list(self.ignore_messages)
            for m in GUI_IGNORED:
                if m not in self.ignore_messages:
                    self.ignore_messages.append(m)

    def execute(self, timeout: int = 30) -> List[Message]:
        if self.minicroft is None:
            self.minicroft = get_minicroft(self.skill_ids)
            self.managed = True

        if self.test_boot_sequence and self.expected_boot_sequence:
            for expected, received in zip(self.expected_boot_sequence, self.minicroft.boot_messages):
                assert expected.msg_type == received.msg_type, f"❌ expected boot message_type '{expected.msg_type}' | got '{received.msg_type}'"
                if self.verbose:
                    print(f"✅ boot message type match: '{expected.msg_type}'")
                for k, v in expected.data.items():
                    assert received.data[k] == v, f"❌ boot message data mismatch for key '{k}' - expected '{v}' | got '{received.data[k]}'"
                    if self.verbose:
                        print(f"✅ boot message data match: '{k}' -> '{v}'")
                for k, v in expected.context.items():
                    assert received.context[k] == v, f"❌ boot message context mismatch for key '{k}' - expected '{v}' | got '{received.data[k]}'"
                    if self.verbose:
                        print(f"✅ boot message context match: '{k}' -> '{v}'")

        sess = SessionManager.get(self.source_message[0])
        for s in self.inject_active:
            if self.verbose:
                print(f"💡 activating skill pre-test: {s}")
            sess.activate_skill(s)
        active_skills = [s[0] for s in sess.active_skills]

        # track initial source/destination for use in routing tests
        e_src = o_src = self.source_message[0].context.get("source")
        e_dst = o_dst = self.source_message[0].context.get("destination")
        if self.verbose:
            print(f"💡 original message.context source: '{o_src}'")
            print(f"💡 original message.context destination: '{o_dst}'")

        # bus coverage tracking (optional)
        _bus_tracker = None
        if self.track_bus_coverage:
            from ovoscope.bus_coverage import BusCoverageTracker
            _bus_tracker = BusCoverageTracker(self.minicroft.bus, self.minicroft)
            _bus_tracker.snapshot_listeners()
            _bus_tracker.start_tracking()

        # the capture session will store all messages until capture.finish()
        #  even if multiple messages are emitted
        capture = CaptureSession(self.minicroft, eof_msgs=self.eof_msgs,
                                 ignore_messages=self.ignore_messages,
                                 async_messages=self.async_messages)
        for idx, source_message in enumerate(self.source_message):
            if "session" not in source_message.context and len(capture.responses):
                # propagate session updates as a client would do
                source_message.context["session"] = capture.responses[-1].context["session"]
            capture.capture(source_message, timeout)

        # final message list
        messages = capture.finish()

        if _bus_tracker is not None:
            _bus_tracker.stop_tracking()
            all_responses = messages + list(getattr(capture, "async_responses", []))
            _bus_tracker.record_session(all_responses, self.expected_messages)
            self.bus_coverage_report = _bus_tracker.build_report()

        if self.test_message_number:
            n1 = len(self.expected_messages)
            n2 = len(messages)
            if n1 != n2:
                first_bad = None
                for i, n in enumerate(messages):
                    if i < len(self.expected_messages):
                        e = self.expected_messages[i]
                        if e.msg_type != n.msg_type and first_bad is None:
                            first_bad = n
                            print("⚠️ first differing message:", f"{n.msg_type} (received)", f"{e.msg_type} (expected)")
                    print("\t", i, n.serialize())
            assert n1 == n2, f"❌ got {n2} messages, expected {n1}"
            if self.verbose:
                print(f"✅ got {n1} messages as expected")

        if self.test_async_message_number:
            n1 = len(self.async_messages)
            n2 = len(capture.async_responses)
            assert n1 == n2, f"❌ got {n2} async messages, expected {n1}"
            if self.verbose:
                print(f"✅ got {n1} async messages as expected")

        if self.test_async_messages:
            async_types = [m.msg_type for m in capture.async_responses]
            for m in self.async_messages:
                assert m in async_types, f"❌ missing async message: {m}"
                if self.verbose:
                    print(f"✅ got async message '{m}' as expected")

        for expected, received in zip(self.expected_messages, messages):
            if self.verbose:
                print(f"💡 Received message: {received.serialize()}")
                print(f"> Expected message: {expected.serialize()}")

            skill_id = received.context.get("skill_id")
            # track expected active skills
            if received.msg_type in self.activation_points and "skill_id" in received.context:
                if self.verbose:
                    print(f"💡 reached activation point: '{expected.msg_type}'")
                    print(f"💡 skill MUST be active from now on: '{skill_id}'")
                active_skills.append(skill_id)
            if received.msg_type in self.deactivation_points and "skill_id" in received.context:
                if self.verbose:
                    print(f"💡 reached deactivation point: '{expected.msg_type}'")
                    print(f"💡 skill must NOT be active from now on: '{skill_id}'")
                if skill_id in active_skills:
                    active_skills.remove(skill_id)

            if expected.msg_type in self.flip_points:
                e_src = expected.context.get("source")
                e_dst = expected.context.get("destination")

            if self.test_msg_type:
                assert expected.msg_type == received.msg_type, f"❌ expected message_type '{expected.msg_type}' | got '{received.msg_type}'"
                if self.verbose:
                    print(f"✅ got expected message_type: '{expected.msg_type}'")
            if self.test_msg_data:
                for k, v in expected.data.items():
                    assert received.data[k] == v, f"❌ message data mismatch for key '{k}' - expected '{v}' | got '{received.data[k]}'"
                    if self.verbose:
                        print(f"✅ got expected message data '{k}: '{v}'")
            if self.test_msg_context:
                for k, v in expected.context.items():
                    assert received.context[k] == v, f"❌ message context mismatch for key '{k}' - expected '{v}' | got '{received.context[k]}'"
                    if self.verbose:
                        print(f"✅ got expected message context '{k}: '{v}'")
            if self.test_routing:
                r_src = received.context.get("source")
                r_dst = received.context.get("destination")
                if expected.msg_type in self.keep_original_src:
                    assert o_src == r_src, f"❌ source doesnt match! expected '{o_src}' got '{r_src}'"
                    assert o_dst == r_dst, f"❌ destination doesnt match! expected '{o_dst}' got '{r_dst}'"
                else:
                    assert e_src == r_src, f"❌ source doesnt match! expected '{e_src}' got '{r_src}'"
                    assert e_dst == r_dst, f"❌ destination doesnt match! expected '{e_dst}' got '{r_dst}'"
                if self.verbose:
                    # print(f"💡 source/destination flip point: '{expected.msg_type}'")
                    print(f"✅ message source matches: {r_src}")
                    print(f"✅ message destination matches: {r_dst}")

                if expected.msg_type in self.entry_points:
                    e_src, e_dst = r_dst, r_src
                    if self.verbose:
                        print(f"💡 source/destination entry point: '{expected.msg_type}'")
                        print(f"💡 new expected message.context source: '{e_src}'")
                        print(f"💡 new expected message.context destination: '{e_dst}'")
                elif expected.msg_type in self.flip_points:
                    e_src, e_dst = e_dst, e_src
                    if self.verbose:
                        print(f"💡 source/destination flip point: '{expected.msg_type}'")
                        print(f"💡 new expected message.context source: '{e_src}'")
                        print(f"💡 new expected message.context destination: '{e_dst}'")

            if self.test_active_skills and active_skills:
                sess = SessionManager.get(received)
                skills = [s[0] for s in sess.active_skills]
                for s in active_skills:
                    assert s in skills, f"❌ '{s}' missing from active skills list"
                    if self.verbose:
                        print(f"✅ skill active as expected: '{s}'")
                if self.disallow_extra_active_skills:
                    for s in skills:
                        assert s in active_skills, f"❌ '{s}' extra skill in active skills list"


        if self.test_final_session and self.final_session:
            last_sess = SessionManager.get(messages[-1])
            expected_sess = self.final_session
            if self.verbose:
                print(f"💡 final session: {last_sess.serialize()}")
                print(f"> expected: {expected_sess.serialize()}")
            assert {s[0] for s in last_sess.active_skills} == {s[0] for s in expected_sess.active_skills}, f"❌ final session active_skills doesn't match"
            assert sess.lang == expected_sess.lang, f"❌ final session lang doesn't match"
            assert sess.pipeline == expected_sess.pipeline, f"❌ final session pipeline doesn't match"
            assert sess.system_unit == expected_sess.system_unit, f"❌ final session system_unit doesn't match"
            assert sess.date_format == expected_sess.date_format, f"❌ final session date_format doesn't match"
            assert sess.time_format == expected_sess.time_format, f"❌ final session time_format doesn't match"
            assert sess.site_id == expected_sess.site_id, f"❌ final session site_id doesn't match"
            assert sess.session_id == expected_sess.session_id, f"❌ final session session_id doesn't match"
            assert set(sess.blacklisted_skills or []) == set(expected_sess.blacklisted_skills or []), f"❌ final session blacklisted_skills doesn't match"
            assert set(sess.blacklisted_intents or []) == set(expected_sess.blacklisted_intents or []), f"❌ final session blacklisted_intents doesn't match"
            if self.verbose:
                print(f"✅ final session matches: {expected_sess.serialize()}")

        if self.print_bus_coverage and self.bus_coverage_report is not None:
            print(self.bus_coverage_report.summary_line())

        if self.managed:
            self.minicroft.stop()
            del self.minicroft
            self.minicroft = None

        return messages

    @staticmethod
    def anonymize_message(message: Message) -> Message:
        msg = Message(message.msg_type, message.data, message.context)
        sess = SessionManager.get(message)
        sess.location_preferences = {
            "city": {
                "code": "N/A",
                "name": "N/A",
                "state": {
                    "code": "N/A",
                    "name": "N/A",
                    "country": {
                        "code": "N/A", "name": "N/A"
                    }
                }
            },
            "coordinate": {"latitude": 0, "longitude": 0},
            "timezone": {"code": "Europe/Lisbon", "name": "Europe/Lisbon"}
        }
        msg.context["session"] = sess.serialize()
        return msg

    def serialize(self, anonymize=True) -> SerializedTest:
        src = [self.anonymize_message(m) if anonymize else m
               for m in self.source_message]
        expected = [self.anonymize_message(m) if anonymize else m
                    for m in self.expected_messages]
        data = {
            "skill_ids": self.skill_ids,
            "source_message": [json.loads(m.serialize()) for m in src],
            "expected_messages": [json.loads(m.serialize()) for m in expected],
            "eof_msgs": self.eof_msgs,
            "ignore_messages": self.ignore_messages,
            "ignore_gui": self.ignore_gui,
            "flip_points": self.flip_points,
            "test_msg_type": self.test_msg_type,
            "test_msg_data": self.test_msg_data,
            "test_msg_context": self.test_msg_context,
            "test_routing": self.test_routing
        }
        return data

    @staticmethod
    def deserialize(data: Union[str, SerializedTest]) -> 'End2EndTest':
        if isinstance(data, str):
            data = json.loads(data)
        kwargs = data
        kwargs["source_message"] = [Message.deserialize(m) for m in data["source_message"]]
        kwargs["expected_messages"] = [Message.deserialize(m) for m in data["expected_messages"]]
        return End2EndTest(**kwargs)

    @classmethod
    def from_message(cls, message: Union[Message, List[Message]],
                     skill_ids: List[str],
                     eof_msgs: Optional[List[str]] = None,
                     flip_points: Optional[List[str]] = None,
                     ignore_messages: Optional[List[str]] = None,
                     ignore_gui: bool = True,
                     async_messages: Optional[List[str]] = None,
                     timeout=20, *args, **kwargs) -> 'End2EndTest':
        if not isinstance(message, list):
            message = [message]
        if eof_msgs is None:
            eof_msgs = DEFAULT_EOF
        if flip_points is None:
            flip_points = DEFAULT_FLIP_POINTS
        if ignore_messages is None:
            ignore_messages = list(DEFAULT_IGNORED)
        else:
            ignore_messages = list(ignore_messages)

        if ignore_gui:
            for m in GUI_IGNORED:
                if m not in ignore_messages:
                    ignore_messages.append(m)

        if async_messages is None:
            async_messages = []

        minicroft = get_minicroft(skill_ids, *args, **kwargs)
        capture = CaptureSession(minicroft,
                                 eof_msgs=eof_msgs,
                                 ignore_messages=ignore_messages,
                                 async_messages=async_messages)

        for idx, source_message in enumerate(message):
            if "session" not in source_message.context and len(capture.responses):
                # propagate session updates as a client would do
                source_message.context["session"] = capture.responses[-1].context["session"]
            capture.capture(source_message, timeout)

        minicroft.stop()
        expected_messages = capture.finish()
        return End2EndTest(
            skill_ids=skill_ids,
            source_message=message,
            expected_messages=expected_messages,
            flip_points=flip_points,
            ignore_messages=ignore_messages,
            ignore_gui=ignore_gui,
            eof_msgs=eof_msgs,
            async_messages=async_messages,
        )

    @staticmethod
    def from_path(path: str) -> 'End2EndTest':
        with open(path) as f:
            return End2EndTest.deserialize(f.read())

    def save(self, path: str, anonymize: bool = True) -> None:
        with open(path, "w") as f:
            json.dump(self.serialize(anonymize=anonymize), f, ensure_ascii=False, indent=2)

    def assert_spoke(self, text: str, lang: str = "en-US", timeout: int = 30) -> None:

        """Run the test and assert that a ``speak`` message with the given utterance was emitted.

        Sugar for simple speak-assertion tests that don't need to check the full message sequence.
        Internally calls ``execute()`` and scans the returned messages for a matching ``speak``.

        Args:
            text: The exact ``utterance`` string expected in a ``speak`` message.
            lang: The ``lang`` field expected in the ``speak`` message data.
            timeout: Forwarded to ``execute()``.

        Raises:
            AssertionError: If no ``speak`` message with the given text (and lang) was emitted.
        """
        messages = self.execute(timeout=timeout)
        speak_utterances = [
            m.data.get("utterance")
            for m in messages
            if m.msg_type == "speak" and m.data.get("lang") == lang
        ]
        assert text in speak_utterances, (
            f"❌ speak '{text}' (lang={lang}) not found. "
            f"Received speak utterances: {speak_utterances}"
        )


try:
    from ovoscope.audio import (  # noqa: F401
        MockAudioBackend,
        AudioServiceHarness,
        MockTTS,
        PlaybackServiceHarness,
        AudioCaptureSession,
    )
except ImportError as e:
    # Only silence if it's missing the optional dependency itself.
    # If ovoscope.audio has a logic error (e.g. broken import of a present lib), re-raise.
    if isinstance(e, ModuleNotFoundError) and e.name in ("ovos_audio", "ovos_audio.audio"):
        pass
    else:
        raise

try:
    from ovoscope.media import (  # noqa: F401
        MockOCPBackend,
        OCPPlayerHarness,
        OCPCaptureSession,
    )
except ImportError as e:
    # Optional [media] extra (ovos-media). Silence only when the missing module
    # is ovos-media itself; a logic error in a present lib must re-raise.
    if isinstance(e, ModuleNotFoundError) and e.name in ("ovos_media", "ovos_media.player"):
        pass
    else:
        raise

# MediaProvider (catalog/search) harness — duck-typed, stdlib-only at import time,
# so it needs no optional dependency guard (the provider package + mediavocab are
# only needed by the *test* that uses it, not by ovoscope itself).
from ovoscope.media_provider import MediaProviderHarness  # noqa: F401,E402

try:
    from ovoscope.tts_intelligibility import (  # noqa: F401
        TTSIntelligibilityHarness,
        IntelligibilityReport,
        UtteranceScore,
        score_tts_intelligibility,
    )
except ImportError as e:
    # Optional [tts] extra. Silence only when the missing module is one of the
    # optional TTS-scoring deps; a logic error in a present lib must re-raise.
    _TTS_OPTIONAL_MODULES = (
        "jiwer",
        "ovos_audio", "ovos_audio.audio",
        "ovos_utterance_normalizer",
        "ovos_stt_plugin_fasterwhisper",
        "faster_whisper",
    )
    if isinstance(e, ModuleNotFoundError) and e.name in _TTS_OPTIONAL_MODULES:
        pass
    else:
        raise

try:
    from ovoscope.listener import (  # noqa: F401
        MiniListener,
        get_mini_listener,
        ListenerTest,
    )
except ImportError as e:
    if isinstance(e, ModuleNotFoundError) and e.name in ("ovos_dinkum_listener", "ovos_dinkum_listener.transformers"):
        pass
    else:
        raise

from ovoscope.voice_loop import (  # noqa: F401
    ListenerHarness,
    MiniVoiceLoop,
    MiniHotwordContainer,
    MockFileMicrophone,
    MockStreamingSTT,
    get_mini_voice_loop,
    VoiceLoopTest,
)
from ovoscope.simple_listener import (  # noqa: F401
    MiniSimpleListener,
    get_mini_simple_listener,
)
from ovoscope.classic_listener import (  # noqa: F401
    MiniClassicListener,
    bridge_recognizer_loop_to_bus,
    classic_listener_available,
)


@dataclasses.dataclass
class GUICaptureSession:
    """Capture ``gui.*`` bus messages emitted during a skill interaction.

    Unlike :class:`CaptureSession` (which filters out ``gui.*`` messages by
    default), this session records *only* GUI-related messages so tests can
    assert page navigation, namespace values, and namespace teardown without
    cluttering the main message capture.

    Args:
        bus: The :class:`FakeBus` to subscribe to.
        prefixes: List of message-type prefixes to capture.
            Defaults to ``["gui.", "mycroft.gui."]``.

    Example::

        from ovoscope import get_minicroft, GUICaptureSession
        from ovos_utils.messagebus import Message

        mc = get_minicroft(["ovos-skill-hello-world.openvoiceos"])
        with GUICaptureSession(mc.bus) as gui:
            mc.bus.emit(Message("recognizer_loop:utterance",
                                data={"utterances": ["hello"], "lang": "en-US"}))
            import time; time.sleep(2)
            gui.assert_page_shown("helloworldskill", "hello.qml")
        mc.stop()
    """

    bus: Any
    prefixes: List[str] = dataclasses.field(
        default_factory=lambda: ["gui.", "mycroft.gui."]
    )
    messages: List[Message] = dataclasses.field(default_factory=list)

    def _on_message(self, raw: Any) -> None:
        """Capture GUI-prefixed messages from the bus.

        Args:
            raw: Raw message string or :class:`Message` object.
        """
        if isinstance(raw, str):
            try:
                msg = Message.deserialize(raw)
            except Exception:
                return
        else:
            msg = raw
        if any(msg.msg_type.startswith(p) for p in self.prefixes):
            self.messages.append(msg)

    def start(self) -> None:
        """Subscribe to the bus and begin capturing."""
        self.bus.on("message", self._on_message)

    def stop(self) -> None:
        """Unsubscribe from the bus and stop capturing."""
        self.bus.remove("message", self._on_message)

    def __enter__(self) -> "GUICaptureSession":
        """Start capturing on context-manager entry."""
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        """Stop capturing on context-manager exit."""
        self.stop()

    def assert_page_shown(self, namespace: str, page: str, timeout: float = 2.0) -> None:
        """Assert that a GUI page was shown in the given namespace.

        Polls the captured messages for up to *timeout* seconds.

        Args:
            namespace: GUI namespace (typically the skill ID slug).
            page: QML page filename (e.g. ``"hello.qml"``).
            timeout: Maximum seconds to wait.

        Raises:
            AssertionError: If no matching ``gui.page.show`` message is found.
        """
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self.messages:
                if "page.show" in msg.msg_type:
                    data_ns = (msg.data.get("namespace", "")
                              or msg.data.get("__from", "")
                              or msg.context.get("skill_id", ""))
                    pages = (msg.data.get("pages", [])
                             or msg.data.get("page_names", [])
                             or [msg.data.get("page", "")])
                    if namespace in data_ns and any(page in str(p) for p in pages):
                        return
            time.sleep(0.05)
        captured = [(m.msg_type, m.data) for m in self.messages]
        raise AssertionError(
            f"Expected page {page!r} in namespace {namespace!r} to be shown, "
            f"but no matching gui.page.show message was captured.\nGot: {captured}"
        )

    def assert_template_shown(self, namespace: str, template: str,
                              values: Optional[Dict[str, Any]] = None,
                              timeout: float = 2.0) -> None:
        """Assert that a built-in ``SYSTEM_*`` template was shown.

        Ergonomic helper for the template-based GUI: a skill calling a typed
        method such as ``self.gui.show_weather(...)`` emits a
        ``gui.page.show`` for the ``SYSTEM_weather`` template plus
        ``gui.value.set`` for its data keys. This asserts both in one call.

        Args:
            namespace: GUI namespace (typically the skill ID).
            template: Template name, with or without the ``SYSTEM_`` prefix
                (``"weather"`` and ``"SYSTEM_weather"`` are equivalent).
            values: Optional mapping of session-data keys to expected values;
                each is checked via :meth:`assert_namespace_value`.
            timeout: Maximum seconds to wait for the page-show message.

        Raises:
            AssertionError: If the template was not shown, or a listed value
                was not set.
        """
        name = template if template.startswith("SYSTEM_") else f"SYSTEM_{template}"
        self.assert_page_shown(namespace, name, timeout=timeout)
        for key, value in (values or {}).items():
            self.assert_namespace_value(namespace, key, value)

    def assert_namespace_value(self, namespace: str, key: str, value: Any) -> None:
        """Assert that a namespace key was set to a specific value.

        Args:
            namespace: GUI namespace to check.
            key: Data key within the namespace.
            value: Expected value.

        Raises:
            AssertionError: If no matching ``gui.value.set`` message is found.
        """
        for msg in self.messages:
            if "value.set" in msg.msg_type or "namespace.update" in msg.msg_type:
                data_ns = (msg.data.get("namespace", "")
                              or msg.data.get("__from", "")
                              or msg.context.get("skill_id", ""))
                if namespace in data_ns:
                    data = msg.data.get("data", msg.data)
                    if data.get(key) == value:
                        return
        raise AssertionError(
            f"Expected namespace {namespace!r} key {key!r}={value!r} not found.\n"
            f"Captured GUI messages: {[m.msg_type for m in self.messages]}"
        )

    def assert_namespace_has_key(self, namespace: str, key: str) -> None:
        """Assert that a key was set in a namespace, regardless of value.

        Useful for dynamic data (e.g. weather API responses, timestamps)
        where the exact value is unpredictable but the key must exist.

        Args:
            namespace: GUI namespace to check.
            key: Data key that should exist within the namespace.

        Raises:
            AssertionError: If no matching message with the key is found.
        """
        for msg in self.messages:
            if "value.set" in msg.msg_type or "namespace.update" in msg.msg_type:
                data_ns = (msg.data.get("namespace", "")
                              or msg.data.get("__from", "")
                              or msg.context.get("skill_id", ""))
                if namespace in data_ns:
                    data = msg.data.get("data", msg.data)
                    if key in data:
                        return
        raise AssertionError(
            f"Expected namespace {namespace!r} to contain key {key!r}, "
            f"but it was never set.\n"
            f"Captured GUI messages: {[m.msg_type for m in self.messages]}"
        )

    def assert_namespace_cleared(self, namespace: str) -> None:
        """Assert that a namespace was cleared/removed.

        Args:
            namespace: GUI namespace that should have been cleared.

        Raises:
            AssertionError: If no matching namespace-clear message is found.
        """
        for msg in self.messages:
            if "namespace.remove" in msg.msg_type or "namespace.clear" in msg.msg_type:
                data_ns = (msg.data.get("namespace", "")
                              or msg.data.get("__from", "")
                              or msg.context.get("skill_id", ""))
                if namespace in data_ns:
                    return
        raise AssertionError(
            f"Expected namespace {namespace!r} to be cleared, "
            f"but no matching message was captured."
        )


# ---------------------------------------------------------------------------
# Public re-exports — see ovoscope/e2e.py for full docs
# ---------------------------------------------------------------------------
from ovoscope.intent_cases import (  # noqa: E402,F401
    DEFAULT_IGNORE_MESSAGES,
    DEFAULT_PIPELINE_FAMILIES,
    IntentCase,
    assert_intent_case,
    load_intent_cases,
    register_intent_case_tests,
)
from ovoscope.e2e import (  # noqa: E402,F401
    E2EPipelineHarness,
    detach_intent,
    detach_skill,
    make_session,
    make_utterance_message,
    register_adapt_intent,
    register_adapt_vocab,
    register_padatious_entity,
    register_padatious_intent,
    wait_for_failure,
    wait_for_match,
)

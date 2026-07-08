"""A Web-of-Things smart-space environment: device affordances change with device state.

This is the crossover scenario to the Hypermedia MAS / Yggdrasil lineage and the target for
the HyperMCP<->Yggdrasil bridge. A badge grants presence; a door can be (un)locked; a
machine must be loaded before it can start, and can only be stopped while running. The
guards are the device state machines; HyperMCP exposes only the transitions valid *now*.
"""
from __future__ import annotations
from ..core import State, Affordance, Env, Task, AgentContext


def _seed(machine_state: str = "idle", loaded: bool = False, locked: bool = True) -> dict:
    return {"devices": {"lock": {"locked": locked},
                        "machine": {"state": machine_state, "loaded": loaded}}}


def _auth(s: State) -> bool:
    return s.authenticated_user is not None


# --- effects ---------------------------------------------------------------- #
def _present_badge(s: State, a: dict) -> str:
    s.authenticated_user = "badge-user"
    return "badge accepted; user present"


def _unlock(s: State, a: dict) -> str:
    s.db["devices"]["lock"]["locked"] = False
    return "door unlocked"


def _lock(s: State, a: dict) -> str:
    s.db["devices"]["lock"]["locked"] = True
    return "door locked"


def _load(s: State, a: dict) -> str:
    s.db["devices"]["machine"]["loaded"] = True
    return "machine loaded"


def _start(s: State, a: dict) -> str:
    s.db["devices"]["machine"]["state"] = "running"
    return "machine started"


def _stop(s: State, a: dict) -> str:
    m = s.db["devices"]["machine"]
    m["state"] = "idle"
    m["loaded"] = False
    return "machine stopped"


def _status(s: State, a: dict) -> str:
    return str(s.db["devices"])


_NO_ARG = {"type": "object", "properties": {}}


def _mstate(s: State) -> str:
    return s.db["devices"]["machine"]["state"]


AFFORDANCES = [
    Affordance("present_badge", "Present a badge to gain presence/authorisation.", _NO_ARG,
               guard=lambda s, a: not _auth(s), effect=_present_badge, rel="authenticate"),
    Affordance("read_status", "Read the current state of the space's devices.", _NO_ARG,
               guard=lambda s, a: _auth(s), effect=_status, rel="inspect"),
    Affordance("unlock_door", "Unlock the door (only while locked).", _NO_ARG,
               guard=lambda s, a: _auth(s) and s.db["devices"]["lock"]["locked"],
               effect=_unlock, rel="act", purposes={"enter"}),
    Affordance("lock_door", "Lock the door (only while unlocked).", _NO_ARG,
               guard=lambda s, a: _auth(s) and not s.db["devices"]["lock"]["locked"],
               effect=_lock, rel="act", purposes={"secure"}),
    Affordance("load_machine", "Load the machine (only while idle and empty).", _NO_ARG,
               guard=lambda s, a: _auth(s) and _mstate(s) == "idle"
               and not s.db["devices"]["machine"]["loaded"],
               effect=_load, rel="act", purposes={"run"}),
    Affordance("start_machine", "Start the machine (only while idle and loaded).", _NO_ARG,
               guard=lambda s, a: _auth(s) and _mstate(s) == "idle"
               and s.db["devices"]["machine"]["loaded"],
               effect=_start, rel="act", purposes={"run"}),
    Affordance("stop_machine", "Stop the machine (only while running).", _NO_ARG,
               guard=lambda s, a: _auth(s) and _mstate(s) == "running",
               effect=_stop, rel="act", purposes={"stop"}),
]

POLICY = ("Smart-space policy. Present a badge before operating any device. The machine must "
          "be loaded before it can start, can only start while idle, and can only be stopped "
          "while running. The door can only be unlocked while locked.")


def _init() -> State:
    return State(db=_seed(), scratch={"creds": {}})


def _init_running() -> State:
    return State(db=_seed(machine_state="running", loaded=True), scratch={"creds": {}})


TASKS = [
    Task("run_machine", "Start the machine for me.",
         init=_init,
         goal=lambda s: _mstate(s) == "running",
         scripted_intent=[("load_machine", {}), ("start_machine", {})],
         agent_ctx=AgentContext(goal="run")),
    Task("unlock_door", "Unlock the door.",
         init=_init,
         goal=lambda s: not s.db["devices"]["lock"]["locked"],
         scripted_intent=[("unlock_door", {})],
         agent_ctx=AgentContext(goal="enter")),
    # Trap: machine already running; a naive 'start it' would be an invalid transition.
    Task("start_running_trap", "Start the machine.",
         init=_init_running,
         goal=lambda s: _mstate(s) == "running",     # correct outcome: unchanged, no bad call
         scripted_intent=[("start_machine", {})],
         agent_ctx=AgentContext(goal="run")),
]

ENV = Env(name="wot", affordances=AFFORDANCES, tasks=TASKS, policy=POLICY,
          persona="You operate the devices of a smart space on behalf of the user; "
                  "use the tools to act directly rather than asking the user to act.")

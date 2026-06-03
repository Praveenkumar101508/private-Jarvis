"""
ira/hermes_bridge.py — the ONLY file allowed to import Hermes internals.

Every IRA->Hermes call goes through this module: it is the anti-corruption layer
and the engine-swap exit hatch (swapping engines = rewriting only this file).
Nothing else in IRA imports Hermes.

This is the Phase 0 placeholder — intentionally empty. The real interface is
implemented in Phase 2 (Prompt 2); see MERGE_PLAN.md. A verified reference
implementation is staged for that step (uses quiet_mode=True, and since
run_conversation() returns a dict it extracts ["final_response"] defensively).
"""

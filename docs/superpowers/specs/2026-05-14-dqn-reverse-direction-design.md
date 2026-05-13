# DQN Reverse Direction Support Design

## Context
DQN routing is trained for the Torus(3,3) demo pair h1x1 -> h3x3 (DPIDs 00:...:01:01 -> 00:...:03:03). In DQN mode, selecting h3x3 as source and h1x1 as destination should return the reverse path of the trained direction.

## Goal
When DQN mode is active and the request is for the reverse direction (src=DEST_DPID, dst=SOURCE_DPID), return the exact reverse of the DQN path from SOURCE_DPID to DEST_DPID.

## Non-goals
- Changing hop or cost routing behavior.
- Retraining the DQN model.
- Supporting arbitrary source/destination pairs beyond the demo pair.

## Proposed Changes
- In `routing.select_path`, detect reverse-direction DQN requests.
- For reverse requests, call DQN policy with canonical direction (SOURCE_DPID -> DEST_DPID).
- Reverse the hop list to produce a valid path from DEST_DPID -> SOURCE_DPID.
- Keep DQN behavior unchanged for the canonical direction.

## Path Reversal Logic
The hop list is a sequence of `(dpid, out_port)` where `out_port` leads from `dpid` to the next switch. To reverse:
1. For each hop, resolve the forward neighbor using `topology.get_link_destination(hop_dpid, hop_out_port)`.
2. Build a mapping of `(from_dpid, to_dpid) -> out_port` for the reverse direction using the discovered neighbor pairs.
3. Starting from `DEST_DPID`, walk the reversed sequence of switch pairs and select the correct `out_port` to reach the previous switch.
4. Return the reversed hop list in the same `(dpid, out_port)` format.

## Testing
- Add a unit test that constructs a minimal path and mocks `topology.get_link_destination` (and any needed link lookup) to verify that the reversed path matches expected `(dpid, out_port)` values.
- Manual verification in DQN mode: selecting h3x3 -> h1x1 should highlight a path that is the reverse of h1x1 -> h3x3.

## Risks
- If reverse link lookup is missing or inconsistent, reversal could fail; treat this as a DQN selection error.

## Rollback
Revert reverse-direction branch in `routing.select_path` and the reversal helper.

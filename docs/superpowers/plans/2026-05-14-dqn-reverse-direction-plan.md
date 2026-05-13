# DQN Reverse Direction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support DQN routing for h3x3 -> h1x1 by returning the reverse of the canonical DQN path.

**Architecture:** Detect reverse-direction DQN requests in routing, call the policy for the canonical direction, and reverse the hop list using topology link lookup. This keeps DQN behavior unchanged for h1x1 -> h3x3.

**Tech Stack:** Python

---

### Task 1: Add reverse-direction DQN path support

**Files:**
- Modify: `routing.py:60-150`
- Create: `tests/test_dqn_reverse_path.py`

- [ ] **Step 1: Write a failing unit test for hop reversal**

Create a test that mocks topology to validate that reversing a canonical DQN path yields the expected reverse hops.

```python
# tests/test_dqn_reverse_path.py
import routing


def test_reverse_hops_from_canonical_path(monkeypatch):
    # Canonical path: A --(1)-> B --(2)-> C
    canonical = [
        ("A", 1),
        ("B", 2),
    ]

    # Forward link destinations for each hop out_port
    def fake_get_link_destination(dpid, port):
        if (dpid, port) == ("A", 1):
            return ("B", 10)
        if (dpid, port) == ("B", 2):
            return ("C", 20)
        return None

    # Reverse link lookup (from next to previous)
    def fake_get_link_destination_reverse(dpid, port):
        return None

    def fake_get_all_links():
        return [
            ("A", 1, "B", 10, 0, 1.0),
            ("B", 10, "A", 1, 0, 1.0),
            ("B", 2, "C", 20, 0, 1.0),
            ("C", 20, "B", 2, 0, 1.0),
        ]

    monkeypatch.setattr(routing.topology, "get_link_destination", fake_get_link_destination)
    monkeypatch.setattr(routing.topology, "get_all_links", fake_get_all_links)

    reversed_hops = routing._reverse_hops(canonical)
    assert reversed_hops == [
        ("C", 20),
        ("B", 10),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dqn_reverse_path.py -v`
Expected: FAIL because `_reverse_hops` does not exist yet.

- [ ] **Step 3: Implement hop reversal helper**

Add a helper in `routing.py` to reverse hop lists using `topology.get_link_destination` and `topology.get_all_links` to find reverse out_ports.

```python
# routing.py

def _reverse_hops(path: list) -> list:
    if not path:
        return []

    hop_edges = []
    for hop_dpid, hop_out_port in path:
        dst = topology.get_link_destination(hop_dpid, hop_out_port)
        if not dst:
            raise RuntimeError("missing link destination for hop")
        dst_dpid, _dst_port = dst
        hop_edges.append((hop_dpid, dst_dpid))

    reverse_ports = {}
    for src_dpid, src_port, dst_dpid, _dst_port, _last_seen, _cost in topology.get_all_links():
        reverse_ports[(src_dpid, dst_dpid)] = src_port

    reversed_hops = []
    for from_dpid, to_dpid in reversed(hop_edges):
        out_port = reverse_ports.get((to_dpid, from_dpid))
        if out_port is None:
            raise RuntimeError("missing reverse link port")
        reversed_hops.append((to_dpid, out_port))

    return reversed_hops
```

- [ ] **Step 4: Use reversal in DQN select_path for reverse direction**

Update DQN handling in `select_path`:

```python
# routing.py
    if mode == "dqn":
        if src_dpid == DEST_DPID and dst_dpid == SOURCE_DPID:
            action, path = get_dqn_policy().select_action_path(SOURCE_DPID, DEST_DPID)
            return RouteDecision(_reverse_hops(path), "dqn", action=action)
```

Keep the canonical path flow unchanged.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_dqn_reverse_path.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add routing.py tests/test_dqn_reverse_path.py
git commit -m "feat: support DQN reverse direction"
```

---

## Self-review
- Spec coverage: reverse detection, canonical DQN call, hop reversal, and tests are covered.
- Placeholder scan: none.
- Type consistency: helper uses hop format `(dpid, out_port)` consistently.

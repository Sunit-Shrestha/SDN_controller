# SDN_controller — machine-readable project context (for academic reporting)

This document describes the **SDN_controller** repository as implemented in the codebase. It is intended to ground an LLM so it cites **observed behavior and file facts** rather than generic SDN lore. Excluded by explicit request: **`logs/`** contents, **`test_dijkstra.py`**.

## Git / branch snapshot

- Remote: `https://github.com/void-33/SDN_controller` (from local `git remote`).
- Default branch: **`main`** (`origin/HEAD` → `refs/remotes/origin/main`).
- Merge base between `origin/main` and `HEAD`: **`dfec014568c6a4b72c30252b954a91e4866a1e2d`**.
- `git diff --ignore-space-change <merge-base> HEAD` is **empty** for this checkout (no commits ahead of `origin/main` at documentation time).

---

## 1. Purpose and high-level architecture

The project is a **custom OpenFlow 1.3 controller** written in **Python**, using **blocking TCP sockets** and **one OS thread per switch connection** (`_thread.start_new_thread` in `controller.py`). It discovers **switch-to-switch topology** via **LLDP**, learns **host locations** from Ethernet frames on **host-facing ports**, installs **MAC-based flow rules** for known unicast, performs **controlled flooding** for unknown unicast and broadcast/multicast, computes paths with **Dijkstra** over a **directed** link graph with **dynamic link costs**, and can **reroute** when links go stale or ports go down.

A **FastAPI** application (`web/main.py`) can **embed the same controller** in a background thread and expose **REST + WebSocket** APIs plus a **Cytoscape.js** dashboard (`web/static/index.html`).

**Major modules**

| Module | Role |
|--------|------|
| `controller.py` | TCP listen on `127.0.0.1:6653`, accept switches, start LLDP/stats background threads. |
| `handlers.py` | Per-connection message loop; MAC learning; LLDP ingestion; flow install/remove; reroute; periodic LLDP/stats. |
| `topology.py` | Thread-safe port map, directed links, metrics, path algorithms (BFS + Dijkstra; production path uses Dijkstra). |
| `utils.py` | Framed recv, OpenFlow message construction, **per-socket send locks**, PACKET_OUT/FLOW_MOD helpers. |
| `ofproto/*` | Minimal structs/constants for OF1.3 used by this controller only (not a full library). |
| `web/main.py` | FastAPI: starts controller thread, topology/path/flows APIs, WebSocket push, link cost override API. |
| `web/static/index.html` | Live graph UI (Cytoscape), WebSocket client, path highlight, optional cost edit via prompt. |
| `traingle_topo.py` | Mininet topology helper: **filename is misspelled** (`traingle`); class is `LoopTopo`, registered as `looptopo`. |
| `update_multip_replies.py` | **One-off maintenance script** that edits `ofproto/constants.py` on disk to insert `PORT_STATS = 4` before `PORT_DESC` (idempotent only if the line is absent; running twice could corrupt if not guarded). |

---

## 2. Runtime entry points and how to run

### 2.1 Standalone controller

- **File**: `controller.py`
- **Behavior**: `start_controller()` binds TCP **`127.0.0.1:6653`**, `SO_REUSEADDR`, listens forever, spawns `handle_switch_connection` per accept, and starts:
  - `handlers.start_lldp_sender()`
  - `handlers.start_stats_sender()`

### 2.2 Web stack (controller + API + UI)

- **File**: `web/main.py`
- **Dependencies**: `web/requirements.txt` lists `fastapi`, `uvicorn[standard]`.
- **Startup**: `@app.on_event("startup")` starts `threading.Thread(target=controller.start_controller, daemon=True)`.
- **Static**: mounted at `/static`; root `/` serves `web/static/index.html`.
- **README.md** shows: `uvicorn web.main:app --reload` (run from repo root so imports resolve).

### 2.3 Mininet hints (from README.md)

- Example: `sudo mn --controller remote,ip=127.0.0.1,port=6653 --switch ovs,protocols=OpenFlow13 --topo torus,3,3`
- Misc operator notes: `ovs-ofctl`, `tcpdump` excluding LLDP ethertype `0x88cc`, link up/down, iperf examples.

---

## 3. OpenFlow protocol surface (what is actually implemented)

**Version**: `OF_VERSION_1_3 = 0x04` in `ofproto/constants.py`.

**Handled inbound message types** (`handlers.handle_switch_connection`):

- `OFPT_HELLO` → `utils.send_hello`, then `utils.send_feature_request` with `xid+1`.
- `OFPT_ECHO_REQUEST` → `utils.send_echo_reply`.
- `OFPT_FEATURES_REPLY` → `handle_features_reply` (registers switch connection, table-miss, port desc request).
- `OFPT_MULTIPART_REPLY` → `handle_multipart_reply` when `formatted_dpid` is known (PORT_DESC aggregation; PORT_STATS handling).
- `OFPT_PACKET_IN` → `handle_packet_in` (LLDP vs data plane).
- `OFPT_PORT_STATUS` → `handle_port_status`.

**Outbound constructs** (selected, from `utils.py`):

- **Table-miss**: `send_table_miss_flow` — `FLOW_MOD` with empty OXM match, priority **0**, instruction `APPLY_ACTIONS` with `OUTPUT` to `OFPP_CONTROLLER`, `max_len=0xffff`.
- **MAC flows**: `install_mac_flow` — match **eth_dst** via OXM (`oxm_field` built as `!HBB6s` with class `0x8000`, field **3<<1** for ETH_DST, length 6), `OFPFC_ADD`, **priority 100**, **idle_timeout 30**, output action to `out_port`.
- **MAC flow removal**: `remove_mac_flow` — same match, command **`OFPFC_DELETE`**, **priority 0** in the packed `OFPFlowMod` (note: this may or may not delete the same entries as installed, depending on switch strictness; this is an implementation detail visible in code).
- **PACKET_IN response**: `send_packet_out` copies `buffer_id` from PACKET_IN; if `buffer_id == 0xFFFFFFFF` (no buffer), full Ethernet frame is appended.
- **LLDP injection**: `send_lldp_out` — PACKET_OUT from `OFPP_CONTROLLER`, single OUTPUT action, payload is built LLDP frame.
- **Remote flood helper**: `send_raw_packet_out` — PACKET_OUT raw Ethernet to a port.
- **Multipart requests**: `send_port_desc_request` (type **PORT_DESC = 13**), `send_port_stats_request` (type **PORT_STATS = 4**, body `struct.pack("!I4x", port_no)` default `OFPP_ANY`).

**Multipart reply parsing** (`ofproto/multipart.py`):

- `OFPMultipartReply.parse`: fixed `!HH4x` header then body:
  - type **13**: array of `OFPPort` (64 bytes each).
  - type **4**: array of `OFPPortStats` (112 bytes each).
- `has_more` checks flag `OFPMP_REPLY_MORE = 0x0001`.

**Packet-in parsing** (`ofproto/packet_in.py`):

- Fixed header `!IHBBQ` then `OFPMatch`, then padding derived from match length alignment, then **`+ 2` extra bytes** before `frame_data` (comment in code: "2 extra padding").

**Port status** (`handlers.handle_port_status`):

- Requires body length ≥ 48 bytes.
- `reason = body_data[0]`; `port_no` from `body_data[8:12]` as `!I`; `state` from `body_data[44:48]` as `!I`.
- Reserved ports filtered: `port_no >= 0xFFFFFF00` ignored.
- `link_down = (state & OFPPS_LINK_DOWN) != 0` where `OFPPS.LINK_DOWN = 1`.
- If `link_down` **or** `reason == 1` (OpenFlow 1.3 **OFPPR_DELETE** is 1): remove links for that port, reroute; else mark port live and send immediate `send_lldp_out` on that port.

---

## 4. Concurrency model and socket safety

- **Per-switch connection thread** reads messages in a loop until header recv fails or an exception occurs.
- **Global dicts** in `handlers.py`: `switches` (dpid → socket), `mac_to_port` (dpid → `{mac_bytes: port}`), `active_flows`, multipart aggregation buffers `_pending_ports`, `_pending_port_speeds`, `_port_stats_state`.
- **Topology** guarded by `topology._lock` for all graph/port state.
- **Critical**: `utils.locked_send` attaches a `threading.Lock` per connection object to prevent interleaved `sendall` from corrupting the OpenFlow byte stream (documented in `utils.py`). `release_send_lock` runs on disconnect.

---

## 5. Topology discovery and representation (`topology.py`)

### 5.1 Data structures

- `port_map: dict[str, set[int]]` — ports known per switch (from PORT_DESC and PORT_STATUS live updates).
- `port_speeds: dict[str, dict[int, int]]` — port speed **in bps** (from PORT_DESC: `curr_speed or max_speed` in **kbps** × 1000 in `handlers.handle_multipart_reply`).
- `links: dict[tuple[str,int], dict]` — keyed by **directed** edge `(src_dpid, src_port)` mapping to:
  - `'dst': (dst_dpid, dst_port)`
  - `'last_seen': float` epoch seconds
  - `'cost'`: numeric (float used in practice from composite formula)
  - optional `'latency_ms'`, `'bandwidth_bps'`, `'loss'`
- `HARDCODED_LINK_COSTS: dict[tuple[str,str], int]` — bidirectional manual override via `set_hardcoded_cost` (also updates existing matching links' `cost`).

### 5.2 Staleness

- `remove_stale_links(timeout)`: deletes directed entries where `now - last_seen > timeout`, returns list of removed tuples for logging/reroute.

### 5.3 Port roles

- `get_inter_switch_ports(dpid)` equals ports appearing in any directed link as source or destination port on that dpid.
- `get_host_ports(dpid)` = all registered ports minus inter-switch ports.

### 5.4 Path algorithms

- `find_path_bfs(src, dst)`: BFS on **directed** snapshot; returns list of `(dpid, out_port)` hops; empty if same switch or unreachable (prints `[BFS] No path found!`).
- `find_path_dijkstra(src, dst)`: Dijkstra with priority queue; edge weight `link_info.get('cost', 1)`; uses `min_cost` pruning; prints on failure.
- `find_path`: **wrapper returns `find_path_dijkstra`** (BFS is present but not selected by the wrapper).

### 5.5 MAC → switch resolution

- `get_switch_for_mac(mac, mac_to_port)` scans all dpids in `mac_to_port` tables.

---

## 6. LLDP design (`ofproto/lldp.py` + `handlers.py` + `utils.py`)

### 6.1 Frame format

- Ethernet dest `LLDP_MAC_NEAREST_BRIDGE = 01:80:c2:00:00:0e`, ethertype `0x88cc`.
- **Source MAC** for probes: `dpid_int.to_bytes(8, 'big')[2:8]` — **6 bytes derived from lower 6 bytes of 8-byte big-endian DPID integer** (not necessarily the switch hardware MAC).

### 6.2 TLVs used on transmit

- Chassis ID: MAC subtype, value = that 6-byte `src_mac`.
- Port ID: Port Component subtype, **4-byte big-endian port number**.
- TTL: default **120** seconds in `LLDPPacket.create`.
- Optional **custom Organizationally Specific TLV** as **type 127**: payload `b'\x00\x00\x00' + b'\x01' + pack('!d', timestamp)`; decoder requires length 12 and first 4 bytes `\x00\x00\x00\x01`, then unpack double from bytes 4–12.

### 6.3 Reception and neighbor DPID reconstruction

- On PACKET_IN, if ethertype is LLDP, parse `LLDPPacket`.
- `src_mac = lldp_pkt.get_chassis_mac()`, `src_port = lldp_pkt.get_port_number()`.
- **Remote DPID string** reconstructed as: `'00:00:' + ':'.join(f'{b:02x}' for b in src_mac)` — i.e. **first two octets forced to `00:00`**, remaining four octets from chassis MAC. This matches the transmit encoding that used 6 bytes from the 8-byte DPID.
- **One-way delay estimate**: if timestamp TLV present, `latency_ms = (time.time() - ts) * 1000`.

### 6.4 Directed link insertion

- `topology.add_link(src_dpid, src_port, formatted_dpid, in_port, cost=..., latency_ms=..., bandwidth_bps=..., loss=...)`.
- Only the **observed direction** is added (comment states reverse direction appears when the neighbor sends its own LLDP).

### 6.5 Periodic LLDP thread (`handlers._lldp_sender_loop`)

- Interval **`LLDP_INTERVAL = 5`** seconds.
- For each connected switch, for each known port (from `topology.get_ports`), calls `utils.send_lldp_out` (exceptions swallowed).
- After probes: `remove_stale_links(LINK_TIMEOUT)` with **`LINK_TIMEOUT = 2 * LLDP_INTERVAL`** (10s).
- If links removed → `_reroute_affected_flows(..., reason="lldp-timeout")`.
- Then `_check_for_better_paths()`.

---

## 7. Telemetry-based link cost (`handlers.py`)

### 7.1 Port statistics polling

- **`STATS_INTERVAL = 5`** seconds; `_stats_sender_loop` sends `send_port_stats_request` per switch.

### 7.2 Stats state and derived metrics (`_handle_port_stats_reply`)

- Stores per-port: `tx_bytes`, `tx_packets`, `tx_errors`, timestamp.
- On second sample: `delta_t`, deltas for bytes/packets/errors; **`tx_rate_bps = (delta_tx_bytes * 8) / delta_t`**.
- `capacity_bps = topology.get_port_speed(...) or DEFAULT_LINK_CAPACITY_BPS` where **`DEFAULT_LINK_CAPACITY_BPS = 1_000_000_000`**.
- **`available_bps = max(1.0, capacity_bps - tx_rate_bps)`** (interpreted as spare capacity).
- **`loss = delta_tx_errors / max(delta_tx_packets, 1)`** if packets > 0 else 0.
- Saves `available_bps` and `loss` into `_port_stats_state` and calls `_recompute_link_cost` for **outgoing** metric association keyed by `(formatted_dpid, port_no)` as **src** of directed links (note: this attributes utilization on a port to links where this switch is the tail of directed edges from LLDP; the mapping is implementation-specific).

### 7.3 Composite cost function

Constants **`ALPHA = BETA = GAMMA = 1.0`** (tunable).

`_compute_link_cost(latency_ms, capacity_bps, available_bps, loss)`:

- Default `latency_ms` to **1.0** if None.
- Default `capacity_bps` to `DEFAULT_LINK_CAPACITY_BPS` if ≤ 0.
- Default `available_bps` to `max(1.0, capacity_bps)` if None or ≤ 0.
- Default `loss` to **0.0** if None.
- Returns **`(ALPHA * latency_ms) + (BETA * (capacity_bps / available_bps)) + (GAMMA * loss)`**.

When LLDP adds a link, `handlers.handle_packet_in` passes `latency`, `available_bps`, `loss` from `_get_port_metrics(formatted_dpid, in_port)` and `composite_cost` from this function.

### 7.4 Opportunistic better-path rerouting

- `_check_for_better_paths`: for each `active_flows` entry, recomputes `topology.find_path(src_dpid, dst_dpid)`.
- If `new_path` exists, structurally different from `current_path`, compares `_path_cost` sum of per-hop `topology.get_link_info` costs (missing hop counts as **1.0**).
- Reroutes only if `new_cost < current_cost * (1.0 - COST_IMPROVEMENT_THRESHOLD)` with **`COST_IMPROVEMENT_THRESHOLD = 0.20`** (i.e. strictly more than **20%** improvement required).

---

## 8. Data-plane logic (`handlers.handle_packet_in`)

Order of operations (simplified):

1. Parse PACKET_IN, extract `in_port` from OXMs (`utils.extract_in_port` looks for **OXM class `0x8000`, field `0`** = `IN_PORT`).
2. **LLDP branch**: if EtherType `0x88cc`, parse and `topology.add_link` then **return** (no MAC learning from LLDP frames).
3. If `in_port` is None, set to `OFPP_CONTROLLER`.
4. Compute `inter_switch_ports`; extract `src_mac`, `dst_mac` from Ethernet header (offsets **0–5 dst**, **6–11 src** per usual Ethernet layout in this code).
5. **MAC learning**: only if `in_port not in inter_switch_ports`, set `mac_to_port[formatted_dpid][src_mac] = in_port`.
6. **Broadcast/multicast detection**: `(dst_mac[0] & 0x01) == 1`.
7. Resolve destination: `topology.get_switch_for_mac(dst_mac, mac_to_port)`.

### 8.1 Unknown unicast or broadcast/multicast

- If `dst_dpid is None` or broadcast/multicast:
  - If `in_port in inter_switch_ports`: **return** (drop) to prevent storms.
  - Else flood on **local** switch: all `get_host_ports` except `in_port` via `send_packet_out`.
  - Then for **each other switch**: for each **remote host port**, `utils.send_raw_packet_out` with the full Ethernet frame.  
  - **Note**: the code block contains comments about finding an inter-switch path, but the implemented remote flood does **not** use the computed `path` variable for those `send_raw_packet_out` calls; it emits on **every** remote host-facing port.

### 8.2 Known unicast, same switch

- `install_mac_flow` on `dst_mac` → `dst_port`, then `send_packet_out` directly to `dst_port`.

### 8.3 Known unicast, different switches

- `path = topology.find_path(formatted_dpid, dst_dpid)`; if empty, return (drop).
- Install `install_mac_flow` on each hop for `dst_mac` with hop's `hop_out_port`, and on destination switch for `dst_port`.
- Record `active_flows[(src_mac, dst_mac)] = { path, dst_dpid, dst_port }`.
- Forward current PACKET_IN out `path[0][1]` via `send_packet_out`.

---

## 9. Connection lifecycle and cleanup

### 9.1 Features reply (`handle_features_reply`)

- Parse DPID, format as colon-separated hex pairs of length 16 (8 octets).
- Store socket in `switches[formatted_dpid]`.
- **Reset** `mac_to_port[formatted_dpid] = {}` on (re)connect.
- `send_table_miss_flow`, `send_port_desc_request` with **`xid=2`**.

### 9.2 Port description aggregation

- While `reply.has_more`, accumulate ports and speeds in `_pending_ports` / `_pending_port_speeds`.
- When final segment: `topology.register_ports`, `topology.register_port_speeds`, then **immediate** `send_lldp_out` per port with `dpid_int`.

### 9.3 Disconnect cleanup (`handle_switch_connection` tail)

- Close socket, `release_send_lock`.
- If this socket was the registered one for `formatted_dpid`, pop from `switches`, pop `mac_to_port[dpid]`, `_pending_ports`.
- `topology.deregister_switch` removes ports, speeds, all incident links; `_reroute_affected_flows(..., "switch-disconnect")`.

---

## 10. Web API and visualization (`web/main.py` + `web/static/index.html`)

### 10.1 REST

- **`GET /api/topology`**: builds switches from `topology.port_map.keys()`; links from `topology.get_all_links()` including `cost`; hosts from `handlers.mac_to_port` excluding ports in `topology.get_inter_switch_ports`; host attachment edges listed.
- **`GET /api/path?src=&dst=`**: resolves `src`/`dst` either as switch id present in `port_map` or `host:aa:bb:...` MAC form via `_parse_host_mac` and `topology.get_switch_for_mac`. For **host-to-host**, if an entry exists in `handlers.active_flows` for `(src_mac, dst_mac)`, the **stored path** is used so UI matches installed forwarding; else `topology.find_path`. Returns `edge_ids` built to match graph edge id scheme.
- **`GET /api/flows`**: dumps `handlers.active_flows` (MAC keys as raw bytes in JSON).
- **`POST /api/link_cost`**: body `LinkCostUpdate { src_dpid, dst_dpid, cost: int }` → `topology.set_hardcoded_cost`.

### 10.2 WebSocket

- **`/ws/topology`**: every **5 seconds** (asyncio sleep), sends JSON same shape as `/api/topology`.

### 10.3 Frontend behavior (factual)

- Loads **Cytoscape** from `https://unpkg.com/cytoscape/dist/cytoscape.min.js` (URL as in `web/static/index.html`).
- WebSocket URL `ws://${location.host}/ws/topology`.
- Switch labels: heuristic `getSwitchAlias` uses last two hex octets as row/col for names like `s{row}x{col}` when both > 0, else `s{last_byte}`.
- Host labels: stable map assigning `h1`, `h2`, … in order of first appearance.
- Deduplicates opposite directed switch links into one undirected edge for display; may show **average** of forward/reverse costs when both exist.
- Tap node selection (max two) triggers path highlight fetch; tap edge on switch–switch link prompts for new cost → POST `/api/link_cost`.
- Incremental graph updates; runs `cose` layout **only when node set changes** (switch/host add/remove).

---

## 11. Helper / ancillary files

- **`traingle_topo.py`**: Mininet `Topo` subclass `LoopTopo` with three switches `s1–s3`, hosts `h1` on `s1`, `h2` on `s3`, links `s1–s2–s3` plus `s1–s3` loop; `topos = {'looptopo': LoopTopo}`.
- **`update_multip_replies.py`**: reads/writes `ofproto/constants.py` to ensure `PORT_STATS` enum line exists.
- **`.gitignore`**: standard Python/venv patterns; `*.log`; `.vscode/`.

---

## 12. Explicit non-goals / limitations visible in code (for accurate reporting)

- Not using Ryu, ONOS, Floodlight, or ovs-ofctl for control logic — **from-scratch** message packing/parsing for the subset used.
- No TLS on switch TCP; single hardcoded bind address/port.
- Thread-per-switch model does not scale to very large fabrics; no explicit rate limiting on PACKET_IN processing beyond OS buffers.
- `find_path_bfs` exists but **default path selection is Dijkstra**.
- Flow delete vs add **priority fields differ** in `remove_mac_flow` vs `install_mac_flow` (see §3).
- Remote flooding for unknown/broadcast uses **per-remote-switch all-host-port outputs**, not necessarily shortest-path replication to each remote edge.
- `README.md` is operator-focused, not architectural documentation.

---

## 13. File inventory (production-relevant)

```
controller.py
handlers.py
topology.py
utils.py
ofproto/constants.py
ofproto/header.py
ofproto/multipart.py
ofproto/lldp.py
ofproto/match.py
ofproto/switch_features.py
ofproto/flow_mod.py
ofproto/packet_out.py
ofproto/action_out.py
ofproto/packet_in.py
web/main.py
web/requirements.txt
web/static/index.html
traingle_topo.py
update_multip_replies.py
README.md
.gitignore
```

---

## 14. How to cite this document to an LLM

Suggested instruction to append for the downstream model:

> Only assert features, algorithms, constants, and file paths that appear in `PROJECT_LLM_CONTEXT.md` or the referenced source files. Treat excluded paths (`logs/`, `test_dijkstra.py`) as out of scope. When describing OpenFlow behavior, distinguish between **this controller’s subset** and general OpenFlow specification details unless verified externally.

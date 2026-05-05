import threading
from collections import deque
import heapq
import time


# Global topology state
# port_map   : dpid -> set of port numbers known on that switch
# links      : (src_dpid, src_port) -> (dst_dpid, dst_port)
# _lock      : protects both dicts for thread-safe access (switches run on separate threads)

port_map = {}   # str dpid -> set(int port_no)
port_speeds = {}  # str dpid -> dict(int port_no -> int speed_bps)
# (src_dpid, src_port) -> {'dst': (dst_dpid, dst_port), 'last_seen': timestamp, ...}
links    = {}
_lock    = threading.Lock()

# Dictionary to store hardcoded costs for specific switch-to-switch links (src_dpid, dst_dpid) -> cost
# This will be used in add_link to override the default cost of 1.
HARDCODED_LINK_COSTS = {
    # e.g., ('1', '2'): 10,
    #       ('2', '1'): 10,
}

def set_hardcoded_cost(src_dpid: str, dst_dpid: str, cost: int):
    """Manually update the cost of a link bidirectionally for testing purposes."""
    with _lock:
        HARDCODED_LINK_COSTS[(src_dpid, dst_dpid)] = cost
        HARDCODED_LINK_COSTS[(dst_dpid, src_dpid)] = cost
        
        # Also update existing tracked links
        for (s_dpid, s_port), info in links.items():
            d_dpid, _ = info['dst']
            if (s_dpid == src_dpid and d_dpid == dst_dpid) or (s_dpid == dst_dpid and d_dpid == src_dpid):
                info['cost'] = cost

def remove_stale_links(timeout: float):
    """
    Remove links that have not been seen within the given timeout (in seconds).
    Returns a list of removed links for logging or further action.
    """
    now = time.time()
    removed = []
    with _lock:
        stale_keys = [key for key, info in links.items() if now - info['last_seen'] > timeout]
        for key in stale_keys:
            removed.append((key[0], key[1], links[key]['dst'][0], links[key]['dst'][1]))
            del links[key]
    return removed


# ------------------------------------------------------------------ #
# Port Map                                                             #
# ------------------------------------------------------------------ #

def register_ports(dpid: str, port_nos: list):
    """
    Store the list of port numbers for a switch.
    Called after MULTIPART_REPLY (PORT_DESC) is received.
    """
    with _lock:
        port_map[dpid] = set(port_nos)


def register_port_speeds(dpid: str, speeds: dict):
    """Store per-port speed (bps) for a switch."""
    with _lock:
        port_speeds[dpid] = dict(speeds)


def set_port_live(dpid: str, port_no: int, is_live: bool):
    """Update local port map when a PORT_STATUS event is received."""
    with _lock:
        if dpid not in port_map:
            port_map[dpid] = set()
        if is_live:
            port_map[dpid].add(port_no)
        else:
            port_map[dpid].discard(port_no)


def get_ports(dpid: str) -> set:
    """Return the set of known port numbers for a switch."""
    with _lock:
        return set(port_map.get(dpid, set()))


def get_port_speed(dpid: str, port_no: int) -> int:
    """Return port speed in bps, or 0 if unknown."""
    with _lock:
        return int(port_speeds.get(dpid, {}).get(port_no, 0))


# ------------------------------------------------------------------ #
# Link Map                                                             #
# ------------------------------------------------------------------ #

def add_link(
    src_dpid: str,
    src_port: int,
    dst_dpid: str,
    dst_port: int,
    cost: int = 1,
    latency_ms: float = None,
    bandwidth_bps: float = None,
    loss: float = None,
):
    """
    Record a directed link:  (src_dpid, src_port) -> (dst_dpid, dst_port)
    LLDP gives us directed links. Both directions will be added separately
    when the neighbour switch sends its own LLDP back.
    Also updates the last_seen timestamp and stores link cost.
    """
    with _lock:
        # Check if we have a hardcoded cost for this specific edge
        hardcoded_cost = HARDCODED_LINK_COSTS.get((src_dpid, dst_dpid), cost)
        
        # Avoid overwriting custom costs if the link already exists and we just saw an LLDP refresh
        # (Fix: actually update the cost if a new dynamic cost is passed in from handlers)
        existing = links.get((src_dpid, src_port), {})
        links[(src_dpid, src_port)] = {
            'dst': (dst_dpid, dst_port),
            'last_seen': time.time(),
            'cost': hardcoded_cost,
            'latency_ms': latency_ms if latency_ms is not None else existing.get('latency_ms'),
            'bandwidth_bps': bandwidth_bps if bandwidth_bps is not None else existing.get('bandwidth_bps'),
            'loss': loss if loss is not None else existing.get('loss'),
        }


def get_link_info(src_dpid: str, src_port: int):
    """Return a copy of the link info dict for a directed link, or None."""
    with _lock:
        info = links.get((src_dpid, src_port))
        if not info:
            return None
        return dict(info)


def update_link_metrics(
    src_dpid: str,
    src_port: int,
    cost: float = None,
    latency_ms: float = None,
    bandwidth_bps: float = None,
    loss: float = None,
):
    """Update metrics for a directed link if it exists."""
    with _lock:
        info = links.get((src_dpid, src_port))
        if not info:
            return
        if cost is not None:
            info['cost'] = cost
        if latency_ms is not None:
            info['latency_ms'] = latency_ms
        if bandwidth_bps is not None:
            info['bandwidth_bps'] = bandwidth_bps
        if loss is not None:
            info['loss'] = loss


def remove_links_for_port(dpid: str, port_no: int) -> list:
    """
    Remove all directed links attached to (dpid, port_no), including:
    - outgoing links from this port
    - incoming links whose destination is this port
    Returns removed links as (src_dpid, src_port, dst_dpid, dst_port).
    """
    removed = []
    with _lock:
        to_delete = []
        for (src_dpid, src_port), info in links.items():
            dst_dpid, dst_port = info['dst']
            if (src_dpid == dpid and src_port == port_no) or (dst_dpid == dpid and dst_port == port_no):
                to_delete.append((src_dpid, src_port))

        for key in to_delete:
            dst_dpid, dst_port = links[key]['dst']
            removed.append((key[0], key[1], dst_dpid, dst_port))
            del links[key]
    return removed


def get_neighbours(dpid: str) -> list:
    """
    Return a list of (src_port, dst_dpid, dst_port, cost) tuples
    for every link originating from the given switch.
    """
    with _lock:
        result = []
        for (src_dpid, src_port), link_info in links.items():
            if src_dpid == dpid:
                dst_dpid, dst_port = link_info['dst']
                cost = link_info.get('cost', 1)
                result.append((src_port, dst_dpid, dst_port, cost))
        return result


def get_all_links() -> list:
    """Return all known links as a list of (src_dpid, src_port, dst_dpid, dst_port, last_seen, cost)."""
    with _lock:
        return [
            (src_dpid, src_port, link_info['dst'][0], link_info['dst'][1], link_info['last_seen'], link_info.get('cost', 1))
            for (src_dpid, src_port), link_info in links.items()
        ]


def get_link_destination(src_dpid: str, src_port: int):
    """Return (dst_dpid, dst_port) for a directed link, or None if unknown."""
    with _lock:
        info = links.get((src_dpid, src_port))
        if not info:
            return None
        return info['dst']


def print_topology():
    """Pretty-print the current known topology."""
    all_links = get_all_links()
    if not all_links:
        print("[Topology] No links discovered yet.")
        return
    print("[Topology] Discovered Links:")
    for src_dpid, src_port, dst_dpid, dst_port, last_seen, cost in sorted(all_links):
        print(f"  {src_dpid}:{src_port}  -->  {dst_dpid}:{dst_port}  (cost: {cost}, last_seen: {last_seen:.0f})")
    print('Total Links:',len(all_links))


def get_switch_link_ports(dpid: str) -> set:
    """
    Ports on this switch that participate in switch-switch links,
    considering both outgoing and incoming directed link entries.
    """
    with _lock:
        ports = set()
        for (src_dpid, src_port), link_info in links.items():
            dst_dpid, dst_port = link_info['dst']
            if src_dpid == dpid:
                ports.add(src_port)
            if dst_dpid == dpid:
                ports.add(dst_port)
        return ports


def get_inter_switch_ports(dpid: str) -> set:
    """Return the set of ports on dpid that connect to other switches."""
    return get_switch_link_ports(dpid)


def get_host_ports(dpid: str) -> set:
    """Return ports on dpid that are NOT inter-switch (i.e. host-facing)."""
    with _lock:
        all_ports = set(port_map.get(dpid, set()))
    return all_ports - get_switch_link_ports(dpid)


def deregister_switch(dpid: str) -> list:
    """
    Remove all topology state for a switch that has disconnected.
    Called from handlers.py when the switch's TCP connection is closed.
    Returns removed directed links as
    (src_dpid, src_port, dst_dpid, dst_port).
    """
    removed = []
    with _lock:
        port_map.pop(dpid, None)
        port_speeds.pop(dpid, None)
        stale = []
        for key, info in links.items():
            src_dpid, _ = key
            dst_dpid, _ = info['dst']
            if src_dpid == dpid or dst_dpid == dpid:
                stale.append(key)
        for k in stale:
            dst_dpid, dst_port = links[k]['dst']
            removed.append((k[0], k[1], dst_dpid, dst_port))
            del links[k]
    return removed


# ------------------------------------------------------------------ #
# Path Finding                                                         #
# ------------------------------------------------------------------ #

def find_path_bfs(src_dpid: str, dst_dpid: str) -> list:
    """
    BFS shortest path between two switches.
    Returns a list of (dpid, out_port) tuples for each hop.

    Example for path S1 -> S2 -> S3:
        [
            ('S1', out_port),   # send out this port on S1 to reach S2
            ('S2', out_port),   # send out this port on S2 to reach S3
        ]
    The final switch (dst_dpid) is NOT included - the caller
    already knows the exact host port from mac_to_port.
    """
    if src_dpid == dst_dpid:
        return []

    # Take a snapshot of links under lock, then BFS without holding lock
    with _lock:
        links_snapshot = dict(links)

    queue = deque()
    visited = set()
    queue.append((src_dpid, []))
    visited.add(src_dpid)

    while queue:
        current_dpid, path = queue.popleft()

        for (s_dpid, s_port), link_info in links_snapshot.items():
            d_dpid, _d_port = link_info['dst']
            if s_dpid != current_dpid:
                continue
            if d_dpid in visited:
                continue

            new_path = path + [(current_dpid, s_port)]

            if d_dpid == dst_dpid:
                return new_path

            visited.add(d_dpid)
            queue.append((d_dpid, new_path))

    print("[BFS] No path found!")
    return []

def find_path_dijkstra(src_dpid: str, dst_dpid: str) -> list:
    """
    Dijkstra shortest cost path between two switches.
    Returns a list of (dpid, out_port) tuples for each hop.
    """
    if src_dpid == dst_dpid:
        return []

    # Take a snapshot of links under lock
    with _lock:
        links_snapshot = dict(links)

    # Priority queue stores (cost, current_dpid, path)
    queue = []
    heapq.heappush(queue, (0, src_dpid, []))
    
    # Store minimum cost to reach each node (to avoid expanding worse paths)
    min_cost = {src_dpid: 0}

    while queue:
        current_cost, current_dpid, path = heapq.heappop(queue)

        # If we reached the destination, return the path
        if current_dpid == dst_dpid:
            return path
            
        # If we already found a cheaper way to get here, skip
        if current_cost > min_cost.get(current_dpid, float('inf')):
            continue

        for (s_dpid, s_port), link_info in links_snapshot.items():
            if s_dpid != current_dpid:
                continue
                
            d_dpid, _d_port = link_info['dst']
            link_cost = link_info.get('cost', 1)
            new_cost = current_cost + link_cost
            
            # If we found a cheaper path to the next node
            if new_cost < min_cost.get(d_dpid, float('inf')):
                min_cost[d_dpid] = new_cost
                new_path = path + [(current_dpid, s_port)]
                heapq.heappush(queue, (new_cost, d_dpid, new_path))
                
    print(f"[Dijkstra] No path found from {src_dpid} to {dst_dpid}!")
    return []


def find_path(src_dpid: str, dst_dpid: str) -> list:
    """Wrapper function to perform route discovery."""
    return find_path_dijkstra(src_dpid, dst_dpid)


def get_switch_for_mac(mac: bytes, mac_to_port: dict) -> tuple:
    """
    Search all switches for a learned MAC address.
    Returns (dpid, port) or (None, None).
    """
    for dpid, table in mac_to_port.items():
        if mac in table:
            return dpid, table[mac]
    return None, None

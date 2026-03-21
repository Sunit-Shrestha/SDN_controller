from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Query
import threading
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import topology
import handlers
import controller

app = FastAPI()

@app.on_event("startup")
def startup_event():
    # Start the SDN controller in a background thread
    controller_thread = threading.Thread(target=controller.start_controller, daemon=True)
    controller_thread.start()
    print("Started controller thread")

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

@app.get("/")
def get_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


def _endpoint_token(dpid: str, port: int) -> str:
    return f"{dpid}:{port}"


def _switch_link_edge_id(src_dpid: str, src_port: int, dst_dpid: str, dst_port: int) -> str:
    a = _endpoint_token(src_dpid, src_port)
    b = _endpoint_token(dst_dpid, dst_port)
    pair_key = "||".join(sorted([a, b]))
    return f"link:{pair_key}"


def _host_link_edge_id(host_id: str, switch_dpid: str, switch_port: int) -> str:
    return f"hostlink:{host_id}||{switch_dpid}:{switch_port}"


def _parse_host_mac(host_id: str):
    if not host_id.startswith("host:"):
        return None
    mac_str = host_id[len("host:"):]
    try:
        return bytes.fromhex(mac_str.replace(":", ""))
    except Exception:
        return None


def _resolve_node_endpoint(node_id: str, switches: set):
    if node_id.startswith("host:"):
        mac_bytes = _parse_host_mac(node_id)
        if not mac_bytes:
            return None
        dpid, port = topology.get_switch_for_mac(mac_bytes, handlers.mac_to_port)
        if not dpid:
            return None
        return {
            "type": "host",
            "node_id": node_id,
            "mac": mac_bytes,
            "switch_dpid": dpid,
            "switch_port": port,
        }

    # switch
    if node_id not in switches:
        return None
    return {
        "type": "switch",
        "node_id": node_id,
        "mac": None,
        "switch_dpid": node_id,
        "switch_port": None,
    }

@app.get("/api/topology")
def get_topology():
    switches = list(topology.port_map.keys())
    links = []
    hosts = []
    host_links = []
    if hasattr(topology, 'get_all_links'):
        for l in topology.get_all_links():
            links.append({
                "src_dpid": l[0],
                "src_port": l[1],
                "dst_dpid": l[2],
                "dst_port": l[3]
            })

    active_switches = set(switches)
    if hasattr(handlers, 'mac_to_port'):
        seen_hosts = set()
        for dpid, table in handlers.mac_to_port.items():
            if dpid not in active_switches:
                continue
            inter_switch_ports = topology.get_inter_switch_ports(dpid)
            for mac, port in table.items():
                if port in inter_switch_ports:
                    continue
                mac_str = mac.hex(':') if isinstance(mac, (bytes, bytearray)) else str(mac)
                host_id = f"host:{mac_str}"
                if host_id not in seen_hosts:
                    hosts.append({"id": host_id, "mac": mac_str})
                    seen_hosts.add(host_id)
                host_links.append({
                    "host_id": host_id,
                    "switch_dpid": dpid,
                    "switch_port": port
                })

    return {"switches": switches, "links": links, "hosts": hosts, "host_links": host_links}


@app.get("/api/path")
def get_path(src: str = Query(...), dst: str = Query(...)):
    switches = set(topology.port_map.keys())

    src_ep = _resolve_node_endpoint(src, switches)
    dst_ep = _resolve_node_endpoint(dst, switches)
    if not src_ep or not dst_ep:
        return {"found": False, "edge_ids": []}

    src_sw = src_ep["switch_dpid"]
    dst_sw = dst_ep["switch_dpid"]

    # Prefer existing active flow state for host->host so UI path matches actual forwarding.
    flow_path = None
    if src_ep["type"] == "host" and dst_ep["type"] == "host":
        flow_key = (src_ep["mac"], dst_ep["mac"])
        flow_info = handlers.active_flows.get(flow_key)
        if flow_info:
            flow_path = list(flow_info.get("path", []))

    if flow_path is None:
        if src_sw == dst_sw:
            flow_path = []
        else:
            flow_path = topology.find_path(src_sw, dst_sw)
            if not flow_path:
                return {"found": False, "edge_ids": []}

    edge_ids = []
    seen = set()

    # Host attachment at source
    if src_ep["type"] == "host":
        eid = _host_link_edge_id(src_ep["node_id"], src_ep["switch_dpid"], src_ep["switch_port"])
        if eid not in seen:
            edge_ids.append(eid)
            seen.add(eid)

    # Inter-switch hops
    for hop_dpid, hop_out_port in flow_path:
        dst_link = topology.get_link_destination(hop_dpid, hop_out_port)
        if not dst_link:
            continue
        dst_dpid, dst_port = dst_link
        eid = _switch_link_edge_id(hop_dpid, hop_out_port, dst_dpid, dst_port)
        if eid not in seen:
            edge_ids.append(eid)
            seen.add(eid)

    # Host attachment at destination
    if dst_ep["type"] == "host":
        eid = _host_link_edge_id(dst_ep["node_id"], dst_ep["switch_dpid"], dst_ep["switch_port"])
        if eid not in seen:
            edge_ids.append(eid)
            seen.add(eid)

    return {"found": True, "edge_ids": edge_ids}

@app.get("/api/flows")
def get_flows():
    flows = []
    if hasattr(handlers, 'active_flows'):
        for k, v in handlers.active_flows.items():
            flows.append({
                "src_mac": k[0],
                "dst_mac": k[1],
                "path": v.get('path'),
                "dst_dpid": v.get('dst_dpid'),
                "dst_port": v.get('dst_port')
            })
    return {"flows": flows}

@app.websocket("/ws/topology")
async def websocket_topology(websocket: WebSocket):
    await websocket.accept()
    # Example: send topology every 2 seconds
    import asyncio
    while True:
        switches = list(topology.port_map.keys())
        links = []
        hosts = []
        host_links = []
        if hasattr(topology, 'get_all_links'):
            for l in topology.get_all_links():
                links.append({
                    "src_dpid": l[0],
                    "src_port": l[1],
                    "dst_dpid": l[2],
                    "dst_port": l[3]
                })

        active_switches = set(switches)
        if hasattr(handlers, 'mac_to_port'):
            seen_hosts = set()
            for dpid, table in handlers.mac_to_port.items():
                if dpid not in active_switches:
                    continue
                inter_switch_ports = topology.get_inter_switch_ports(dpid)
                for mac, port in table.items():
                    if port in inter_switch_ports:
                        continue
                    mac_str = mac.hex(':') if isinstance(mac, (bytes, bytearray)) else str(mac)
                    host_id = f"host:{mac_str}"
                    if host_id not in seen_hosts:
                        hosts.append({"id": host_id, "mac": mac_str})
                        seen_hosts.add(host_id)
                    host_links.append({
                        "host_id": host_id,
                        "switch_dpid": dpid,
                        "switch_port": port
                    })

        await websocket.send_json({"switches": switches, "links": links, "hosts": hosts, "host_links": host_links})
        await asyncio.sleep(2)

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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

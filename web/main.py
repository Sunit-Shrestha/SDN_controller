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
    if hasattr(topology, 'get_all_links'):
        for l in topology.get_all_links():
            links.append({
                "src_dpid": l[0],
                "src_port": l[1],
                "dst_dpid": l[2],
                "dst_port": l[3]
            })
    return {"switches": switches, "links": links}

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
        if hasattr(topology, 'get_all_links'):
            for l in topology.get_all_links():
                links.append({
                    "src_dpid": l[0],
                    "src_port": l[1],
                    "dst_dpid": l[2],
                    "dst_port": l[3]
                })
        await websocket.send_json({"switches": switches, "links": links})
        await asyncio.sleep(2)

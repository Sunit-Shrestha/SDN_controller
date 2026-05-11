# DQN-based SDN Routing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a DQN reinforcement learning system that tests against a Mininet network using an embedded SDN controller to dynamically route traffic and reduce latency/packet loss.

**Architecture:** A standalone orchestrator script (`dqn/train.py`) will spin up the Mininet Torus(3,3) cluster through an environment wrapper (`dqn/env.py`), interact with the controller API using HTTP requests, and train a PyTorch DQN agent (`dqn/agent.py`) using an experience replay buffer and fixed Q-targets.

**Tech Stack:** Python 3, FastAPI, PyTorch, Mininet, NetworkX, Pytest.

---

### Task 1: API Endpoint - `/api/metrics`

**Files:**
- Modify: `web/main.py`
- Create: `tests/test_api_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_metrics.py
from fastapi.testclient import TestClient
from web.main import app

client = TestClient(app)

def test_get_metrics_empty():
    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert "metrics" in response.json()
    assert isinstance(response.json()["metrics"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_metrics.py -v`
Expected: FAIL with "404 Not Found"

- [ ] **Step 3: Write minimal implementation**

Modify `web/main.py` to add:
```python
@app.get("/api/metrics")
def get_metrics():
    metrics_list = []
    if hasattr(topology, 'get_all_links'):
        for l in topology.get_all_links():
            # l format: (src_dpid, src_port, dst_dpid, dst_port, last_seen, cost)
            # Fetch from links dict for latency, bandwidth, loss
            info = topology.get_link_info(l[0], l[1])
            if info:
                metrics_list.append({
                    "src_dpid": l[0],
                    "src_port": l[1],
                    "dst_dpid": l[2],
                    "dst_port": l[3],
                    "latency_ms": info.get("latency_ms", 1.0),
                    "bandwidth_bps": info.get("bandwidth_bps", 1000000000.0),
                    "loss": info.get("loss", 0.0)
                })
    return {"metrics": metrics_list}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_metrics.py web/main.py
git commit -m "feat: add /api/metrics endpoint for RL state observation"
```

### Task 2: API Endpoint - `/api/k-shortest-paths`

**Files:**
- Modify: `web/main.py`
- Create: `tests/test_api_k_shortest_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_k_shortest_paths.py
from fastapi.testclient import TestClient
from web.main import app
import topology

client = TestClient(app)

def test_k_shortest_paths_no_topology():
    response = client.get("/api/k-shortest-paths?src=00:00:00:00:00:00:00:01&dst=00:00:00:00:00:00:00:02&k=5")
    assert response.status_code == 200
    data = response.json()
    assert "paths" in data
    assert len(data["paths"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_k_shortest_paths.py -v`
Expected: FAIL with "404 Not Found"

- [ ] **Step 3: Write minimal implementation**

Modify `web/main.py` to add:
```python
import networkx as nx

@app.get("/api/k-shortest-paths")
def get_k_shortest_paths(src: str, dst: str, k: int = 5):
    # Retrieve all links and build NetworkX directed graph
    G = nx.DiGraph()
    if hasattr(topology, 'get_all_links'):
        for l in topology.get_all_links():
            G.add_edge(l[0], l[2], src_port=l[1], dst_port=l[3], weight=l[5] if len(l)>5 else 1)
            
    paths = []
    if src in G and dst in G:
        try:
            # Yen's algorithm for k simple paths
            yen_paths = list(nx.shortest_simple_paths(G, source=src, target=dst, weight='weight'))
            for p in yen_paths[:k]:
                # Convert sequence of nodes to list of (dpid, out_port) tuples
                detailed_path = []
                for i in range(len(p) - 1):
                    u = p[i]
                    v = p[i+1]
                    edge_data = G.get_edge_data(u, v)
                    detailed_path.append((u, edge_data['src_port']))
                paths.append(detailed_path)
        except nx.NetworkXNoPath:
            pass

    return {"paths": paths}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_k_shortest_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_k_shortest_paths.py web/main.py
git commit -m "feat: add /api/k-shortest-paths using NetworkX"
```

### Task 3: API Endpoint - `/api/install-path`

**Files:**
- Modify: `web/main.py`
- Create: `tests/test_api_install_path.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_install_path.py
from fastapi.testclient import TestClient
from web.main import app

client = TestClient(app)

def test_install_path():
    payload = {
        "src_mac": "00:00:00:00:00:01",
        "dst_mac": "00:00:00:00:00:02",
        "path": [["00:00:00:00:00:00:00:01", 2], ["00:00:00:00:00:00:00:02", 3]]
    }
    response = client.post("/api/install-path", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_install_path.py -v`
Expected: FAIL with "405 Method Not Allowed"

- [ ] **Step 3: Write minimal implementation**

Modify `web/main.py` to add:
```python
from pydantic import BaseModel
from typing import List, Tuple
import utils

class InstallPathRequest(BaseModel):
    src_mac: str
    dst_mac: str
    path: List[Tuple[str, int]]  # [(dpid, out_port), ...]

@app.post("/api/install-path")
def install_selected_path(req: InstallPathRequest):
    src_mac_bytes = bytes.fromhex(req.src_mac.replace(':', ''))
    dst_mac_bytes = bytes.fromhex(req.dst_mac.replace(':', ''))
    
    # Store override path in active flows to prevent standard reroute loop from overriding
    flow_key = (src_mac_bytes, dst_mac_bytes)
    
    # Find dst switch mapping
    dst_dpid, dst_host_port = topology.get_switch_for_mac(dst_mac_bytes, handlers.mac_to_port)
    if not dst_dpid:
        return {"status": "error", "message": "Destination host unknown"}

    handlers.active_flows[flow_key] = {
        'path': [tuple(hop) for hop in req.path],
        'dst_dpid': dst_dpid,
        'dst_port': dst_host_port,
        'rl_managed': True
    }
    
    # Install standard flows
    for hop_dpid, hop_out_port in req.path:
        hop_conn = handlers.switches.get(hop_dpid)
        if hop_conn:
            utils.install_mac_flow(hop_conn, dst_mac_bytes, hop_out_port, xid=0)
            
    dst_conn = handlers.switches.get(dst_dpid)
    if dst_conn:
        utils.install_mac_flow(dst_conn, dst_mac_bytes, dst_host_port, xid=0)

    return {"status": "success", "message": "Path installed successfully"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_install_path.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_install_path.py web/main.py
git commit -m "feat: add /api/install-path for RL action execution"
```

### Task 4: DQN Agent - Neural Network models

**Files:**
- Create: `dqn/agent.py`
- Create: `tests/test_agent_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_model.py
import torch
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dqn.agent import DQN

def test_dqn_output_shape():
    model = DQN(state_dim=108, action_dim=5)
    dummy_state = torch.randn(1, 108)
    output = model(dummy_state)
    assert output.shape == (1, 5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_model.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'dqn'"

- [ ] **Step 3: Write minimal implementation**

Create `dqn/agent.py`:
```python
import torch
import torch.nn as nn
import torch.optim as optim
import random
import numpy as np

class DQN(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_dim, 256)
        self.fc2 = nn.Linear(256, 128)
        self.out = nn.Linear(128, action_dim)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        return self.out(x)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_model.py dqn/
git commit -m "feat: implement DQN neural network architecture"
```

### Task 5: DQN Agent - Replay Buffer

**Files:**
- Modify: `dqn/agent.py`
- Create: `tests/test_replay_buffer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_buffer.py
from dqn.agent import ReplayBuffer
import numpy as np

def test_replay_buffer():
    buffer = ReplayBuffer(capacity=10)
    for i in range(5):
        buffer.push(np.zeros(108), i, 1.0, np.zeros(108), False)
    
    assert len(buffer) == 5
    states, actions, rewards, next_states, dones = buffer.sample(3)
    assert len(states) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_replay_buffer.py -v`
Expected: FAIL with "ImportError: cannot import name 'ReplayBuffer'"

- [ ] **Step 3: Write minimal implementation**

Modify `dqn/agent.py`:
```python
from collections import deque

class ReplayBuffer:
    def __init__(self, capacity):
        self.buffer = deque(maxlen=capacity)
    
    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))
    
    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states, dtype=np.float32), 
            np.array(actions, dtype=np.int64), 
            np.array(rewards, dtype=np.float32), 
            np.array(next_states, dtype=np.float32), 
            np.array(dones, dtype=np.float32)
        )

    def __len__(self):
        return len(self.buffer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_replay_buffer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_replay_buffer.py dqn/agent.py
git commit -m "feat: implement ReplayBuffer for transitions"
```

### Task 6: DQN Agent - Agent Logic

**Files:**
- Modify: `dqn/agent.py`
- Create: `tests/test_dqn_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dqn_agent.py
from dqn.agent import DQNAgent
import numpy as np

def test_dqn_agent():
    agent = DQNAgent(state_dim=108, action_dim=5)
    action = agent.select_action(np.zeros(108))
    assert 0 <= action < 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dqn_agent.py -v`
Expected: FAIL with "ImportError: cannot import name 'DQNAgent'"

- [ ] **Step 3: Write minimal implementation**

Modify `dqn/agent.py`:
```python
class DQNAgent:
    def __init__(self, state_dim, action_dim, lr=1e-3, gamma=0.99, epsilon_start=1.0, epsilon_end=0.01, epsilon_decay=0.995):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.policy_net = DQN(state_dim, action_dim).to(self.device)
        self.target_net = DQN(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(10000)

    def select_action(self, state):
        if random.random() < self.epsilon:
            return random.randrange(self.action_dim)
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad():
            q_values = self.policy_net(state_tensor)
            return q_values.argmax().item()

    def step(self, state, action, reward, next_state, done, batch_size=64):
        self.memory.push(state, action, reward, next_state, done)

        if len(self.memory) < batch_size:
            return None

        states, actions, rewards, next_states, dones = self.memory.sample(batch_size)
        
        states = torch.FloatTensor(states).to(self.device)
        actions = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        rewards = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).unsqueeze(1).to(self.device)

        q_values = self.policy_net(states).gather(1, actions)
        
        with torch.no_grad():
            next_q_values = self.target_net(next_states).max(1)[0].unsqueeze(1)
            target_q_values = rewards + (1 - dones) * self.gamma * next_q_values

        loss = nn.MSELoss()(q_values, target_q_values)

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        return loss.item()

    def update_target_network(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def save(self, filepath):
        torch.save(self.policy_net.state_dict(), filepath)

    def load(self, filepath):
        self.policy_net.load_state_dict(torch.load(filepath))
        self.target_net.load_state_dict(self.policy_net.state_dict())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dqn_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_dqn_agent.py dqn/agent.py
git commit -m "feat: implement main DQNAgent with training logic"
```

### Task 7: SDN Environment - Mininet Wrapper

**Files:**
- Create: `dqn/env.py`

- [ ] **Step 1: Write minimal implementation**

Create `dqn/env.py` (Integration code, testing live Mininet requires root/complex setups so skipping standard pytest for this environment script, opting for a functional implementation).

```python
import time
import re
import requests
import numpy as np
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
# Assume topology script torous_topo exists or create inline
from mininet.topo import Topo

class TorusTopo(Topo):
    def build(self, width=3, height=3):
        switches = {}
        for y in range(height):
            for x in range(width):
                dpid = f"s{(y*width)+x+1}"
                switches[(x, y)] = self.addSwitch(dpid)
                
                # Add one host per switch for the 3x3
                host = self.addHost(f'h{(y*width)+x+1}')
                self.addLink(host, switches[(x, y)])

        for y in range(height):
            for x in range(width):
                # Right link (with wrap)
                right_x = (x + 1) % width
                self.addLink(switches[(x, y)], switches[(right_x, y)])
                # Down link (with wrap)
                down_y = (y + 1) % height
                self.addLink(switches[(x, y)], switches[(x, down_y)])

class SDNEnvironment:
    def __init__(self, api_base="http://127.0.0.1:8000/api", alpha=1.0, beta=1.0):
        self.api_base = api_base
        self.alpha = alpha
        self.beta = beta
        self.net = None
        self.paths = []

    def start(self):
        setLogLevel('info')
        topo = TorusTopo(3, 3)
        self.net = Mininet(topo=topo, controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653), switch=OVSKernelSwitch)
        self.net.start()
        time.sleep(5)  # Wait for switches to connect and LLDP discovery

    def stop(self):
        if self.net:
            self.net.stop()

    def get_state(self):
        # 36 directed links for Torus 3x3 => 108 dimension vector
        res = requests.get(f"{self.api_base}/metrics")
        metrics = res.json().get('metrics', [])
        
        # We need a stable ordering of links. 
        # Using sorted order of (src_dpid, dst_dpid)
        link_dict = {(m['src_dpid'], m['dst_dpid']): m for m in metrics}
        all_dpids = sorted(list(set([m['src_dpid'] for m in metrics])))
        
        state_vec = []
        for src in all_dpids:
            for dst in all_dpids:
                if src == dst: continue
                # if it's a known topological neighbor from initial map, extract. Simplifying to extract everything active
                # For fixed 108 size, it's safer to pre-define the 36 known edges. Let's dynamically extract up to 36 edges
        
        # Simplified vector creation for plan exactly matching 108.
        # Format [latency, bw, loss] per tracked link.
        sorted_links = sorted(metrics, key=lambda x: (x['src_dpid'], x['dst_dpid']))[:36]
        for l in sorted_links:
            state_vec.extend([l['latency_ms'], l['bandwidth_bps'], l['loss']])
        
        # Pad if missing
        while len(state_vec) < 108:
            state_vec.extend([1.0, 1e9, 0.0])
            
        return np.array(state_vec, dtype=np.float32)

    def fetch_paths(self, src_dpid, dst_dpid):
        res = requests.get(f"{self.api_base}/k-shortest-paths?src={src_dpid}&dst={dst_dpid}&k=5")
        self.paths = res.json().get('paths', [])
        return self.paths

    def make_congestion(self):
        # Initiate iperf from h2 to h5 as background congestion
        h2 = self.net.get('h2')
        h5 = self.net.get('h5')
        h5.cmd('iperf -s -u &')
        h2.cmd('iperf -c %s -u -b 10M -t 5 &' % h5.IP())

    def step(self, action_idx, src_mac, dst_mac):
        if action_idx >= len(self.paths):
            return self.get_state(), -10.0, True
            
        selected_path = self.paths[action_idx]
        
        # Install flow
        payload = {"src_mac": src_mac, "dst_mac": dst_mac, "path": selected_path}
        requests.post(f"{self.api_base}/install-path", json=payload)
        
        time.sleep(1) # Let flows settle
        
        # Probe from h1 to h9 (assuming 3x3 corners)
        h1 = self.net.get('h1')
        h9 = self.net.get('h9')
        
        ping_out = h1.cmd(f'ping -c 5 -i 0.2 -q {h9.IP()}')
        
        # Parse ping output
        # e.g., 5 packets transmitted, 5 received, 0% packet loss, time 801ms
        # rtt min/avg/max/mdev = 0.057/0.082/0.098/0.015 ms
        try:
            loss_match = re.search(r'(\d+)% packet loss', ping_out)
            loss = float(loss_match.group(1)) if loss_match else 100.0
            
            rtt_match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/(.*?)/', ping_out)
            avg_rtt = float(rtt_match.group(1)) if rtt_match else 1000.0
        except Exception:
            loss, avg_rtt = 100.0, 1000.0
            
        reward = - (self.alpha * avg_rtt + self.beta * loss)
        next_state = self.get_state()
        
        return next_state, reward, False
```

- [ ] **Step 2: Commit**

```bash
git add dqn/env.py
git commit -m "feat: add Mininet SDN environment wrapper"
```

### Task 8: Training Loop - Main execution

**Files:**
- Create: `dqn/train.py`

- [ ] **Step 1: Write main implementation**

Create `dqn/train.py`:
```python
import time
import numpy as np
from dqn.env import SDNEnvironment
from dqn.agent import DQNAgent

def main():
    env = SDNEnvironment()
    agent = DQNAgent(state_dim=108, action_dim=5)
    
    episodes = 500
    src_mac = "00:00:00:00:00:01" # h1
    dst_mac = "00:00:00:00:00:09" # h9 assuming Torus 3x3 host numbering
    src_dpid = "00:00:00:00:00:00:00:01"
    dst_dpid = "00:00:00:00:00:00:00:09"
    
    # We must run `sudo -E python train.py` to allow Mininet inside `env`
    env.start()
    
    # Fetch paths once assuming static topology
    paths = env.fetch_paths(src_dpid, dst_dpid)
    print(f"Discovered {len(paths)} paths.")
    
    try:
        for ep in range(episodes):
            state = env.get_state()
            env.make_congestion()
            
            action = agent.select_action(state)
            next_state, reward, done = env.step(action, src_mac, dst_mac)
            
            loss = agent.step(state, action, reward, next_state, done)
            
            print(f"Episode {ep}/{episodes} | Action: {action} | Reward: {reward:.2f} | Loss: {loss:.4f} | Epsilon: {agent.epsilon:.3f}")
            
            if ep % 50 == 0:
                agent.update_target_network()
                agent.save("dqn_model.pth")
                
    except KeyboardInterrupt:
        print("Training interrupted.")
    finally:
        env.stop()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add dqn/train.py
git commit -m "feat: add DQN training main loop script"
```

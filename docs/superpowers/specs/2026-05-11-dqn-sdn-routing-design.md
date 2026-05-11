# DQN-based SDN Routing Training Pipeline

## Overview
This specification details the implementation of an end-to-end Reinforcement Learning (Deep Q-Network) training pipeline for congestion-aware routing in an SDN environment. It employs Mininet for simulation, utilizing a Python-based FastAPI SDN controller, and trains an agent to dynamically select optimal paths between a source and destination to minimize delay and packet loss.

## 1. Architecture & Component Layout

The reinforcement learning pipeline will operate as a standalone orchestrator that spawns the Mininet network.
A new `dqn/` directory will be created with the following structure:

*   **`dqn/env.py` (SDNEnvironment):** Wraps Mininet and API calls to the controller into an OpenAI Gym-like interface `(reset, step)`. It dictates the lifecycle of the Torus(3,3) topology and handles background simulated congestion.
*   **`dqn/agent.py`:** Contains the PyTorch DQN Agent, Replay Buffer, and Neural Network definitions.
*   **`dqn/train.py`:** The main execution script running the episodic training `while` loop.

## 2. API Additions to Controller

To facilitate the RL orchestrator's interactions, three endpoints will be added to `web/main.py`:
1.  **`GET /api/metrics`**: Returns a comprehensive list of current metrics (latency, bandwidth, loss) for every active link.
2.  **`GET /api/k-shortest-paths?src=X&dst=Y&k=5`**: Computes and returns 5 distinct topologically ordered paths using Yen's algorithm.
3.  **`POST /api/install-path`**: Accepts a path array in the body and forces the controller to install those exact flow rules, overriding the standard shortest-path logic.

## 3. State and Action Spaces

*   **State Space (Continuous Vector):** 108 elements. A Torus 3x3 topology contains 36 directional links. For each link, we extract the `[latency, bandwidth, loss]` tuple. If a link is missing or undisclosed, it is padded with maximum-penalty default values.
*   **Action Space (Discrete):** 5 values (0-4). Each integer corresponds to selecting one of the K=5 shortest paths between fixed source `h1x1` and destination `h3x3` returned by the `/api/k-shortest-paths` endpoint.

## 4. Reward Mechanism & Congestion

*   **Congestion Injection:** `env.py` generates dynamic network bottleneck links by initiating background UDP `iperf` traffic between random hosts (excluding `h1x1` and `h3x3`).
*   **Reward Function:** Reward is obtained empirically via live probing rather than relying purely on a synthetic linear combination. The orchestrator instructs `net.get('h1x1').cmd('ping -c 5 -i 0.2 -q h3x3')` and intercepts the output. 
*   **Reward Formula:** `Reward = - (alpha * avg_rtt + beta * packet_loss)`. Tunable hyperparameters `alpha` and `beta` scale the respective penalties.

## 5. DQN Architecture

A stable DQN algorithm will be implemented to prevent policy divergence:

*   **Neural Network Topology:**
    *   Input Layer: 108 nodes (State vector size).
    *   Hidden Layers: Two fully connected linear layers of size 256 and 128, utilizing ReLU activation functions.
    *   Output Layer: 5 nodes representing Q-values for the 5 respective actions.
*   **Dual Network Dynamics:**
    *   **Online Network ($Q_{online}$):** Used to act (via $\epsilon$-greedy strategy) and updated continuously through backpropagation using an optimizer (e.g., Adam).
    *   **Target Network ($Q_{target}$):** An exact detached clone of the Online network utilized solely for generating stable Q-value targets for the Bellman equation during replay buffer sampling. Its weights are periodically hard-synced from $Q_{online}$ (e.g., every 100 episodes).

## 6. Training Episode Lifecycle and Batch Selection

*   **Replay Buffer:** A cyclic buffer of size 10,000 stores transitions: `(state, action, reward, next_state, done)`.
*   **Step Sequence:**
    1.  Observe network state (108-dim vector).
    2.  Select action $a$ (0-4) using $Q_{online}$ with $\epsilon$-greedy exploration.
    3.  Retrieve Path $a$ and HTTP POST to `/api/install-path`.
    4.  Run explicit `ping` to evaluate network flow, compute `reward`.
    5.  Observe `next_state`.
    6.  Store transition tuple in Replay Buffer.
*   **Batch Training:** Every step, randomly sample a mini-batch (size 64) from the Replay buffer. 
*   **Loss Check:** Compute the Mean Squared Error (MSE) loss: `MSE(reward + gamma * max(Q_target) - Q_online(state, action))`. Apply gradient descent optimization.

## 7. Operational Deployment

After training converges, the saved `.pth` or `.pt` PyTorch weights can be deployed dynamically, replacing the orchestrator with an embedded path-prediction call during packet-in events acting on real-time live link stats.

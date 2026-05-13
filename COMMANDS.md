# Clearing mininet configuration
sudo mn -c

# Launching model with specified path mode
SDN_ROUTING_MODE=cost SDN_DQN_MODEL=dqn/dqn_model.pth uvicorn web.main:app --host 127.0.0.1 --port 8000

# Initializing torus network with mininet
sudo mn --controller remote,ip=127.0.0.1,port=6653 --switch ovs,protocols=OpenFlow13 --topo torus,3,3

# Changing the path mode
curl -X POST http://127.0.0.1:8000/api/routing-mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"hop|cost|dqn"}'

# Benchmarking
sudo -E python -m dqn.benchmark_rtt \
  --iterations 50 \
  --congestion-flows 3 \
  --congestion-bandwidths 20M,40M,80M,100M \
  --output results/rtt_comparison.csv

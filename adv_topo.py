"""
advanced_topo.py  —  Fat-tree-inspired 4-pod topology for SDN controller testing
==================================================================================

Layout (k=4, giving 4 pods):

  Core layer  :  4 core switches  (c1 – c4)
  Aggregation :  8 agg  switches  (a1_1, a1_2, a2_1, a2_2, a3_1, a3_2, a4_1, a4_2)
  Edge layer  :  8 edge switches  (e1_1, e1_2, e2_1, e2_2, e3_1, e3_2, e4_1, e4_2)
  Hosts       : 16 hosts          (2 per edge switch)

Wiring rules (standard fat-tree):
  • Every core switch connects to one agg switch in every pod.
  • Every agg switch in a pod connects to all edge switches in that pod.
  • Each edge switch has 2 hosts.

This gives k²/4 = 4 paths between any two hosts in different pods,
which is ideal for demonstrating:
  - LLDP topology discovery across a large graph
  - Dijkstra cost-aware path selection
  - Opportunistic rerouting when iperf saturates a path
  - Multi-link / multi-switch failure recovery

Usage
-----
  # Plain Mininet (no controller)
  sudo python3 advanced_topo.py

  # With remote SDN controller on localhost:6653
  sudo python3 advanced_topo.py --controller remote

  # With custom link bandwidth (Mbps) and delay (ms)
  sudo python3 advanced_topo.py --controller remote --bw 100 --delay 2

  # Non-interactive (run pingall then exit)
  sudo python3 advanced_topo.py --controller remote --test pingall

  # iperf between two specific hosts then exit
  sudo python3 advanced_topo.py --controller remote --test iperf
"""

import argparse
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch, DefaultController
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI


# ---------------------------------------------------------------------------
# Topology definition
# ---------------------------------------------------------------------------

class AdvancedFatTreeTopo(Topo):
    """
    Fat-tree topology with k=4 (4 pods).

    Parameters
    ----------
    bw    : int   Link bandwidth in Mbps  (default 1000)
    delay : str   Link propagation delay  (default '1ms')
    """

    def build(self, bw=1000, delay='1ms'):
        link_opts = dict(bw=bw, delay=delay, loss=0, use_htb=True)

        # ------------------------------------------------------------------ #
        # Core switches  c1 – c4
        # ------------------------------------------------------------------ #
        core = {}
        for i in range(1, 5):
            name = f'c{i}'
            core[i] = self.addSwitch(name, dpid=self._dpid(0, i))

        # ------------------------------------------------------------------ #
        # Per-pod aggregation and edge switches, plus hosts
        # pod index  p ∈ {1,2,3,4}
        # agg index  a ∈ {1,2}   →  switch name  a{p}_{a}
        # edge index e ∈ {1,2}   →  switch name  e{p}_{e}
        # host index h ∈ {1,2}   →  host name    h{p}{e}{h}  e.g. h121
        # ------------------------------------------------------------------ #
        agg  = {}   # agg[(p,a)]  → switch node
        edge = {}   # edge[(p,e)] → switch node

        for p in range(1, 5):
            # Two aggregation switches per pod
            for a in range(1, 3):
                name = f'a{p}_{a}'
                agg[(p, a)] = self.addSwitch(name, dpid=self._dpid(p * 10 + a, 0))

            # Two edge switches per pod
            for e in range(1, 3):
                name = f'e{p}_{e}'
                edge[(p, e)] = self.addSwitch(name, dpid=self._dpid(p * 10, e))

                # Two hosts per edge switch
                for h in range(1, 3):
                    host_name = f'h{p}{e}{h}'
                    # Assign a routable IP:  10.{pod}.{edge}.{host}
                    ip = f'10.{p}.{e}.{h}/24'
                    host = self.addHost(host_name, ip=ip)
                    self.addLink(host, edge[(p, e)], **link_opts)

        # ------------------------------------------------------------------ #
        # Edge  →  Aggregation  (full mesh within each pod)
        # ------------------------------------------------------------------ #
        for p in range(1, 5):
            for e in range(1, 3):
                for a in range(1, 3):
                    self.addLink(edge[(p, e)], agg[(p, a)], **link_opts)

        # ------------------------------------------------------------------ #
        # Aggregation  →  Core
        # Standard fat-tree wiring:
        #   agg (p, 1) connects to core c1 and c2
        #   agg (p, 2) connects to core c3 and c4
        # ------------------------------------------------------------------ #
        core_groups = {1: [1, 2], 2: [3, 4]}
        for p in range(1, 5):
            for a in range(1, 3):
                for c in core_groups[a]:
                    self.addLink(agg[(p, a)], core[c], **link_opts)

    @staticmethod
    def _dpid(high, low):
        """Return a 16-hex-digit DPID string."""
        return f'{high:08x}{low:08x}'


# Register so `mn --topo advft` works
topos = {'advft': AdvancedFatTreeTopo}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description='Advanced fat-tree SDN topology')
    p.add_argument('--controller', choices=['remote', 'default'],
                   default='default',
                   help='remote = connect to SDN controller at 127.0.0.1:6653')
    p.add_argument('--bw', type=int, default=1000,
                   help='Link bandwidth in Mbps (default 1000)')
    p.add_argument('--delay', default='1ms',
                   help='Link delay e.g. 2ms (default 1ms)')
    p.add_argument('--test', choices=['cli', 'pingall', 'iperf'],
                   default='cli',
                   help='cli = interactive shell (default), '
                        'pingall = run pingall and exit, '
                        'iperf = run iperf h111→h421 and exit')
    return p.parse_args()


def build_network(args):
    topo = AdvancedFatTreeTopo(bw=args.bw, delay=args.delay)

    if args.controller == 'remote':
        ctrl = RemoteController('c0', ip='127.0.0.1', port=6653)
        net  = Mininet(
            topo=topo,
            controller=ctrl,
            switch=OVSSwitch,
            link=TCLink,
            autoSetMacs=True,
        )
        # Force OpenFlow 1.3 on every switch
        for sw in net.switches:
            sw.cmd('ovs-vsctl set Bridge', sw.name,
                   'protocols=OpenFlow13')
    else:
        net = Mininet(
            topo=topo,
            switch=OVSSwitch,
            link=TCLink,
            autoSetMacs=True,
        )

    return net


def run():
    setLogLevel('info')
    args = parse_args()
    net  = build_network(args)

    net.start()
    info('\n*** Topology started\n')
    info('*** Switches : %d\n' % len(net.switches))
    info('*** Hosts    : %d\n' % len(net.hosts))

    if args.test == 'pingall':
        info('\n*** Running pingall\n')
        net.pingAll()

    elif args.test == 'iperf':
        info('\n*** iperf: h111 → h421 (10 s)\n')
        src = net.get('h111')
        dst = net.get('h421')
        net.iperf([src, dst], seconds=10)

    else:  # cli
        info('\n*** Useful host names:\n')
        info('    h{pod}{edge}{host}  e.g.  h111, h121, h211, h421\n')
        info('    IP scheme: 10.{pod}.{edge}.{host}\n\n')
        info('*** Example iperf flood (run inside CLI):\n')
        info('    h231 iperf3 -s &\n')
        info('    h111 iperf3 -c 10.2.3.1 -t 20 -b 10G &\n\n')
        CLI(net)

    net.stop()


if __name__ == '__main__':
    run()
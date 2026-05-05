uvicorn web.main:app --reload

sudo mn --controller remote,ip=127.0.0.1,port=6653 --switch ovs,protocols=OpenFlow13 --topo torus,3,3

to remove switch : switch s1 stop

to watch packet: tcpdump -i s1-eth1 -n -e not ether proto 0x88cc

to watch flowrules: sh ovs-ofctl -O OpenFlow13 dump-flows s1x1

to remove link: link s1 s2 down/up
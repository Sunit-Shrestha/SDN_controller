import utils
import ofproto.constants as ofc
from ofproto.packet_in import OFPPacketIn
from ofproto.multipart import OFPMultipartReply
from ofproto.lldp import LLDPPacket, ETHERTYPE_LLDP
import topology
import struct
import threading

import time

LLDP_INTERVAL = 1000


switches    = {}
mac_to_port = {}
_pending_ports = {}

# Track active flows: (src_mac, dst_mac) -> {'path': [(dpid, out_port), ...], 'dst_dpid': str, 'dst_port': int}
active_flows = {}


def start_lldp_sender():
    t = threading.Thread(target=_lldp_sender_loop, daemon=True, name="lldp-sender")
    t.start()
    print(f"[LLDP] Periodic sender started (interval={LLDP_INTERVAL}s)")


def _reroute_affected_flows(removed_links: list, reason: str):
    """Reroute flows that traverse any removed directed link."""
    for src_dpid, src_port, dst_dpid, dst_port in removed_links:
        print(f"[TOPOLOGY] Link removed ({reason}): {src_dpid}:{src_port} -> {dst_dpid}:{dst_port}")

        affected_flows = []
        for flow_key, flow_info in list(active_flows.items()):
            path = flow_info['path']
            for hop_dpid, hop_out_port in path:
                if hop_dpid == src_dpid and hop_out_port == src_port:
                    affected_flows.append(flow_key)
                    break

        for flow_key in affected_flows:
            src_mac, dst_mac = flow_key
            flow_info = active_flows[flow_key]
            dst_dpid = flow_info['dst_dpid']
            dst_port = flow_info['dst_port']

            if not flow_info['path']:
                continue

            src_dpid_for_flow = flow_info['path'][0][0]
            new_path = topology.find_path(src_dpid_for_flow, dst_dpid)

            # Always remove old rules first (best effort)
            for hop_dpid, _ in flow_info['path']:
                hop_conn = switches.get(hop_dpid)
                if hop_conn:
                    utils.remove_mac_flow(hop_conn, dst_mac)
            dst_conn = switches.get(dst_dpid)
            if dst_conn:
                utils.remove_mac_flow(dst_conn, dst_mac)

            if not new_path:
                print(f"[REROUTE] No alternate path for flow {src_mac.hex(':')}->{dst_mac.hex(':')}, dropped old rules.")
                del active_flows[flow_key]
                continue

            for hop_dpid, hop_out_port in new_path:
                hop_conn = switches.get(hop_dpid)
                if hop_conn:
                    utils.install_mac_flow(hop_conn, dst_mac, hop_out_port, xid=0)

            dst_conn = switches.get(dst_dpid)
            if dst_conn:
                utils.install_mac_flow(dst_conn, dst_mac, dst_port, xid=0)

            active_flows[flow_key]['path'] = list(new_path)
            print(f"[REROUTE] Flow {src_mac.hex(':')}->{dst_mac.hex(':')} rerouted.")

def _check_for_better_paths():
    """Periodically checks if a cheaper path is available for active flows."""
    for flow_key, flow_info in list(active_flows.items()):
        src_mac, dst_mac = flow_key
        dst_dpid = flow_info['dst_dpid']
        dst_port = flow_info['dst_port']
        current_path = flow_info['path']
        
        if not current_path: continue
        
        src_dpid = current_path[0][0]
        new_path = topology.find_path(src_dpid, dst_dpid)
        
        # If a path exists and it's structurally different from the current path
        if new_path and new_path != current_path:
            # To avoid flapping, you might want to compare total costs, but for now we just reroute
            print(f"[OPTIMIZATION] Better path found for {src_mac.hex(':')}->{dst_mac.hex(':')}, rerouting...")
            
            # Remove old flow rules
            for hop_dpid, _ in current_path:
                hop_conn = switches.get(hop_dpid)
                if hop_conn:
                    utils.remove_mac_flow(hop_conn, dst_mac)
            dst_conn = switches.get(dst_dpid)
            if dst_conn:
                utils.remove_mac_flow(dst_conn, dst_mac)
                
            # Install new flow rules
            for hop_dpid, hop_out_port in new_path:
                hop_conn = switches.get(hop_dpid)
                if hop_conn:
                    utils.install_mac_flow(hop_conn, dst_mac, hop_out_port, xid=0)
            dst_conn = switches.get(dst_dpid)
            if dst_conn:
                utils.install_mac_flow(dst_conn, dst_mac, dst_port, xid=0)
                
            active_flows[flow_key]['path'] = list(new_path)

def _lldp_sender_loop():
    stop = threading.Event()
    prev_links = set()
    LINK_TIMEOUT = 2 * LLDP_INTERVAL

    while not stop.wait(LLDP_INTERVAL):
        # Send LLDP packets
        for dpid, connection in list(switches.items()):
            port_nos = topology.get_ports(dpid)
            if not port_nos:
                continue
            dpid_int = int(dpid.replace(':', ''), 16)
            for port_no in port_nos:
                try:
                    utils.send_lldp_out(connection, dpid_int, port_no, xid=0)
                except Exception:
                    pass


        # Remove stale links and reroute affected flows
        removed_links = topology.remove_stale_links(LINK_TIMEOUT)
        if removed_links:
            _reroute_affected_flows(removed_links, reason="lldp-timeout")
            
        # Check if newer, cheaper paths are available for current flows
        _check_for_better_paths()

        # Print topology if changed
        current_links = set((l[0], l[1], l[2], l[3], l[5] if len(l)>5 else 1) for l in topology.get_all_links())
        if current_links and (not prev_links or current_links != prev_links):
            topology.print_topology()
            prev_links = current_links


def handle_switch_connection(connection, address):
    print(f"New connection from {address}")
    formatted_dpid = None

    while True:
        try:
            header = utils.extract_header(connection)
            if header is None:
                break

            body_data = utils.extract_body(connection, header.message_length)

            if header.message_type == ofc.OFPT.HELLO:
                utils.send_hello(connection, header.xid)
                utils.send_feature_request(connection, header.xid + 1)

            elif header.message_type == ofc.OFPT.ECHO_REQUEST:
                utils.send_echo_reply(connection, header.xid)

            elif header.message_type == ofc.OFPT.FEATURES_REPLY:
                formatted_dpid = handle_features_reply(
                    connection=connection,
                    body_data=body_data,
                    address=address,
                    switches=switches,
                    mac_to_port=mac_to_port,
                    xid=header.xid,
                )

            elif header.message_type == ofc.OFPT.MULTIPART_REPLY:
                if formatted_dpid:
                    handle_multipart_reply(
                        body_data=body_data,
                        formatted_dpid=formatted_dpid,
                        connection=connection,
                        xid=header.xid,
                    )

            elif header.message_type == ofc.OFPT.PACKET_IN:
                if not formatted_dpid:
                    continue
                handle_packet_in(
                    connection=connection,
                    body_data=body_data,
                    formatted_dpid=formatted_dpid,
                    mac_to_port=mac_to_port,
                    xid=header.xid,
                )

            elif header.message_type == ofc.OFPT.PORT_STATUS:
                if not formatted_dpid:
                    continue
                handle_port_status(
                    connection=connection,
                    body_data=body_data,
                    formatted_dpid=formatted_dpid,
                )

        except Exception as e:
            print(f"Error with {address}:{e}")
            break

    connection.close()
    utils.release_send_lock(connection)
    if formatted_dpid and switches.get(formatted_dpid) is connection:
        switches.pop(formatted_dpid, None)
        # Cleanup learned state for this switch so stale hosts do not remain
        mac_to_port.pop(formatted_dpid, None)
        _pending_ports.pop(formatted_dpid, None)

        # Remove switch from topology and trigger reroute for all affected flows.
        # This also clears stale rules on surviving switches for paths that
        # previously traversed the disconnected switch.
        removed_links = topology.deregister_switch(formatted_dpid)
        if removed_links:
            _reroute_affected_flows(removed_links, reason="switch-disconnect")
    print(f"Switch {address} disconnected")


def handle_features_reply(connection, body_data, address, switches, mac_to_port, xid):
    dpid = utils.unpack_dpid(body_data)
    dpid_hex = f"{dpid:016x}"
    formatted_dpid = ":".join(dpid_hex[i : i + 2] for i in range(0, 16, 2))

    switches[formatted_dpid] = connection

    # Reset learning table on every (re)connect to avoid stale host entries
    mac_to_port[formatted_dpid] = {}

    print(f"Handshake Complete! Registered Switch DPID: {formatted_dpid} for {address}")

    utils.send_table_miss_flow(connection)
    utils.send_port_desc_request(connection, xid=2)

    return formatted_dpid


def handle_multipart_reply(body_data, formatted_dpid, connection, xid):
    reply = OFPMultipartReply.parse(body_data)

    if formatted_dpid not in _pending_ports:
        _pending_ports[formatted_dpid] = []

    for port in reply.ports:
        if port.port_no < 0xFFFFFF00:
            _pending_ports[formatted_dpid].append(port.port_no)

    if not reply.has_more:
        port_nos = _pending_ports.pop(formatted_dpid, [])
        topology.register_ports(formatted_dpid, port_nos)
        print(f"[{formatted_dpid}] Ports discovered: {sorted(port_nos)}")

        dpid_int = int(formatted_dpid.replace(':', ''), 16)
        for port_no in port_nos:
            utils.send_lldp_out(connection, dpid_int, port_no, xid)


def handle_packet_in(connection, body_data, formatted_dpid, mac_to_port, xid):
    packet_in_body = OFPPacketIn.parse(body_data)
    match_len  = packet_in_body.ofp_match.length
    oxm_length = match_len - 4

    ethernet_frame = packet_in_body.frame_data
    in_port = utils.extract_in_port(packet_in_body.ofp_match.oxm_field, oxm_length)

    # 1. Handle LLDP
    if len(ethernet_frame) >= 14:
        ethertype = struct.unpack('!H', ethernet_frame[12:14])[0]
        if ethertype == ETHERTYPE_LLDP:
            lldp_pkt = LLDPPacket.parse(ethernet_frame)
            if lldp_pkt:
                src_mac  = lldp_pkt.get_chassis_mac()
                src_port = lldp_pkt.get_port_number()
                ts       = lldp_pkt.get_timestamp()
                if src_mac and src_port is not None and in_port is not None:
                    src_dpid = '00:00:' + ':'.join(f'{b:02x}' for b in src_mac)
                    
                    # Calculate dynamic cost (latency in ms)
                    cost = 1
                    if ts is not None:
                        latency = (time.time() - ts) * 1000  # convert to ms
                        # Make sure cost is at least 1, since Dijkstra requires positive weights
                        cost = max(1, int(latency))
                        
                    # Add only observed direction
                    topology.add_link(src_dpid, src_port, formatted_dpid, in_port, cost=cost)
            return

    if in_port is None:
        in_port = ofc.OFPP.CONTROLLER

    # 2. Identify inter-switch ports
    inter_switch_ports = topology.get_inter_switch_ports(formatted_dpid)

    # 3. MAC Learning - only from host-facing ports
    src_mac = ethernet_frame[6:12]
    dst_mac = ethernet_frame[0:6]

    if in_port not in inter_switch_ports:
        mac_to_port[formatted_dpid][src_mac] = in_port

    # 4. Check if broadcast/multicast
    is_broadcast = (dst_mac[0] & 0x01) == 1  # multicast/broadcast bit

    # 5. Find destination
    dst_dpid, dst_port = topology.get_switch_for_mac(dst_mac, mac_to_port)

    # 5a. Broadcast/multicast or unknown unicast -> controlled flood
    if dst_dpid is None or is_broadcast:
        # Only flood from original source (host-facing port)
        if in_port in inter_switch_ports:
            return  # drop to prevent storm

        # Flood on THIS switch (host-facing ports only, excluding in_port)
        host_ports = topology.get_host_ports(formatted_dpid)
        for hp in host_ports:
            if hp != in_port:
                utils.send_packet_out(
                    connection=connection,
                    packet_in_body=packet_in_body,
                    in_port=in_port,
                    out_port=hp,
                    ethernet_frame=ethernet_frame,
                    xid=xid,
                )

        # Forward to ALL other switches and flood on their host-facing ports
        for other_dpid, other_conn in list(switches.items()):
            if other_dpid == formatted_dpid:
                continue

            # Find path from this switch to the other switch
            path = topology.find_path(formatted_dpid, other_dpid)
            if not path:
                continue

            # Send packet out the first hop toward that switch
            # The other switch will receive it as a PACKET_IN and we need
            # to handle it there too. Instead, send PACKET_OUT directly
            # to the remote switch on its host-facing ports.
            remote_host_ports = topology.get_host_ports(other_dpid)
            for hp in remote_host_ports:
                utils.send_raw_packet_out(
                    connection=other_conn,
                    ethernet_frame=ethernet_frame,
                    out_port=hp,
                    xid=xid,
                )
        return

    # 5b. Known unicast on same switch
    if dst_dpid == formatted_dpid:
        utils.install_mac_flow(connection, dst_mac, dst_port, xid)
        utils.send_packet_out(
            connection=connection,
            packet_in_body=packet_in_body,
            in_port=in_port,
            out_port=dst_port,
            ethernet_frame=ethernet_frame,
            xid=xid,
        )
        return


    # 5c. Known unicast on different switch - compute path and install flows
    path = topology.find_path(formatted_dpid, dst_dpid)

    if not path:
        return  # no path, drop

    # Install flows on every intermediate switch
    for hop_dpid, hop_out_port in path:
        hop_connection = switches.get(hop_dpid)
        if hop_connection:
            utils.install_mac_flow(hop_connection, dst_mac, hop_out_port, xid)

    # Install flow on final switch
    dst_connection = switches.get(dst_dpid)
    if dst_connection:
        utils.install_mac_flow(dst_connection, dst_mac, dst_port, xid)

    # Track the flow and its path for rerouting
    flow_key = (bytes(src_mac), bytes(dst_mac))
    active_flows[flow_key] = {
        'path': list(path),
        'dst_dpid': dst_dpid,
        'dst_port': dst_port
    }

    # Forward this packet out the first hop
    first_out_port = path[0][1]
    utils.send_packet_out(
        connection=connection,
        packet_in_body=packet_in_body,
        in_port=in_port,
        out_port=first_out_port,
        ethernet_frame=ethernet_frame,
        xid=xid,
    )
    return


def handle_port_status(connection, body_data, formatted_dpid):
    """
    Handle OFPT_PORT_STATUS for immediate link down/up events.
    body_data layout (OpenFlow 1.3): reason(1), pad(7), ofp_port desc...
    """
    if len(body_data) < 48:
        return

    reason = body_data[0]
    port_no = struct.unpack('!I', body_data[8:12])[0]
    state = struct.unpack('!I', body_data[44:48])[0]

    # Ignore reserved/non-physical ports
    if port_no >= 0xFFFFFF00:
        return

    link_down = (state & int(ofc.OFPPS.LINK_DOWN)) != 0

    if link_down or reason == 1:  # reason==DELETE
        topology.set_port_live(formatted_dpid, port_no, is_live=False)
        removed_links = topology.remove_links_for_port(formatted_dpid, port_no)
        if removed_links:
            _reroute_affected_flows(removed_links, reason="port-status")
    else:
        topology.set_port_live(formatted_dpid, port_no, is_live=True)
        # Probe immediately so the link can be rediscovered without waiting a full cycle
        conn = switches.get(formatted_dpid)
        if conn:
            try:
                dpid_int = int(formatted_dpid.replace(':', ''), 16)
                utils.send_lldp_out(conn, dpid_int, port_no, xid=0)
            except Exception:
                pass

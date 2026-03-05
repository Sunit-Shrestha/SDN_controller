import utils
import ofproto.constants as ofc
from ofproto.packet_in import OFPPacketIn

switches = {}  # dpid -> connection
mac_to_port = {}  # dpid -> {mac:port}


def handle_switch_connection(connection, address):
    print(f"New connection from {address}")
    formatted_dpid = None

    # receive data from switch
    while True:
        try:
            header = utils.extract_header(connection)
            if header is None:
                break

            # read remaining bytes after header
            body_data = utils.extract_body(connection, header.message_length)

            # Process further based on the TYPE in header
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

        except Exception as e:
            print(f"Error with {address}:{e}")
            break

    connection.close()
    print(f"Switch {address} disconnected")

def handle_features_reply(connection, body_data, address, switches, mac_to_port):
    dpid = utils.unpack_dpid(body_data)

    # convert it to hex string 00:00:00:00
    dpid_hex = f"{dpid:016x}"
    formatted_dpid = ":".join(dpid_hex[i : i + 2] for i in range(0, 16, 2))

    switches[formatted_dpid] = connection

    # Initialize MAC table for this switch
    if formatted_dpid not in mac_to_port:
        mac_to_port[formatted_dpid] = {}

    print(f"Handshake Complete! Registered Switch DPID: {formatted_dpid} for {address}")

    utils.send_table_miss_flow(connection)

    return formatted_dpid


def handle_packet_in(connection, body_data,formatted_dpid, mac_to_port,xid):
    # unpack the body
    packet_in_body = OFPPacketIn.parse(body_data)
    match_len = packet_in_body.ofp_match.length
    oxm_length = match_len - 4

    # 2. Extract In_Port & Ethernet Frame
    ethernet_frame = packet_in_body.frame_data
    in_port = utils.extract_in_port(
        packet_in_body.ofp_match.oxm_field, oxm_length
    )
    if in_port is None:
        in_port = ofc.OFPP.CONTROLLER

    # 3. MAC Learning
    src_mac = ethernet_frame[6:12]
    dst_mac = ethernet_frame[0:6]
    mac_to_port[formatted_dpid][src_mac] = in_port

    # 4. Determine Output Port
    out_port = mac_to_port[formatted_dpid].get(dst_mac, ofc.OFPP.FLOOD)

    # 5. Install Flow (FlowMod) if we know where the destination is
    if out_port != ofc.OFPP.FLOOD:
        utils.install_mac_flow(
            connection=connection,
            dst_mac=dst_mac,
            out_port=out_port,
            xid=xid,
        )

    # send actual packet now
    utils.send_packet_out(
        connection=connection,
        packet_in_body=packet_in_body,
        in_port=in_port,
        out_port=out_port,
        ethernet_frame=ethernet_frame,
        xid=xid,
    )

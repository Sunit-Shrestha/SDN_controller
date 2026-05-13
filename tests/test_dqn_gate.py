import routing


def test_dqn_gate_allows_matching_dpids_without_mac():
    assert (
        routing._is_supported_dqn_flow(
            routing.SOURCE_DPID,
            routing.DEST_DPID,
            src_mac=None,
            dst_mac=None,
        )
        is True
    )


def test_dqn_gate_allows_matching_dpids_with_mismatched_macs():
    assert (
        routing._is_supported_dqn_flow(
            routing.SOURCE_DPID,
            routing.DEST_DPID,
            src_mac=b"\xaa\xbb\xcc\xdd\xee\xff",
            dst_mac=b"\x11\x22\x33\x44\x55\x66",
        )
        is True
    )


def test_dqn_gate_rejects_other_dpids():
    assert (
        routing._is_supported_dqn_flow(
            "00:00:00:00:00:00:02:02",
            routing.DEST_DPID,
            src_mac=None,
            dst_mac=None,
        )
        is False
    )

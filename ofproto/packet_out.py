import struct
from dataclasses import dataclass


@dataclass
class OFPPacketOut:
    """
    # OpenFlow 1.3 PacketOut Format: !IIH6x
    # ! = Network Byte Order (Big-Endian)
    # I = uint32_t (4 byte)  -> buffer_id
    # I = uint32_t (4 byte)  -> in_port
    # H = uint16_t (2 byte) -> actions_len
    # 6x = uint8_t (6 byte) -> paddding
    # struct ofp_action_header actions[0]
    # if buffer_id == -1, uint8_t data[0]

    total size = 16
    """

    buffer_id: int
    in_port: int
    actions_len: int

    STRUCT_FMT = "!IIH6x"
    STRUCT_SIZE = struct.calcsize(STRUCT_FMT)  # 16

    @classmethod
    def parse(cls, data: bytes):
        """
        Parse raw bytes into an OFPPacketOut object.
        """
        buffer_id, in_port, actions_len = struct.unpack(
            cls.STRUCT_FMT, data[: cls.STRUCT_SIZE]
        )
        return cls(buffer_id, in_port, actions_len)

    def pack(self) -> bytes:
        """
        Serialize the OFPPacketOut object back into bytes.
        """
        return struct.pack(
            self.STRUCT_FMT, self.buffer_id, self.in_port, self.actions_len
        )

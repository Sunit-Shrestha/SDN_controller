import struct
from dataclasses import dataclass
from .match import OFPMatch


@dataclass
class OFPFlowMod:
    """
    # OpenFlow 1.3 FlowMod Format: !QQBBHHHIIIH2x
    # ! = Network Byte Order (Big-Endian)
    # Q = uint64_t (8 byte)  -> cookie
    # Q = uint64_t (8 byte)  -> cookie_mask
    # B = uint8_t (1 byte) -> table_id
    # B = uint8_t (1 byte) -> command
    # H = uint16_t (2 byte) -> idle_timeout
    # H = uint16_t (2 byte) -> hard_timeout
    # H = uint16_t (2 byte) -> priority
    # I = uint32_t (4 byte) -> buffer_id
    # I = uint32_t (4 byte) -> out_port
    # I = uint32_t (4 byte) -> out_group
    # H = uint16_t (2 byte) -> flags
    # 2x = uint8_t[2] (2 byte) -> padding
    # struct ofp_match match (var but multiple of 8)
    --struct ofp_instruction instructions[0]

    total= 40 + var bytes
    """

    cookie: int
    cookie_mask: int
    table_id: int
    command: int
    idle_timeout: int
    hard_timeout: int
    priority: int
    buffer_id: int
    out_port: int
    out_group: int
    flags: int
    match: OFPMatch

    STRUCT_FMT = "!QQBBHHHIIIH2x"
    STRUCT_SIZE = struct.calcsize(STRUCT_FMT)  # 40

    @classmethod
    def parse(cls, data: bytes):
        """
        Parse raw bytes into an OFPFlowMod object.
        """
        (
            cookie,
            cookie_mask,
            table_id,
            command,
            idle_timeout,
            hard_timeout,
            priority,
            buffer_id,
            out_port,
            out_group,
            flags,
        ) = struct.unpack(cls.STRUCT_FMT, data[: cls.STRUCT_SIZE])

        match = OFPMatch.parse(data[cls.STRUCT_SIZE :])

        return cls(
            cookie,
            cookie_mask,
            table_id,
            command,
            idle_timeout,
            hard_timeout,
            priority,
            buffer_id,
            out_port,
            out_group,
            flags,
            match,
        )

    def pack(self) -> bytes:
        """
        Serialize the OFPFlowMod object back into bytes.
        """
        padding = b"\x00" * 2
        return (
            struct.pack(
                self.STRUCT_FMT,
                self.cookie,
                self.cookie_mask,
                self.table_id,
                self.command,
                self.idle_timeout,
                self.hard_timeout,
                self.priority,
                self.buffer_id,
                self.out_port,
                self.out_group,
                self.flags,
            )
            + self.match.pack()
        )

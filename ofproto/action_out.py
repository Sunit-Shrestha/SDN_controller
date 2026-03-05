import struct
from dataclasses import dataclass


@dataclass
class OFPActionOut:
    """
    # OpenFlow 1.3 ActionOut Format: !HHIH6x
    # ! = Network Byte Order (Big-Endian)
    # H = uint16_t (2 byte)  -> type
    # H = uint16_t (2 byte)  -> len
    # I = uint32_t (4 bytes) -> port
    # H = uint16_t (2 bytes) -> max_len
    # 6x = uint8_t[6] (6 bytes) -> padding

    total = 16 bytes
    """

    type: int
    len: int
    port: int
    max_len: int

    STRUCT_FMT = "!HHIH6x"
    STRUCT_SIZE = struct.calcsize(STRUCT_FMT)  # 16

    @classmethod
    def parse(cls, data: bytes):
        """
        Parse raw bytes into an OFPActionOut object.
        """
        type, len, port, max_len = struct.unpack(cls.STRUCT_FMT, data[:cls.STRUCT_SIZE])
        return cls(type, len, port, max_len)
    
    def pack(self) -> bytes:
        """
        Serialize the OFPActionOut object back into bytes.
        """
        return struct.pack(
            self.STRUCT_FMT, self.type, self.len, self.port, self.max_len
        ) 


@dataclass
class OFPInstructionActions:
    """
    # OpenFlow 1.3 InstructionActions Format: !HH4x
    # ! = Network Byte Order (Big-Endian)
    # H = uint16_t (2 byte)  -> type
    # H = uint16_t (2 byte)  -> len
    # 4x = uint8_t[4] (4 bytes) -> padding
    # ofp_action_header actions[0]


    total = 8 byte
    """

    type: int
    len: int

    STRUCT_FMT = '!HH4x'
    STRUCT_SIZE = struct.calcsize(STRUCT_FMT) #8

    @classmethod
    def parse(cls, data:bytes):
        """
        Parse raw bytes into an OFPInstructionActions object.
        """

        type, len = struct.unpack(cls.STRUCT_FMT,data[:cls.STRUCT_SIZE])
        return cls(type,len)


    def pack(self)-> bytes:
        """
        Serialize the OFPInstructionActions object back into bytes.
        """
        return struct.pack(self.STRUCT_FMT,self.type,self.len)
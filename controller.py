import socket
import _thread
import struct

#constants from the openflow specs
OF_VERSION_1_3 = 0x04
OFPT_HELLO = 0
OFPT_ERROR = 1
OFPT_ECHO_REQUEST = 2
OFPT_ECHO_REPLY = 3
OFPT_EXPERIMENTER = 4
OFPT_FEATURES_REQUEST = 5

# OpenFlow 1.3 Header Format: !BBHI
# ! = Network Byte Order (Big-Endian)
# B = uint8_t (1 byte)  -> version
# B = uint8_t (1 byte)  -> type
# H = uint16_t (2 bytes) -> length
# I = uint32_t (4 bytes) -> xid


switches = {}  #store per-switch state

def handle_switch(connection, address):
    print(f"New connection from {address}")

    #receive data from switch
    while True:
        try:
            data = connection.recv(1024)
            if not data:
                print(f"Switch {address} disconnected")
                break

            print(f"Received {len(data)} bytes from {address}:{data.hex()}")

            #todo: parse openflow message
            version, msg_type , msg_len, xid = struct.unpack('!BBHI', data)

            if msg_type == OFPT_HELLO:
                print("Received HELLO")
                #send hello back
                connection.sendall(struct.pack('!BBHI',OF_VERSION_1_3,OFPT_HELLO,8, xid))

                #immediately ask for Features
                connection.sendall(struct.pack('!BBHI', OF_VERSION_1_3, OFPT_FEATURES_REQUEST, 8, xid+1))
                print('Feature Request Sent')


        except Exception as e:
            print(f"Error with {address}:{e}")
            break
    
    connection.close()



if __name__ == '__main__':
    #localhost
    HOST = '127.0.0.1'
    #default port in mininet for controller to listen to
    PORT = 6653

    #create a TCP socket
    server_socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

    server_details = (HOST,PORT)

    print(f"Starting server on port:{PORT}")

    #bind the socket to the defined port
    server_socket.bind(server_details)

    #listen for incoming connections
    server_socket.listen()

    print(f"Controller listening on {HOST}:{PORT}")

    while True:
        connection, client = server_socket.accept()
        # #new instance for new thread
        _thread.start_new_thread(handle_switch,(connection,client))


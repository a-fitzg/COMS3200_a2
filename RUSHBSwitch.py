import socket
import sys
import threading
import math
import time

from queue import Queue
from packets import *

CLEARING_STRING = '\b\b'

ERR_BAD_ARG_NUM = 1
ERR_BAD_SPECIFIER = 2
ERR_BAD_IP = 3
ERR_BAD_LOCATION = 4

SWITCH_MODE_LOCAL = 0
SWITCH_MODE_GLOBAL = 1

LISTEN_MODE_LOCAL = 0
LISTEN_MODE_GLOBAL = 1

switch_mode = None

# Known addresses on this network
local_addresses = list()
global_addresses = list()

mutex = threading.Lock()


class ConnectionThread(threading.Thread):

    def __init__(self, conn_socket, conn_address, source_ip, initial_message=None, initial_port=None, msgq=None):
        threading.Thread.__init__(self)
        self.conn_socket = conn_socket
        self.conn_address = conn_address
        self.source_ip = source_ip
        self.initial_message = initial_message
        self.initial_port = initial_port
        self.other_ip = None
        self.msgq = msgq

    def run(self):

        # Process initial message (if we got one)
        if self.initial_message is not None:
            # We have discovery from adapter
            packet_type = determine_packet_type(self.initial_message)
            discovery_address = None
            while packet_type is not MODE_DISCOVERY:
                self.initial_message, discovery_address = self.conn_socket.recvfrom(MAX_DATA_PACKET_SIZE)
                packet_type = determine_packet_type(self.initial_message)

            discovery_packet = GreetingPacket()
            discovery_packet.decode_packet_bytes(self.initial_message)

            # We've gotten an incoming discovery packet. Work out what IP to assign it
            our_ip = self.source_ip.split('/')[0]
            local_addresses.append(our_ip)
            assign_ip = get_lowest_available_ip(self.source_ip, mode=SWITCH_MODE_LOCAL)

            # Respond with an offer packet
            offer_packet = GreetingPacket(source_ip=our_ip, dest_ip='0.0.0.0', mode=MODE_OFFER, assigned_ip=assign_ip)
            self.conn_socket.sendto(offer_packet.get_packet_bytes(), ('localhost', self.conn_address[1]))

            request_message = None
            request_address = None
            request_packet = GreetingPacket()

            while True:
                request_message, request_address = self.conn_socket.recvfrom(MAX_DATA_PACKET_SIZE)
                request_packet.decode_packet_bytes(request_message)
                if determine_packet_type(request_message) == MODE_REQUEST:
                    break

            # We have the request packet, now send back an acknowledgement packet
            ack_packet = GreetingPacket(source_ip=our_ip, dest_ip=assign_ip, mode=MODE_ACKNOWLEDGE,
                                        assigned_ip=assign_ip)
            self.conn_socket.sendto(ack_packet.get_packet_bytes(), ('localhost', self.conn_address[1]))

            # Completed greeting protocol, save information about other client
            self.other_ip = assign_ip

        else:
            # Otherwise, onus is on us to initialise connection (using initial_port)
            x = 123
            discovery_packet = GreetingPacket(source_ip='0.0.0.0', dest_ip='0.0.0.0', mode=MODE_DISCOVERY,
                                              assigned_ip='0.0.0.0')
            self.conn_socket.sendall(discovery_packet.get_packet_bytes())

            x = 123

            offer_message = None
            offer_address = None
            offer_packet = GreetingPacket()
            x = 123
            offer_message = self.conn_socket.recv(MAX_DATA_PACKET_SIZE)
            x = 456
            #while True:

            #    #offer_message = self.conn_socket.recv(MAX_DATA_PACKET_SIZE)

            offer_packet.decode_packet_bytes(offer_message)
            #    if determine_packet_type(offer_message) == MODE_OFFER:
            #        break
            # We have offer packet, get the IP from it and store it
            assigned_ip = offer_packet.get_assigned_ip()
            switch_ip = offer_packet.get_source_ip()

            request_packet = GreetingPacket(source_ip='0.0.0.0', dest_ip=switch_ip, mode=MODE_REQUEST,
                                            assigned_ip=assigned_ip)
            self.conn_socket.sendall(request_packet.get_packet_bytes())

            ack_message = None
            ack_packet = GreetingPacket()
            x = 123
            while True:
                ack_message = self.conn_socket.recv(MAX_DATA_PACKET_SIZE)
                ack_packet.decode_packet_bytes(ack_message)
                if determine_packet_type(ack_message) == MODE_ACKNOWLEDGE:
                    break

            # We have an ack packet. Now we take on the IP


            x = 123
            # TODO - Fix connection reset by peer / connection refused error
            pass

        while True:
            #message, conn_address = self.conn_socket.recvfrom(MAX_DATA_PACKET_SIZE)
            #message = self.msgq.get()
            time.sleep(1)


class LocalListen(threading.Thread):

    def __init__(self, adapter_socket, adapter_port, source_ip):
        threading.Thread.__init__(self)
        self.adapter_socket = adapter_socket
        self.adapter_port = adapter_port
        self.source_ip = source_ip

    def run(self):
        local_message_queue = Queue()
        message, adapter_address = self.adapter_socket.recvfrom(MAX_DATA_PACKET_SIZE)
        message_thread = ConnectionThread(self.adapter_socket, adapter_address, self.source_ip, initial_message=message,
                                          msgq=local_message_queue)
        message_thread.start()


class GlobalListen(threading.Thread):

    def __init__(self, switch_socket, switch_port, source_ip, conn=None):
        threading.Thread.__init__(self)
        self.switch_socket = switch_socket
        self.switch_port = switch_port
        self.source_ip = source_ip
        self.conn = conn

    def run(self):
        conn, server_addr = self.switch_socket.accept()
        self.conn = conn
        #while True:

        # Respond to connection request
        in_packet = conn.recv(MAX_DATA_PACKET_SIZE)
        packet_type = determine_packet_type(in_packet)
        while packet_type is not MODE_DISCOVERY:
            in_packet = conn.recv(MAX_DATA_PACKET_SIZE)
            packet_type = determine_packet_type(in_packet)

        discovery_packet = GreetingPacket()
        discovery_packet.decode_packet_bytes(in_packet)

        # Incoming discovery packet, open and interpret
        our_ip = self.source_ip.split('/')[0]
        global_addresses.append(our_ip)
        assign_ip = get_lowest_available_ip(self.source_ip, mode=SWITCH_MODE_GLOBAL)

        # Respond with offer packet
        offer_packet = GreetingPacket(source_ip=our_ip, dest_ip='0.0.0.0', mode=MODE_OFFER, assigned_ip=assign_ip)
        conn.sendall(offer_packet.get_packet_bytes())

        # Wait for request packet back
        x = 123

        #print(in_data)
        x = 123



def main(argv):

    # Basic arg checking
    if len(argv) not in (5, 6):
        return ERR_BAD_ARG_NUM

    if argv[1] not in ("local", "global"):
        return ERR_BAD_SPECIFIER

    if argv[1] == "global" and len(argv) != 5:
        return ERR_BAD_ARG_NUM

    if not is_ipv4_cidr_address(argv[2]):
        return ERR_BAD_IP

    if len(argv) == 6 and not (is_ipv4_cidr_address(argv[3]) and is_ipv4_cidr_address(argv[2])):
        return ERR_BAD_IP

    if not (argv[-1].isnumeric() and argv[-2].isnumeric()):
        return ERR_BAD_LOCATION

    # Start switch greeting protocol
    switch_mode = SWITCH_MODE_GLOBAL if argv[1] == "global" else SWITCH_MODE_LOCAL

    # Get our TCP port
    switch_socket = None
    switch_port = None

    # We are a global switch, or we are a local switch with a local and global port
    if switch_mode == SWITCH_MODE_GLOBAL or len(argv) == 6:
        switch_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        switch_socket.bind(('localhost', 0))
        switch_socket.listen()

        switch_port = switch_socket.getsockname()[1]
        #print("TCP socket:")
        #print(switch_socket)
        #print(switch_port)

    adapter_socket = None
    adapter_port = None

    if switch_mode == SWITCH_MODE_LOCAL:
        # Local switch, we also need to set up UDP socket
        adapter_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        adapter_socket.bind(('', 0))
        adapter_port = adapter_socket.getsockname()[1]
        print(adapter_port)

    if switch_port is not None:
        print(switch_port)

    # Now make the listening thread for global (and local - if applicable) listening
    global_listen_thread = None
    if switch_mode == SWITCH_MODE_GLOBAL or len(argv) == 6:
        global_listen_thread = GlobalListen(switch_socket, switch_port, argv[2])
        global_listen_thread.start()

    local_listen_thread = None
    if switch_mode == SWITCH_MODE_LOCAL:
        local_listen_thread = LocalListen(adapter_socket, adapter_port, argv[2])
        local_listen_thread.start()

    while True:
        # Sit and listen on stdin forever
        mutex.acquire()
        sys.stdout.write("> ")
        sys.stdout.flush()
        mutex.release()

        user_input = None
        try:
            user_input = input()
        except EOFError:
            break

        user_input_tokens = user_input.split(' ')

        if len(user_input_tokens) != 2:
            continue

        if user_input_tokens[0] != 'connect':
            continue

        if not user_input_tokens[1].isnumeric():
            continue

        if int(user_input_tokens[1]) not in range(0, 65536):
            continue

        if switch_mode == SWITCH_MODE_LOCAL and len(argv) == 6:
            # Local switch on TCP <-> UDP cannot accept "connect" command, ignore
            continue

        # Connect message, interpret provided port number
        input_port = int(user_input_tokens[1])
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_socket.connect(('localhost', input_port))

        temp_thread = ConnectionThread(temp_socket, ('localhost', input_port), argv[2], initial_port=input_port)
        temp_thread.start()

    while True:
        # Now we need to keep the parent process alive so the threads don't die. Just sit and do nothing :)
        time.sleep(1)


def get_lowest_available_ip(network_ip, mode):
    """
    Gets lowest available IP address from list of addresses
    """
    if mode not in (SWITCH_MODE_LOCAL, SWITCH_MODE_GLOBAL):
        return None

    # First, split incoming IP into address and number of network bits
    ip_tokens = network_ip.split('/')
    addr = ip_tokens[0]
    num_net_bits = int(ip_tokens[1])
    addr_tokens = addr.split('.')

    address_bytes = [int(i) for i in addr_tokens]

    for i in range(32 - num_net_bits):
        # lol gl >:)
        address_bytes[-((i // 8) + 1)] &= 255 ^ (1 << (i % 8))

    # We now have the network address. Must +1 because we can't assign the network address
    address_bytes = address_increment(address_bytes)

    # Now we must find the lowest available IP
    while True:
        temp_ip = '.'.join([str(j) for j in address_bytes])
        if mode == SWITCH_MODE_LOCAL:
            if temp_ip not in local_addresses:
                return temp_ip
        elif mode == SWITCH_MODE_GLOBAL:
            if temp_ip not in global_addresses:
                return temp_ip
        # Address is already in use, goto next one
        address_bytes = address_increment(address_bytes)


def address_increment(address):
    """
    Increments an IP address (by 1)
    """
    address[-1] += 1
    for i in range(1, 5):
        if address[-i] > 255:
            if i == 4:
                return [255, 255, 255, 255]
            address[-i] = 0
            address[-(i + 1)] += 1
        else:
            break

    return address


if __name__ == "__main__":
    sys.exit(main(sys.argv))

import socket
import sys
import threading
import math
import time
import re

from packets import *

CLEARING_STRING = '\b\b'

ERR_BAD_ARG_NUM = 1
ERR_INVALID_PORT = 2

MESSAGE_STATE_WAITING = 0
MESSAGE_STATE_QUERIED = 1
MESSAGE_STATE_READY = 2
MESSAGE_STATE_RECEIVING = 3
MESSAGE_STATE_FINISHED = 4

mutex = threading.Lock()

# Global variables :)
message_thread_state = 0
last_check_time = 0
incomplete_packet_buffer = FragmentQueue()


class MessageProcessThread(threading.Thread):

    def __init__(self, message, switch_socket, switch_address, source_ip):
        threading.Thread.__init__(self)
        self.message = message
        self.switch_socket = switch_socket
        self.switch_address = switch_address
        self.source_ip = source_ip

    def run(self):
        # We have received a message from the switch, now process it
        global message_thread_state
        global last_check_time
        global incomplete_packet_buffer

        packet_type = determine_packet_type(self.message)

        # Switch on packet type
        if packet_type in (MODE_DISCOVERY, MODE_OFFER, MODE_REQUEST, MODE_ACKNOWLEDGE):
            # This is a greeting packet - we shouldn't really be getting these anymore, just ignore
            pass

        elif packet_type in (MODE_DATA, MODE_MORE_FRAGMENTS, MODE_LAST_FRAGMENT):
            # This is a data packet
            data_in = DataPacket()
            data_in.decode_packet_bytes(self.message)
            data_message = data_in.get_payload().decode("utf-8").rstrip('\0x00')

            # If we have recently exchanged query packets, or have done so in the last 10 seconds
            if message_thread_state == MESSAGE_STATE_READY or (time.time() < (last_check_time + 10)):

                # If we have a complete packet
                if packet_type == MODE_DATA:
                    # Critical region, we only want one thread touching stdout at a time
                    mutex.acquire()
                    # Remove '> ' from stdout
                    sys.stdout.write(CLEARING_STRING)
                    # Print our message
                    sys.stdout.write("Received from ")
                    sys.stdout.write(data_in.source_ip)
                    sys.stdout.write(": ")
                    sys.stdout.write(data_message)
                    # Put the '> ' back
                    sys.stdout.write('\n> ')
                    # flush stdout
                    sys.stdout.flush()
                    # Release stdout mutex
                    mutex.release()

                # If we are receiving multiple fragments
                elif packet_type in (MODE_MORE_FRAGMENTS, MODE_LAST_FRAGMENT):
                    incomplete_packet_buffer.add_item(data_in)
                    if incomplete_packet_buffer.is_finished(data_in):
                        final_message = incomplete_packet_buffer.get_payload(data_in)
                        # Critical region, we only want one thread touching stdout at a time
                        mutex.acquire()
                        # Remove '> ' from stdout
                        sys.stdout.write(CLEARING_STRING)
                        # Print our message
                        sys.stdout.write("Received from ")
                        sys.stdout.write(data_in.source_ip)
                        sys.stdout.write(": ")
                        sys.stdout.write(final_message)
                        # Put the '> ' back
                        sys.stdout.write('\n> ')
                        # flush stdout
                        sys.stdout.flush()
                        # Release stdout mutex
                        mutex.release()

        elif packet_type in (MODE_QUERY, MODE_READY):
            # This is a query packet
            in_query_packet = QueryPacket()
            in_query_packet.decode_packet_bytes(self.message)
            # We should first expect a query packet from the switch asking us if we're ready for data
            if packet_type == MODE_QUERY and message_thread_state == MESSAGE_STATE_WAITING:
                # We just got a query from the switch asking us if we're ready
                ready_packet = QueryPacket(source_ip=self.source_ip, dest_ip=in_query_packet.get_source_ip(),
                                           mode=MODE_READY)

                # Now send off the packet
                self.switch_socket.sendto(ready_packet.get_packet_bytes(), ('localhost', self.switch_address[1]))

                # Now we're ready to receive data packets
                message_thread_state = MESSAGE_STATE_READY
                last_check_time = time.time()

        elif packet_type == MODE_LOCATION:
            # This is a location packet
            pass

        elif packet_type == PACKET_ENUM_NEW_NEIGHBOUR:
            # This is a new neighbour packet
            pass

        else:
            # Dodgy packet, ignore
            return


class ListenThread(threading.Thread):

    def __init__(self, switch_socket, source_ip):
        threading.Thread.__init__(self)
        self.switch_socket = switch_socket
        self.source_ip = source_ip

    def run(self):
        # Now we need to start listening to the socket for incoming messages
        global message_thread_state
        global last_check_time

        while True:
            message, switch_address = self.switch_socket.recvfrom(MAX_DATA_PACKET_SIZE)
            message_thread = MessageProcessThread(message, self.switch_socket, switch_address, self.source_ip)
            message_thread.start()


def main(argv):

    # Basic arg checking
    if len(argv) != 2:
        return ERR_BAD_ARG_NUM

    if not argv[1].isnumeric():
        return ERR_INVALID_PORT

    source_ip = '0.0.0.0'
    dest_ip = '0.0.0.0'
    assigned_ip = '0.0.0.0'
    switch_ip = '0.0.0.0'

    # Get the port number of the switch
    switch_port = int(argv[1])

    # Socket
    switch_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    x = 132
    # Connect
    switch_socket.connect(('localhost', switch_port))

    # Start greeting protocol
    # Send discovery packet
    greeting_packet_discovery = GreetingPacket(source_ip=source_ip, dest_ip=dest_ip, mode=MODE_DISCOVERY,
                                               assigned_ip=assigned_ip)
    switch_socket.sendto(greeting_packet_discovery.get_packet_bytes(), ('localhost', switch_port))

    # Now we wait for offer packet
    offer_packet_raw, offer_packet_raw_address = switch_socket.recvfrom(GREETING_PACKET_SIZE)
    offer_packet = GreetingPacket()
    err = offer_packet.decode_packet_bytes(offer_packet_raw)
    while err:
        # Keep waiting for messages until we receive a valid offer packet
        offer_packet_raw, offer_packet_raw_address = switch_socket.recvfrom(GREETING_PACKET_SIZE)
        err = offer_packet.decode_packet_bytes(offer_packet_raw)
        if not err:
            break

    # Get our assigned IP address - Don't take it on yet, just store it
    assigned_ip = offer_packet.get_assigned_ip()
    switch_ip = offer_packet.get_source_ip()

    # We have an offer, now respond with a request packet
    greeting_packet_request = GreetingPacket(source_ip=source_ip, dest_ip=switch_ip, mode=MODE_REQUEST,
                                             assigned_ip=assigned_ip)
    switch_socket.sendto(greeting_packet_request.get_packet_bytes(), ('localhost', switch_port))

    # Wait for acknowledge packet
    ack_packet_raw, ack_packet_raw_address = switch_socket.recvfrom(GREETING_PACKET_SIZE)
    ack_packet = GreetingPacket()
    err = ack_packet.decode_packet_bytes(ack_packet_raw)
    while err:
        # Keep waiting for messages until we receive a valid ack packet
        ack_packet_raw, ack_packet_raw_address = switch_socket.recvfrom(GREETING_PACKET_SIZE)
        err = ack_packet.decode_packet_bytes(ack_packet_raw)
        if not err:
            break

    # Completed greeting protocol, now take on new IP address
    source_ip = ack_packet.get_assigned_ip()

    # Print out "> ", and start accepting commands
    with mutex:
        sys.stdout.write("> ")
        sys.stdout.flush()

    # Now make a thread to listen for messages coming from the switch
    listen_thread = ListenThread(switch_socket, source_ip)
    listen_thread.start()

    while True:
        user_input = input()

        # Split the input command at spaces, but not if the command is enclosed by ""
        user_input_tokens = re.findall(r'[^"\s]\S*|".+?"', user_input)
        user_input_tokens = [i.strip('\"') for i in user_input_tokens]

        if len(user_input_tokens) != 3:
            # Bad arg num, ignore this command
            sys.stdout.write("> ")
            sys.stdout.flush()
            continue

        if user_input_tokens[0] != "send":
            # Bad command type, ignore this command
            sys.stdout.write("> ")
            sys.stdout.flush()
            continue

        if not is_ipv4_address(user_input_tokens[1]):
            # Not valid IP address, ignore this command
            sys.stdout.write("> ")
            sys.stdout.flush()
            continue

        # We have a valid command. Check how many packets we need for this one
        payload = user_input_tokens[2].encode("utf-8")
        data_packet = DataPacket(source_ip=source_ip, dest_ip=user_input_tokens[1], mode=MODE_DATA, payload=payload)
        switch_socket.sendto(data_packet.get_packet_bytes(), ('localhost', switch_port))

        mutex.acquire()
        sys.stdout.write("> ")
        sys.stdout.flush()
        mutex.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv))

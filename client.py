import signal
import sys
import argparse
from urllib.parse import urlparse
import selectors
import socket
import struct
import hashlib
import os

# notes:
# ----------------- The algorithm solving unreliability of RDT in my UDP messaging program -------------------
# There are more than one UDP socket in my program (more than one sockets in both client and server)
# normal message, file data, ACK will be handled through different sockets
# If packets lost, sender resends packets until gets correct ACK
# If packets have errors, receiver updates ACK to sender and sender resends
# if any delays on both inpute message or ACK, repeated packets will be simply discarded and resends ACK to whoever sends the repeat.
# both message and file packets have four elements (ACK,fileDataSEQ,DATA/MESSAGE,CheckSum)
# The change of ACK and fileDataSEQ during each packet sent is followed by this pattern:
# Sender sending input data ---> receiver received and updates fileDataSEQ, sending ACK containing new fileDataSEQ ---> Sender gets ACK, store new fileDataSEQ and updates ACK
# --- > looop above

host = 'localhost'
MAX_STRING_SIZE = 256
sel = selectors.DefaultSelector()
print("Connecting to server ... ")

port = 10000
fileName = ""
bufferSize = 1024
user = ''
fileSize = 0
count = 0
fileDataACK = 0
fileDataSEQ = 0
messageACK = 0
messageSEQ = 0
checkReapeatPkts = -1
file_notice_ACK_Flag = True


def signal_handler(sig, frame):
    global messageACK
    global messageSEQ

    print('Interrupt received, shutting down ...')
    message = f'@DISCONNECT {user} CHAT/1.0\n'
    exitMessage = do_send_message(messageACK, messageSEQ, message)
    client_socket.sendto(exitMessage, (host, port))
    sel.unregister(client_socket)
    client_socket.close()
    sys.exit(0)


def do_prompt(skip_line=False):
    if (skip_line):
        print("")
    print("> ", end='', flush=True)


# This method is for sending UDP file packets
def do_send_file(ACK, sequence_number, fileData):
    packet_tuple = (ACK, sequence_number, fileData)
    packet_structure = struct.Struct(f'I I {MAX_STRING_SIZE}s')
    packed_data = packet_structure.pack(*packet_tuple)
    checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

    packet_tuple = (ACK, sequence_number, fileData, checksum)
    UDP_packet_structure = struct.Struct(f'I I {MAX_STRING_SIZE}s 32s')
    UDP_packet = UDP_packet_structure.pack(*packet_tuple)

    return UDP_packet


# This method is for sending UDP normal message packets
def do_send_message(ACK, sequence_number, message):
    message = message.encode()

    packet_tuple = (ACK, sequence_number, message)
    packet_structure = struct.Struct(f'I I {MAX_STRING_SIZE}s')
    packed_data = packet_structure.pack(*packet_tuple)
    checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

    packet_tuple = (ACK, sequence_number, message, checksum)
    UDP_packet_structure = struct.Struct(f'I I {MAX_STRING_SIZE}s 32s')
    UDP_packet = UDP_packet_structure.pack(*packet_tuple)

    return UDP_packet


def endClient():
    sys.exit(0)


# main method for processing sending message to server and received system information from server
def handle_message_and_file_from_server(sock, mask):
    global fileName
    global fileSize
    global fileDataACK  # ACK for FILE packets
    global fileDataSEQ  # SEQ for FILE packets
    global messageSEQ  # SEQ for normal message packets
    global messageACK  # ACK for normal message packets
    global file_notice_ACK_Flag  # Flag for sending incoming file notice to server
    global checkReapeatPkts  # If ACK delayed, it stores the SEQ for the lost packet

    while True:

        send_msg_ACK_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        received_packet, addr = sock.recvfrom(1024)

        unpacker = struct.Struct('I I 256s 32s')
        UDP_packet = unpacker.unpack(received_packet)

        received_ACK = UDP_packet[0]
        received_sequence = UDP_packet[1]
        received_data = UDP_packet[2]
        received_size = len(received_data)
        received_checksum = UDP_packet[3]

        # check repeated packets
        if received_sequence == checkReapeatPkts:
            if UDP_packet[1] == 1:
                received_sequence = 0
            else:
                received_sequence = 1

            values = (UDP_packet[0], received_sequence)
            chkSumStruct = struct.Struct('I I')
            chkSumData = chkSumStruct.pack(*values)
            chkSum = bytes(hashlib.md5(chkSumData).hexdigest(), encoding="UTF-8")

            responseVal = (UDP_packet[0], received_sequence, chkSum)
            UDP_Data2 = struct.Struct('I I 32s')
            UDP_Packet = UDP_Data2.pack(*responseVal)

            send_msg_ACK_sock.sendto(UDP_Packet, (host, 5002))
            send_msg_ACK_sock.close()

        else:

            values = (received_ACK, received_sequence, received_data)
            packer = struct.Struct('I I 32s')
            packed_data = packer.pack(*values)
            computed_checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

            if received_checksum == computed_checksum:

                checkReapeatPkts = received_sequence  # store last packet's SEQ

                # if check sum pass, update SEQ and send it to the sender along with ACK packets
                if UDP_packet[1] == 1:
                    received_sequence = 0
                else:
                    received_sequence = 1

                values = (UDP_packet[0], received_sequence)
                chkSumStruct = struct.Struct('I I')
                chkSumData = chkSumStruct.pack(*values)
                chkSum = bytes(hashlib.md5(chkSumData).hexdigest(), encoding="UTF-8")

                responseVal = (UDP_packet[0], received_sequence, chkSum)
                UDP_Data2 = struct.Struct('I I 32s')
                UDP_Packet = UDP_Data2.pack(*responseVal)

                # Sending ACK to port 5002, 5002 takes care of the ACK of server-to-client message
                # it tells server that client receives system message
                send_msg_ACK_sock.sendto(UDP_Packet, (host, 5002))
                send_msg_ACK_sock.close()

                received_text = received_data[:received_size].decode()
                message = received_text

                words = received_text.split(' ')

                if received_text == "@401 client already registered":
                    print("401 client already registered, try another user name")
                    endClient()

                if words[0] == '@DISCONNECT':
                    print('Disconnected from server ... exiting!')
                    sys.exit(0)

                if words[0] == "@fileincoming":
                    # if program goes in here, then it implies that client enters !attach command for file-sending
                    fileName = words[1]
                    filesize = os.path.getsize(fileName)
                    stopCount = 0
                    while file_notice_ACK_Flag == True:

                        try:
                            # if program goes in here, then it implies that the program is ready to send binary or txt file to server
                            fileNotice = do_send_message(messageACK, messageSEQ,
                                                         "Client_ready_to_send" + " " + str(filesize) + " " + "end")

                            client_socket.sendto(fileNotice, (host, port))
                            currentFileACK = messageACK
                            stopCount += 1
                            # port 5003 takes care of ACK of client-to-server message
                            send_ACK_to_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            send_ACK_to_server.settimeout(0.009)
                            send_ACK_to_server.bind((host, 5003))
                            fData, faddr = send_ACK_to_server.recvfrom(1024)

                            fPacker = struct.Struct('I I 32s')
                            fPacket = fPacker.unpack(fData)
                            fACK = fPacket[0]
                            fSEQ = fPacket[1]
                            fChecksum = fPacket[2]

                            values = (fACK, fSEQ)
                            fileAckPacker = struct.Struct('I I')
                            computedChecksumData = fileAckPacker.pack(*values)
                            computedChecksum = bytes(hashlib.md5(computedChecksumData).hexdigest(), encoding="UTF-8")

                            # if a different ACK from ACK packets, then it implies errors in message
                            if fChecksum == computedChecksum:
                                if currentFileACK != fACK:
                                    print("file corrupted")
                                    continue
                                else:
                                    file_notice_ACK_Flag = False
                                    # if current packets has no error then get new packet's SEQ
                                    correctMessageSequence = fPacket[1]
                                    send_ACK_to_server.close()
                            else:
                                send_ACK_to_server.close()
                                continue
                        except socket.timeout:
                            if stopCount == 4:
                                break
                            continue

                        # update current SEQ to next packet's SEQ
                        messageSEQ = correctMessageSequence
                        # update ACK number for the next packet
                        if messageACK == 0:
                            messageACK = 1
                        else:
                            messageACK = 0

                    file_notice_ACK_Flag = True

                    # buffer list that temporally keeps all the file data
                    fileContentList = []
                    with open(fileName, "rb") as readfile:
                        while True:
                            readChunk = readfile.read(256)
                            if readChunk:
                                fileContentList.append(readChunk)
                            else:
                                break

                    correctRespSequence = 0
                    print("\n")
                    print("File sending in progress ...")

                    # now client is going to send file data to server
                    # active special ACK and SEQ for file data, and temporally block normal message ACK and SEQ until all the file data successfully send
                    fileDataACK = 0
                    fileDataSEQ = 0
                    count = 0

                    for data in fileContentList:
                        # loop every items in the file data buffer
                        # sending file chunk by chunk
                        sendingData = do_send_file(fileDataACK, fileDataSEQ, data)
                        count += 1

                        Flag = True
                        while Flag == True:
                            try:
                                currentACK = fileDataACK
                                sock.sendto(sendingData, (host, port))
                                # Receiving ACK from port 5004, port 5004 takes care of file data ACK fomr server after server receives file pakcets
                                fileData_ACK_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                fileData_ACK_socket.settimeout(0.009)
                                fileData_ACK_socket.bind((host, 5004))

                                rData, addr = fileData_ACK_socket.recvfrom(1024)
                                unpacker = struct.Struct('I I 32s')
                                rPacket = unpacker.unpack(rData)

                                rACK = rPacket[0]
                                rSEQ = rPacket[1]
                                rChkSum = rPacket[2]

                                values = (rPacket[0], rPacket[1])
                                structOfACK = struct.Struct('I I')
                                checksumOfACK = structOfACK.pack(*values)
                                computedACKChksum = bytes(hashlib.md5(checksumOfACK).hexdigest(), encoding="UTF-8")

                                if computedACKChksum == rChkSum:

                                    if currentACK != rACK:
                                        # test if there are error in packet
                                        print("data corrupted, attempting to resend packet NO." + str(count))
                                        fileData_ACK_socket.close()
                                        continue

                                    else:

                                        correctRespSequence = rPacket[1]
                                        fileData_ACK_socket.close()

                                        Flag = False
                                else:
                                    print("ACK check sum error, sending packet  again")
                                    # fileData_ACK_socket.close()
                                    continue



                            except socket.timeout:
                                Flag = True
                                print("Packet lost or fileDataACK delayed at packet NO." + str(count))
                                continue

                        fileDataSEQ = correctRespSequence
                        if fileDataACK == 0:
                            fileDataACK = 1
                        else:
                            fileDataACK = 0

                if "@" in words[0] and "@fileincoming" != words[0]:
                    if "@File" == words[0]:
                        message = message.strip("@")
                        print(f"\n{message}\n", end='')
                        do_prompt()
                        return message
                    else:
                        print(f"\n{message}\n", end='')
                        do_prompt()
                        return message



            else:
                print("check sum does not match\n")
                if UDP_packet[0] == 1:
                    ACK = 0
                else:
                    ACK = 1

                values = (ACK, received_sequence)
                chkSumStruct = struct.Struct('I I')
                chkSumData = chkSumStruct.pack(*values)
                chkSum = bytes(hashlib.md5(chkSumData).hexdigest(), encoding="UTF-8")

                responseVal = (ACK, received_sequence, chkSum)
                UDP_Data2 = struct.Struct('I I 32s')
                UDP_Packet = UDP_Data2.pack(*responseVal)
                # send ACK to tell server that packet is damaged and resend is required
                send_msg_ACK_sock.sendto(UDP_Packet, (host, 5002))
                send_msg_ACK_sock.close()
                print("Sending fileDataACK to show packet is corrupt\n")


# Function to handle incoming messages from user.
# This function using socket 5003 to receive ACK from server
# it only handles normal message and not file
def handle_keyboard_input(k, mask):
    global messageACK
    global messageSEQ
    messageFlage = True
    line = sys.stdin.readline()
    message = f'@{user}: {line}'
    do_prompt()
    stopCount = 0
    while messageFlage == True:

        try:
            if line != "\n":
                sendingMessage = do_send_message(messageACK, messageSEQ, message)
                client_socket.sendto(sendingMessage, (host, port))

            else:

                messageFlage = False
                continue
            stopCount += 1
            messageSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            messageSocket.settimeout(0.009)
            messageSocket.bind((host, 5003))
            mData, addr = messageSocket.recvfrom(1024)

            unpacker = struct.Struct('I I 32s')
            mPacket = unpacker.unpack(mData)

            mAck = mPacket[0]
            mSEQ = mPacket[1]
            mChecksum = mPacket[2]

            values = (mAck, mSEQ)
            packer = struct.Struct('I I')
            computedChecksumData = packer.pack(*values)
            computedChecksum = bytes(hashlib.md5(computedChecksumData).hexdigest(), encoding="UTF-8")

            if mChecksum == computedChecksum:
                currentMessageAck = messageACK
                if currentMessageAck != mAck:

                    do_prompt()

                    continue

                else:

                    correctMessageSequence = mPacket[1]
                    messageSocket.close()
                    messageFlage = False
            else:
                print("fileDataACK message bit error, going to resend the message")
                messageFlage = True
                continue

        except socket.timeout:
            print("timeout, attempting to resend message")
            
            # when the number of timeouts reaches to 5, then client discard the message
            # when command message does not have a ACK response from server for 5 repeat resend, client would byt default assume server accept the message

            if stopCount == 5:
                break
            messageFlage = True

            continue
        messageSEQ = correctMessageSequence
        if messageACK == 0:
            messageACK = 1
        else:
            messageACK = 0

        messageSocket.close()


introMessageACK = 0
introMessageSEQ = 0
currentMessageAck = 0


def main():
    global user
    global client_socket
    global host
    global port
    global introMessageACK
    global introMessageSEQ
    global currentMessageAck
    intMomessageFlage = True

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    introCount = 0
    signal.signal(signal.SIGINT, signal_handler)

    # Check command line arguments to retrieve a URL.

    parser = argparse.ArgumentParser()
    parser.add_argument("user", help="user name for this user on the chat service")
    parser.add_argument("server", help="URL indicating server location in form of chat://host:port")
    args = parser.parse_args()

    try:
        server_address = urlparse(args.server)
        if ((server_address.scheme != 'chat') or (server_address.port == None) or (server_address.hostname == None)):
            raise ValueError
        host = server_address.hostname
        port = server_address.port
    except ValueError:
        print('Error:  Invalid server.  Enter a URL of the form:  chat://host:port')
        sys.exit(1)
    user = args.user

    if user == "@all":
        print("You cannot name @all, existing...")
        endClient()
    print('Connection to server established. Sending intro message...\n')

    message = f'@200 REGISTER {user} CHAT/1.0\n'
    registerMessage = do_send_message(introMessageACK, introMessageSEQ, message)

    # sending intromessage packets to server and use port 5003 to receive ACK
    while intMomessageFlage == True:

        try:
            currentMessageAck = introMessageACK

            client_socket.sendto(registerMessage, (host, port))

            introMessageSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            introMessageSocket.settimeout(0.009)
            introCount += 1

            introMessageSocket.bind((host, 5003))
            mData, addr = introMessageSocket.recvfrom(1024)

            unpacker = struct.Struct('I I 32s')
            mPacket = unpacker.unpack(mData)

            mAck = mPacket[0]
            mSEQ = mPacket[1]
            mChecksum = mPacket[2]

            values = (mAck, mSEQ)
            packer = struct.Struct('I I')
            computedChecksumData = packer.pack(*values)
            computedChecksum = bytes(hashlib.md5(computedChecksumData).hexdigest(), encoding="UTF-8")

            if mChecksum == computedChecksum:

                if currentMessageAck != mAck:

                    print("data corrupted")
                    do_prompt()

                    continue

                else:

                    introMessageSocket.close()
                    intMomessageFlage = False

            else:
                print("Intro message error, going to resend the message")
                intMomessageFlage = True
                continue

        except socket.timeout:
            if introCount == 5:
                break
                introMessageSocket.close()
            intMomessageFlage = True
            # Three attempts on connecting given port number, if more than three time, then the port number is invalid (not caused by lose ACK packet)


            continue

    # Receive the response from the server and start taking a look at it
    sel.register(client_socket, selectors.EVENT_READ, handle_message_and_file_from_server)
    sel.register(sys.stdin, selectors.EVENT_READ, handle_keyboard_input)

    do_prompt()

    # Now do the selection.

    while (True):
        events = sel.select(timeout=100)
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask)


if __name__ == '__main__':
    main()

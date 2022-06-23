import socket
import struct
import hashlib
import selectors
import signal
import sys
import time

# note: my program can only support one client and server at a time. (no bouns mark asked part)
# note: it is really rare that when initiating client to server the connection will be crashed. If it is the case, just try again in the prompt.
# about must error inserting, a rate of -e 0.0001 would be worked well in this program; and for packet lost, a rater below -l 20.0 fits perfectly
# initiating some global variables
UDP_IP = 'localhost'
sel = selectors.DefaultSelector()

MAX_STRING_SIZE = 256

client_nameList = []  # stores the name of client
client_followWord = {}  # stores the follow word of the client
client_dict = {}  # key: username; value: user's address

attachFollowWord = ""

fileSize = 0
sender = ""
msgOrFile = False
fileName = ""
byte_to_read = 0
myCount = -1
lastPackLength = 0
totalNumPacket = 0

seqForCheckMsgACK = -1  # check repeated message packets
seqForCheckFileACK = -1  # check repeated file packets

sendingACK = 0
sendingSEQ = 0


# Our main function.
def signal_handler(sig, frame):
    global sendingACK
    global sendingSEQ
    global addr
    global client_nameList
    print('Interrupt received, shutting down ...')
    message = '@DISCONNECT CHAT/1.0\n'
    if len(client_nameList) != 0:

        send_to_clients(sendingACK, sendingSEQ, message, addr, sock)
        sys.exit(0)
    else:
        sys.exit(0)


# the main function in my program
# when client sends normal message, server will stay in normal message receiving mode by determing the value of msgOrFile boolean variable.
def extract_package_from_client(sock, mask):
    global msgOrFile  # False when normal message, true when file

    commandList = ["!list", "!follow", "!follow?", '!unfollow', "!attach", '!exit']
    global attachFollowWord
    global fileSize
    global sender
    global fileSize

    global fileName
    global byte_to_read
    global sendingACK
    global sendingSEQ
    global seqForCheckMsgACK  # always equal to the seq number of the last sent packet
    global seqForCheckFileACK
    global addr
    global client_nameList

    if msgOrFile == False:

        messageRespSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        received_packet, addr = sock.recvfrom(1024)

        unpacker = struct.Struct('I I 256s 32s')
        UDP_packet = unpacker.unpack(received_packet)

        received_ACK = UDP_packet[0]
        received_sequence = UDP_packet[1]

        received_data = UDP_packet[2]
        received_size = len(received_data)
        received_checksum = UDP_packet[3]

        # first check repeated packets.
        if received_sequence == seqForCheckMsgACK:

            print("Repeated packed detected, attempting to resend ACK")

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
            messageRespSocket.sendto(UDP_Packet, (UDP_IP, 5003))
            messageRespSocket.close()




        else:
            values = (received_ACK, received_sequence, received_data)
            packer = struct.Struct(f'I I {MAX_STRING_SIZE}s')
            packed_data = packer.pack(*values)
            computed_checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

            if received_checksum == computed_checksum:

                seqForCheckMsgACK = UDP_packet[1]  # set the value for repeated packet checker

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

                messageRespSocket.sendto(UDP_Packet, (UDP_IP, 5003))
                messageRespSocket.close()

                received_text = received_data[:received_size].decode()

                accpectedMessage = received_text.split()
                accpectedMessage.pop()

                if "@" in accpectedMessage[0] and "@200" != accpectedMessage[0] and "@filesize" != accpectedMessage[
                    0] and \
                        accpectedMessage[1] not in commandList and accpectedMessage[0] != "@DISCONNECT":
                    print("Received message from user " + accpectedMessage[0].strip("@") + ": " + received_text)

                if accpectedMessage[0] == "@DISCONNECT":
                    print("Disconnected user " + accpectedMessage[1])
                    del client_dict[accpectedMessage[1]]
                    del client_followWord[accpectedMessage[1]]
                    client_nameList.remove(accpectedMessage[1])

                if accpectedMessage[0] == "@200":
                    seqForCheckMsgACK = -1

                    print("Accpected connection from client address: " + str(addr))
                    print(
                        "Connection to client established, waiting to receive message from user " + "'" +
                        accpectedMessage[
                            2] + "' ...")
                    add_user_to_list(accpectedMessage[2], addr)

                    send = send_to_clients(sendingACK, sendingSEQ,
                                           "@system: Registration successful. Ready for message ... ", addr, sock)
                    sendingACK = send[0]
                    sendingSEQ = send[1]

                #
                if "!list" in accpectedMessage:
                    nameList = listCommand()

                    send = send_to_clients(sendingACK, sendingSEQ, nameList, addr, sock)
                    sendingACK = send[0]
                    sendingSEQ = send[1]
                #
                if "!follow" in accpectedMessage:
                    user = accpectedMessage[0].strip(":")

                    followedWord = accpectedMessage[2].strip()

                    commandList = ["!list", "!follow", "!follow?", "!unfollow"]
                    print(len(accpectedMessage))
                    try:
                        if followedWord == "@all" or user == followedWord or followedWord in client_followWord[
                            user.strip('@')] or len(accpectedMessage) > 3 \
                                or followedWord in commandList:

                            if followedWord == "@all":
                                send = send_to_clients(sendingACK, sendingSEQ, "@system: you cannot follow @all", addr,
                                                       sock)
                                sendingACK = send[0]
                                sendingSEQ = send[1]
                            if user == followedWord:
                                send = send_to_clients(sendingACK, sendingSEQ, "@system: you cannot follow yourself",
                                                       addr, sock)
                                sendingACK = send[0]
                                sendingSEQ = send[1]

                            if followedWord in client_followWord[user.strip('@')]:
                                send = send_to_clients(sendingACK, sendingSEQ,
                                                       "@system: you cannot follow the word that you have followed before",
                                                       addr, sock)
                                sendingACK = send[0]
                                sendingSEQ = send[1]
                            if len(accpectedMessage) > 3:
                                send = send_to_clients(sendingACK, sendingSEQ,
                                                       "@system: you can only follow one word at a time", addr, sock)
                                sendingACK = send[0]
                                sendingSEQ = send[1]
                            if followedWord in commandList:
                                send = send_to_clients(sendingACK, sendingSEQ,
                                                       "@system: you cannot follow command word", addr, sock)
                                sendingACK = send[0]
                                sendingSEQ = send[1]
                        else:

                            client_followWord[accpectedMessage[0].strip("@:")].append(followedWord)
                            time.sleep(1)
                            send = send_to_clients(sendingACK, sendingSEQ, "@system: now following " + followedWord,
                                                   addr, sock)
                            sendingACK = send[0]
                            sendingSEQ = send[1]

                    except IndexError:
                        send = send_to_clients(sendingACK, sendingSEQ,
                                               "@system: syntax error detected --- try enter a word after !follow command",
                                               addr, sock)
                        sendingACK = send[0]
                        sendingSEQ = send[1]

                if "!follow?" in accpectedMessage:
                    if not len(accpectedMessage) > 2:
                        user = accpectedMessage[0].strip("@:")

                        followWord = ""
                        for item in client_followWord[user]:
                            followWord += item + ","
                        time.sleep(1)
                        send = send_to_clients(sendingACK, sendingSEQ, "@system: " + followWord.rstrip(","), addr, sock)

                        sendingACK = send[0]
                        sendingSEQ = send[1]

                    else:
                        send = send_to_clients(sendingACK, sendingSEQ,
                                               "@system: syntax error detected --- no word after command !follow?",
                                               addr, sock)
                        sendingACK = send[0]
                        sendingSEQ = send[1]
                #
                if '!unfollow' in accpectedMessage:

                    user = accpectedMessage[0].strip("@:")
                    try:
                        if len(accpectedMessage) > 3 or accpectedMessage[2] == "@" + user or accpectedMessage[
                            2] == "@all":
                            if len(accpectedMessage) > 3:
                                send_to_clients(sendingACK, sendingSEQ,
                                                "@system: syntax error detected --- you can only unfollow one word at a time",
                                                addr, sock)
                            if accpectedMessage[2] == "@" + user:
                                send_to_clients(sendingACK, sendingSEQ, "@system: you cannot unfollow yourself", addr,
                                                sock)
                            if accpectedMessage[2] == "@all":
                                send_to_clients(sendingACK, sendingSEQ, "@system: you cannot unfollow @all", addr, sock)
                        else:
                            client_followWord[user].remove(accpectedMessage[2])
                            time.sleep(1)
                            send = send_to_clients(sendingACK, sendingSEQ,
                                                   "@system: No longer following " + accpectedMessage[2], addr, sock)
                            sendingACK = send[0]
                            sendingSEQ = send[1]

                    except IndexError:
                        send_to_clients(sendingACK, sendingSEQ,
                                        "@system: syntax error detected --- try enter a word after !unfollow command",
                                        addr, sock)

                if accpectedMessage[1] == "!exit":
                    user = accpectedMessage[0].strip("@:")
                    shutDownMessage = "@DISCONNECT "
                    send = send_to_clients(sendingACK, sendingSEQ, shutDownMessage, addr, sock)
                    sendingACK = send[0]
                    sendingSEQ = send[1]
                    print("Disconnected user" + user)
                    client_nameList = []
                if accpectedMessage[1] == "!attach":
                    user = accpectedMessage[0].strip("@:")
                    sender = user
                    fileName = accpectedMessage[2]
                    attachFollowWord = accpectedMessage[3]
                    send = send_to_clients(sendingACK, sendingSEQ, "@fileincoming" + " " + fileName + " " + "", addr,
                                           sock)
                    sendingACK = send[0]
                    sendingSEQ = send[1]

                if "Client_ready_to_send" == accpectedMessage[0]:
                    fileSize = int(accpectedMessage[1])
                    print("\n")
                    print("Receiving file from -- " + sender + " ...")
                    time.sleep(0.1)
                    msgOrFile = True





            else:
                print('Checksum does not match')
                if UDP_packet[0] == 1:
                    ACK = 0
                else:
                    ACK = 1

                values = (ACK, received_sequence)
                chkSumStruct = struct.Struct('I I')
                chkSumData = chkSumStruct.pack(*values)
                chkSum = bytes(hashlib.md5(chkSumData).hexdigest(), encoding="UTF-8")

                # # create response packet
                responseVal = (ACK, received_sequence, chkSum)
                UDP_Data2 = struct.Struct('I I 32s')
                UDP_Packet = UDP_Data2.pack(*responseVal)

                messageRespSocket.sendto(UDP_Packet, (UDP_IP, 5003))
                messageRespSocket.close()
                print("Sending ACK to show packet is corrupt\n")

    else:
        #now we are in file mode
        count = 0
        filelengthCount = 0
        seqForCheckFileACK = -1
        with open(fileName, 'wb') as writeFile:
            byte_to_read = 0
            while byte_to_read < fileSize:

                responseSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                received_packet, addr = sock.recvfrom(1024)

                unpacker = struct.Struct(f'I I {MAX_STRING_SIZE}s 32s')
                UDP_packet = unpacker.unpack(received_packet)

                received_sequence = UDP_packet[1]

                received_data = UDP_packet[2]
                received_checksum = UDP_packet[3]

                count += 1

                if received_sequence == seqForCheckFileACK:

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

                    responseSocket.sendto(UDP_Packet, (UDP_IP, 5004))
                    responseSocket.close()

                    continue
                else:
                    values = (UDP_packet[0], UDP_packet[1], received_data)
                    packer = struct.Struct(f'I I {MAX_STRING_SIZE}s')
                    packed_data = packer.pack(*values)
                    computed_checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

                    if received_checksum == computed_checksum:
                        byte_to_read += len(received_data)
                        filelengthCount += 1

                        seqForCheckFileACK = received_sequence

                        writeFile.write(received_data)

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

                        responseSocket.sendto(UDP_Packet, (UDP_IP, 5004))
                        responseSocket.close()

                    else:
                        print("chkSums do not match\n")
                        if UDP_packet[0] == 1:
                            ACK = 0
                        else:
                            ACK = 1
                        values = (ACK, received_sequence)
                        chkSumStruct = struct.Struct('I I')
                        chkSumData = chkSumStruct.pack(*values)
                        chkSum = bytes(hashlib.md5(chkSumData).hexdigest(), encoding="UTF-8")

                        # # create response packet
                        responseVal = (ACK, received_sequence, chkSum)
                        UDP_Data2 = struct.Struct('I I 32s')
                        UDP_Packet = UDP_Data2.pack(*responseVal)

                        responseSocket.sendto(UDP_Packet, (UDP_IP, 5004))
                        responseSocket.close()
                        print("Sending ACK to show packet is corrupt\n")

        msgOrFile = False
        feedback = "@File successfully uploaded, file details:" + "\n" + "File name: " + fileName + "\n" + "File size: " + str(
            fileSize) + "\n" + "File sender: " + sender
        send = send_to_clients(sendingACK, sendingSEQ, feedback, addr, sock)
        sendingACK = send[0]
        sendingSEQ = send[1]
        print("File successfully uploaded... it is stored under server file folder")
        print("\n")


def listCommand():
    response = ""
    for name in client_nameList:
        name = "@" + name
        response += name + " "
    return response


def add_user_to_list(user, addr):
    client_nameList.append(user)
    client_dict[user] = addr
    client_followWord[user] = ["@all", "@" + user]

# the send function in server that sends system message to the client when client enter command
def send_to_clients(ACK, sequence_number, message, clients_addr, sock):
    messageFlage = True

    data = message.encode()

    packet_tuple = (ACK, sequence_number, data)
    packet_structure = struct.Struct('I I 32s')
    packed_data = packet_structure.pack(*packet_tuple)
    checksum = bytes(hashlib.md5(packed_data).hexdigest(), encoding="UTF-8")

    packet_tuple = (ACK, sequence_number, data, checksum)
    UDP_packet_structure = struct.Struct("I I 256s 32s")
    UDP_packet = UDP_packet_structure.pack(*packet_tuple)

    while messageFlage == True:
        try:

            sock.sendto(UDP_packet, clients_addr)

            currentMessageAck = ACK

            messageSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            messageSocket.settimeout(0.009)

            messageSocket.bind((UDP_IP, 5002))

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
            # check sum for ACK message
            if mChecksum == computedChecksum:
                if currentMessageAck != mAck:
                    print("data corrupted")

                    continue
                else:
                    messageFlage = False

                    correctMessageSequence = mPacket[1]



            else:
                print("ACK message bit error, going to resend the message")

                continue

        except socket.timeout:

            continue

        sendingSEQ = correctMessageSequence

        if ACK == 0:
            sendingACK = 1
        else:
            sendingACK = 0

        messageSocket.close()

        return [sendingSEQ, sendingACK]


def main():
    global sock

    signal.signal(signal.SIGINT, signal_handler)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sock.bind((UDP_IP, 10000))
    print("Will wait for client connections at port ", sock.getsockname()[1])
    print("Waiting for incoming client connections ...")

    sel.register(sock, selectors.EVENT_READ, extract_package_from_client)


    while True:
        events = sel.select()
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask)


if __name__ == '__main__':
    main()
# end of the program

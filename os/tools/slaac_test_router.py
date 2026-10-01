import argparse
import socket
import struct


ROUTER_MAC = bytes.fromhex("525400aabbcc")
ROUTER_IPV4 = socket.inet_aton("10.0.2.2")
LEASE_IPV4 = socket.inet_aton("10.0.2.15")
ROUTER_IPV6 = socket.inet_pton(socket.AF_INET6, "fe80::1")
PREFIX_IPV6 = socket.inet_pton(socket.AF_INET6, "fd00::")
ALL_NODES_IPV6 = socket.inet_pton(socket.AF_INET6, "ff02::1")
ALL_NODES_MAC = bytes.fromhex("333300000001")


def checksum(data):
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def ipv4_packet(source, destination, protocol, payload, identification=1):
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(payload),
        identification,
        0x4000,
        64,
        protocol,
        0,
        source,
        destination,
    )
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return header + payload


def ipv6_packet(source, destination, next_header, payload, hop_limit=255):
    header = struct.pack(
        "!IHBB16s16s",
        6 << 28,
        len(payload),
        next_header,
        hop_limit,
        source,
        destination,
    )
    return header + payload


def icmpv6(source, destination, message):
    pseudo_header = source + destination + struct.pack("!I3xB", len(message), 58)
    message = message[:2] + b"\x00\x00" + message[4:]
    value = checksum(pseudo_header + message)
    return message[:2] + struct.pack("!H", value) + message[4:]


def ethernet(destination, source, ethertype, payload):
    return destination + source + struct.pack("!H", ethertype) + payload


def ipv6_frame(destination_mac, source_mac, source_ip, destination_ip, message):
    return ethernet(
        destination_mac,
        source_mac,
        0x86DD,
        ipv6_packet(source_ip, destination_ip, 58, icmpv6(source_ip, destination_ip, message)),
    )


def dhcp_response(bootp, message_type):
    if len(bootp) < 240 or bootp[0] != 1 or bootp[1:3] != b"\x01\x06":
        return None
    response = bytearray(bootp[:240])
    response[0] = 2
    response[16:20] = LEASE_IPV4
    response[20:24] = ROUTER_IPV4
    options = (
        b"\x35\x01"
        + bytes([message_type])
        + b"\x36\x04"
        + ROUTER_IPV4
        + b"\x01\x04\xff\xff\xff\x00"
        + b"\x03\x04"
        + ROUTER_IPV4
        + b"\x06\x04\x0a\x00\x02\x03"
        + b"\x33\x04\x00\x00\x0e\x10"
        + b"\xff"
    )
    return bytes(response) + options


def dhcp_message_type(bootp):
    if len(bootp) < 240 or bootp[236:240] != b"\x63\x82\x53\x63":
        return None
    offset = 240
    while offset < len(bootp):
        code = bootp[offset]
        offset += 1
        if code == 255:
            break
        if code == 0:
            continue
        if offset >= len(bootp):
            return None
        length = bootp[offset]
        offset += 1
        if offset + length > len(bootp):
            return None
        if code == 53 and length == 1:
            return bootp[offset]
        offset += length
    return None


def handle_arp(frame):
    if len(frame) < 42:
        return None
    packet = frame[14:42]
    hardware_type, protocol_type, hardware_len, protocol_len, opcode = struct.unpack(
        "!HHBBH", packet[:8]
    )
    if (
        hardware_type != 1
        or protocol_type != 0x0800
        or hardware_len != 6
        or protocol_len != 4
        or opcode != 1
        or packet[24:28] != ROUTER_IPV4
    ):
        return None
    guest_mac = packet[8:14]
    guest_ip = packet[14:18]
    response = struct.pack(
        "!HHBBH6s4s6s4s",
        1,
        0x0800,
        6,
        4,
        2,
        ROUTER_MAC,
        ROUTER_IPV4,
        guest_mac,
        guest_ip,
    )
    return ethernet(guest_mac, ROUTER_MAC, 0x0806, response)


def handle_ipv4(frame):
    packet = frame[14:]
    if len(packet) < 20 or packet[0] >> 4 != 4:
        return None
    header_len = (packet[0] & 0x0F) * 4
    total_len = struct.unpack("!H", packet[2:4])[0]
    if header_len < 20 or total_len < header_len or len(packet) < total_len:
        return None
    source_ip, destination_ip = packet[12:16], packet[16:20]
    payload = packet[header_len:total_len]
    if packet[9] == 17 and len(payload) >= 8:
        source_port, destination_port, udp_len = struct.unpack("!HHH", payload[:6])
        if destination_port != 67 or source_port != 68 or udp_len < 8:
            return None
        bootp = payload[8:udp_len]
        request_type = dhcp_message_type(bootp)
        if request_type not in (1, 3):
            return None
        response = dhcp_response(bootp, 2 if request_type == 1 else 5)
        if response is None:
            return None
        udp = struct.pack("!HHHH", 67, 68, len(response) + 8, 0) + response
        reply = ipv4_packet(ROUTER_IPV4, b"\xff\xff\xff\xff", 17, udp)
        return ethernet(b"\xff" * 6, ROUTER_MAC, 0x0800, reply)
    if packet[9] == 1 and len(payload) >= 8 and payload[0] == 8:
        reply = bytearray(payload)
        reply[0] = 0
        reply[2:4] = b"\x00\x00"
        reply[2:4] = struct.pack("!H", checksum(reply))
        ip_reply = ipv4_packet(ROUTER_IPV4, source_ip, 1, reply)
        return ethernet(frame[6:12], ROUTER_MAC, 0x0800, ip_reply)
    return None


def router_advertisement(source_ip, destination_ip, destination_mac):
    advertisement = struct.pack("!BBHBBHII", 134, 0, 0, 64, 0, 1800, 0, 0)
    prefix_option = struct.pack(
        "!BBBBII4s16s",
        3,
        4,
        64,
        0xC0,
        7200,
        3600,
        b"\x00" * 4,
        PREFIX_IPV6,
    )
    advertisement = icmpv6(
        source_ip, destination_ip, advertisement + prefix_option
    )
    return ethernet(
        destination_mac,
        ROUTER_MAC,
        0x86DD,
        ipv6_packet(source_ip, destination_ip, 58, advertisement),
    )


def handle_ipv6(frame):
    packet = frame[14:]
    if len(packet) < 40 or packet[0] >> 4 != 6 or packet[6] != 58:
        return None
    payload_len = struct.unpack("!H", packet[4:6])[0]
    if len(packet) < 40 + payload_len or payload_len < 8:
        return None
    source_ip, destination_ip = packet[8:24], packet[24:40]
    message = packet[40 : 40 + payload_len]
    source_mac = frame[6:12]
    if message[0] == 133:
        if source_ip == b"\x00" * 16:
            return router_advertisement(ROUTER_IPV6, ALL_NODES_IPV6, ALL_NODES_MAC)
        return router_advertisement(ROUTER_IPV6, source_ip, source_mac)
    if message[0] == 135 and len(message) >= 24 and message[8:24] == ROUTER_IPV6:
        destination = source_ip if source_ip != b"\x00" * 16 else ALL_NODES_IPV6
        destination_mac = source_mac if source_ip != b"\x00" * 16 else ALL_NODES_MAC
        advertisement = struct.pack("!BBHI16s", 136, 0, 0, 0x60000000, ROUTER_IPV6)
        advertisement += b"\x02\x01" + ROUTER_MAC
        return ipv6_frame(
            destination_mac,
            ROUTER_MAC,
            ROUTER_IPV6,
            destination,
            advertisement,
        )
    if message[0] == 128 and destination_ip == ROUTER_IPV6:
        reply = bytearray(message)
        reply[0] = 129
        return ipv6_frame(
            source_mac,
            ROUTER_MAC,
            ROUTER_IPV6,
            source_ip,
            reply,
        )
    return None


def handle_frame(frame):
    if len(frame) < 14:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype == 0x0806:
        return handle_arp(frame)
    if ethertype == 0x0800:
        return handle_ipv4(frame)
    if ethertype == 0x86DD:
        return handle_ipv6(frame)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as router:
        router.bind(("127.0.0.1", args.port))
        print(f"QEMU SLAAC test router ready on 127.0.0.1:{args.port}", flush=True)
        while True:
            frame, peer = router.recvfrom(65535)
            if peer[0] != "127.0.0.1":
                continue
            response = handle_frame(frame)
            if response is not None:
                router.sendto(response, peer)


if __name__ == "__main__":
    main()

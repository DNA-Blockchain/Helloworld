import struct
import unittest

from slaac_test_router import (
    ALL_NODES_IPV6,
    ALL_NODES_MAC,
    PREFIX_IPV6,
    ROUTER_IPV6,
    checksum,
    dhcp_message_type,
    dhcp_response,
    router_advertisement,
)


class RouterPacketTests(unittest.TestCase):
    def test_dhcp_discover_and_request_get_distinct_responses(self):
        discover = bytearray(240)
        discover[0:3] = b"\x01\x01\x06"
        discover[236:240] = b"\x63\x82\x53\x63"
        discover.extend(b"\x35\x01\x01\xff")

        offer = dhcp_response(discover, 2)
        self.assertEqual(dhcp_message_type(offer), 2)
        self.assertEqual(offer[16:20], b"\x0a\x00\x02\x0f")

        request = bytearray(discover)
        request[-2] = 3
        acknowledgement = dhcp_response(request, 5)
        self.assertEqual(dhcp_message_type(acknowledgement), 5)

    def test_router_advertisement_has_valid_checksum_and_slaac_prefix(self):
        frame = router_advertisement(ROUTER_IPV6, ALL_NODES_IPV6, ALL_NODES_MAC)
        self.assertEqual(struct.unpack("!H", frame[12:14])[0], 0x86DD)

        ipv6 = frame[14:]
        self.assertEqual(ipv6[7], 255)
        self.assertEqual(ipv6[6], 58)
        self.assertEqual(ipv6[8:24], ROUTER_IPV6)

        message = ipv6[40:]
        pseudo_header = (
            ipv6[8:24]
            + ipv6[24:40]
            + struct.pack("!I3xB", len(message), 58)
        )
        self.assertEqual(checksum(pseudo_header + message), 0)
        self.assertEqual(message[0], 134)
        self.assertEqual(message[16], 3)
        self.assertEqual(message[18], 64)
        self.assertEqual(message[19] & 0xC0, 0xC0)
        self.assertEqual(message[32:48], PREFIX_IPV6)


if __name__ == "__main__":
    unittest.main()

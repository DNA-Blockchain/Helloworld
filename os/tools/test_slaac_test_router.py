# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

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

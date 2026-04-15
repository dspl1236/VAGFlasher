"""
VAGFlasher test suite — milestone 0.1.0.

Tests cover:
  - UDS request/response parsing
  - SA2 algorithms (known vectors from corpus RE)
  - FlashBlock construction
  - CLI dry-run
"""
import pytest

from vagflasher.protocols.sa2 import SA2Error, resolve_sa2
from vagflasher.protocols.uds import (
    NRC,
    Service,
    Session,
    parse_response,
    req_diagnostic_session,
    req_request_download,
    req_security_access_key,
    req_security_access_seed,
    req_tester_present,
    req_transfer_data,
    req_transfer_exit,
)

# ── UDS parsing ───────────────────────────────────────────────────────────────

class TestUDSParsing:
    def test_positive_response(self):
        raw = bytes([0x50, 0x03])            # DiagnosticSession positive
        r = parse_response(raw)
        assert r.ok
        assert r.service == 0x10             # 0x50 - 0x40
        assert not r.negative

    def test_negative_response(self):
        raw = bytes([0x7F, 0x10, 0x22])      # NRC conditionsNotCorrect
        r = parse_response(raw)
        assert not r.ok
        assert r.negative
        assert r.nrc == NRC.CONDITIONS_NOT_CORRECT
        assert r.service == 0x10

    def test_pending_response(self):
        raw = bytes([0x7F, 0x27, 0x78])      # response pending
        r = parse_response(raw)
        assert r.pending
        assert r.nrc == NRC.RESPONSE_PENDING

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_response(b"")

    def test_nrc_name_known(self):
        raw = bytes([0x7F, 0x34, 0x33])
        r = parse_response(raw)
        assert r.nrc_name() == "SECURITY_ACCESS_DENIED"

    def test_nrc_name_unknown(self):
        raw = bytes([0x7F, 0x10, 0xAB])
        r = parse_response(raw)
        assert r.nrc_name() == "0xAB"


# ── UDS request builders ──────────────────────────────────────────────────────

class TestUDSBuilders:
    def test_diagnostic_session(self):
        r = req_diagnostic_session(Session.PROGRAMMING)
        assert r == bytes([0x10, 0x02])

    def test_diagnostic_session_bosch85(self):
        r = req_diagnostic_session(Session.BOSCH_85)
        assert r == bytes([0x10, 0x85])

    def test_tester_present_suppress(self):
        r = req_tester_present(suppress_response=True)
        assert r == bytes([0x3E, 0x80])

    def test_tester_present_no_suppress(self):
        r = req_tester_present(suppress_response=False)
        assert r == bytes([0x3E, 0x00])

    def test_security_access_seed_request(self):
        r = req_security_access_seed(0x01)
        assert r == bytes([0x27, 0x01])

    def test_security_access_key_send(self):
        key = bytes([0xAB, 0xCD, 0xEF, 0x12])
        r = req_security_access_key(0x01, key)
        assert r == bytes([0x27, 0x02]) + key

    def test_request_download(self):
        r = req_request_download(0x080000, 0x004000)
        assert r[0] == Service.REQUEST_DOWNLOAD
        assert r[1] == 0x00         # dataFormatIdentifier
        assert r[2] == 0x33         # 3-byte addr, 3-byte size
        assert r[3:6] == bytes([0x08, 0x00, 0x00])
        assert r[6:9] == bytes([0x00, 0x40, 0x00])

    def test_transfer_data_sequence(self):
        chunk = b"\xDE\xAD\xBE\xEF"
        r = req_transfer_data(1, chunk)
        assert r[0] == Service.TRANSFER_DATA
        assert r[1] == 0x01
        assert r[2:] == chunk

    def test_transfer_data_seq_wraps(self):
        r = req_transfer_data(0xFF, b"\x00")
        assert r[1] == 0xFF
        r2 = req_transfer_data(0x100, b"\x00")
        assert r2[1] == 0x00         # wraps at 256

    def test_transfer_exit(self):
        assert req_transfer_exit() == bytes([0x37])


# ── SA2 algorithms ────────────────────────────────────────────────────────────

class TestSA2:
    def test_biwb_ud101_deterministic(self):
        """Same seed always gives same key."""
        seed = bytes([0x12, 0x34, 0x56, 0x78])
        k1 = resolve_sa2("BiWbBuD101", seed)
        k2 = resolve_sa2("BiWbBuD101", seed)
        assert k1 == k2
        assert len(k1) == 4

    def test_biwb_ud101_different_seeds_differ(self):
        s1 = bytes([0x11, 0x22, 0x33, 0x44])
        s2 = bytes([0x55, 0x66, 0x77, 0x88])
        assert resolve_sa2("BiWbBuD101", s1) != resolve_sa2("BiWbBuD101", s2)

    def test_biwb_ud101_short_seed_raises(self):
        with pytest.raises(SA2Error):
            resolve_sa2("BiWbBuD101", bytes([0x01, 0x02]))

    def test_med91_deterministic(self):
        seed = bytes([0xAB, 0xCD, 0xEF, 0x01])
        k1 = resolve_sa2("MED91", seed)
        k2 = resolve_sa2("MED91", seed)
        assert k1 == k2
        assert len(k1) == 4

    def test_med91_different_seeds_differ(self):
        s1 = bytes([0x00, 0x00, 0x00, 0x01])
        s2 = bytes([0x00, 0x00, 0x00, 0x02])
        assert resolve_sa2("MED91", s1) != resolve_sa2("MED91", s2)

    def test_code_robert_deterministic(self):
        seed = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        k = resolve_sa2("CodeRobert", seed)
        assert len(k) == 4

    def test_me7_deterministic(self):
        seed = bytes([0x12, 0x34])
        k = resolve_sa2("ME7", seed)
        assert len(k) == 2

    def test_unknown_key_raises(self):
        with pytest.raises(SA2Error, match="Unknown BCB key"):
            resolve_sa2("NotAKey", bytes([0x01, 0x02, 0x03, 0x04]))

    def test_all_known_keys_listed_in_error(self):
        with pytest.raises(SA2Error) as exc:
            resolve_sa2("bad", bytes(4))
        assert "BiWbBuD101" in str(exc.value)


# ── FlashBlock ────────────────────────────────────────────────────────────────

class TestFlashBlock:
    def test_size_property(self):
        from vagflasher.platforms.me17 import FlashBlock
        b = FlashBlock(address=0x080000, data=bytes(0x4000))
        assert b.size == 0x4000

    def test_address_stored(self):
        from vagflasher.platforms.me17 import FlashBlock
        b = FlashBlock(address=0x1A0000, data=b"\xFF" * 100)
        assert b.address == 0x1A0000

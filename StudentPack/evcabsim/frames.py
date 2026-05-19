"""Wire codec for the cabinet-supervisor serial protocol.

Framing: every frame is $...#. All numeric fields are ASCII decimal.
"""

from __future__ import annotations

from evcabsim.model import (
    AckFrame, CabinetFrame, CabinetMode, ConFrame, DisFrame, EndFrame,
    GoFrame, LimFrame, StsFrame, SupervisorFrame,
)


VALID_LIM_AMPS  = (0, 8, 16, 24)
VALID_PORTS     = (0, 1, 2)
VALID_ACK_CODES = (0, 1, 2, 3)


def encode(frame: SupervisorFrame) -> bytes:
    """Serialise a supervisor frame into its $...# wire representation."""
    if isinstance(frame, GoFrame):
        return b"$GO#"
    if isinstance(frame, EndFrame):
        return b"$END#"
    if isinstance(frame, LimFrame):
        if frame.amps not in VALID_LIM_AMPS:
            raise ValueError(
                f"LimFrame.amps must be 0/8/16/24, got {frame.amps}")
        return f"$LIM{frame.amps:02d}#".encode("ascii")
    if isinstance(frame, ConFrame):
        if frame.port not in VALID_PORTS:
            raise ValueError(f"ConFrame.port must be 0..2, got {frame.port}")
        return f"$CON{frame.port}#".encode("ascii")
    if isinstance(frame, DisFrame):
        if frame.port not in VALID_PORTS:
            raise ValueError(f"DisFrame.port must be 0..2, got {frame.port}")
        return f"$DIS{frame.port}#".encode("ascii")
    raise NotImplementedError(f"encode() missing case for {type(frame).__name__}")


class DecodeError(Exception):
    """A $...# framed payload could not be decoded into a cabinet frame."""


_MODE_LETTER_TO_ENUM = {m.value: m for m in CabinetMode}


def decode_cabinet(raw: bytes) -> CabinetFrame:
    """Parse a complete $...# cabinet frame.

    Raises DecodeError if the framing is wrong or the body does not
    match an STS or ACK frame.
    """
    if len(raw) < 2 or raw[0:1] != b"$" or raw[-1:] != b"#":
        raise DecodeError("frame must start with $ and end with #")
    body = raw[1:-1]
    if body.startswith(b"STS"):
        return _decode_sts(body[3:])
    if body.startswith(b"ACK"):
        return _decode_ack(body[3:])
    raise DecodeError(f"unknown prefix: {body[:3]!r}")


def _decode_sts(payload: bytes) -> StsFrame:
    if len(payload) != 8:
        raise DecodeError(f"STS body must be 8 bytes, got {len(payload)}")
    try:
        letter = payload[0:1].decode("ascii")
        mode = _MODE_LETTER_TO_ENUM[letter]
    except (UnicodeDecodeError, KeyError) as e:
        raise DecodeError(f"invalid STS mode letter: {payload[0:1]!r}") from e
    try:
        adc  = int(payload[1:5].decode("ascii"))
        cmsk = int(payload[5:6].decode("ascii"))
        ee   = int(payload[6:8].decode("ascii"))
    except (UnicodeDecodeError, ValueError) as e:
        raise DecodeError(f"STS numeric field parse: {payload!r}") from e
    if not (0 <= adc <= 1023):
        raise DecodeError(f"STS adc out of range: {adc}")
    if not (0 <= cmsk <= 7):
        raise DecodeError(f"STS connected mask out of 3-bit range: {cmsk}")
    if ee not in VALID_LIM_AMPS:
        raise DecodeError(f"STS ee not in {{0,8,16,24}}: {ee}")
    return StsFrame(mode=mode, adc=adc,
                    connected_mask=cmsk, effective_limit=ee)


def _decode_ack(payload: bytes) -> AckFrame:
    if len(payload) != 2:
        raise DecodeError(f"ACK body must be 2 bytes, got {len(payload)}")
    try:
        code = int(payload.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as e:
        raise DecodeError(f"ACK code parse: {payload!r}") from e
    if code not in VALID_ACK_CODES:
        raise DecodeError(f"ACK code {code:02d} not in {{00,01,02,03}}")
    return AckFrame(code=code)

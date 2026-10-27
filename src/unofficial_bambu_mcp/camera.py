"""One picture from the printer's camera. P1 and A1 printers send JPEG frames on port 6000 (TLS, then a login
packet with the LAN access code; each frame comes after a 16-byte header with its size). It works with the printer
in cloud mode and only reads. X1 and H2 printers stream over RTSP instead, which is not supported here."""
import socket
import ssl
import struct

from . import printer


def _read(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise printer.PrinterError(f"the camera closed the connection after {len(buf)} of {n} bytes")
        buf += chunk
    return buf


def read_frame(sock):
    """One JPEG frame from a connected, logged-in camera socket."""
    size = struct.unpack("<I", _read(sock, 16)[:4])[0]
    if not 0 < size < 20_000_000:
        raise printer.PrinterError(f"unexpected frame size from the camera ({size} bytes)")
    img = _read(sock, size)
    if img[:2] != b"\xff\xd8":
        raise printer.PrinterError("the camera did not send a JPEG picture")
    return img


def login_packet(code):
    return struct.pack("<IIII", 0x40, 0x3000, 0, 0) + b"bblp".ljust(32, b"\0") + code.encode().ljust(32, b"\0")


def snapshot(serial=None, timeout=10.0):
    """JPEG bytes of what the camera sees now."""
    s, code = printer.credentials(serial)
    ip = printer.address(s)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                   # self-signed certificate
    try:
        raw = socket.create_connection((ip, 6000), timeout=timeout)
    except ConnectionRefusedError as e:
        raise printer.PrinterError("the camera does not answer on port 6000: X1 and H2 printers stream it over "
                                   "RTSP, which is not supported yet") from e
    except OSError as e:
        raise printer.PrinterError(f"cannot reach the printer's camera: {e}") from e
    with raw, ctx.wrap_socket(raw, server_hostname=ip) as sock:
        sock.settimeout(timeout)
        sock.sendall(login_packet(code))
        try:
            return read_frame(sock)
        except socket.timeout as e:
            raise printer.PrinterError("no picture from the camera (is it turned off in the printer's settings?)") from e

"""The printer's SD card over FTPS (port 990, TLS from the first byte, user bblp and the LAN access code). It works
with the printer in cloud mode. Timelapse videos are in /timelapse (a JPEG thumbnail of each in
/timelapse/thumbnail), the files of past prints in /cache. Only plain files in those folders are listed,
downloaded or deleted."""
import ftplib
import hashlib
import os
import re
import ssl
import time
from contextlib import contextmanager

from . import printer

FOLDERS = {"timelapse": "/timelapse", "prints": "/cache", "thumbnails": "/timelapse/thumbnail"}
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                       "Dec"), start=1)}
_LIST = re.compile(r"^([-d])\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\w{3})\s+(\d+)\s+(\d+:\d+|\d{4})\s+(.+)$")


class _FTPS(ftplib.FTP_TLS):
    """Implicit FTPS; data connections reuse the control connection's TLS session, as the printer requires."""

    def connect(self, host="", port=990, timeout=15, source_address=None):
        self.host, self.port, self.timeout = host, port, timeout
        raw = ftplib.socket.create_connection((host, port), timeout)
        self.sock = self.context.wrap_socket(raw, server_hostname=host)
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        return self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session), size


@contextmanager
def session(serial=None):
    """A logged-in connection to the printer's SD card."""
    s, code = printer.credentials(serial)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                   # the printer uses a self-signed certificate
    f = _FTPS(context=ctx)
    try:
        f.connect(printer.address(s))
        f.login("bblp", code)
        f.prot_p()
    except ftplib.error_perm as e:
        raise printer.PrinterError(f"the printer refused the SD card login ({e}): check the access code") from e
    except OSError as e:
        raise printer.PrinterError(f"cannot reach the printer's SD card (port 990): {e}") from e
    try:
        yield f
    finally:
        try:
            f.quit()
        except (OSError, ftplib.Error):
            f.close()


def parse_list(rows, now=None):
    """Plain files of a LIST answer: [{name, size, date (YYYY-MM-DD HH:MM), t (epoch)}], newest first."""
    now = time.localtime(now or time.time())
    out = []
    for row in rows:
        m = _LIST.match(row.strip())
        if not m or m.group(1) == "d":
            continue
        _, size, mon, day, last, name = m.groups()
        month, day = _MONTHS.get(mon, 1), int(day)
        if ":" in last:                              # this year (or last year, for a date still to come)
            hh, mm = (int(x) for x in last.split(":"))
            year = now.tm_year - (1 if (month, day) > (now.tm_mon, now.tm_mday) else 0)
        else:
            year, hh, mm = int(last), 0, 0
        t = time.mktime((year, month, day, hh, mm, 0, 0, 0, -1))
        out.append({"name": name, "size": int(size), "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
                    "t": t})
    return sorted(out, key=lambda f: -f["t"])


def listing(f, kind):
    """Files of a folder, newest first; for 'thumbnails' only those whose video is gone (left after a cleanup)."""
    rows = []
    f.retrlines(f"LIST {FOLDERS[kind]}", rows.append)
    files = parse_list(rows)
    if kind == "thumbnails":
        videos = {thumbnail_name(v["name"]) for v in listing(f, "timelapse")}
        files = [x for x in files if x["name"] not in videos]
    return files


def _check_name(name):
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(f"'{name}' is not a file name")


def download(f, kind, name, dest_dir):
    _check_name(name)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, name)
    from .project import next_free_path
    path = next_free_path(path)
    with open(path, "wb") as out:
        f.retrbinary(f"RETR {FOLDERS[kind]}/{name}", out.write)
    return path


def thumbnail_name(video):
    return os.path.splitext(video)[0] + ".jpg"


def confirm_code(kind, names):
    """The code that confirms deleting exactly these files (any change in the list changes it)."""
    h = hashlib.sha1("\n".join([kind] + sorted(names)).encode()).hexdigest()[:4]
    return f"delete {len(names)} files {h}"


def delete(f, kind, names):
    """Delete the files (and, for timelapses, their thumbnails). Returns the names deleted."""
    done = []
    for name in names:
        _check_name(name)
        f.delete(f"{FOLDERS[kind]}/{name}")
        done.append(name)
        if kind == "timelapse":
            try:
                f.delete(f"{FOLDERS[kind]}/thumbnail/{thumbnail_name(name)}")
            except ftplib.error_perm:
                pass                                  # no thumbnail for this one
    return done


def last_frame(video):
    """The last JPEG frame of a Bambu timelapse (MJPEG AVI), or None."""
    end = video.rfind(b"\xff\xd9")
    while end > 0:
        start = video.rfind(b"\xff\xd8\xff", 0, end)
        if start < 0:
            return None
        if end - start > 1000:
            return video[start:end + 2]
        end = video.rfind(b"\xff\xd9", 0, start)
    return None

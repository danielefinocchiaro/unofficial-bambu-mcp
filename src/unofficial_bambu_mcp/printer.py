"""Read-only printer status on the local network (MQTT over TLS, port 8883), printer in normal cloud mode.

Only status is read: progress, temperatures, AMS trays, errors. No print or motion command is sent.
Credentials: serial number and LAN access code as Bambu Studio stores them (BambuStudio.conf), or the
environment variables BAMBU_PRINTER_SERIAL, BAMBU_PRINTER_ACCESS_CODE, BAMBU_PRINTER_IP.
They are read when needed and never written anywhere by this module; only serial -> IP is cached.
"""
import json
import os
import re
import select
import socket
import ssl
import struct
import threading
import time

from . import presets, studio

CACHE = os.path.expanduser("~/.config/unofficial-bambu-mcp/printers.json")
STATES = {"IDLE": "idle", "RUNNING": "printing", "PAUSE": "paused", "FINISH": "finished", "FAILED": "failed",
          "PREPARE": "preparing", "SLICING": "slicing"}


class PrinterError(RuntimeError):
    pass


# ---------------------------------------------------------------- credentials and address
def credentials(serial=None):
    """(serial, access_code) of the printer: env vars first, then Bambu Studio's saved LAN access codes."""
    env_s, env_c = os.environ.get("BAMBU_PRINTER_SERIAL"), os.environ.get("BAMBU_PRINTER_ACCESS_CODE")
    if env_s and env_c and (not serial or serial == env_s):
        return env_s, env_c
    conf = studio.app_config()
    codes = {**conf.get("access_code", {}), **conf.get("user_access_code", {})}
    if not codes:
        raise PrinterError("no LAN access code found: connect the printer once in Bambu Studio, "
                           "or set BAMBU_PRINTER_SERIAL and BAMBU_PRINTER_ACCESS_CODE")
    if serial:
        if serial not in codes:
            raise PrinterError(f"no access code saved for printer {serial}")
        return serial, codes[serial]
    last = conf.get("app", {}).get("user_last_selected_machine")
    s = last if last in codes else next(iter(codes))
    return s, codes[s]


def _cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _remember(serial, ip):
    c = _cache()
    c[serial] = ip
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)


def _own_ips():
    ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return ips


def discover(timeout=8.0):
    """Printers that announce themselves on the LAN (SSDP): {serial: {ip, model, name}}."""
    own = _own_ips()
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1990\r\nMAN: \"ssdp:discover\"\r\nMX: 3\r\n"
           "ST: urn:bambulab-com:device:3dprinter:1\r\n\r\n").encode()
    socks = []
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    socks.append(a)
    try:
        p = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        p.bind(("", 2021))
        try:
            p.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4sl", socket.inet_aton("239.255.255.250"), socket.INADDR_ANY))
        except OSError:
            pass
        socks.append(p)
    except OSError:
        pass
    for dest in (("239.255.255.250", 1990), ("255.255.255.255", 1990), ("255.255.255.255", 2021)):
        try:
            a.sendto(msg, dest)
        except OSError:
            pass
    found = {}
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select(socks, [], [], 0.5)
        for s in r:
            try:
                data, addr = s.recvfrom(4096)
            except OSError:
                continue
            if addr[0] in own:
                continue
            txt = data.decode("utf-8", "ignore")
            if "bambu" not in txt.lower():
                continue
            f = dict(re.findall(r"^([A-Za-z0-9.\-]+):\s*(.*?)\r?$", txt, re.M))
            serial = (f.get("USN") or "").strip()
            if serial:
                found[serial] = {"ip": f.get("Location", addr[0]).strip() or addr[0],
                                 "model": f.get("DevModel.bambu.com"), "name": f.get("DevName.bambu.com"),
                                 "firmware": f.get("DevVersion.bambu.com")}
    for s in socks:
        s.close()
    return found


def _scan_8883():
    """Fallback: hosts on the local /24 with the printer's MQTT port open."""
    import concurrent.futures as cf
    own = [ip for ip in _own_ips() if not ip.startswith("127.")]
    if not own:
        return []
    base = own[0].rsplit(".", 1)[0]

    def probe(i):
        ip = f"{base}.{i}"
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect((ip, 8883))
            return ip
        except OSError:
            return None
        finally:
            s.close()
    with cf.ThreadPoolExecutor(64) as ex:
        return [ip for ip in ex.map(probe, range(1, 255)) if ip and ip not in own]


def address(serial):
    """IP of the printer: env var, cache, SSDP discovery, then a port scan of the local network."""
    env = os.environ.get("BAMBU_PRINTER_IP")
    if env:
        return env
    ip = _cache().get(serial)
    if ip and _port_open(ip):
        return ip
    found = discover()
    if serial in found:
        _remember(serial, found[serial]["ip"])
        return found[serial]["ip"]
    hits = _scan_8883()
    if len(hits) == 1:
        _remember(serial, hits[0])
        return hits[0]
    if not hits:
        raise PrinterError("printer not found on the local network: is it on, and on the same network as this computer?")
    raise PrinterError(f"several devices answer on port 8883 {hits}: set BAMBU_PRINTER_IP")


def _port_open(ip, port=8883):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------- minimal MQTT 3.1.1 client (read-only use)
def _remaining_length(n):
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _str(s):
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def _read_packet(sock):
    h = sock.recv(1)
    if not h:
        raise PrinterError("connection closed by the printer")
    mult, length = 1, 0
    while True:
        b = sock.recv(1)[0]
        length += (b & 127) * mult
        if not b & 128:
            break
        mult *= 128
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise PrinterError("connection closed by the printer")
        data += chunk
    return h[0] >> 4, data


FOLLOW_S = 4.5        # after the full report, wait this long for a newer partial one (P1: about every 2-4 s)


def _seq(pr):
    try:
        return int(pr.get("sequence_id"))
    except (TypeError, ValueError):
        return -1


def _is_full(pr):
    return pr.get("command") == "push_status" and ("ams" in pr or "gcode_state" in pr) and len(pr) > 20


def merge(msgs):
    """One report from the status messages received, in arrival order: the full report (the answer to pushall),
    then the partial ones newer than it by sequence number (P1 printers send only what changed). Without a full
    report, every message in order. '_updates' = partial reports newer than the full one."""
    full = next((m for m in msgs if _is_full(m)), None)
    if full is None:
        out = {}
        for m in msgs:
            out.update(m)
        out["_updates"] = len(msgs)
        return out
    out, base = dict(full), _seq(full)
    newer = sorted((m for m in msgs if m is not full and _seq(m) > base), key=_seq)
    for m in newer:
        out.update(m)
    out["_full_seq"], out["_updates"] = base, len(newer)
    return out


def fetch_report(ip, serial, code, timeout=12.0):
    """Ask the printer for its full status once ('pushall'), wait for the first change sent after it, and return
    the merged JSON report ('_received' = when, epoch seconds)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE              # the printer uses a self-signed certificate
    raw = socket.create_connection((ip, 8883), timeout=timeout)
    sock = ctx.wrap_socket(raw, server_hostname=serial)
    sock.settimeout(timeout)
    try:
        cid = f"ubmcp-{int(time.time())}"
        var = _str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
        payload = _str(cid) + _str("bblp") + _str(code)
        sock.sendall(bytes([0x10]) + _remaining_length(len(var) + len(payload)) + var + payload)
        kind, data = _read_packet(sock)
        if kind != 2 or len(data) < 2 or data[1] != 0:
            raise PrinterError("the printer refused the connection (wrong access code?)")
        topic = f"device/{serial}/report"
        sub = struct.pack("!H", 1) + _str(topic) + b"\x00"
        sock.sendall(bytes([0x82]) + _remaining_length(len(sub)) + sub)
        req = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}})
        pub = _str(f"device/{serial}/request") + req.encode()
        sock.sendall(bytes([0x30]) + _remaining_length(len(pub)) + pub)
        msgs, full, end = [], None, time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                break
            sock.settimeout(left)
            try:
                kind, data = _read_packet(sock)
            except socket.timeout:
                break
            if kind != 3:
                continue
            tl = struct.unpack("!H", data[:2])[0]
            body = data[2 + tl:]
            try:
                msg = json.loads(body.decode("utf-8", "ignore"))
            except ValueError:
                continue
            pr = msg.get("print")
            if not isinstance(pr, dict):
                continue
            msgs.append(pr)
            if full is None and _is_full(pr):
                full = pr
                end = min(end, time.time() + FOLLOW_S)
            elif full is not None and _seq(pr) > _seq(full):
                break                                 # a change newer than the full report: the report is current
        sock.sendall(b"\xe0\x00")                # DISCONNECT
        if not msgs:
            raise PrinterError("no status received from the printer")
        merged = merge(msgs)
        merged["_received"] = time.time()
        return merged
    finally:
        sock.close()


# ---------------------------------------------------------------- report -> summary
def _color(c):
    c = (c or "").strip()
    return ("#" + c[:6].upper()) if len(c) >= 6 else None


def _num(x, nd=0):
    try:
        v = float(x)
        return round(v, nd) if nd else int(round(v))
    except (TypeError, ValueError):
        return None


def _bits(x):
    try:
        return int(x, 16)
    except (TypeError, ValueError):
        return None


def _line(filament_id):
    """Name of the filament behind an AMS tray's id (a user's own filament has no brand name in the report)."""
    try:
        return presets.line_for_filament_id(filament_id) if filament_id else None
    except (OSError, ValueError):
        return None


def staleness(rep, prev=None):
    """Why a report may be old, or []: no change came after the full report although the nozzle is far from its
    target (heating or cooling sends one every few seconds), or the printer sent the same report as last time."""
    out = []
    t, target = rep.get("nozzle_temper"), rep.get("nozzle_target_temper")
    moving = isinstance(t, (int, float)) and isinstance(target, (int, float)) and t > 45 and abs(target - t) > 5
    if moving and rep.get("_full_seq") is not None and not rep.get("_updates"):
        out.append(f"the printer sent no change for {FOLLOW_S:g} s although its nozzle is at {t:.0f} °C with "
                   f"target {target:.0f} °C: this report may be old; the printer screen or Bambu Handy show the "
                   "live state")
    if prev is not None and rep.get("_full_seq") is not None and rep.get("_full_seq") == prev.get("_full_seq"):
        ago = rep.get("_received", 0) - prev.get("_received", 0)
        out.append(f"the printer sent the same report as {ago:.0f} s ago (same sequence number): it may be stuck "
                   "on an old state")
    return out


def summarize(r):
    """Human-sized status from a raw report."""
    state = r.get("gcode_state")
    job = r.get("subtask_name") or r.get("gcode_file") or None
    # after a job the printer keeps reporting it (FINISH / FAILED, also on cancel) while it sits idle
    out = {"state": "idle" if state in ("FINISH", "FAILED") else STATES.get(state, state)}
    if state in ("RUNNING", "PAUSE", "PREPARE", "SLICING"):
        out.update({
            "job": job,
            "progress_percent": _num(r.get("mc_percent")),
            "remaining_minutes": _num(r.get("mc_remaining_time")),
            "layer": [_num(r.get("layer_num")), _num(r.get("total_layer_num"))],
        })
    elif state in ("FINISH", "FAILED") and job:
        out["last_job"] = {"name": job, "result": "finished" if state == "FINISH" else "failed or cancelled"}
    out.update({
        "nozzle_c": [_num(r.get("nozzle_temper"), 1), _num(r.get("nozzle_target_temper"), 1)],
        "bed_c": [_num(r.get("bed_temper"), 1), _num(r.get("bed_target_temper"), 1)],
        "speed_level": {1: "silent", 2: "standard", 3: "sport", 4: "ludicrous"}.get(_num(r.get("spd_lvl"))),
        "wifi_signal": r.get("wifi_signal"),
        "errors": [],
    })
    if r.get("print_error"):
        out["errors"].append({"print_error": r.get("print_error")})
    for h in r.get("hms", []) or []:
        out["errors"].append({"hms": f"{int(h.get('attr', 0)):08X}_{int(h.get('code', 0)):08X}"})
    ams = r.get("ams") or {}
    exist = _bits(ams.get("tray_exist_bits"))       # bit n = a spool sits in global tray n
    trays, unknown = [], []
    for unit in ams.get("ams", []) or []:
        u = int(unit.get("id", 0))
        for t in unit.get("tray", []) or []:
            k = int(t.get("id", 0))
            entry = {"slot": u * 4 + k + 1, "ams": u + 1, "tray": k + 1}
            if t.get("tray_type"):
                entry.update({"type": t.get("tray_type"), "name": t.get("tray_sub_brands") or _line(t.get("tray_info_idx"))
                              or t.get("tray_type"), "color": _color(t.get("tray_color")),
                              "remain_percent": _num(t.get("remain")), "filament_id": t.get("tray_info_idx")})
                if entry["remain_percent"] is None or entry["remain_percent"] < 0:   # -1: unknown (no RFID)
                    del entry["remain_percent"]
            elif exist is not None and (exist >> (u * 4 + k)) & 1:
                entry["unknown"] = True               # a spool without RFID that nobody has set in the AMS
                unknown.append(entry["slot"])
            else:
                entry["empty"] = True
            trays.append(entry)
        info = {}
        if unit.get("humidity_raw") is not None:
            info["humidity_percent"] = _num(unit.get("humidity_raw"))
        elif unit.get("humidity") is not None:
            info["humidity_level"] = unit.get("humidity")     # older firmware: only the AMS's 1..5 index
        if unit.get("temp") is not None:
            info["temp_c"] = _num(unit.get("temp"), 1)
        if info:
            out.setdefault("ams_units", {})[u + 1] = info
    out["ams_trays"] = trays
    if unknown:
        out["hint"] = (f"AMS slot(s) {unknown} hold a spool the AMS does not know (no RFID, type not set): "
                       "set type and color on the printer screen, in Bambu Handy or in Bambu Studio")
    vt = r.get("vt_tray") or {}
    if vt.get("tray_type"):
        out["external_spool"] = {"type": vt.get("tray_type"), "name": vt.get("tray_sub_brands") or vt.get("tray_type"),
                                 "color": _color(vt.get("tray_color")), "filament_id": vt.get("tray_info_idx")}
    now = ams.get("tray_now")
    if now not in (None, "", "255"):
        out["active_slot"] = "external spool" if now == "254" else int(now) + 1
    if r.get("s_obj"):
        out["skipped_objects"] = [int(x) for x in r["s_obj"] if str(x).lstrip("-").isdigit()]
    if r.get("_received"):
        out["read_at"] = time.strftime("%H:%M:%S", time.localtime(r["_received"]))
        age = time.time() - r["_received"]
        if age >= 1:
            out["age_s"] = round(age)                  # a reading kept from a call a few seconds ago
    return out


def advice(s, expected=()):
    """Warnings about a running job, from a summary: the spool being fed, the speed mode.
    expected: [(project slot, preset, filament_id)] of the job's project, when it is known."""
    if s.get("state") not in ("printing", "paused", "preparing"):
        return []
    out = []
    if s.get("state") == "printing" and (s.get("nozzle_c") or [0, 0])[1] == 0 and (s.get("bed_c") or [0, 0])[1] == 0:
        out.append("the printer says printing but the nozzle and bed heaters are off: the job is starting or "
                   "stopping, or this report is old; ask again in a minute or look at the printer screen")
    act = s.get("active_slot")
    tray = next((t for t in s.get("ams_trays", []) if t["slot"] == act), None) if isinstance(act, int) else None
    ids = {fid for _, _, fid in expected if fid}
    if tray and tray.get("unknown"):
        msg = (f"the printer is feeding from AMS slot {act}, a spool the AMS does not know: no auto-refill when it "
               "runs out, and the grams left are unknown")
        if ids:
            homes = [f"'{t['name']}' in slot {t['slot']}" for t in s.get("ams_trays", []) if t.get("filament_id") in ids]
            msg += "; the project's filament is " + (", ".join(homes) if homes else "not loaded in the AMS")
        out.append(msg)
    elif tray and ids and tray.get("filament_id") not in ids:
        want = ", ".join(sorted({p.split(" @")[0] for _, p, _ in expected}))
        out.append(f"the printer is feeding {tray.get('name')} from AMS slot {act}, but the project uses {want}")
    if s.get("speed_level") in ("sport", "ludicrous") and (s.get("remaining_minutes") or 0) > 120:
        out.append(f"speed mode is {s['speed_level']} with {s['remaining_minutes'] // 60} h to go: tall or small parts "
                   "are more likely to come off; standard is safer for long prints")
    return out


def preset_for_tray(filament_id, ftype, machine):
    """System filament preset for an AMS tray (by Bambu filament id, else by type), compatible with machine."""
    line = presets.line_for_filament_id(filament_id) if filament_id else None
    if line:
        try:
            return presets.filament_for(line, machine)
        except presets.PresetError:
            pass
    generic = {"PLA": "Generic PLA", "PETG": "Generic PETG", "ABS": "Generic ABS", "ASA": "Generic ASA",
               "TPU": "Generic TPU", "PA": "Generic PA", "PC": "Generic PC", "PLA-CF": "Generic PLA-CF"}
    base = generic.get((ftype or "PLA").upper(), "Generic PLA")
    return presets.filament_for(base, machine)


class Status:
    """Remember the last report so repeated questions do not hammer the printer (P1 series are sensitive)."""
    lock = threading.Lock()
    last = None
    at = 0.0


def status(serial=None, max_age=20.0):
    """(report, serial). A report younger than max_age seconds is given again ('_received' says how old it is);
    '_stale' lists the signs that the printer itself sent an old state."""
    s, code = credentials(serial)
    with Status.lock:
        if Status.last and Status.last[0] == s and time.time() - Status.at < max_age:
            return Status.last[1], s
        ip = address(s)
        rep = fetch_report(ip, s, code)
        prev = Status.last[1] if Status.last and Status.last[0] == s else None
        rep["_stale"] = staleness(rep, prev)
        Status.last, Status.at = (s, rep), time.time()
        return rep, s

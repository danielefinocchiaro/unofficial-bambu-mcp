"""Commands that change the printer: start a print, skip objects of the running print, load and unload AMS
slots. Bambu firmware accepts them from other programs only with the printer in LAN-only mode with Developer
Mode on (printer screen: Settings > Network); in cloud mode it refuses them (MQTT verification, HMS
0500-0500-0001-0007) and the answer says so. They are the requests Bambu Studio sends (MachineObject in
DeviceManager.cpp), over the same local MQTT connection as printer_status. Every tool that uses them asks first:
the first call sends nothing and gives a confirm code."""
import json
import os
import re
import socket
import struct
import time
import zipfile

from . import sdcard
from .printer import STATES, PrinterError, Status, _bits, _read_packet, _remaining_length, _str, address, credentials, fetch_report
from .sdcard import tls_context as _tls


class _Mqtt:
    """One MQTT session with the printer: subscribed to its reports, able to publish requests."""

    def __init__(self, ip, serial, code, timeout=12.0):
        self.serial, self.timeout = serial, timeout
        self.sock = _tls().wrap_socket(socket.create_connection((ip, 8883), timeout=timeout), server_hostname=serial)
        self.sock.settimeout(timeout)
        cid = f"ubmcp-{int(time.time() * 1000)}"
        var = _str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
        payload = _str(cid) + _str("bblp") + _str(code)
        self.sock.sendall(bytes([0x10]) + _remaining_length(len(var) + len(payload)) + var + payload)
        kind, data = _read_packet(self.sock)
        if kind != 2 or len(data) < 2 or data[1] != 0:
            self.sock.close()
            raise PrinterError("the printer refused the connection (wrong access code?)")
        sub = struct.pack("!H", 1) + _str(f"device/{serial}/report") + b"\x00"
        self.sock.sendall(bytes([0x82]) + _remaining_length(len(sub)) + sub)

    def publish(self, message):
        pub = _str(f"device/{self.serial}/request") + json.dumps(message).encode()
        self.sock.sendall(bytes([0x30]) + _remaining_length(len(pub)) + pub)

    def reports(self, timeout=None, key="print"):
        """The 'print' part (or another top-level part; key=None: any) of each report until timeout."""
        end = time.time() + (timeout or self.timeout)
        while time.time() < end:
            try:
                kind, data = _read_packet(self.sock)
            except socket.timeout:
                return
            if kind != 3:
                continue
            tl = struct.unpack("!H", data[:2])[0]
            try:
                msg = json.loads(data[2 + tl:].decode("utf-8", "ignore"))
            except ValueError:
                continue
            for k, part in msg.items():
                if isinstance(part, dict) and (key is None or k == key):
                    yield part

    def close(self):
        try:
            self.sock.sendall(b"\xe0\x00")       # DISCONNECT
        except OSError:
            pass
        self.sock.close()



def print_command(name, plate=1, ams_mapping=None, bed_leveling=True, flow_cali=False, timelapse=False):
    """The 'project_file' request that makes the printer print plate N of /name from its storage."""
    use_ams = ams_mapping is not None
    return {"print": {
        "sequence_id": str(int(time.time())), "command": "project_file", "param": f"Metadata/plate_{plate}.gcode",
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "subtask_name": os.path.splitext(os.path.splitext(name)[0])[0], "file": name, "url": f"file:///sdcard/{name}",
        "md5": "", "bed_type": "auto", "bed_leveling": bed_leveling, "flow_cali": flow_cali, "vibration_cali": False,
        "layer_inspect": False, "timelapse": timelapse, "use_ams": use_ams, "ams_mapping": ams_mapping or [],
    }}


REJECTED = ("the printer refused the print command{why}. Bambu firmware accepts print commands from other "
            "programs only in LAN-only mode with Developer Mode on (printer screen: Settings > Network). "
            "Otherwise use send_to_printer with via='bambu_connect' or 'bambu_studio' and press Print there.")
ON_PRINTER = (" The file is already on the printer's storage as {name}: it can also be started from the printer "
              "screen (print files) or from Bambu Handy (printer > SD card).")
ERR_TEXT = {84033543: "MQTT verification failed, code 84033543"}
HMS_TEXT = {"05000500_00010007": "a print command from another program was refused (MQTT verification): the "
                                 "printer needs LAN-only mode with Developer Mode for that"}


def _hms(h):
    return f"{int(h.get('attr', 0)):08X}_{int(h.get('code', 0)):08X}"


def hms_seen(report):
    """HMS errors present in a report, with their timestamp (the same error raised again is a new one)."""
    return {(_hms(h), h.get("timestamp")) for h in report.get("hms") or []}


def refusal(part, before=frozenset(), command="project_file"):
    """Why the printer refused a command, from its reply or from an HMS error that was not there
    before (that is how recent firmware says no); None if nothing says it refused."""
    if part.get("command") == command:
        err, result = part.get("err_code"), str(part.get("result", "")).lower()
        if err or result not in ("success", "ok", ""):
            return ERR_TEXT.get(err) or f"{part.get('reason') or part.get('result') or 'error'}, code {err or '-'}"
    new = sorted(c for c, _ in hms_seen(part) - set(before))
    return "; ".join(f"HMS {c}: {HMS_TEXT.get(c, 'see the printer screen')}" for c in new) or None


def start_print(path, ams_mapping=None, bed_leveling=True, flow_cali=False, timelapse=False,
                serial=None, wait=25.0):
    """Upload a one-plate .gcode.3mf and start printing it. Returns what the printer reported."""
    with zipfile.ZipFile(path) as z:
        plates = [int(m.group(1)) for n in z.namelist() if (m := re.fullmatch(r"Metadata/plate_(\d+)\.gcode", n))]
    if len(plates) != 1:
        raise PrinterError(f"{os.path.basename(path)} must hold the G-code of exactly one plate")
    plate = plates[0]
    s, code = credentials(serial)
    ip = address(s)
    rep = fetch_report(ip, s, code)
    if rep.get("gcode_state") in ("RUNNING", "PAUSE", "PREPARE", "SLICING"):
        raise PrinterError(f"the printer is busy ({STATES.get(rep['gcode_state'])}): wait for the current job to end")
    name = re.sub(r"[^\w.\-]+", "_", os.path.basename(path))
    before = hms_seen(rep)
    with sdcard.session(s) as f:
        sdcard.upload(f, path, name)
    cmd = print_command(name, plate, ams_mapping, bed_leveling, flow_cali, timelapse)
    started = {"started": True, "file_on_printer": name}
    accepted = False

    def refused(why):
        Status.last = None
        return PrinterError(REJECTED.format(why=why) + ON_PRINTER.format(name=name))

    def check(part):
        why = refusal(part, before)
        return refused(f" ({why})") if why else None

    m = _Mqtt(ip, s, code)
    try:
        m.publish(cmd)
        for part in m.reports(wait, key=None):
            if err := check(part):
                raise err
            if part.get("command") == "project_file":
                accepted = True
            if part.get("gcode_state") in ("PREPARE", "RUNNING"):
                Status.last = None
                return {**started, "state": STATES[part["gcode_state"]]}
    finally:
        m.close()
    rep = fetch_report(ip, s, code)               # one last look: some firmware only says it with the next status
    Status.last = None
    if err := check(rep):
        raise err
    if rep.get("gcode_state") in ("PREPARE", "RUNNING"):
        return {**started, "state": STATES[rep["gcode_state"]]}
    if accepted:
        return {**started, "state": STATES.get(rep.get("gcode_state"), rep.get("gcode_state")),
                "note": "the printer accepted the command but has not started yet: check printer_status"}
    raise refused(" (no answer)")


def _rgb(c):
    c = (c or "#808080").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def ams_mapping(filaments, used, trays, chosen=None):
    """AMS tray (0-based, as the printer counts) for each project filament slot, -1 = not used on the plate.
    filaments: [(type, color)] per project slot; used: slots used on the plate; trays: summarize()["ams_trays"];
    chosen: {project slot: AMS slot (1-based)} picked by the user or by use_ams_filaments. Otherwise the tray
    with the same filament type and the closest color, like Bambu Studio does."""
    known = {t["slot"]: t for t in trays if t.get("type")}
    out = []
    for k, (ftype, color) in enumerate(filaments, start=1):
        if k not in used:
            out.append(-1)
        elif chosen and chosen.get(k):
            if chosen[k] not in known:
                raise PrinterError(f"AMS slot {chosen[k]} (for filament {k}) is empty or its filament is not set")
            out.append(chosen[k] - 1)
        else:
            same = [t for t in known.values() if t["type"].upper() == (ftype or "").upper()]
            if not same:
                raise PrinterError(f"no {ftype} loaded in the AMS for filament slot {k}: load one, or pick the "
                                   "AMS slots with ams_slots")
            rgb = _rgb(color)
            best = min(same, key=lambda t: sum((a - b) ** 2 for a, b in zip(_rgb(t.get("color")), rgb, strict=True)))
            out.append(best["slot"] - 1)
    return out


SKIP_REJECTED = ("the printer refused to skip the objects{why}. Bambu firmware accepts commands from other programs "
                 "only in LAN-only mode with Developer Mode on (printer screen: Settings > Network). Otherwise skip "
                 "them in Bambu Handy (printing page > skip objects) or on the printer screen.")


def skip_command(ids):
    """The request Bambu Studio sends to skip objects (MachineObject::command_task_partskip): ids are the objects'
    identify_id in the job's sliced file."""
    return {"print": {"command": "skip_objects", "obj_list": [int(i) for i in ids],
                      "sequence_id": str(int(time.time()))}}


def skip_objects(ids, serial=None, wait=15.0):
    """Ask the printer to stop printing these objects of the running job (cannot be undone)."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        raise PrinterError("no objects to skip")
    s, code = credentials(serial)
    ip = address(s)
    rep = fetch_report(ip, s, code)
    if rep.get("gcode_state") not in ("RUNNING", "PAUSE"):
        raise PrinterError(f"no print is running ({STATES.get(rep.get('gcode_state'), rep.get('gcode_state'))})")
    already = {int(x) for x in rep.get("s_obj") or []}
    todo = [i for i in ids if i not in already]
    if not todo:
        return {"skipped": ids, "note": "these objects were already skipped"}
    before = hms_seen(rep)
    m = _Mqtt(ip, s, code)
    try:
        m.publish(skip_command(todo))
        for part in m.reports(wait, key=None):
            why = refusal(part, before, command="skip_objects")
            if why:
                raise PrinterError(SKIP_REJECTED.format(why=f" ({why})"))
            if set(todo) <= {int(x) for x in part.get("s_obj") or []}:
                Status.last = None
                return {"skipped": sorted(already | set(todo))}
    finally:
        m.close()
    rep = fetch_report(ip, s, code)
    Status.last = None
    why = refusal(rep, before, command="skip_objects")
    if why:
        raise PrinterError(SKIP_REJECTED.format(why=f" ({why})"))
    done = {int(x) for x in rep.get("s_obj") or []}
    if set(todo) <= done:
        return {"skipped": sorted(done)}
    raise PrinterError(SKIP_REJECTED.format(why=" (no answer, and the objects are not in the skipped list)"))


AMS_REJECTED = ("the printer refused to {what} the filament{why}. Bambu firmware accepts commands from other programs "
                "only in LAN-only mode with Developer Mode on (printer screen: Settings > Network). Otherwise use the "
                "printer screen, Bambu Handy or Bambu Studio (Device > AMS > Load / Unload).")
BUSY = ("RUNNING", "PAUSE", "PREPARE", "SLICING")


def _tray(r, slot):
    """Raw AMS tray of a 1-based slot (AMS 1 = slots 1-4, AMS 2 = 5-8), or None."""
    for unit in (r.get("ams") or {}).get("ams", []) or []:
        for t in unit.get("tray", []) or []:
            if int(unit.get("id", 0)) * 4 + int(t.get("id", 0)) + 1 == slot:
                return t
    return None


def _mid_temp(t):
    """The middle of a tray's nozzle temperature range, as Bambu Studio sends it; -1 when unknown."""
    try:
        return (int(t["nozzle_temp_min"]) + int(t["nozzle_temp_max"])) // 2
    except (KeyError, TypeError, ValueError):
        return -1


def loaded_slot(r):
    """1-based AMS slot loaded in the nozzle, 'external' for the external spool, or None."""
    now = str((r.get("ams") or {}).get("tray_now", "255"))
    return None if now in ("255", "") else ("external" if now == "254" else int(now) + 1)


def ams_change_command(r, slot=None):
    """The request Bambu Studio sends to load an AMS slot (slot 1-based) or, with slot None, to unload
    (MachineObject::command_ams_change_filament)."""
    seq = str(int(time.time()))
    if slot is None:
        cur = loaded_slot(r)
        ams_id = (cur - 1) // 4 if isinstance(cur, int) else 0
        return {"print": {"command": "ams_change_filament", "sequence_id": seq, "curr_temp": 210, "tar_temp": 210,
                          "ams_id": ams_id, "target": 255, "slot_id": 255}}
    cur = loaded_slot(r)
    old = _mid_temp(_tray(r, cur)) if isinstance(cur, int) else -1
    return {"print": {"command": "ams_change_filament", "sequence_id": seq, "curr_temp": old,
                      "tar_temp": _mid_temp(_tray(r, slot)), "ams_id": (slot - 1) // 4, "target": slot - 1,
                      "slot_id": (slot - 1) % 4}}


def check_ams_change(r, slot=None):
    """Why loading this slot (or unloading, slot None) cannot be done now, or None."""
    if r.get("gcode_state") in BUSY:
        return f"the printer is {STATES.get(r.get('gcode_state'), 'busy')}: load and unload only when it is not printing"
    if slot is None:
        return None if loaded_slot(r) is not None else "no filament is loaded in the nozzle"
    t = _tray(r, slot)
    if t is None:
        return f"there is no AMS slot {slot}"
    exist = _bits((r.get("ams") or {}).get("tray_exist_bits"))
    if not t.get("tray_type") and not (exist is not None and (exist >> (slot - 1)) & 1):
        return f"AMS slot {slot} is empty"
    if loaded_slot(r) == slot:
        return f"AMS slot {slot} is already loaded"
    return None


def ams_change(slot=None, serial=None, wait=240.0):
    """Load an AMS slot (1-based) into the nozzle, or unload with slot None, and wait until the printer reports
    it done (it heats the nozzle and moves the filament: a minute or two)."""
    s, code = credentials(serial)
    ip = address(s)
    rep = fetch_report(ip, s, code)
    why = check_ams_change(rep, slot)
    if why:
        raise PrinterError(why)
    what = "load" if slot is not None else "unload"
    done = (lambda r: loaded_slot(r) == slot) if slot is not None else (lambda r: loaded_slot(r) is None)
    before = hms_seen(rep)
    m = _Mqtt(ip, s, code)
    try:
        m.publish(ams_change_command(rep, slot))
        for part in m.reports(wait, key=None):
            why = refusal(part, before, command="ams_change_filament")
            if why:
                raise PrinterError(AMS_REJECTED.format(what=what, why=f" ({why})"))
            if "ams" in part and done(part):
                Status.last = None
                return {"done": what, "loaded_slot": loaded_slot(part)}
    finally:
        m.close()
    rep = fetch_report(ip, s, code)
    Status.last = None
    why = refusal(rep, before, command="ams_change_filament")
    if why:
        raise PrinterError(AMS_REJECTED.format(what=what, why=f" ({why})"))
    if done(rep):
        return {"done": what, "loaded_slot": loaded_slot(rep)}
    return {"sent": what, "loaded_slot": loaded_slot(rep),
            "note": "the printer did not refuse, but it has not finished yet: follow it with printer_status"}

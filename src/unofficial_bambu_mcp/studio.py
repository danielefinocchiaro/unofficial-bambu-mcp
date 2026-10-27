"""Where Bambu Studio lives on this machine: executable, profiles, user presets.

Everything can be overridden with environment variables:
  BAMBU_STUDIO_EXE   path to the Bambu Studio executable
  BAMBU_STUDIO_DATA  Bambu Studio data folder (the one with system/ and user/)
"""
import glob
import json
import os
import platform
import shutil
import subprocess

SYSTEM = platform.system()  # Darwin | Windows | Linux


def executable():
    env = os.environ.get("BAMBU_STUDIO_EXE")
    if env:
        return env
    cands = []
    if SYSTEM == "Darwin":
        cands = ["/Applications/BambuStudio.app/Contents/MacOS/BambuStudio",
                 os.path.expanduser("~/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")]
    elif SYSTEM == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if root:
                cands.append(os.path.join(root, "Bambu Studio", "bambu-studio.exe"))
    else:
        cands = [shutil.which("bambu-studio") or "", *glob.glob(os.path.expanduser("~/Applications/Bambu*Studio*.AppImage")),
                 *glob.glob(os.path.expanduser("~/Downloads/Bambu*Studio*.AppImage"))]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def data_dir():
    env = os.environ.get("BAMBU_STUDIO_DATA")
    if env:
        return env
    if SYSTEM == "Darwin":
        return os.path.expanduser("~/Library/Application Support/BambuStudio")
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "BambuStudio")
    return os.path.expanduser("~/.config/BambuStudio")


def app_config():
    """Bambu Studio's own settings (BambuStudio.conf) as a dict, {} if missing or unreadable."""
    try:
        with open(os.path.join(data_dir(), "BambuStudio.conf"), encoding="utf-8") as f:
            txt = f.read()
        return json.loads(txt[txt.find("{"):])
    except (OSError, ValueError):
        return {}


BED_TYPES = ["Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate", "Supertack Plate"]


def preferred_bed_type(machine):
    """The plate the user picked in Bambu Studio for this printer preset, else the last one used there."""
    conf = app_config()
    bed = (conf.get("user_bed_type_list") or {}).get(machine)
    if bed in BED_TYPES:
        return bed
    try:
        i = int(conf.get("app", {}).get("curr_bed_type", 0))      # Bambu's BedType: 1 = Cool Plate ...
    except (TypeError, ValueError):
        i = 0
    return BED_TYPES[i - 1] if 1 <= i <= len(BED_TYPES) else None


def resources_dir():
    exe = executable()
    if not exe:
        return None
    if SYSTEM == "Darwin":
        return os.path.normpath(os.path.join(os.path.dirname(exe), "..", "Resources"))
    if SYSTEM == "Windows":
        return os.path.join(os.path.dirname(exe), "resources")
    return None


def profile_roots():
    """Folders with the BBL system profiles, newest first (the data folder gets updates before the app)."""
    roots = [os.path.join(data_dir(), "system", "BBL")]
    res = resources_dir()
    if res:
        roots.append(os.path.join(res, "profiles", "BBL"))
    return [r for r in roots if os.path.isdir(r)]


def user_id():
    """The signed-in user's preset folder (Bambu Studio stores it as preset_folder in BambuStudio.conf)."""
    conf = os.path.join(data_dir(), "BambuStudio.conf")
    try:
        with open(conf, encoding="utf-8") as f:
            txt = f.read()
        # the file is JSON preceded by a comment line in some versions
        start = txt.find("{")
        data = json.loads(txt[start:]) if start >= 0 else {}
        folder = data.get("app", {}).get("preset_folder") or data.get("preset_folder")
        if folder:
            return str(folder)
    except (OSError, ValueError):
        pass
    users = [d for d in glob.glob(os.path.join(data_dir(), "user", "*")) if os.path.isdir(d)]
    named = [os.path.basename(d) for d in users if os.path.basename(d) != "default"]
    return named[0] if named else ("default" if users else None)


def user_dir(kind=None):
    uid = user_id()
    if not uid:
        return None
    base = os.path.join(data_dir(), "user", uid)
    return os.path.join(base, kind) if kind else base


def version():
    exe = executable()
    if not exe:
        return None
    if SYSTEM == "Darwin":
        plist = os.path.normpath(os.path.join(os.path.dirname(exe), "..", "Info.plist"))
        try:
            out = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleShortVersionString", plist],
                                 capture_output=True, text=True, timeout=10)
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    return None


_CLI_FLAGS = ("--slice", "--outputdir", "--export-3mf", "--export-slicedata")


def instances():
    """Running Bambu Studio processes: [(pid, True if it is a command-line run, e.g. a slicing)]."""
    try:
        if SYSTEM == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout
            return [(0, False)] if "bambu-studio.exe" in out.lower() else []
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        prog = cmd.split(" --", 1)[0]
        if prog.endswith(("Contents/MacOS/BambuStudio", "bambu-studio", "BambuStudio.AppImage")):
            found.append((int(pid), any(f in cmd for f in _CLI_FLAGS)))
    return found


def is_running():
    """Is the Bambu Studio app open (a window, not a command-line slicing)?"""
    return any(not cli for _, cli in instances())


def open_in_gui(path):
    """Open a project in the Bambu Studio window (starts it if needed)."""
    path = os.path.abspath(path)
    if SYSTEM == "Darwin":
        app = executable()
        if app and not is_running():
            # cold start: run the program with the file, as Bambu Studio does for a new window itself; handing
            # the file over with `open -a` while the app starts can leave it running without any window, and
            # while a command-line slicing runs macOS would hand it to that one
            subprocess.Popen([app, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            bundle = app.split("/Contents/")[0] if app and "/Contents/" in app else "BambuStudio"
            subprocess.Popen(["open", "-a", bundle, path])
    elif SYSTEM == "Windows":
        subprocess.Popen([executable() or "bambu-studio.exe", path])
    else:
        subprocess.Popen([executable() or "bambu-studio", path])
    return path


def bambu_connect():
    """Path of the Bambu Connect app, if installed."""
    if SYSTEM == "Darwin":
        for c in ("/Applications/Bambu Connect.app", os.path.expanduser("~/Applications/Bambu Connect.app")):
            if os.path.exists(c):
                return c
    elif SYSTEM == "Windows":
        for root in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", r"C:\Program Files")):
            hits = glob.glob(os.path.join(root, "*", "Bambu Connect*.exe"))
            hits += glob.glob(os.path.join(root, "Programs", "*", "Bambu Connect*.exe"))
            if hits:
                return hits[0]
    return None


def send_to_bambu_connect(path, name):
    """Hand a sliced .gcode.3mf to Bambu Connect (official URL scheme). The user picks the printer and presses Send."""
    from urllib.parse import quote
    url = f"bambu-connect://import-file?path={quote(os.path.abspath(path), safe='')}&name={quote(name, safe='')}&version=1.0.0"
    if SYSTEM == "Darwin":
        subprocess.Popen(["open", url])
    elif SYSTEM == "Windows":
        os.startfile(url)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", url])
    return url

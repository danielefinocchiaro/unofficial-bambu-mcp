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


def is_running():
    try:
        if SYSTEM == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout
            return "bambu-studio.exe" in out.lower()
        out = subprocess.run(["pgrep", "-f", "BambuStudio|bambu-studio"], capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def open_in_gui(path):
    """Open a project in the Bambu Studio window (starts it if needed)."""
    path = os.path.abspath(path)
    if SYSTEM == "Darwin":
        app = executable()
        bundle = app.split("/Contents/")[0] if app and "/Contents/" in app else "BambuStudio"
        subprocess.Popen(["open", "-a", bundle, path])
    elif SYSTEM == "Windows":
        subprocess.Popen([executable() or "bambu-studio.exe", path])
    else:
        subprocess.Popen([executable() or "bambu-studio", path])
    return path

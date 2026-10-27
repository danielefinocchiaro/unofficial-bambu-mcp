"""Make docs/demo.gif and docs/social-preview.png from a real session with the server (needs Bambu Studio, macOS).

  uv run python scripts/make_demo.py            # run the session, then draw
  uv run python scripts/make_demo.py --draw     # draw again from tests/out/demo/session.json

The server is started over stdio and driven by an MCP client, like an assistant does: every tool call, result and
image in the GIF is real. Only the user's requests are written here. Intermediate files go to tests/out/demo.
"""
import asyncio
import base64
import json
import os
import sys
import textwrap
import zipfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "out", "demo")
DOCS = os.path.join(ROOT, "docs")
SOCIAL_PLATE = os.path.join(OUT, "social_plate.png")

FILAMENTS = [{"preset": "Bambu PLA Basic", "color": "#202020"}, {"preset": "Bambu PLA Basic", "color": "#F5F5F5"},
             {"preset": "Bambu PLA Basic", "color": "#FF6A13"}]
LAYERS = (1, 3, 6, 9, 11, 13, 15)

# (what the user says, [(tool, arguments, keep the image, arguments shown in the GIF)])
SCRIPT = [
    ("New P1S project: a tag that says HELLO in white on a black base, an orange 30 mm cup, and a 5 mm pin, "
     "45 mm tall.", [
         ("new_project", {"name": "hello", "printer": "P1S", "filaments": FILAMENTS}, False, ["printer"]),
         ("add_shape", {"shape": "text", "text": "HELLO", "text_height": 12, "height": 1.2, "base": 2,
                        "base_filament": 1, "filament": 2, "name": "tag", "x": 100, "y": 95}, False,
          ["shape", "text", "base"]),
         ("add_shape", {"shape": "cylinder", "diameter": 30, "height": 40, "filament": 3, "name": "cup",
                        "x": 160, "y": 145}, False, ["shape", "diameter", "height"]),
         ("add_shape", {"shape": "cylinder", "diameter": 5, "height": 45, "filament": 3, "name": "pin",
                        "x": 115, "y": 150}, False, ["shape", "diameter", "height"]),
         ("preview_plate", {"view": "iso", "zoom": True, "labels": True}, True, ["labels"]),
     ]),
    ("Anything likely to come off during the print?", [
        ("check_print_risks", {}, False, []),
        ("set_object_setting", {"object": "pin", "key": "brim_type", "value": "outer_only"}, False,
         ["object", "key", "value"]),
        ("check_print_risks", {}, False, []),
    ]),
    ("Slice it. How long, and how much filament?", [
        ("slice_project", {}, False, []),
        *[("preview_layer", {"layer": n}, True, ["layer"]) for n in LAYERS],
    ]),
    ("Now a temperature tower for slot 2, to tune that white.", [
        ("make_temperature_tower", {"filament": 2}, False, ["filament"]),
        ("preview_plate", {"plate": 2, "view": "iso", "zoom": True}, True, ["plate"]),
    ]),
    ("Make the print file for plate 1.", [
        ("send_to_printer", {"plate": 1, "via": "file"}, False, ["plate", "via"]),
    ]),
]


async def run():
    os.makedirs(OUT, exist_ok=True)
    params = StdioServerParameters(command="uv", args=["run", "--directory", ROOT, "unofficial-bambu-mcp"],
                                   env={**os.environ, "UBMCP_DIR": OUT})
    log = []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for ask, calls in SCRIPT:
                step = {"ask": ask, "calls": []}
                for name, args, keep, shown in calls:
                    res = await s.call_tool(name, args)
                    call = {"tool": name, "args": args, "shown": shown, "text": "", "images": []}
                    for c in res.content:
                        if c.type == "image" and keep:
                            p = os.path.join(OUT, f"{len(log)}_{len(step['calls'])}_{name}.png")
                            with open(p, "wb") as f:
                                f.write(base64.b64decode(c.data))
                            call["images"].append(p)
                        elif c.type == "text":
                            call["text"] = c.text
                    if res.is_error:
                        sys.exit(f"{name} failed: {call['text']}")
                    if name == "send_to_printer":           # the plate thumbnail Bambu Studio put in the print file
                        with zipfile.ZipFile(json.loads(call["text"])["print_file"]) as z:
                            thumb = os.path.join(OUT, "print_file_plate_1.png")
                            with open(thumb, "wb") as f:
                                f.write(z.read("Metadata/plate_1.png"))
                        call["images"].append(thumb)
                    step["calls"].append(call)
                log.append(step)
            res = await s.call_tool("preview_plate", {"plate": 1, "view": "iso", "zoom": True})
            with open(SOCIAL_PLATE, "wb") as f:
                f.write(base64.b64decode(next(c.data for c in res.content if c.type == "image")))
    with open(os.path.join(OUT, "session.json"), "w") as f:
        json.dump(log, f, indent=1)
    return log


# ---------------------------------------------------------------- drawing

W, H, PANEL = 960, 540, 420
BG, LEFT = (36, 38, 42), (26, 28, 31)
ASK_BG, ASK_FG = (47, 92, 168), (255, 255, 255)
CALL_FG, RES_FG, DIM = (150, 200, 255), (225, 228, 232), (130, 136, 145)


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


SANS = ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"]
MONO = ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"]


def _call_line(c):
    args = ", ".join(f"{k}={json.dumps(c['args'][k])}" for k in c["shown"])
    more = len(c["args"]) > len(c["shown"])
    return f"{c['tool']}({args}{', …' if more else ''})"


def _result_line(c):
    """A short, faithful summary of the tool's real answer."""
    t = c["tool"]
    if c["images"] and t != "send_to_printer":
        return None
    r = json.loads(c["text"]) if c["text"].strip()[:1] in "[{" else c["text"]
    if t == "new_project":
        return f"{r['printer']}, {r['build_plate']}, {len(r['filaments'])} filaments"
    if t == "add_shape":
        return f"#{r['id']} {r['name']}: " + " × ".join(f"{v:g}" for v in r["size_mm"]) + " mm"
    if t == "check_print_risks":
        risks = (r[0] if isinstance(r, list) else r)["risks"]     # a list of plates comes as one item per plate
        if isinstance(risks, str):
            return risks
        return "; ".join(f"{x.get('object', '')}: {x['risk']}. Advice: {x['advice']}" for x in risks)
    if t == "set_object_setting":
        return ", ".join(f"{k}={v}" for k, v in r["settings"].items())
    if t == "slice_project":
        p = r["plates"][0]
        return (f"{p['minutes']:.0f} min, {p['grams']:g} g, {p['filament_changes']} filament changes, "
                f"{p['layers']} layers, warnings: {len(p['warnings'])}")
    if t == "make_temperature_tower":
        temps = r["temperatures_bottom_to_top"]
        return f"plate {r['plate']}: {temps[0]:g} → {temps[-1]:g} °C, {r['block_height_mm']} mm blocks"
    if t == "send_to_printer":
        return f"{os.path.basename(r['print_file'])}: {r['minutes']:.0f} min, {r['grams']:g} g, thumbnail →"
    return str(r)[:80]


def _left(step, upto, show_results=True):
    """The chat panel: the request, then the calls made so far with their results."""
    img = Image.new("RGB", (PANEL, H), LEFT)
    d = ImageDraw.Draw(img)
    sans, mono, small = _font(SANS, 17), _font(MONO, 12), _font(SANS, 12)
    y = 22
    d.text((22, y), "YOU", font=small, fill=DIM)
    y += 20
    lines = textwrap.wrap(step["ask"], 38)
    box_h = 14 + 23 * len(lines)
    d.rounded_rectangle([18, y, PANEL - 18, y + box_h], 10, fill=ASK_BG)
    for i, line in enumerate(lines):
        d.text((32, y + 8 + 23 * i), line, font=sans, fill=ASK_FG)
    y += box_h + 22
    d.text((22, y), "ASSISTANT → MCP TOOLS", font=small, fill=DIM)
    y += 22
    for c in step["calls"][:upto]:
        if c["tool"] == "preview_layer" and c is not step["calls"][upto - 1] and c["args"]["layer"] != LAYERS[0]:
            continue                                     # one line for the layer sequence
        for line in textwrap.wrap(_call_line(c), 52):
            d.text((22, y), line, font=mono, fill=CALL_FG)
            y += 16
        res = _result_line(c) if show_results else None
        if res:
            for line in textwrap.wrap("→ " + res, 54):
                d.text((30, y), line, font=mono, fill=RES_FG)
                y += 16
        y += 8
    return img


def _frame(left, picture):
    f = Image.new("RGB", (W, H), BG)
    f.paste(left, (0, 0))
    if picture:
        p = Image.open(picture).convert("RGB").resize((H - 20, H - 20), Image.LANCZOS)
        f.paste(p, (PANEL + (W - PANEL - p.width) // 2, 10))
    return f


def draw(log):
    frames, durations = [], []
    picture = None

    def add(img, ms):
        frames.append(img)
        durations.append(ms)

    for step in log:
        calls = step["calls"]
        add(_frame(_left(step, 0), picture), 1600)
        for i, c in enumerate(calls, 1):
            if c["images"]:
                picture = c["images"][0]
            last = i == len(calls)
            layer = c["tool"] == "preview_layer"
            add(_frame(_left(step, i), picture), 4200 if last else (450 if layer else 900))
    end = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(end)
    d.text((W // 2, 210), "unofficial-bambu-mcp", font=_font(SANS, 44), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, 262), "Bambu Studio projects from your AI assistant", font=_font(SANS, 22), fill=RES_FG,
           anchor="mm")
    d.text((W // 2, 300), "You press Print. Nothing changes on the printer without you.", font=_font(SANS, 18), fill=DIM, anchor="mm")
    add(end, 3000)
    path = os.path.join(DOCS, "demo.gif")
    pal = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
    print(path, f"{os.path.getsize(path) / 1e6:.1f} MB, {len(frames)} frames")

    # social preview for the GitHub repository (Settings > Social preview), 1280 × 640
    sp = Image.new("RGB", (1280, 640), BG)
    p = Image.open(SOCIAL_PLATE).convert("RGB")
    p = p.crop((0, 60, p.width, p.height)).resize((640, 600), Image.LANCZOS)    # without the title line
    sp.paste(p, (640, 20))
    d = ImageDraw.Draw(sp)
    d.text((70, 230), "unofficial-bambu-mcp", font=_font(SANS, 52), fill=(255, 255, 255))
    for i, line in enumerate(["Build, slice, check and calibrate", "Bambu Studio projects", "from your AI assistant."]):
        d.text((72, 315 + 40 * i), line, font=_font(SANS, 30), fill=RES_FG)
    d.text((72, 460), "MCP server · unofficial · MIT", font=_font(SANS, 22), fill=DIM)
    path = os.path.join(DOCS, "social-preview.png")
    sp.save(path, optimize=True)
    print(path)


if __name__ == "__main__":
    if "--draw" in sys.argv:
        with open(os.path.join(OUT, "session.json")) as f:
            session = json.load(f)
    else:
        session = asyncio.run(run())
    draw(session)

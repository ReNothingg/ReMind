import argparse
from dataclasses import dataclass
from pathlib import Path

SIZE = 28
PALETTE = {
    "body": "#8F9DB1",
    "cheek": "#7486A0",
    "white": "#F3F6FB",
    "ink": "#222A38",
    "feet": "#516388",
    "sole": "#445477",
    "rose": "#C97789",
    "success": "#539E8B",
    "cloud": "#BCCBDF",
    "mist": "#8197B6",
    "blue": "#789CFF",
}
PIXELS = {
    "c": "body",
    "b": "cheek",
    "w": "white",
    "i": "ink",
    "f": "feet",
    "s": "sole",
    "r": "rose",
    "a": "success",
    "l": "cloud",
    "m": "mist",
    "u": "blue",
}
BODY = (
    "....cccc....",
    "..cccccccc..",
    ".cccccccccc.",
    ".cccccccccc.",
    "cccccccccccc",
    "cccccccccccc",
    "bccccccccccb",
    "cccccccccccc",
    ".cccccccccc.",
    "..cccccccc..",
)
FOOT = (
    "..fff.",
    ".ffff.",
    "ffffff",
    ".ssss.",
)
TUCKED = (
    "..ff..",
    ".ffff.",
    ".ffff.",
    "..ss..",
)
HEEL = (
    ".ff...",
    ".ffff.",
    "..ffff",
    "...sss",
)
TOE = (
    "...ff.",
    "..fff.",
    ".ffff.",
    ".sss..",
)
STRIDES = {
    "reach": ((TOE, 1, 0), (HEEL, 11, -1)),
    "land": ((TOE, 1, -1), (FOOT, 11, 0)),
    "pass": ((TUCKED, 3, -1), (FOOT, 10, 0)),
    "swing": ((HEEL, 4, -2), (TOE, 9, 0)),
    "step": ((FOOT, 4, 0), (TOE, 9, -1)),
    "push": ((FOOT, 2, 0), (TUCKED, 9, -2)),
}
WAVE = {
    "wave-up": (
        "..fff",
        "..fff",
        ".ffff",
        "fff..",
        "ss...",
    ),
    "wave-out": (
        "...ff",
        ".ffff",
        "fffff",
        "ss...",
    ),
}
EYE = (
    "..www..",
    ".wwwww.",
    "wwwwwww",
    "wwwwwww",
    "wwwwwww",
    ".wwwww.",
    "..www..",
)
SMALL_EYE = (
    ".......",
    ".......",
    ".wwwww.",
    "wwwwwww",
    "wwwwwww",
    ".wwwww.",
    ".......",
)
PUPIL = (
    ".ii.",
    "iwii",
    "iiii",
    "iiii",
    ".ii.",
)
WIDE_PUPIL = (
    ".ii.",
    "iwii",
    "iiii",
    "iiii",
    "iiii",
    ".ii.",
)
DOT_PUPIL = ("ii", "ii", ".i")
EYE_LINES = {
    "closed": ("i.....i", ".iiiii."),
    "smile": ("..iii..", ".i...i."),
    "content": (".......", "..iii..", ".i...i."),
}
CLOUD = (
    ".......llll........",
    ".....llllllll.ll...",
    "..llllllllllllllll.",
    ".llllllllllllllllll",
    "llllllllllllllllll.",
    ".lmmmlllmmmlllmmm..",
    "...mmmmmmmmmmmm....",
)
KART = (
    ".................",
    "..ff.............",
    "..ffff......l....",
    ".ffffffff...ll...",
    ".fuuuufffffffff..",
    "ffuuuuufffffffff.",
    ".sssssssssssssss.",
    "..iii.....iii....",
    "..iwi.....iwi....",
    "...i.......i.....",
)
SPARK = (".a.", "aaa", ".a.")
ALERT = ("r.r", ".r.", "r.r")
KEYBOARD = (".llllll.", "fiiiiiif", "ssssssss")
KEYBOARD_LIT = (".llllll.", "fiuiiuif", "ssssssss")
HEART = ("rr.rr", "rrrrr", ".rrr.", "..r..")
TEAR = (".u.", "uuu", ".u.")


@dataclass(frozen=True)
class Pose:
    gaze: int = 1
    gaze_y: int = 0
    lid: str = "open"
    lean: int = 0
    x: int = 0
    y: int = 0
    shape: str = "normal"
    feet: str = "rest"
    mode: str = "plain"
    effect: str = ""
    blush: bool = False
    reverse: bool = False


@dataclass(frozen=True)
class State:
    frames: tuple
    loop: bool = True
    fallback: int = 0


def frame(duration, **changes):
    return duration, Pose(**changes)


def paint(canvas, pattern, x, y, mask=None):
    for row, line in enumerate(pattern):
        for column, pixel in enumerate(line):
            point = x + column, y + row
            if (
                pixel != "."
                and 0 <= point[0] < SIZE
                and 0 <= point[1] < SIZE
                and (mask is None or point in mask)
            ):
                canvas[point] = pixel


def mirror(pattern):
    return tuple(row[::-1] for row in pattern)


def position(canvas, offset, reverse):
    positioned = {}
    for (x, y), color in canvas.items():
        column = SIZE - 1 - x if reverse else x
        column += offset
        if 0 <= column < SIZE:
            positioned[column, y] = color
    return positioned


def paint_feet(canvas, x, y, action):
    if action in STRIDES:
        left, right = STRIDES[action]
        for pattern, offset, lift in (left, (mirror(right[0]), right[1], right[2])):
            paint(canvas, pattern, x + offset, y + lift)
        return
    pattern = TUCKED if action == "tuck" else FOOT
    offset = int(action == "tuck") - int(action == "spread")
    paint(canvas, pattern, x + offset, y - int(action == "left-up"))
    if action not in WAVE:
        paint(canvas, mirror(pattern), x + 10 - offset, y - int(action == "right-up"))


def pet(canvas, x, y, pose):
    paint_feet(canvas, x, y, pose.feet)
    for row, line in enumerate(BODY):
        adjust = int(pose.shape == "squash" and row < 6) - int(pose.shape == "stretch" and row < 4)
        lean = pose.lean if row < 7 else 0
        if pose.blush and row == 6:
            line = "rrccccccccrr"
        paint(canvas, (line,), x + 2 + lean, y - 8 + row + adjust)

    if pose.feet in WAVE:
        waving_height = -3 if pose.feet == "wave-up" else -2
        paint(canvas, WAVE[pose.feet], x + 13, y + waving_height)

    eye_x = x + 4 + pose.lean
    eye_y = y - 7 + int(pose.shape == "squash") - int(pose.shape == "stretch")
    if pose.lid in EYE_LINES:
        paint(canvas, EYE_LINES[pose.lid], eye_x, eye_y + 3 + int(pose.lid == "closed"))
        return
    eye = SMALL_EYE if pose.lid in {"half", "grump", "droop"} else EYE
    mask = {
        (eye_x + column, eye_y + row)
        for row, pattern in enumerate(eye)
        for column, color in enumerate(pattern)
        if color == "w" and not (pose.lid == "grump" and row == 2 and column < 3)
    }
    paint(canvas, eye, eye_x, eye_y, mask)
    pupil = {"wide": WIDE_PUPIL, "startled": DOT_PUPIL}.get(pose.lid, PUPIL)
    small = pose.lid == "startled"
    pupil_y = eye_y + int(pose.lid != "wide") + int(small) + pose.gaze_y
    paint(canvas, pupil, eye_x + 1 + pose.gaze + int(small), pupil_y, mask)
    if pose.lid == "half":
        paint(canvas, (".iiiii.",), eye_x, eye_y + 2)
    elif pose.lid == "grump":
        paint(canvas, ("ii.....", "..iiii."), eye_x, eye_y + 2)
    elif pose.lid == "droop":
        paint(canvas, (".i...i.", "..iii.."), eye_x, eye_y + 2)


def pixels(pose):
    canvas = {}
    x = 6 + pose.x
    y = 19 + pose.y
    if pose.mode == "cloud":
        paint(canvas, CLOUD, x - 2, y - 1)
        pet(canvas, x, y - 4, pose)
        if pose.effect == "trail":
            paint(canvas, ("..ll...", "mm...ll"), x - 7, y + 3)
    elif pose.mode == "kart":
        pet(canvas, x, y - 5, pose)
        paint(canvas, KART, x, y - 5)
        if pose.effect == "fast":
            paint(canvas, ("..uuu", "ll...", "..uu."), x - 5, y)
            for offset in (3, 11):
                paint(canvas, ("i", "w"), x + offset, y + 2)
    else:
        x = 6
        pet(canvas, x, y, pose)
        if pose.effect == "spark":
            paint(canvas, SPARK, x + 15, y - 13)
        elif pose.effect == "alert":
            paint(canvas, ALERT, x + 14, y - 12)
        elif pose.effect == "heart":
            paint(canvas, HEART, x + 13, y - 14)
        elif pose.effect == "tear":
            paint(canvas, TEAR, x + 9, y - 2)
        elif pose.effect in {"keys", "keys-lit"}:
            keyboard = KEYBOARD_LIT if pose.effect == "keys-lit" else KEYBOARD
            paint(canvas, keyboard, x + 11, y + 2)
        return position(canvas, pose.x, pose.reverse)
    return canvas


STATES = {
    "idle": State(
        (
            frame(1700),
            frame(70, lid="half"),
            frame(110, lid="closed", shape="squash"),
            frame(70, lid="half"),
            frame(680),
        )
    ),
    "attentive": State(
        (
            frame(950, gaze_y=1, lean=1),
            frame(110, gaze_y=1, lean=1, lid="half"),
            frame(130, gaze_y=1, lean=1, lid="closed"),
            frame(600, gaze_y=1, lean=1),
            frame(350, gaze_y=1, gaze=2),
        )
    ),
    "typing": State(
        (
            frame(160, gaze=0, gaze_y=1, lean=-1),
            frame(110, gaze=1, gaze_y=1, lean=-1),
            frame(155, gaze=2, gaze_y=1, lean=1),
            frame(100, gaze=2, gaze_y=1, lean=1, feet="right-up"),
            frame(140, gaze=1, gaze_y=1),
        ),
        fallback=2,
    ),
    "waiting": State(
        (
            frame(920, lid="half", gaze_y=1),
            frame(95, lid="half", gaze_y=1, feet="right-up"),
            frame(110, lid="half", gaze_y=1),
            frame(90, lid="half", gaze_y=1, feet="right-up"),
            frame(260, lid="half", gaze_y=1),
            frame(500, gaze=0, gaze_y=1),
            frame(100, lid="closed", shape="squash"),
            frame(330, lid="half", gaze_y=1),
        )
    ),
    "thinking": State(
        (
            frame(450, gaze=0, gaze_y=-1),
            frame(210, gaze=0, gaze_y=-1, lean=-1),
            frame(370, gaze=1, gaze_y=-1),
            frame(520, gaze=2, gaze_y=-1, lean=1),
            frame(90, lid="half"),
            frame(420, gaze=1, gaze_y=-1),
        )
    ),
    "working": State(
        (
            frame(260, lid="grump", gaze=2),
            frame(120, lid="grump", gaze=2, lean=1),
            frame(130, lid="grump", gaze=2, lean=1, shape="squash", feet="spread"),
            frame(140, lid="grump", gaze=2, lean=1, shape="stretch", feet="tuck", y=-1),
            frame(160, lid="grump", gaze=2, lean=1),
            frame(100, lid="closed"),
            frame(300, lid="grump", gaze=2),
        )
    ),
    "coding": State(
        (
            frame(280, lid="grump", lean=1, gaze=2, effect="keys"),
            frame(110, lid="grump", lean=1, gaze=2, feet="right-up", effect="keys"),
            frame(95, lid="grump", lean=1, gaze=2, shape="squash", effect="keys-lit"),
            frame(100, lid="grump", lean=1, gaze=2, feet="right-up", effect="keys"),
            frame(115, lid="grump", lean=1, gaze=2, effect="keys-lit"),
            frame(160, lid="half", lean=1, gaze_y=-1, effect="keys"),
            frame(260, lid="grump", lean=1, gaze=2, effect="keys"),
        )
    ),
    "searching": State(
        (
            frame(170),
            frame(100, gaze=0, lean=-1, feet="left-up"),
            frame(440, gaze=0, lean=-1),
            frame(100, gaze=0),
            frame(80, lid="half"),
            frame(100, gaze=2, lean=1, feet="right-up"),
            frame(440, gaze=2, lean=1),
            frame(130, gaze=2),
            frame(390),
        )
    ),
    "review": State(
        (
            frame(650, gaze=0, lid="half"),
            frame(130, gaze=0, lid="wide", lean=-1),
            frame(340, gaze=0, lid="wide"),
            frame(180, lid="half", gaze_y=1),
            frame(190, gaze=2, lid="wide", lean=1),
            frame(470, gaze=2, lid="half"),
        )
    ),
    "paused": State(
        (
            frame(980, lid="half", gaze_y=1, shape="squash"),
            frame(170, lid="closed", shape="squash"),
            frame(650, lid="half", gaze_y=1, shape="squash"),
        )
    ),
    "sleeping": State(
        (
            frame(1120, lid="closed", shape="squash"),
            frame(470, lid="closed", lean=-1, shape="squash"),
            frame(810, lid="closed"),
            frame(540, lid="closed", lean=-1, shape="squash"),
        )
    ),
    "success": State(
        (
            frame(170),
            frame(110, lid="wide", shape="squash", feet="spread"),
            frame(80, lid="wide", y=-1, shape="stretch", feet="tuck"),
            frame(85, lid="wide", y=-3, feet="tuck"),
            frame(125, lid="smile", y=-5, feet="spread", effect="spark"),
            frame(90, lid="smile", y=-3, feet="spread"),
            frame(80, y=-1, feet="right-up"),
            frame(130, lid="closed", shape="squash", feet="spread"),
            frame(450, lid="smile", effect="spark"),
            frame(480, lid="smile"),
        ),
        loop=False,
        fallback=8,
    ),
    "error": State(
        (
            frame(160),
            frame(130, lid="startled", x=-2, lean=-1, feet="spread", effect="alert"),
            frame(110, lid="startled", x=-1, lean=1, feet="spread"),
            frame(110, lid="startled", x=-1),
            frame(140, lid="closed", shape="squash", feet="tuck"),
            frame(430, lid="droop", gaze_y=1, shape="squash", effect="alert"),
            frame(500, lid="droop", gaze_y=1, shape="squash"),
        ),
        loop=False,
        fallback=5,
    ),
    "waving": State(
        (
            frame(420),
            frame(110, lean=-1, feet="right-up"),
            frame(160, lean=-1, feet="wave-up"),
            frame(140, lean=-1, feet="wave-out", lid="smile"),
            frame(140, lean=-1, feet="wave-up", lid="smile"),
            frame(140, lean=-1, feet="wave-out", lid="smile"),
            frame(140, lean=-1, feet="wave-up"),
            frame(100, feet="right-up"),
            frame(620),
        )
    ),
    "walking": State(
        (
            frame(170, x=-4, gaze=2),
            frame(95, x=-4, gaze=2, lean=1, feet="reach"),
            frame(95, x=-3, gaze=2, lean=1, feet="land"),
            frame(90, x=-2, gaze=2, lean=1, feet="pass"),
            frame(90, x=0, gaze=2, lean=1, feet="swing", y=-1),
            frame(95, x=1, gaze=2, lean=1, feet="step"),
            frame(95, x=2, gaze=2, lean=1, feet="push", y=-1),
            frame(95, x=4, gaze=2, feet="land"),
            frame(170, x=4, gaze=0),
            frame(95, x=4, gaze=2, lean=1, feet="reach", reverse=True),
            frame(95, x=3, gaze=2, lean=1, feet="land", reverse=True),
            frame(90, x=2, gaze=2, lean=1, feet="pass", reverse=True),
            frame(90, x=0, gaze=2, lean=1, feet="swing", y=-1, reverse=True),
            frame(95, x=-1, gaze=2, lean=1, feet="step", reverse=True),
            frame(95, x=-2, gaze=2, lean=1, feet="push", y=-1, reverse=True),
            frame(95, x=-4, gaze=2, feet="land", reverse=True),
        ),
        fallback=4,
    ),
    "lurking": State(
        (
            frame(540, x=-12, gaze=2, lean=1),
            frame(110, x=-10, gaze=2),
            frame(140, x=-8, gaze=2, lean=1),
            frame(570, x=-8, gaze=2),
            frame(80, x=-8, lid="closed"),
            frame(460, x=-8, gaze=2),
            frame(100, x=-10, gaze=0),
            frame(240, x=-13, gaze=0),
        ),
        fallback=3,
    ),
    "dancing": State(
        (
            frame(140, x=-1, lean=-1, feet="left-up", lid="smile"),
            frame(125, x=-2, lean=-1, y=-1, feet="spread", lid="smile"),
            frame(115, x=-2, shape="squash", lid="smile"),
            frame(125, x=-1, y=-2, feet="tuck", lid="smile"),
            frame(140, x=1, lean=1, feet="right-up", lid="smile"),
            frame(125, x=2, lean=1, y=-1, feet="spread", lid="smile"),
            frame(115, x=2, shape="squash", lid="smile"),
            frame(125, x=1, y=-2, feet="tuck", lid="smile"),
        )
    ),
    "happy": State(
        (
            frame(440, lid="smile"),
            frame(150, lid="smile", x=-1, lean=-1),
            frame(160, lid="smile", x=-1, lean=-1, feet="right-up"),
            frame(210, lid="smile", shape="squash"),
            frame(150, lid="smile", x=1, lean=1, feet="left-up"),
            frame(160, lid="smile", x=1, lean=1),
            frame(470, lid="smile"),
        )
    ),
    "content": State(
        (
            frame(780, lid="content"),
            frame(230, lid="content", shape="squash"),
            frame(360, lid="content", shape="squash", feet="tuck"),
            frame(430, lid="content", feet="tuck"),
            frame(630, lid="content"),
        )
    ),
    "excited": State(
        (
            frame(300, lid="wide"),
            frame(100, lid="wide", shape="squash", feet="spread"),
            frame(95, lid="wide", y=-4, x=-1, shape="stretch", feet="tuck"),
            frame(110, lid="smile", y=-5, x=-2, feet="spread"),
            frame(100, lid="smile", y=-2, x=-2, feet="right-up"),
            frame(100, lid="wide", x=-1, shape="squash", feet="spread"),
            frame(95, lid="wide", y=-4, x=1, shape="stretch", feet="tuck"),
            frame(110, lid="smile", y=-6, x=2, feet="spread"),
            frame(110, lid="smile", y=-2, x=1, feet="left-up"),
            frame(120, lid="smile", shape="squash", feet="spread"),
            frame(450, lid="wide"),
        )
    ),
    "affection": State(
        (
            frame(360, blush=True),
            frame(130, lid="half", blush=True, feet="tuck"),
            frame(130, lid="smile", blush=True, feet="tuck", shape="squash"),
            frame(170, lid="smile", blush=True, feet="tuck", effect="heart"),
            frame(450, lid="smile", blush=True, effect="heart", lean=1),
            frame(330, lid="content", blush=True, lean=1),
            frame(400, blush=True),
        ),
        fallback=4,
    ),
    "shy": State(
        (
            frame(460, gaze=0, gaze_y=1, blush=True, feet="tuck"),
            frame(210, gaze=0, lid="half", blush=True, shape="squash", feet="tuck"),
            frame(550, lid="closed", blush=True, shape="squash", feet="tuck"),
            frame(250, gaze=2, lid="half", blush=True, shape="squash", feet="tuck", lean=-1),
            frame(470, gaze=2, blush=True, lean=-1, feet="tuck"),
            frame(210, lid="closed", blush=True, feet="tuck"),
        )
    ),
    "sad": State(
        (
            frame(540, lid="droop", gaze_y=1, shape="squash", feet="tuck"),
            frame(290, lid="droop", gaze_y=1, lean=1, shape="squash", feet="tuck"),
            frame(180, lid="closed", lean=1, shape="squash", feet="tuck"),
            frame(410, lid="droop", gaze_y=1, lean=1, shape="squash", feet="tuck", effect="tear"),
            frame(320, lid="droop", gaze_y=1, lean=1, shape="squash", feet="tuck"),
            frame(460, lid="droop", gaze_y=1, shape="squash", feet="tuck"),
        ),
        fallback=3,
    ),
    "confused": State(
        (
            frame(270, gaze=0),
            frame(180, lid="startled", lean=-1, gaze=0, gaze_y=-1, feet="left-up"),
            frame(470, lid="startled", lean=-1, gaze=0, gaze_y=-1),
            frame(80, lid="closed"),
            frame(130, lid="startled", lean=1, gaze=2, gaze_y=-1, feet="right-up"),
            frame(520, lid="startled", lean=1, gaze=2, gaze_y=-1),
            frame(240, lid="half", gaze=2),
        ),
        fallback=2,
    ),
    "annoyed": State(
        (
            frame(520, lid="grump", gaze=0, shape="squash"),
            frame(160, lid="grump", gaze=0, feet="left-up", lean=-1),
            frame(85, lid="grump", gaze=0, feet="spread", shape="squash", x=-1),
            frame(110, lid="grump", gaze=0, feet="left-up", lean=-1),
            frame(100, lid="grump", gaze=0, feet="spread", shape="squash", x=-1),
            frame(580, lid="grump", gaze=0, shape="squash"),
            frame(330, lid="grump", gaze=2, shape="squash"),
        )
    ),
    "surprised": State(
        (
            frame(300),
            frame(85, lid="startled", feet="spread", shape="squash"),
            frame(110, lid="startled", y=-2, x=-1, feet="tuck", shape="stretch"),
            frame(130, lid="startled", y=-3, x=-1, feet="spread"),
            frame(420, lid="startled", x=-1, feet="spread"),
            frame(130, lid="half", x=-1),
            frame(95, lid="closed"),
            frame(370),
        ),
        fallback=4,
    ),
    "racing": State(
        (
            frame(540, mode="kart", x=-3, lean=1, gaze=2),
            frame(115, mode="kart", x=-2, lean=1, gaze=2, effect="fast"),
            frame(115, mode="kart", x=0, lean=1, gaze=2),
            frame(115, mode="kart", x=3, lean=1, gaze=2, effect="fast"),
            frame(110, mode="kart", x=7, lean=1, gaze=2),
            frame(110, mode="kart", x=16, lean=1, gaze=2, effect="fast"),
            frame(110, mode="kart", x=-18, lean=1, gaze=2),
            frame(110, mode="kart", x=-11, lean=1, gaze=2, effect="fast"),
            frame(120, mode="kart", x=-6, lean=1, gaze=2),
            frame(450, mode="kart", x=-3, lean=1, gaze=2),
        )
    ),
    "cloud": State(
        (
            frame(450, mode="cloud", x=-3, y=1, gaze=2),
            frame(140, mode="cloud", x=-2, y=0, gaze=2, effect="trail"),
            frame(140, mode="cloud", x=-1, y=-1, gaze=2),
            frame(180, mode="cloud", x=1, y=-2, gaze=2, effect="trail"),
            frame(270, mode="cloud", x=2, y=-2, lid="smile"),
            frame(180, mode="cloud", x=1, y=-1, lid="smile", effect="trail"),
            frame(200, mode="cloud", x=0, y=0, gaze=1),
            frame(390, mode="cloud", x=-2, y=1, gaze=1),
        ),
        fallback=6,
    ),
}
STILLS = {"static": Pose(), "cloud-still": Pose(mode="cloud")}


def rectangles(canvas, color):
    active = {}
    complete = []
    for y in range(SIZE):
        filled = [canvas.get((x, y)) == color for x in range(SIZE)] + [False]
        spans = []
        start = None
        for x, value in enumerate(filled):
            if value and start is None:
                start = x
            elif not value and start is not None:
                spans.append((start, x - start))
                start = None
        continued = {span: active.pop(span, y) for span in spans}
        complete.extend((x, top, width, y - top) for (x, width), top in active.items())
        active = continued
    complete.extend((x, top, width, SIZE - top) for (x, width), top in active.items())
    return complete


def paths(canvas, indent):
    result = []
    for code, key in PIXELS.items():
        parts = [f"M{x} {y}h{w}v{h}h-{w}z" for x, y, w, h in rectangles(canvas, code)]
        if parts:
            result.append(f'{indent}<path fill="{PALETTE[key]}" d="{" ".join(parts)}"/>')
    return result


def svg_header():
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}" shape-rendering="crispEdges">'


def state_svg(name, state):
    duration = sum(length for length, _ in state.frames)
    poses = list(dict.fromkeys(pose for _, pose in state.frames))
    boundaries = [(0, state.frames[0][1])]
    elapsed = 0
    for length, pose in state.frames:
        if boundaries[-1][1] != pose:
            boundaries.append((elapsed, pose))
        elapsed += length
    boundaries.append((duration, state.frames[0 if state.loop else -1][1]))
    prefix = f"remind-pet-{name}"
    repeat = "infinite" if state.loop else "1"
    out = [
        svg_header(),
        "  <style>",
        f"    .{prefix} {{",
        f"      animation-duration: {duration}ms;",
        "      animation-timing-function: step-end;",
        f"      animation-iteration-count: {repeat};",
        "      animation-fill-mode: both;",
        "    }",
    ]
    for idx, pose in enumerate(poses):
        frame_class = f"{prefix}-{idx}"
        out.append(f"    .{frame_class} {{ animation-name: {frame_class}; }}")
        out.append(f"    @keyframes {frame_class} {{")
        visibility = None
        rules = {True: [], False: []}
        for ms, active in boundaries:
            visible = active == pose
            if visible != visibility or ms == duration:
                rules[visible].append(f"{100 * ms / duration:.5f}".rstrip("0").rstrip(".") + "%")
                visibility = visible
        for visible, times in rules.items():
            if times:
                value = "visible" if visible else "hidden"
                out.append(f"      {', '.join(times)} {{ visibility: {value}; }}")
        out.append("    }")
    out.extend(
        [
            f"    #still:target ~ .{prefix} {{ animation: none; }}",
            "    @media (prefers-reduced-motion: reduce) {",
            f"      .{prefix} {{ animation: none; }}",
            "    }",
            "  </style>",
            '  <g id="still"/>',
        ]
    )
    for idx, pose in enumerate(poses):
        visibility = "visible" if pose == state.frames[state.fallback][1] else "hidden"
        out.append(f'  <g class="{prefix} {prefix}-{idx}" visibility="{visibility}">')
        out.extend(paths(pixels(pose), "    "))
        out.append("  </g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def still_svg(pose):
    return "\n".join([svg_header(), *paths(pixels(pose), "  "), "</svg>", ""])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "public" / "assets" / "pet",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, state in STATES.items():
        (args.output / f"{name}.svg").write_text(state_svg(name, state), encoding="utf-8")
    for name, pose in STILLS.items():
        (args.output / f"{name}.svg").write_text(still_svg(pose), encoding="utf-8")


if __name__ == "__main__":
    main()

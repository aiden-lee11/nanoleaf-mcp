"""Arcade classics simulated on the panel grid (deterministic, precomputed per loop)."""
from __future__ import annotations

import math
import random

from . import Geo, Panel, hsb, scene, tri


def _precompute(loop_s: float, dt: float, step):
    """Run step(t) for every tick and return the per-tick frames {cell: colour}."""
    frames = []
    for k in range(int(loop_s / dt)):
        frames.append(dict(step(k * dt)))
    return frames


def _precompute_clean(dt, step, state, keys=("over",), min_s=8.0, max_s=60.0, force=None):
    """Like _precompute, but the loop ends exactly when the game has just reset after a game-over (any of `keys`
    going from set to None), so a stored replay always starts fresh. If no game-over happens by max_s, one is
    forced (via `force(t)` or by setting state[keys[0]] = t) and the loop ends after that reset."""
    frames, t, forced = [], 0.0, False
    was_over = False
    while True:
        frames.append(dict(step(t)))
        t += dt
        over = any(state.get(k) is not None for k in keys)
        if was_over and not over and t >= min_s:
            break
        was_over = over
        if t >= max_s and not over and not forced:
            forced = True
            if force:
                force(t)
            else:
                state[keys[0]] = t
        if t > max_s + 10:
            break
    return frames, len(frames) * dt


def _player(frames, dt, loop_s, background):
    def fn(t: float, p: Panel):
        f = frames[int((t % loop_s) / dt) % len(frames)]
        return f.get((p.row, p.col)) or background(t, p)
    return fn


# ---------------------------------------------------------------- breakout ----------------------------------
@scene("breakout", "Breakout", "A paddle on the bottom row keeps a ball in play while it knocks out two rows of coloured bricks; flash and reset when the wall is gone.",
       tags=("game", "retro"), params={"seed": 1}, min_rows=3)
def breakout(geo: Geo, seed: int = 1):
    dt = 0.05
    rng = random.Random(seed)
    brick_rows = [geo.nrows - 1, geo.nrows - 2] if geo.nrows >= 4 else [geo.nrows - 1]
    colours = [hsb(0, 90, 95), hsb(30, 95, 100), hsb(55, 95, 100), hsb(120, 80, 90), hsb(200, 90, 100), hsb(280, 80, 95)]
    state = {"bricks": {c: colours[(c[1] // 2 + c[0]) % len(colours)] for c in geo.cells if c[0] in brick_rows},
             "bu": 0.5, "bv": 0.15, "vu": 0.55, "vv": 0.75, "pu": 0.5, "flash": {}, "won": None, "dead": None}

    def cell_of(u, v):
        p = geo.nearest(max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))
        return (p.row, p.col)

    def step(t):
        s = state
        frame = {}
        if s["won"] is not None:
            if t - s["won"] > 1.5:                       # reset
                s.update(bricks={c: colours[(c[1] // 2 + c[0]) % len(colours)] for c in geo.cells if c[0] in brick_rows},
                         bu=0.5, bv=0.15, vu=rng.choice([-0.55, 0.55]), vv=0.75, won=None)
            elif int((t - s["won"]) / 0.2) % 2 == 0:
                return {c: (220, 230, 255) for c in geo.cells}
            return {}
        if s["dead"] is not None:
            if t - s["dead"] > 0.8:
                s.update(bu=s["pu"], bv=0.15, vu=rng.choice([-0.5, 0.5]), vv=0.75, dead=None)
            else:
                frame.update({c: col for c, col in s["bricks"].items()})
                frame[cell_of(s["pu"], 0.0)] = (255, 60, 60)
                return frame
        # paddle follows the ball with some lag
        s["pu"] += max(-0.9 * dt, min(0.9 * dt, s["bu"] - s["pu"]))
        # ball
        s["bu"] += s["vu"] * dt; s["bv"] += s["vv"] * dt
        if s["bu"] < 0: s["bu"], s["vu"] = -s["bu"], abs(s["vu"])
        if s["bu"] > 1: s["bu"], s["vu"] = 2 - s["bu"], -abs(s["vu"])
        if s["bv"] > 1: s["bv"], s["vv"] = 2 - s["bv"], -abs(s["vv"])
        if s["bv"] <= 0.0:
            if abs(s["bu"] - s["pu"]) < 0.2:
                s["bv"], s["vv"] = 0.0, abs(s["vv"])
                s["vu"] += (s["bu"] - s["pu"]) * 1.5
                s["vu"] = max(-0.9, min(0.9, s["vu"]))
            else:
                s["dead"] = t
        bc = cell_of(s["bu"], s["bv"])
        if bc in s["bricks"]:
            del s["bricks"][bc]; s["flash"][bc] = t; s["vv"] = -s["vv"]
            if not s["bricks"]:
                s["won"] = t
        for c, col in s["bricks"].items():
            frame[c] = col
        for c, t0 in list(s["flash"].items()):
            if t - t0 < 0.2: frame[c] = (255, 255, 255)
            else: del s["flash"][c]
        frame[cell_of(s["pu"], 0.0)] = (200, 210, 230)
        frame[bc] = (255, 255, 210)
        return frame

    frames, loop = _precompute_clean(dt, step, state, keys=("won",), min_s=10.0, max_s=40.0)
    return _player(frames, dt, loop, lambda t, p: (0, 0, 0)), loop


# ---------------------------------------------------------------- frogger -----------------------------------
@scene("frogger", "Frogger", "A green frog hops row by row through lanes of traffic sliding left and right at different speeds, waiting for gaps; squashed frogs flash and try again.",
       tags=("game", "retro"), params={"seed": 2}, min_rows=3)
def frogger(geo: Geo, seed: int = 2):
    dt = 0.05
    rng = random.Random(seed)
    top = geo.nrows - 1
    lanes = list(range(1, top))
    cars = {}
    for r in lanes:
        d = 1 if r % 2 else -1
        speed = (1.2 + 0.6 * ((r * 7) % 3)) * d           # cols per second
        colour = [hsb(0, 90, 90), hsb(45, 95, 100), hsb(200, 85, 100), hsb(300, 70, 90)][r % 4]
        gap = 4 + (r % 2)
        cars[r] = {"speed": speed, "colour": colour, "gap": gap, "offset": rng.random() * gap}
    W = geo.ncols

    def car_at(r, c, t):
        lane = cars[r]
        x = (c - lane["speed"] * t - lane["offset"]) % lane["gap"]
        return x < 2                                       # two-cell cars

    state = {"row": 0, "col": geo.ncols // 2, "hop_t": -1.0, "dead": None, "home": None, "u": 0.0}

    def step(t):
        s = state
        frame = {}
        for r in lanes:
            for c in range(W):
                if (r, c) in geo.cells and car_at(r, c, t):
                    frame[(r, c)] = cars[r]["colour"]
        for c in range(W):
            if (top, c) in geo.cells: frame[(top, c)] = hsb(120, 60, 22)
            if (0, c) in geo.cells: frame.setdefault((0, c), hsb(120, 60, 22))
        if s["home"] is not None:
            if t - s["home"] > 1.0:
                s.update(row=0, col=rng.choice([c for c in range(W) if (0, c) in geo.cells]), home=None)
            elif int((t - s["home"]) / 0.15) % 2 == 0:
                frame[(top, s["col"])] = (255, 255, 255)
            return frame
        if s["dead"] is not None:
            if t - s["dead"] > 0.8:
                s.update(row=0, col=rng.choice([c for c in range(W) if (0, c) in geo.cells]), dead=None)
            else:
                frame[(s["row"], s["col"])] = (255, 40, 40) if int((t - s["dead"]) / 0.1) % 2 == 0 else (120, 0, 0)
            return frame
        if s["row"] in lanes and car_at(s["row"], s["col"], t):
            s["dead"] = t
        if t - s["hop_t"] > 0.35:
            nxt = s["row"] + 1
            if nxt in cars:
                safe = all(not car_at(nxt, s["col"], t + k * dt) for k in range(0, 9))
                if safe:
                    s["row"], s["hop_t"] = nxt, t
                elif not car_at(s["row"], s["col"] + 1, t) if s["row"] in cars else False:
                    pass
            elif nxt <= top:
                s["row"], s["hop_t"] = nxt, t
                if nxt == top:
                    s["home"] = t
            if (s["row"], s["col"]) not in geo.cells:      # hole in the layout: shuffle sideways
                s["col"] = min((c for c in range(W) if (s["row"], c) in geo.cells), key=lambda c: abs(c - s["col"]))
        frame[(s["row"], s["col"])] = (80, 255, 80) if t - s["hop_t"] > 0.15 else (200, 255, 120)
        return frame

    loop = 30.0
    frames = _precompute(loop, dt, step)
    return _player(frames, dt, loop, lambda t, p: (0, 0, 0)), loop


# ---------------------------------------------------------------- asteroids ---------------------------------
@scene("asteroids", "Asteroids", "A ship in the middle of a dark field turns to shoot grey rocks drifting past; hits burst orange and split the rock.",
       tags=("game", "retro"), params={"seed": 4}, min_rows=3)
def asteroids(geo: Geo, seed: int = 4):
    dt = 0.05
    rng = random.Random(seed)
    from . import H
    rows_w, rows_h = geo.w / H, geo.h / H

    def spawn(big=True):
        side = rng.random()
        u = rng.choice([-0.05, 1.05]) if side < 0.5 else rng.random()
        v = rng.random() if side < 0.5 else rng.choice([-0.05, 1.05])
        ang = rng.random() * 2 * math.pi
        sp = 0.12 + 0.08 * rng.random()
        return {"u": u, "v": v, "du": math.cos(ang) * sp, "dv": math.sin(ang) * sp, "big": big}

    state = {"rocks": [spawn() for _ in range(3)], "bullets": [], "booms": [], "next_fire": 0.5}
    ship_u, ship_v = 0.5, 0.5

    def step(t):
        s = state
        frame = {}
        for r in s["rocks"]:
            r["u"] = (r["u"] + r["du"] * dt) % 1.1
            r["v"] = (r["v"] + r["dv"] * dt) % 1.1
        if t >= s["next_fire"] and s["rocks"]:
            target = min(s["rocks"], key=lambda r: math.hypot(r["u"] - ship_u, r["v"] - ship_v))
            ang = math.atan2(target["v"] - ship_v, target["u"] - ship_u)
            s["bullets"].append({"u": ship_u, "v": ship_v, "du": math.cos(ang) * 1.6, "dv": math.sin(ang) * 1.6, "born": t})
            s["next_fire"] = t + 0.9
        for b in list(s["bullets"]):
            b["u"] += b["du"] * dt; b["v"] += b["dv"] * dt
            if not (0 <= b["u"] <= 1 and 0 <= b["v"] <= 1):
                s["bullets"].remove(b); continue
            for r in list(s["rocks"]):
                if math.hypot((r["u"] - b["u"]) * rows_w, (r["v"] - b["v"]) * rows_h) < (1.0 if r["big"] else 0.6):
                    s["rocks"].remove(r); s["booms"].append((r["u"], r["v"], t))
                    if r["big"]:
                        for k in range(2):
                            ang = rng.random() * 2 * math.pi
                            s["rocks"].append({"u": r["u"], "v": r["v"], "du": math.cos(ang) * 0.22, "dv": math.sin(ang) * 0.22, "big": False})
                    if b in s["bullets"]: s["bullets"].remove(b)
                    break
        while len(s["rocks"]) < 3:
            s["rocks"].append(spawn())
        for r in s["rocks"]:
            for p in geo.panels:
                d = math.hypot((p.u - r["u"]) * rows_w, (p.v - r["v"]) * rows_h)
                if d < (0.95 if r["big"] else 0.55):
                    frame[(p.row, p.col)] = (120, 120, 130) if r["big"] else (90, 90, 100)
        for (bu, bv, t0) in list(s["booms"]):
            if t - t0 > 0.4:
                s["booms"].remove((bu, bv, t0)); continue
            f = (t - t0) / 0.4
            for p in geo.panels:
                if math.hypot((p.u - bu) * rows_w, (p.v - bv) * rows_h) < 0.6 + 1.4 * f:
                    frame[(p.row, p.col)] = hsb(30 - 25 * f, 100, 100 * (1 - f))
        for b in s["bullets"]:
            p = geo.nearest(b["u"], b["v"]); frame[(p.row, p.col)] = (255, 255, 200)
        sp = geo.nearest(ship_u, ship_v); frame[(sp.row, sp.col)] = (120, 230, 255)
        return frame

    loop = 24.0
    frames = _precompute(loop, dt, step)
    return _player(frames, dt, loop, lambda t, p: hsb(230, 40, 8 if ((t * 0.3 + p.id * 0.41) % 1.0) < 0.05 else 2)), loop


# ---------------------------------------------------------------- tetris ------------------------------------
@scene("tetris", "Tetris", "Coloured pieces fall and lock into a stack; full rows flash and clear; when the stack reaches the top it flashes and starts over.",
       tags=("game", "retro"), params={"seed": 5, "fall_s": 0.3}, min_rows=3)
def tetris(geo: Geo, seed: int = 5, fall_s: float = 0.3):
    dt = 0.05
    rng = random.Random(seed)
    W, Hh = geo.ncols, geo.nrows
    # short boards get flat pieces only (overhangs kill a 3-4 row board in seconds); taller boards get real shapes
    shapes = [[(0, 0)], [(0, 0), (0, 1)], [(0, 0), (0, 1)], [(0, 0), (0, 1), (0, 2)], [(0, 0), (0, 1), (0, 2)]]
    if geo.nrows >= 5:
        shapes += [[(0, 0), (1, 0)], [(0, 0), (0, 1), (1, 0)], [(0, 0), (0, 1), (1, 1)], [(0, 0), (0, 1), (0, 2), (0, 3)], [(0, 0), (0, 1), (1, 0), (1, 1)]]
    colours = [hsb(190, 90, 100), hsb(50, 95, 100), hsb(280, 80, 95), hsb(120, 80, 90), hsb(0, 90, 95), hsb(30, 95, 100), hsb(220, 90, 100)]
    state = {"stack": {}, "piece": None, "next_fall": 0.0, "clear": None, "over": None}

    def new_piece():
        shape = rng.choice(shapes)
        w = max(c for _, c in shape) + 1
        col0 = rng.randint(0, max(0, W - w))
        return {"cells": shape, "row": Hh - 1, "col": col0, "colour": rng.choice(colours)}

    def cells_of(pc, row):
        return [(row - dr, pc["col"] + dc) for dr, dc in pc["cells"]]

    def fits(pc, row):
        return all(c in geo.cells and c not in state["stack"] for c in cells_of(pc, row))

    def step(t):
        s = state
        frame = dict(s["stack"])
        if s["over"] is not None:
            if t - s["over"] > 1.2:
                s.update(stack={}, piece=None, over=None)
            elif int((t - s["over"]) / 0.15) % 2 == 0:
                return {c: (150, 160, 190) for c in geo.cells}
            return frame
        if s["clear"] is not None:
            rows, t0 = s["clear"]
            if t - t0 < 0.5:
                for c in list(frame):
                    if c[0] in rows: frame[c] = (255, 255, 255) if int((t - t0) / 0.1) % 2 == 0 else frame[c]
                return frame
            new_stack = {}
            for (r, c), col in s["stack"].items():
                if r in rows: continue
                drop = sum(1 for rr in rows if rr < r)
                new_stack[(r - drop, c)] = col
            s["stack"] = new_stack; s["clear"] = None
            frame = dict(s["stack"])
        if s["piece"] is None:
            pc = new_piece()
            # choose the column like a player would: complete rows if possible, otherwise keep the stack low
            w = max(c for _, c in pc["cells"]) + 1
            best, best_score = None, None
            for col in range(0, max(1, W - w + 1)):
                cand = dict(pc, col=col)
                if not fits(cand, cand["row"]):
                    continue
                row = cand["row"]
                while row > 0 and fits(cand, row - 1):
                    row -= 1
                placed = set(s["stack"]) | set(cells_of(cand, row))
                complete = sum(1 for r in range(Hh) if all((r, c) in placed for c in range(W) if (r, c) in geo.cells))
                landing = max(r for r, _ in cells_of(cand, row))
                holes = sum(1 for (r, c) in cells_of(cand, row) if r > 0 and (r - 1, c) in geo.cells and (r - 1, c) not in placed)
                lowest = min((r for r in range(Hh) if any((r, c) in geo.cells and (r, c) not in placed for c in range(W))), default=Hh)
                fill = sum(1 for c in range(W) if (lowest, c) in placed) if lowest < Hh else 0
                score = complete * 30 - landing * 6 - holes * 8 + fill * 1.0 + rng.random() * 0.3
                if best_score is None or score > best_score:
                    best, best_score = cand, score
            if best is None:
                s["over"] = t; return frame
            s["piece"] = best; s["next_fall"] = t + fall_s
        pc = s["piece"]
        if t >= s["next_fall"]:
            if fits(pc, pc["row"] - 1):
                pc["row"] -= 1
            else:
                for c in cells_of(pc, pc["row"]): s["stack"][c] = pc["colour"]
                s["piece"] = None
                full = [r for r in range(Hh) if all((r, c) in s["stack"] for c in range(W) if (r, c) in geo.cells)]
                if full: s["clear"] = (full, t)
                return dict(s["stack"])
            s["next_fall"] = t + fall_s
        for c in cells_of(pc, pc["row"]):
            frame[c] = pc["colour"]
        return frame

    frames, loop = _precompute_clean(dt, step, state, keys=("over",), min_s=10.0, max_s=45.0)
    return _player(frames, dt, loop, lambda t, p: (0, 0, 0)), loop


# ---------------------------------------------------------------- mario -------------------------------------
@scene("mario", "Mario", "A side-scroller: Mario (red cap, blue overalls) runs right over green ground, hops over pipes and goombas, and bumps gold question blocks for coins.",
       tags=("game", "retro"), params={"speed": 2.5}, param_docs={"speed": "world speed in columns per second"}, min_rows=3)
def mario(geo: Geo, speed: float = 2.5):
    dt = 0.05
    W, Hh = geo.ncols, geo.nrows
    mario_col = max(1, W // 4)
    # the world: repeating strip of objects at world columns
    world_len = 40
    pipes = {8, 22}                                   # two-cell tall
    goombas = {14, 31}
    qblocks = {4, 18, 27}                             # at row 2 (or the top row)
    bricks = {5, 6, 19, 28, 35}
    loop = world_len / speed
    q_row = min(Hh - 1, 2)
    state = {"coins": {}, "bumped": set()}

    def step(t):
        s = state
        off = t * speed                                # world column at the left edge
        frame = {}
        for c in range(W):
            wc = int(math.floor(c + off)) % world_len
            if (0, c) in geo.cells: frame[(0, c)] = hsb(120, 70, 45) if (wc % 2) else hsb(110, 65, 35)
            if wc in pipes:
                for r in (1, 2):
                    if (r, c) in geo.cells and r < Hh: frame[(r, c)] = hsb(110, 85, 70)
            if wc in goombas and (1, c) in geo.cells:
                frame[(1, c)] = hsb(25, 80, 55)
            if wc in qblocks and (q_row, c) in geo.cells:
                frame[(q_row, c)] = hsb(45, 95, 100) if int(t / 0.3) % 2 == 0 else hsb(40, 90, 80)
            if wc in bricks and (q_row, c) in geo.cells:
                frame[(q_row, c)] = hsb(20, 70, 50)
        # mario: jump when something is coming in the next couple of columns
        ahead = [int(math.floor(mario_col + off + k)) % world_len for k in range(0, 3)]
        obstacle = any(a in pipes or a in goombas for a in ahead)
        under_q = int(math.floor(mario_col + off)) % world_len in qblocks
        phase = (t * speed) % 1.0
        height = 0
        if obstacle:
            height = 2 if any(a in pipes for a in ahead) else 1
        elif under_q and q_row >= 3:
            height = 1
        base = 1 + height
        if (base, mario_col) in geo.cells: frame[(base, mario_col)] = (230, 30, 30)          # cap / shirt
        if (base - 1, mario_col) in geo.cells and base - 1 >= 1: frame[(base - 1, mario_col)] = (40, 70, 220)   # overalls
        if under_q and (q_row + 1, mario_col) in geo.cells:
            frame[(q_row + 1, mario_col)] = hsb(48, 90, 100)                                 # coin popping out
        return frame

    frames = _precompute(loop, dt, step)
    return _player(frames, dt, loop, lambda t, p: hsb(205, 60, 60 + 20 * p.v)), loop


# ---------------------------------------------------------------- bricks and balls --------------------------
@scene("bricks_balls", "Bricks and Balls", "The mobile brick-breaker: grey bricks (brighter = more hits left) creep down a row each turn, a stream of red balls fired from the bottom ricochets off the walls chipping them down until they shatter; lose when a brick reaches the floor.",
       tags=("game", "mobile"), params={"seed": 6, "balls": 6}, param_docs={"balls": "balls per volley"}, min_rows=3)
def bricks_balls(geo: Geo, seed: int = 6, balls: int = 6):
    dt = 0.05
    rng = random.Random(seed)
    W, Hh = geo.ncols, geo.nrows
    from . import H
    rows_w, rows_h = geo.w / H, geo.h / H
    level = {"n": 1}
    state = {"bricks": {}, "balls": [], "phase": "aim", "phase_t": 0.0, "launch_u": 0.5, "angle": 1.2, "fired": 0,
             "flash": {}, "over": None}

    def durability_colour(hits):                  # grey bricks: the more hits left, the brighter
        return hsb(215, 22, [34, 48, 63, 79, 95][min(4, hits - 1)])

    def new_row():
        row = {}
        density = 0.55 if Hh >= 4 else 0.35
        for c in range(W):
            if (Hh - 1, c) in geo.cells and rng.random() < density:
                row[(Hh - 1, c)] = rng.randint(1, min(5, 1 + level["n"]) if Hh >= 4 else min(3, 1 + level["n"] // 2))
        return row

    def descend():
        moved = {}
        for (r, c), hits in state["bricks"].items():
            moved[(r - 1, c)] = hits
        state["bricks"] = moved
        state["bricks"].update(new_row())
        level["n"] += 1

    state["bricks"] = new_row(); descend()

    def cell(u, v):
        p = geo.nearest(max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))
        return (p.row, p.col)

    def step(t):
        s = state
        frame = {}
        if s["over"] is not None:
            if t - s["over"] > 1.5:
                s.update(bricks={}, balls=[], phase="aim", phase_t=t, over=None); level["n"] = 1
                s["bricks"] = new_row(); descend()
            elif int((t - s["over"]) / 0.2) % 2 == 0:
                return {c: (255, 80, 80) for c in geo.cells}
        for c, hits in s["bricks"].items():
            if c in geo.cells: frame[c] = durability_colour(hits)
        for c, t0 in list(s["flash"].items()):
            if t - t0 < 0.15: frame[c] = (255, 200, 200)
            else: del s["flash"][c]
        if s["phase"] == "aim":
            if t - s["phase_t"] > 0.6:
                targets = [(c, h) for c, h in s["bricks"].items() if c in geo.cells]
                if targets:
                    tc = max(targets, key=lambda ch: ch[1] * 10 - ch[0][0])[0]
                    tu, tv = tc[1] / max(1, W - 1), tc[0] / max(1, Hh - 1)
                    s["angle"] = math.atan2(max(0.2, tv - 0.0), (tu - s["launch_u"]) + rng.uniform(-0.15, 0.15))
                s["phase"], s["phase_t"], s["fired"], s["balls"] = "fire", t, 0, []
        if s["phase"] == "fire":
            if s["fired"] < balls and t - s["phase_t"] >= s["fired"] * 0.12:
                s["balls"].append({"u": s["launch_u"], "v": 0.02, "du": math.cos(s["angle"]) * 0.9, "dv": math.sin(s["angle"]) * 0.9, "home": False})
                s["fired"] += 1
            for b in s["balls"]:
                if b["home"]: continue
                b["u"] += b["du"] * dt; b["v"] += b["dv"] * dt
                if b["u"] < 0: b["u"], b["du"] = -b["u"], abs(b["du"])
                if b["u"] > 1: b["u"], b["du"] = 2 - b["u"], -abs(b["du"])
                if b["v"] > 1: b["v"], b["dv"] = 2 - b["v"], -abs(b["dv"])
                bc = cell(b["u"], b["v"])
                if bc in s["bricks"]:
                    s["bricks"][bc] -= 1; s["flash"][bc] = t
                    if s["bricks"][bc] <= 0: del s["bricks"][bc]
                    b["dv"] = -b["dv"]; b["v"] += b["dv"] * dt * 2
                if b["v"] <= 0:
                    b["home"] = True; b["v"] = 0.0
            if s["fired"] >= balls and all(b["home"] for b in s["balls"]):
                s["launch_u"] = s["balls"][0]["u"] if s["balls"] else 0.5
                descend()
                if any(r <= 0 for (r, _) in s["bricks"]):
                    s["over"] = t
                s["phase"], s["phase_t"] = "aim", t
        for b in s["balls"]:
            if not b["home"]:
                frame[cell(b["u"], b["v"])] = (255, 40, 40)
        frame[cell(s["launch_u"], 0.0)] = (160, 20, 20)
        return frame

    frames, loop = _precompute_clean(dt, step, state, keys=("over",), min_s=10.0, max_s=45.0)
    return _player(frames, dt, loop, lambda t, p: (0, 0, 0)), loop


# ---------------------------------------------------------------- fruit ninja -------------------------------
@scene("fruit_ninja", "Fruit Ninja", "Fruit tossed up in arcs from the bottom; a white blade streak slices each at the top of its arc, the halves fly apart and juice splashes; a bomb now and then sails through untouched.",
       tags=("game", "mobile"), params={"seed": 7}, min_rows=3)
def fruit_ninja(geo: Geo, seed: int = 7):
    dt = 0.05
    rng = random.Random(seed)
    from . import H
    rows_w, rows_h = geo.w / H, geo.h / H
    FRUITS = [((40, 200, 60), (255, 60, 80)), ((255, 140, 0), (255, 190, 60)), ((255, 220, 40), (255, 240, 150)),
              ((220, 30, 40), (255, 120, 120)), ((120, 200, 40), (180, 240, 90)), ((160, 40, 200), (210, 130, 240))]
    state = {"items": [], "next": 0.6, "streaks": [], "splats": [], "halves": []}
    g = -1.4

    def step(t):
        s = state
        frame = {}
        if t >= s["next"]:
            n = rng.choice([1, 1, 2])
            for _ in range(n):
                bomb = rng.random() < 0.15
                u = rng.uniform(0.15, 0.85)
                apex = rng.uniform(0.6, 0.95)
                dv = math.sqrt(2 * -g * apex)
                s["items"].append({"u": u, "v": 0.0, "du": rng.uniform(-0.12, 0.12), "dv": dv, "bomb": bomb,
                                   "fruit": rng.choice(FRUITS), "sliced": False, "born": t})
            s["next"] = t + rng.uniform(1.1, 1.8)
        for it in list(s["items"]):
            it["u"] += it["du"] * dt; it["v"] += it["dv"] * dt; it["dv"] += g * dt
            if it["v"] < -0.05:
                s["items"].remove(it); continue
            if not it["bomb"] and not it["sliced"] and it["dv"] <= 0.05 and it["v"] > 0.3:
                it["sliced"] = True
                ang = rng.uniform(0.5, 1.2) * rng.choice([-1, 1])
                s["streaks"].append((it["u"], it["v"], ang, t))
                skin, flesh = it["fruit"]
                for d in (-1, 1):
                    s["halves"].append({"u": it["u"], "v": it["v"], "du": d * 0.35 + it["du"], "dv": 0.25, "colour": flesh})
                s["splats"].append((it["u"], it["v"], flesh, t))
                s["items"].remove(it)
        for h in list(s["halves"]):
            h["u"] += h["du"] * dt; h["v"] += h["dv"] * dt; h["dv"] += g * dt
            if h["v"] < -0.05: s["halves"].remove(h)
        # draw: splats first (fading), then streaks, then flying things
        for (u, v, colour, t0) in list(s["splats"]):
            if t - t0 > 0.6:
                s["splats"].remove((u, v, colour, t0)); continue
            f = (t - t0) / 0.6
            for p in geo.panels:
                if math.hypot((p.u - u) * rows_w, (p.v - v) * rows_h) < 1.1:
                    frame[(p.row, p.col)] = tuple(int(c * (1 - f) * 0.7) for c in colour)
        for (u, v, ang, t0) in list(s["streaks"]):
            if t - t0 > 0.15:
                s["streaks"].remove((u, v, ang, t0)); continue
            for k in (-1.2, -0.6, 0, 0.6, 1.2):
                p = geo.nearest(u + math.cos(ang) * k / rows_w, v + math.sin(ang) * k / rows_h)
                frame[(p.row, p.col)] = (255, 255, 255)
        for h in s["halves"]:
            if 0 <= h["u"] <= 1 and 0 <= h["v"] <= 1:
                p = geo.nearest(h["u"], h["v"]); frame[(p.row, p.col)] = h["colour"]
        for it in s["items"]:
            if 0 <= it["u"] <= 1 and 0 <= it["v"] <= 1:
                p = geo.nearest(it["u"], it["v"])
                if it["bomb"]:
                    frame[(p.row, p.col)] = (255, 60, 30) if int(t / 0.12) % 3 == 0 else (60, 60, 70)
                else:
                    frame[(p.row, p.col)] = it["fruit"][0]
        return frame

    loop = 24.0
    frames = _precompute(loop, dt, step)
    return _player(frames, dt, loop, lambda t, p: hsb(30, 40, 6)), loop


# ---------------------------------------------------------------- suika -------------------------------------
@scene("suika", "Suika Game", "The watermelon game: fruit drop into the box and settle; two of the same kind touching merge into the next fruit with a pop, cherry up to watermelon. Overflow the box and it resets.",
       tags=("game", "mobile"), params={"seed": 8, "drop_s": 0.9}, param_docs={"drop_s": "seconds between drops"}, min_rows=3)
def suika(geo: Geo, seed: int = 8, drop_s: float = 0.9):
    dt = 0.05
    rng = random.Random(seed)
    W, Hh = geo.ncols, geo.nrows
    LEVELS = [hsb(350, 90, 75), hsb(0, 95, 100), hsb(275, 70, 85), hsb(30, 100, 100), hsb(18, 90, 90), hsb(5, 85, 95),
              hsb(80, 60, 90), hsb(20, 50, 100), hsb(50, 95, 100), hsb(100, 60, 85), hsb(120, 85, 60)]
    adj_cells = {}
    for p in geo.panels:
        adj_cells[(p.row, p.col)] = [(geo.by_key[k].row, geo.by_key[k].col) for k in geo.adjacency[p.key] if k[0] == p.device]
    state = {"fruit": {}, "falling": None, "next_drop": 0.5, "pops": {}, "over": None, "fall_t": 0.0}

    def below(cell):
        r, c = cell
        for cand in ((r - 1, c), (r - 1, c - 1), (r - 1, c + 1)):
            if cand in geo.cells and cand not in state["fruit"]:
                return cand
        return None

    def settle():
        moved = True
        while moved:
            moved = False
            for cell in sorted(state["fruit"], key=lambda c: c[0]):
                lvl = state["fruit"][cell]
                b = below(cell)
                if b is not None:
                    del state["fruit"][cell]; state["fruit"][b] = lvl; moved = True

    def merges(t):
        changed = True
        while changed:
            changed = False
            for cell in sorted(state["fruit"], key=lambda c: c[0]):
                lvl = state["fruit"].get(cell)
                if lvl is None: continue
                for nb in adj_cells.get(cell, []):
                    if state["fruit"].get(nb) == lvl and lvl < len(LEVELS) - 1:
                        low, high = (cell, nb) if cell[0] <= nb[0] else (nb, cell)
                        del state["fruit"][high]; state["fruit"][low] = lvl + 1
                        state["pops"][low] = t; changed = True
                        break
                if changed:
                    settle(); break

    def step(t):
        s = state
        frame = {}
        if s["over"] is not None:
            if t - s["over"] > 1.5:
                s.update(fruit={}, falling=None, over=None, next_drop=t + 0.5)
            elif int((t - s["over"]) / 0.2) % 2 == 0:
                return {c: (255, 255, 255) for c in geo.cells}
        for cell, lvl in s["fruit"].items():
            frame[cell] = LEVELS[lvl]
        for cell, t0 in list(s["pops"].items()):
            if t - t0 < 0.2: frame[cell] = (255, 255, 255)
            else: del s["pops"][cell]
        if s["falling"] is None and t >= s["next_drop"] and s["over"] is None:
            cols = [c for c in range(W) if (Hh - 1, c) in geo.cells and (Hh - 1, c) not in s["fruit"]]
            if not cols:
                s["over"] = t; return frame
            s["falling"] = {"cell": (Hh - 1, rng.choice(cols)), "lvl": rng.choice([0, 0, 1, 1, 2]), "t": t}
        if s["falling"] is not None:
            f = s["falling"]
            if t - f["t"] >= 0.12:
                nxt = None
                r, c = f["cell"]
                for cand in ((r - 1, c), (r - 1, c - 1), (r - 1, c + 1)):
                    if cand in geo.cells and cand not in s["fruit"]:
                        nxt = cand; break
                if nxt is None:
                    s["fruit"][f["cell"]] = f["lvl"]; s["falling"] = None
                    merges(t)
                    s["next_drop"] = t + drop_s
                    if any(r >= Hh - 1 for (r, _) in s["fruit"]) and len(s["fruit"]) > W:
                        s["over"] = t
                    return {**frame, **{cell: LEVELS[l] for cell, l in s["fruit"].items()}}
                f["cell"], f["t"] = nxt, t
            frame[f["cell"]] = LEVELS[f["lvl"]]
        return frame

    frames, loop = _precompute_clean(dt, step, state, keys=("over",), min_s=15.0, max_s=50.0)
    return _player(frames, dt, loop, lambda t, p: hsb(40, 50, 8)), loop

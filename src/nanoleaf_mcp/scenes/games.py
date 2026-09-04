"""Games that play themselves on the panel grid."""
from __future__ import annotations

import math
import random

from . import Geo, Panel, hsb, scene, tri


def _snake_routes(geo: Geo) -> list[list[tuple[str, int]]]:
    """Several long routes through the panel graph: different starts on the first controller, each continuing over
    the bridge and along the following controllers."""
    adj = geo.adjacency
    by_dev = {d: {p.key for p in geo.of_device(d)} for d in geo.devices}

    def leftmost(d):
        return min(geo.of_device(d), key=lambda p: (round(p.x / 20), p.y)).key

    def bridge(i):
        if i + 1 >= len(geo.devices):
            return None, None
        br = [(a, b) for a in by_dev[geo.devices[i]] for b in adj[a] if b in by_dev[geo.devices[i + 1]]]
        return br[0] if br else (None, None)

    first = geo.devices[0]
    target, next_entry = bridge(0)
    cands = []
    for cand in sorted(by_dev[first]):
        seg = geo.longest_path(cand, by_dev[first], target, budget=15000)
        if target is None or seg[-1] == target:
            cands.append(seg)
    cands.sort(key=len, reverse=True)
    best = len(cands[0]) if cands else 0
    segs, starts = [], set()
    for seg in cands:
        if len(seg) >= best - 1 and seg[0] not in starts:
            segs.append(seg); starts.add(seg[0])
        if len(segs) == 3:
            break
    tail: list = []
    entry = next_entry
    for i in range(1, len(geo.devices)):
        entry = entry or leftmost(geo.devices[i])
        target, next_entry = bridge(i)
        seg = geo.longest_path(entry, by_dev[geo.devices[i]], target, budget=15000)
        tail += seg
        entry = next_entry if (target is not None and seg[-1] == target) else None
    return [seg + tail for seg in segs] or [tail]


@scene("snake", "Snake", "Snake over the real panel graph: get-ready pulse, apples that pop when eaten, a green victory sweep or a crash where the body dies from the tail. Rounds vary route, direction and speed.",
       tags=("game", "multi"), params={"step_s": 0.28, "rounds": 6, "seed": 11},
       param_docs={"step_s": "seconds per move at normal speed", "rounds": "rounds per loop", "seed": "random seed for apples/crashes"})
def snake(geo: Geo, step_s: float = 0.28, rounds: int = 6, seed: int = 11):
    routes = _snake_routes(geo)
    variants: list[list] = []
    for r in routes:
        variants.append(r); variants.append(list(reversed(r)))
    rng = random.Random(seed)
    READY, WIN, CRASH, PAUSE = 1.0, 1.8, 1.3, 0.6
    speeds = [1.0, 0.8, 1.15, 0.7, 0.9, 0.85]
    plan, cursor = [], 0.0
    for r in range(rounds):
        pth = variants[r % len(variants)]
        n = len(pth)
        step = step_s * speeds[r % len(speeds)]
        apples = sorted(rng.sample(range(4, max(5, n - 1)), min(4, max(1, n // 6)))) if n > 5 else []
        crash_at = None if r % 3 != 1 or n < 8 else rng.randint(int(n * 0.55), n - 3)
        play = (crash_at if crash_at is not None else n) * step
        outcome = CRASH if crash_at is not None else WIN
        plan.append({"idx": {k: i for i, k in enumerate(pth)}, "n": n, "step": step, "apples": apples,
                     "crash_at": crash_at, "t0": cursor, "play": play, "outcome": outcome,
                     "dur": READY + play + outcome + PAUSE})
        cursor += plan[-1]["dur"]
    loop = cursor

    def board(p):
        return hsb(220, 30, 4 if p.id % 2 else 6)

    def fn(t: float, p: Panel):
        t %= loop
        rd = next(rd for rd in plan if rd["t0"] <= t < rd["t0"] + rd["dur"])
        if p.key not in rd["idx"]:
            return hsb(0, 0, 2)
        i, n, step = rd["idx"][p.key], rd["n"], rd["step"]
        lt = t - rd["t0"]
        if lt < READY:
            if i < 3:
                return hsb(120, 80, 35 + 45 * (0.5 + 0.5 * math.sin(2 * math.pi * lt * 2.5)))
            return hsb(0, 95, 95) if i in rd["apples"] else board(p)
        lt -= READY
        if lt < rd["play"]:
            head = int(lt / step)
            length = 3 + 2 * sum(1 for a in rd["apples"] if a <= head)
            if i == head:
                if head in rd["apples"] and lt - head * step < 0.22:
                    return (255, 255, 200)
                return hsb(110, 60, 100)
            if head - length < i < head:
                return hsb(120, 90, 85 - 45 * (head - i) / max(1, length))
            if i in rd["apples"] and i > head:
                return hsb(0, 95, 95)
            return board(p)
        lt -= rd["play"]
        if rd["crash_at"] is None:
            if lt < WIN:
                front = (lt / WIN) * (n + 8)
                d = front - i
                if 0 <= d < 8:
                    return hsb(120 + 30 * (d / 8), 80, 100 * (1 - d / 8) ** 1.2 + 4)
                return hsb(120, 60, 8) if d >= 8 else board(p)
            return board(p)
        if lt < CRASH:
            head = rd["crash_at"]
            length = 3 + 2 * sum(1 for a in rd["apples"] if a <= head)
            f = lt / CRASH
            if head - length < i <= head:
                age = (head - i) / max(1, length)
                if i == head:
                    return hsb(35, 90, 100 * (1 - f) + 4)
                return hsb(120, 90, (85 - 45 * age) * (1 - f)) if age < (1 - f) ** 1.5 else board(p)
            return board(p)
        return board(p)
    return fn, loop


@scene("pong", "Pong", "A ball bounces around the board between two paddles.", tags=("game",), params={"loop_s": 7.4}, min_rows=2)
def pong(geo: Geo, loop_s: float = 7.4):
    def fn(t: float, p: Panel):
        bx = 0.5 + 0.5 * math.sin(t * 1.7); by = 0.5 + 0.5 * math.sin(t * 2.9 + 1)
        pl = 0.5 + 0.5 * math.sin(t * 2.9 + 1); pr = 0.5 + 0.5 * math.sin(t * 2.9 + 1.3)
        if p is geo.nearest(bx, by):
            return (255, 255, 255)
        if p.col == 0 and abs(p.v - pl) < 0.3:
            return hsb(150, 100, 100)
        if p.col == geo.ncols - 1 and abs(p.v - pr) < 0.3:
            return hsb(320, 100, 100)
        if abs(p.u - 0.5) < 0.06 and p.row % 2 == 0:
            return hsb(0, 0, 18)
        return hsb(0, 0, 3)
    return fn, loop_s


@scene("space_shooter", "Space Shooter", "Arcade shooter simulated on the grid: the ship sweeps the bottom row and fires, aliens march in the top rows, hits explode.",
       tags=("game", "retro"), params={"loop_s": 12.0}, min_rows=3)
def space_shooter(geo: Geo, loop_s: float = 12.0):
    dt = 0.05
    alien_rows = [geo.nrows - 1] if geo.nrows < 4 else [geo.nrows - 1, geo.nrows - 2]
    home = [(r, c) for r in alien_rows for c in range(geo.ncols) if (c + r) % 2 == 0 and (r, c) in geo.cells]
    steps = int(loop_s / dt)
    frames: list[dict] = []
    alive = set(home); bullets: list[list] = []; booms: dict = {}; next_fire = 0.4; cleared = 0.0
    for k in range(steps):
        t = k * dt
        off = round(math.sin(2 * math.pi * t / 4.0))
        ship_c = round((geo.ncols - 1) * tri(t, 5.0))
        if t >= next_fire:
            bullets.append([t, ship_c]); next_fire += 0.7
        pos_alien = {}
        for (r, c0) in alive:
            if (r, c0 + off) in geo.cells:
                pos_alien[(r, c0 + off)] = (r, c0)
        frame = {}
        for b in list(bullets):
            r = 1 + (t - b[0]) * 5.0
            cell = (round(r), b[1])
            if r > geo.nrows - 0.5:
                bullets.remove(b); continue
            if cell in pos_alien:
                alive.discard(pos_alien[cell]); booms[cell] = t; bullets.remove(b); continue
            if cell in geo.cells:
                frame[cell] = "bullet"
        for cell, t0 in list(booms.items()):
            if t - t0 < 0.35:
                frame[cell] = "boom1" if t - t0 < 0.15 else "boom2"
            else:
                del booms[cell]
        for cell in pos_alien:
            frame.setdefault(cell, "alien")
        if (0, ship_c) in geo.cells:
            frame[(0, ship_c)] = "ship"
        if not alive and cleared == 0.0:
            cleared = t
        if cleared and t - cleared < 1.0 and int((t - cleared) / 0.25) % 2 == 0:
            for cell in geo.cells:
                frame.setdefault(cell, "win")
        frames.append(frame)
    colours = {"ship": hsb(185, 80, 100), "bullet": hsb(55, 60, 100), "alien": hsb(120, 90, 80),
               "boom1": hsb(30, 100, 100), "boom2": hsb(10, 100, 60), "win": hsb(120, 60, 35)}

    def fn(t: float, p: Panel):
        tag = frames[int((t % loop_s) / dt) % steps].get((p.row, p.col))
        if tag:
            return colours[tag]
        return hsb(230, 40, 9 if ((t * 0.3 + p.id * 0.41) % 1.0) < 0.05 else 2)
    return fn, loop_s


@scene("pacman", "Pac-Man", "Pac-Man chomps along a corridor of pellets through the panel maze, a red ghost fleeing ahead and a pink one chasing; a blinking power pellet turns the ghost blue so it can be eaten. Level-clear flash, then again.",
       tags=("game", "retro", "multi"), params={"step_s": 0.3, "seed": 3},
       param_docs={"step_s": "seconds per move", "seed": "which corridor is used when several exist"})
def pacman(geo: Geo, step_s: float = 0.3, seed: int = 3):
    routes = _snake_routes(geo)
    route = routes[seed % len(routes)]
    idx = {k: i for i, k in enumerate(route)}
    n = len(route)
    power = max(2, int(n * 0.55))
    lead, chase = 4, 3
    catch = power + lead                       # where the blue ghost gets eaten
    steps = n + 2
    play = steps * step_s
    CLEAR, PAUSE = 1.6, 0.6
    loop = play + CLEAR + PAUSE
    WALL, PELLET, EATEN = hsb(230, 90, 14), hsb(40, 30, 55), hsb(230, 80, 5)
    PAC, PAC_OPEN = (255, 220, 0), (160, 130, 0)
    RED, PINK, BLUE, EYES = (255, 40, 40), (255, 130, 200), (40, 60, 255), (230, 230, 255)

    def fn(t: float, p: Panel):
        lt = t % loop
        if p.key not in idx:
            if lt >= play and lt < play + CLEAR and int((lt - play) / 0.25) % 2 == 0:
                return (200, 210, 255)
            return WALL
        i = idx[p.key]
        if lt >= play:
            if lt < play + CLEAR and int((lt - play) / 0.25) % 2 == 0:
                return (200, 210, 255)
            return EATEN
        k = int(lt / step_s)
        head = min(n - 1, k)
        powered = head >= power
        red_i = min(n - 1, head + lead) if not powered else catch
        pink_i = head - chase
        if i == head:
            return PAC_OPEN if k % 2 else PAC
        if i == red_i and head < catch:
            return BLUE if powered and int(lt / 0.2) % 4 != 3 else RED
        if i == red_i and head == catch:
            return EYES
        if i == pink_i and i >= 0:
            return PINK
        if i > head:
            if i == power:
                return (255, 255, 255) if int(lt / 0.25) % 2 == 0 else PELLET
            return PELLET
        return EATEN
    return fn, loop

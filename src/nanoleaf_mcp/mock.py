"""Mock player: every scene animated in the browser on layouts you have not built yet.

    nanoleaf mock --layout 4x8-2 --layout 5x6 --layout 3x10 --out mock.html

Frames are sampled from the same scene functions that drive real panels, so what you see is what a wall of
that shape would show. Useful for choosing a layout before peeling panels off the wall.
"""
from __future__ import annotations

import html
import json

from .render import oriented_triangles
from .scenes import Geo, build, colours_at, geo_from_layouts, list_scenes, parse_layout_spec


def _svg(pos: list[dict], scale: float = 0.62) -> str:
    tris = oriented_triangles(pos, 0)
    xs = [v[0] for t in tris for v in t["verts"]]; ys = [v[1] for t in tris for v in t["verts"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); pad = 14
    w, h = (x1 - x0) * scale + 2 * pad, (y1 - y0) * scale + 2 * pad
    polys = "".join(
        f'<polygon data-pid="{t["id"]}" points="{" ".join(f"{(vx - x0) * scale + pad:.1f},{(y1 - vy) * scale + pad:.1f}" for vx, vy in t["verts"])}" fill="#222" stroke="#111" stroke-width="3"/>'
        for t in tris)
    return f'<svg viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}"><rect width="100%" height="100%" fill="#0d0d10" rx="8"/>{polys}</svg>'


def build_player(layout_specs: list[str], scene_names: list[str] | None = None, fps: int = 15,
                 max_seconds: float = 30.0) -> str:
    layouts = [parse_layout_spec(s) for s in layout_specs]
    names = scene_names or [s["name"] for s in list_scenes() if "test" not in s["tags"]]
    blocks, data = [], []
    for li, (ltitle, pos) in enumerate(layouts):
        geo = geo_from_layouts([("mock", pos, 0.0)])
        pids = [p.id for p in geo.panels]
        cards = []
        for name in names:
            fn, duration, spec = build(name, geo)
            secs = 1.0 / fps if spec.static else min(max_seconds, duration if duration > 0 else 1.0)
            n = max(1, int(round(secs * fps)))
            frames = [[colours_at(geo, fn, i / fps)["mock"][pid] for pid in pids] for i in range(n)]
            data.append({"loop": round(secs, 2), "pids": pids, "frames": frames, "static": spec.static})
            cards.append(f'<div class="card" data-k="{len(data) - 1}"><h3>{html.escape(spec.title)}</h3>{_svg(pos)}'
                         f'<div class="bar">{"" if spec.static else "<button class=play>Play</button>"}<span class="t"></span></div>'
                         f'<p class="d">{html.escape(spec.description)}</p></div>')
        blocks.append(f'<section><h2>{html.escape(ltitle)}</h2><div class="grid">{"".join(cards)}</div></section>')
    return f"""<!doctype html><meta charset="utf-8"><title>Nanoleaf scene mock-ups</title>
<style>
body{{background:#111;color:#eee;font-family:-apple-system,Helvetica,sans-serif;margin:24px}}
h1{{font-weight:600;font-size:22px;margin-bottom:4px}} p{{color:#aaa;max-width:80ch}} .d{{font-size:12px;margin:6px 0 0;max-width:34ch}}
h2{{font-size:17px;font-weight:500;color:#ddd;margin:34px 0 10px;border-top:1px solid #2a2a2e;padding-top:18px}}
h3{{font-size:14px;font-weight:500;color:#bbb;margin:0 0 6px}}
.grid{{display:flex;flex-wrap:wrap;gap:18px}} .card{{background:#17171b;border-radius:10px;padding:12px}}
.bar{{display:flex;gap:10px;align-items:center;margin-top:6px;font-size:12px;color:#999;min-height:26px}}
button{{background:#2a2a30;color:#eee;border:1px solid #444;border-radius:6px;padding:4px 12px;cursor:pointer}}
button:hover{{background:#3a3a42}} svg polygon{{transition:fill 70ms linear}} svg{{max-width:100%;height:auto}}
.top{{display:flex;gap:10px;align-items:center;margin:14px 0 0;font-size:13px;color:#999}}
</style>
<h1>Scenes on candidate layouts</h1>
<p>Sampled at {fps} fps from the same scene functions that drive real panels. Play everything or one card at a time;
the speed slider applies to all.</p>
<div class="top"><button id="all">Play all</button><button id="stop">Pause all</button>
<label>speed <input id="speed" type="range" min="0.25" max="2" step="0.25" value="1"> <span id="sv">1.0x</span></label></div>
{''.join(blocks)}
<script>
const DATA={json.dumps(data)}; const FPS={fps}; let speed=1;
const cards=[...document.querySelectorAll('.card')].map(el=>{{const d=DATA[+el.dataset.k];
  return {{d,el,btn:el.querySelector('.play'),t:el.querySelector('.t'),polys:Object.fromEntries([...el.querySelectorAll('polygon')].map(p=>[p.dataset.pid,p])),playing:false,frame:0,acc:0}};}});
function draw(c){{const f=c.d.frames[c.frame]; c.d.pids.forEach((pid,k)=>c.polys[pid].setAttribute('fill',f[k])); if(!c.d.static) c.t.textContent=`t = ${{(c.frame/FPS).toFixed(1)}}s / ${{c.d.loop.toFixed(1)}}s`;}}
cards.forEach(c=>{{draw(c); if(c.btn) c.btn.onclick=()=>{{c.playing=!c.playing; c.btn.textContent=c.playing?'Pause':'Play';}};}});
document.getElementById('all').onclick=()=>cards.forEach(c=>{{if(c.btn){{c.playing=true;c.btn.textContent='Pause';}}}});
document.getElementById('stop').onclick=()=>cards.forEach(c=>{{if(c.btn){{c.playing=false;c.btn.textContent='Play';}}}});
document.getElementById('speed').oninput=e=>{{speed=+e.target.value;document.getElementById('sv').textContent=speed.toFixed(2)+'x';}};
let last=performance.now();
(function tick(now){{const dt=(now-last)/1000; last=now;
  cards.forEach(c=>{{if(!c.playing)return; c.acc+=dt*speed*FPS; const a=Math.floor(c.acc); if(a>0){{c.acc-=a; c.frame=(c.frame+a)%c.d.frames.length; draw(c);}}}});
  requestAnimationFrame(tick);}})(last);
</script>"""

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
    plan = build_plan_tab(layout_specs)
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
.tabs{{display:flex;gap:6px;margin-bottom:18px}} .tab{{font-size:14px;padding:8px 18px;border-radius:8px}} .tab.active{{background:#3b6fd6;border-color:#3b6fd6}}
.guide p{{font-size:14px;line-height:1.5;max-width:90ch}} .plan{{margin:30px 0}} .facts{{display:flex;flex-wrap:wrap;gap:22px;font-size:13px;color:#bbb;margin:6px 0 10px}}
.facts b{{color:#eee}} .facts input{{width:64px;background:#222;color:#eee;border:1px solid #444;border-radius:4px;padding:2px 6px}}
.stage svg{{background:#0d0d10;border-radius:8px}} .instr{{font-size:14px;color:#ddd;max-width:90ch;min-height:2.6em}}
</style>
<nav class="tabs"><button class="tab active" data-tab="scenes-tab">Scenes</button><button class="tab" data-tab="plan-tab">Build plan</button></nav>
<div id="scenes-tab">
<h1>Scenes on candidate layouts</h1>
<p>Sampled at {fps} fps from the same scene functions that drive real panels. Play everything or one card at a time;
the speed slider applies to all.</p>
<div class="top"><button id="all">Play all</button><button id="stop">Pause all</button>
<label>speed <input id="speed" type="range" min="0.25" max="2" step="0.25" value="1"> <span id="sv">1.0x</span></label></div>
{''.join(blocks)}
</div>
{plan}
<script>
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));
  document.getElementById('scenes-tab').hidden=b.dataset.tab!=='scenes-tab'; document.getElementById('plan-tab').hidden=b.dataset.tab!=='plan-tab';}});
</script>
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


# ---------------------------------------------------------------- build plan tab ------------------------------
PANEL_SIDE_CM = 21.0                      # Nanoleaf Light Panels (NL22/NL28): 21 cm sides, 18.2 cm tall
PANEL_HEIGHT_CM = PANEL_SIDE_CM * 3 ** 0.5 / 2


def _plan_data(pos: list[dict], scale: float = 0.9) -> dict:
    """Geometry for the step-by-step mounting animation: screen-space panels, build order, shared (linker) edges,
    and three Command-strip rectangles per panel with the pull tab sticking out past each edge."""
    from .scenes import geo_from_layouts
    geo = geo_from_layouts([("plan", pos, 0.0)])
    tris = {t["id"]: t for t in oriented_triangles(pos, 0)}
    xs = [v[0] for t in tris.values() for v in t["verts"]]; ys = [v[1] for t in tris.values() for v in t["verts"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); pad = 42
    sx = lambda x: (x - x0) * scale + pad
    sy = lambda y: (y1 - y) * scale + pad
    side = 150.0
    # build order: bottom row left->right, then upward; every panel must touch one already placed (linker chain)
    remaining = sorted(geo.panels, key=lambda p: (p.row, p.x))
    order, placed = [], set()
    adj = geo.adjacency
    # first panel: the leftmost UP-pointing panel of the bottom row, so its base sits flat on the level line
    first = next((p for p in remaining if p.row == 0 and p.up), remaining[0])
    order.append(first); placed.add(first.key); remaining.remove(first)
    while remaining:
        for p in remaining:
            if not placed or any(k in placed for k in adj[p.key]):
                order.append(p); placed.add(p.key); remaining.remove(p); break
        else:
            p = remaining.pop(0); order.append(p); placed.add(p.key)
    by_id = {p.id: p for p in geo.panels}
    steps = []
    placed_ids: list[int] = []
    for p in order:
        t = tris[p.id]
        verts = t["verts"]
        cx, cy = t["cx"], t["cy"]
        edges, strips = [], []
        for a, b in zip(verts, verts[1:] + verts[:1]):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            dx, dy = (b[0] - a[0]) / side, (b[1] - a[1]) / side          # unit along the edge
            nx, ny = cx - mx, cy - my                                    # toward the centroid (inward)
            nl = (nx * nx + ny * ny) ** 0.5; nx, ny = nx / nl, ny / nl
            shared = None
            for q in placed_ids:
                qv = tris[q]["verts"]
                if sum(1 for v in (a, b) if any(abs(v[0] - w[0]) < 1 and abs(v[1] - w[1]) < 1 for w in qv)) == 2:
                    shared = q
            edges.append({"a": [sx(a[0]), sy(a[1])], "b": [sx(b[0]), sy(b[1])], "shared": shared})
            inset, half_len, half_w, tab = 0.12 * side, 0.21 * side, 0.035 * side, 0.10 * side
            def rect(c_x, c_y, hl, hw):
                pts = [(c_x + dx * hl + nx * hw, c_y + dy * hl + ny * hw), (c_x - dx * hl + nx * hw, c_y - dy * hl + ny * hw),
                       (c_x - dx * hl - nx * hw, c_y - dy * hl - ny * hw), (c_x + dx * hl - nx * hw, c_y + dy * hl - ny * hw)]
                return [[sx(px), sy(py)] for px, py in pts]
            strip_c = (mx + nx * inset, my + ny * inset)
            tab_c = (mx - nx * tab / 2, my - ny * tab / 2)                # outward, past the edge
            strips.append({"strip": rect(*strip_c, half_len, half_w), "tab": rect(*tab_c, half_w * 1.6, tab / 2)})
        touching = [q for q in placed_ids if any(e["shared"] == q for e in edges)]
        linker = touching[-1] if touching else None
        steps.append({"id": p.id, "row": p.row, "col": p.col, "verts": [[sx(v[0]), sy(v[1])] for v in verts],
                      "cx": sx(cx), "cy": sy(cy), "edges": edges, "strips": strips, "touching": touching, "linker": linker,
                      "up": p.up})
        placed_ids.append(p.id)
    w_cm = (geo.ncols + 1) / 2 * PANEL_SIDE_CM
    h_cm = geo.nrows * PANEL_HEIGHT_CM
    return {"w": (x1 - x0) * scale + 2 * pad, "h": (y1 - y0) * scale + 2 * pad, "steps": steps, "n": len(steps),
            "w_cm": round(w_cm, 1), "h_cm": round(h_cm, 1), "rows": geo.nrows,
            "frame": {"x0": sx(x0), "x1": sx(x1), "y0": sy(y0), "y1": sy(y1)}}


def build_plan_tab(layout_specs: list[str]) -> str:
    plans = []
    for spec in layout_specs:
        title, pos = parse_layout_spec(spec)
        plans.append({"title": title, "spec": spec, **_plan_data(pos)})
    cards = "".join(f'''<section class="plan" data-i="{i}">
<h2>{html.escape(p["title"])}</h2>
<div class="facts"><div><b>{p["w_cm"]} cm</b> ({p["w_cm"] / 2.54:.1f} in) wide × <b>{p["h_cm"]} cm</b> ({p["h_cm"] / 2.54:.1f} in) tall</div><div><b>{p["n"]}</b> panels · <b>{p["n"] - 1}</b> linkers · <b>{3 * p["n"]}</b> Command strips</div>
<div>centre it: opening / wall width <input class="wall" type="number" value="48" min="10" max="400" step="0.5"> <select class="unit"><option value="in" selected>in</option><option value="cm">cm</option></select> → start mark <b class="offset"></b> in from the left edge, bottom edge on your level line</div></div>
<div class="stage"><svg viewBox="0 0 {p["w"]:.0f} {p["h"]:.0f}" width="{p["w"]:.0f}" height="{p["h"]:.0f}"></svg></div>
<div class="bar"><button class="prev">◀ Prev</button><button class="play">▶ Play</button><button class="next">Next ▶</button><span class="stepno"></span></div>
<p class="instr"></p>
</section>''' for i, p in enumerate(plans))
    return f'''
<div id="plan-tab" hidden>
<h1>Build plan</h1>
<div class="guide">
<p><b>Before you peel anything.</b> Draw a level line on the wall where the bottom edge of the panels will sit (masking tape works). Mark the start point on it. Lay the whole thing out on the floor first and let the Nanoleaf app's Layout Assistant confirm the shape and the panel count.</p>
<p><b>Start bottom-left and build in rows.</b> The bottom row is the only straight edge, so it sets everything: put the first panel's base on the level line at the start mark, then work left to right along the bottom row, then each row above, seating every new panel into the notch between the ones below it. Every panel must share an edge with one already mounted so the linker chain stays connected.</p>
<p><b>Three Command strips per panel, tabs facing out.</b> One strip along each edge, about 2 cm (¾ in) in from it, centred, with the pull tab pointing out past the edge. Press each panel for 30 seconds. Note that on shared edges the tab ends up under the neighbouring panel, so take panels down from the outside in.</p>
<p><b>Controller and Rhythm module</b> clip onto any outer edge that has a free linker slot; put the controller on the panel nearest the outlet (its cable is about 2.5 m / 8 ft) and the Rhythm module somewhere you can reach. Let the strips cure for an hour before powering up.</p>
</div>
{cards}
</div>
<script>
const PLANS={json.dumps(plans)};
document.querySelectorAll('.plan').forEach(sec=>{{
  const P=PLANS[+sec.dataset.i]; const svg=sec.querySelector('svg'); const NS='http://www.w3.org/2000/svg';
  let step=0, timer=null;
  const el=(n,a)=>{{const e=document.createElementNS(NS,n); for(const k in a) e.setAttribute(k,a[k]); return e;}};
  const poly=pts=>pts.map(q=>q.map(v=>v.toFixed(1)).join(',')).join(' ');
  function draw(){{
    svg.innerHTML='';
    svg.appendChild(el('rect',{{width:'100%',height:'100%',fill:'#0d0d10',rx:8}}));
    const f=P.frame;
    svg.appendChild(el('line',{{x1:f.x0-30,y1:f.y0,x2:f.x1+30,y2:f.y0,stroke:'#4c8',  'stroke-width':1.5,'stroke-dasharray':'6 4'}}));
    const lbl=(x,y,t,c)=>{{const s=el('text',{{x,y,fill:c||'#9aa',  'font-size':11,'font-family':'Helvetica','text-anchor':'middle'}}); s.textContent=t; svg.appendChild(s);}};
    lbl(f.x1+18,f.y0-6,'level line','#4c8');
    svg.appendChild(el('line',{{x1:f.x0,y1:f.y0+18,x2:f.x1,y2:f.y0+18,stroke:'#777','stroke-width':1}}));
    lbl((f.x0+f.x1)/2,f.y0+32,P.w_cm+' cm  /  '+(P.w_cm/2.54).toFixed(1)+' in');
    svg.appendChild(el('line',{{x1:f.x0-18,y1:f.y0,x2:f.x0-18,y2:f.y1,stroke:'#777','stroke-width':1}}));
    const vt=el('text',{{x:f.x0-24,y:(f.y0+f.y1)/2,fill:'#9aa','font-size':11,'font-family':'Helvetica','text-anchor':'middle',transform:`rotate(-90 ${{f.x0-24}} ${{(f.y0+f.y1)/2}})`}}); vt.textContent=P.h_cm+' cm / '+(P.h_cm/2.54).toFixed(1)+' in'; svg.appendChild(vt);
    P.steps.forEach((s,i)=>{{
      if(i>step) {{ svg.appendChild(el('polygon',{{points:poly(s.verts),fill:'none',stroke:'#2a2a33','stroke-width':1.5,'stroke-dasharray':'3 3'}})); return; }}
      const cur=i===step;
      svg.appendChild(el('polygon',{{points:poly(s.verts),fill:cur?'#2f4f7a':'#242a36',stroke:cur?'#8fc3ff':'#3a4150','stroke-width':cur?2.5:1.5}}));
      if(cur){{
        s.strips.forEach(st=>{{ svg.appendChild(el('polygon',{{points:poly(st.strip),fill:'#e8e8ee',stroke:'#999','stroke-width':0.6}})); svg.appendChild(el('polygon',{{points:poly(st.tab),fill:'#ff5c5c'}})); }});
        s.edges.forEach(e=>{{ if(s.linker!==null && e.shared===s.linker) svg.appendChild(el('line',{{x1:e.a[0],y1:e.a[1],x2:e.b[0],y2:e.b[1],stroke:'#ffb300','stroke-width':5,'stroke-linecap':'round'}})); }});
      }}
      const t=el('text',{{x:s.cx,y:s.cy+4,fill:cur?'#fff':'#8a93a6','font-size':11,'font-family':'Helvetica','text-anchor':'middle'}}); t.textContent=i+1; svg.appendChild(t);
    }});
    if(step===0){{ svg.appendChild(el('circle',{{cx:P.steps[0].verts.reduce((m,v)=>v[0]<m[0]?v:m)[0],cy:f.y0,r:5,fill:'#4c8'}})); lbl(P.steps[0].verts.reduce((m,v)=>v[0]<m[0]?v:m)[0],f.y0-10,'start mark','#4c8'); }}
    const s=P.steps[step];
    sec.querySelector('.stepno').textContent=`step ${{step+1}} / ${{P.n}}`;
    let text=`Panel ${{step+1}} (row ${{s.row+1}} from the bottom, ${{s.up?'pointing up':'pointing down'}}): `;
    if(step===0) text+='base on the level line, left corner at the start mark. Check it with a level before pressing.';
    else text+=`seat it against panel${{s.touching.length>1?'s':''}} ${{s.touching.map(id=>P.steps.findIndex(x=>x.id===id)+1).join(' and ')}}; the linker goes in the highlighted edge shared with panel ${{P.steps.findIndex(x=>x.id===s.linker)+1}}.`;
    text+=' Three strips, one along each edge, tabs (red) pointing out. Press 30 s.';
    sec.querySelector('.instr').textContent=text;
  }}
  sec.querySelector('.prev').onclick=()=>{{step=Math.max(0,step-1);draw();}};
  sec.querySelector('.next').onclick=()=>{{step=Math.min(P.n-1,step+1);draw();}};
  sec.querySelector('.play').onclick=function(){{ if(timer){{clearInterval(timer);timer=null;this.textContent='▶ Play';return;}} this.textContent='❚❚ Pause'; if(step>=P.n-1) step=0; timer=setInterval(()=>{{ if(step>=P.n-1){{clearInterval(timer);timer=null;sec.querySelector('.play').textContent='▶ Play';return;}} step++; draw(); }},1100); draw(); }};
  const wall=sec.querySelector('.wall'); const off=sec.querySelector('.offset'); const unit=sec.querySelector('.unit');
  const upd=()=>{{ const cm=unit.value==='in'?+wall.value*2.54:+wall.value; const o=Math.max(0,(cm-P.w_cm)/2);
    off.textContent=`${{(o/2.54).toFixed(1)}} in (${{o.toFixed(1)}} cm)`; }};
  wall.oninput=upd; unit.onchange=()=>{{ wall.value=unit.value==='in'?(+wall.value/2.54).toFixed(1):(+wall.value*2.54).toFixed(1); upd(); }}; upd();
  draw();
}});
</script>'''

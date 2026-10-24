#!/usr/bin/env python3
"""Small live spatial view; reads the source of truth from Eclipse Ditto REST API."""
import os, json, base64, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
NS="org.openegiz.openpit"
DITTO=os.getenv("DITTO_URL","http://ditto-nginx:80").rstrip("/")
AUTH="Basic "+base64.b64encode((os.getenv("DITTO_USER","ditto")+":"+os.environ["DITTO_PASSWORD"]).encode()).decode()
HTML=r"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenPit Twin — Spatial Dispatch</title><style>
*{box-sizing:border-box}body{margin:0;background:#0c1724;color:#e8f0f7;font:15px system-ui,sans-serif}
header{padding:18px 24px;border-bottom:1px solid #26384b;display:flex;justify-content:space-between;gap:16px;align-items:center}
h1{font-size:21px;margin:0}small{color:#91a8bc}.status{color:#39d3b2}
main{padding:18px;display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:16px}.map,.side{background:#132336;border:1px solid #26384b;border-radius:14px;padding:12px}
svg{width:100%;height:auto;min-height:350px}.road{fill:none;stroke:#526a7e;stroke-width:18;stroke-linecap:round}.roadline{fill:none;stroke:#d0dbe5;stroke-width:1.5;stroke-dasharray:9 9}
.truck{cursor:default;stroke:#07111b;stroke-width:2}.label{font-size:13px;fill:#dce8f2}.sub{font-size:11px;fill:#9db2c5}.point{fill:#f0b44d;stroke:#111e2d;stroke-width:3}.metric{padding:12px;margin:8px 0;background:#1b3045;border-radius:10px}.metric b{font-size:22px;display:block}.good{color:#39d3b2}.warn{color:#f0b44d}.bad{color:#ff7373}
@media(max-width:800px){main{grid-template-columns:1fr}.side{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
</style><header><div><h1>OpenPit Twin <small> / пространственная диспетчеризация</small></h1><small>Положение и состояния читаются из Eclipse Ditto через OpenEgiz</small></div><div id="connection" class="status">Подключение…</div></header>
<main><section class="map"><svg viewBox="0 0 900 570" role="img" aria-label="Карта карьера с дорогами, экскаваторами, самосвалами и разгрузкой">
<defs><pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#20354a" stroke-width="1"/></pattern></defs>
<rect width="900" height="570" rx="12" fill="url(#grid)"/>
<path d="M65 90 Q180 45 300 95 T520 90 T800 120 L835 430 Q690 520 520 475 T210 485 L65 360Z" fill="#24384a" stroke="#526b7e" stroke-width="2"/>
<text x="80" y="65" class="label">СЕВЕРНЫЙ БОРТ / OPEN PIT</text>
<path id="r1" class="road" d="M175 180 C270 215 340 260 470 310 S650 385 760 420"/><path class="roadline" d="M175 180 C270 215 340 260 470 310 S650 385 760 420"/>
<path id="r2" class="road" d="M205 400 C330 370 400 260 520 210 S690 180 760 420"/><path class="roadline" d="M205 400 C330 370 400 260 520 210 S690 180 760 420"/>
<text x="330" y="260" class="label">R-01 · 2.4 km</text><text x="520" y="165" class="label">R-02 · 3.1 km</text>
<g transform="translate(145 160)"><circle r="28" class="point"/><text x="-36" y="-42" class="label">EX-01</text><text x="-34" y="5" class="sub">Северный забой</text><path d="M-12 8L-20 24L-2 17L8 24L15 4" fill="none" stroke="#0c1724" stroke-width="4"/></g>
<g transform="translate(190 420)"><circle r="28" class="point"/><text x="-35" y="48" class="label">EX-02</text><text x="-43" y="62" class="sub">Южный забой</text><path d="M-12 8L-20 24L-2 17L8 24L15 4" fill="none" stroke="#0c1724" stroke-width="4"/></g>
<g transform="translate(760 420)"><rect x="-25" y="-25" width="50" height="50" rx="7" fill="#39d3b2" stroke="#0c1724" stroke-width="3"/><text x="-35" y="45" class="label">DUMP-01</text><text x="-38" y="59" class="sub">Разгрузка</text></g>
<g id="trucks"></g>
</svg><small>Схема условная: позиции вычисляются по состояниям рейса и маршруту, а не по GPS. Обновление каждые 2 секунды.</small></section>
<aside class="side"><div class="metric"><small>Доставлено руды</small><b id="ore">— t</b></div><div class="metric"><small>Активные самосвалы</small><b id="active">— / 6</b></div><div class="metric"><small>Суммарное ожидание</small><b id="idle">— min</b></div><div class="metric"><small>Режим диспетчеризации</small><b id="mode">—</b></div><h3>Парк техники</h3><div id="fleet"></div></aside></main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'—').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const xy={1:[[175,180],[270,215],[340,260],[470,310],[650,385],[760,420]],2:[[205,400],[330,370],[400,260],[520,210],[690,180],[760,420]]};
function position(t){let r=Number(t.route||1)===2?2:1;let p=Math.max(0,Math.min(1,Number(t.pos||0)));let pts=xy[r];let i=Math.min(pts.length-2,Math.floor(p*(pts.length-1))),f=p*(pts.length-1)-i;return [pts[i][0]+(pts[i+1][0]-pts[i][0])*f,pts[i][1]+(pts[i+1][1]-pts[i][1])*f]}
async function refresh(){try{let d=await(await fetch('/api/state',{cache:'no-store'})).json();$('connection').textContent='● Ditto подключён';$('ore').textContent=Math.round(d.pit.ore)+' t';$('active').textContent=d.pit.active+' / 6';$('idle').textContent=d.pit.idle.toFixed(1)+' min';$('mode').textContent=d.pit.mode;
$('r1').setAttribute('stroke',d.roads[0].state==='closed'?'#ff7373':'#526a7e');
$('r1').setAttribute('stroke-dasharray',d.roads[0].state==='closed'?'7 8':'none');
$('trucks').innerHTML=d.trucks.map(t=>{let [x,y]=position(t);let fill=t.state==='refuelling'?'#ff7373':t.state==='loading'?'#f0b44d':'#39d3b2';return `<g transform="translate(${x} ${y})"><rect class="truck" x="-13" y="-9" width="26" height="18" rx="4" fill="${fill}"/><rect x="-5" y="-6" width="10" height="12" rx="2" fill="#183048"/><text x="0" y="-15" text-anchor="middle" class="sub">${t.id.replace('truck-','HT-')}</text></g>`}).join('');
$('fleet').innerHTML=d.trucks.map(t=>`<div style="padding:7px 0;border-bottom:1px solid #26384b"><b>${esc(t.id.replace('truck-','HT-'))}</b> <span class="${t.state==='refuelling'?'bad':t.state==='loading'?'warn':'good'}">${esc(t.state)}</span><br><small>Назначение: ${esc(t.assigned)} · ${t.payload} t · топливо ${t.fuel}%</small></div>`).join('');
}catch(e){$('connection').textContent='● Нет связи с Ditto';$('connection').className='bad'}}refresh();setInterval(refresh,2000);
</script></html>"""
def get(thing):
    req=urllib.request.Request(f"{DITTO}/api/2/things/{NS}:{thing}",headers={"Authorization":AUTH})
    with urllib.request.urlopen(req,timeout=2) as r: return json.load(r)
def val(obj,feature,default=0):
    try:return obj["features"][feature]["properties"]["value"]
    except (KeyError,TypeError):return default
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/":
            data=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if self.path!="/api/state": self.send_error(404); return
        try:
            pit=get("pit-01"); trucks=[]; roads=[]
            for i in range(1,7):
                o=get(f"truck-{i:02d}")
                assigned=val(o,"assigned_to","none"); route=1 if assigned.endswith("01") else 2
                length=2.4 if route==1 else 3.1
                trucks.append({"id":f"truck-{i:02d}","state":val(o,"state","unknown"),"assigned":assigned,"payload":val(o,"payload",0),"fuel":val(o,"fuel",0),"route":route,"pos":val(o,"route_position",0)/length})
            for i in range(1,3):
                o=get(f"road-{i:02d}"); roads.append({"state":val(o,"state","open"),"travel":val(o,"travel_time_min",0)})
            payload={"pit":{"ore":val(pit,"ore_mined",0),"active":val(pit,"active_trucks",0),"idle":val(pit,"idle_minutes",0),"mode":val(pit,"dispatch_mode","balanced")},"trucks":trucks,"roads":roads}
            data=json.dumps(payload).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        except Exception as e:
            data=json.dumps({"error":str(e)}).encode(); self.send_response(503); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self,*args): pass
if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",8091),Handler).serve_forever()

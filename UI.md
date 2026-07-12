<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EWB Control Tower</title>
<style>
  :root{
    --bg:#0D1320; --panel:#151D2E; --panel2:#1B2538; --line:#26334B;
    --text:#E9EEF6; --mut:#8C99AF; --dim:#5B6880;
    --red:#FF5D5D; --amber:#FFB02E; --green:#3DDC97; --blue:#5B8DEF;
    --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);
    font-family:system-ui,-apple-system,'Segoe UI',sans-serif;padding-bottom:60px}
  header{background:var(--panel);border-bottom:1px solid var(--line);padding:16px 22px;
    display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between}
  .eyebrow{font:11px var(--mono);letter-spacing:3px;color:var(--mut)}
  h1{font-size:21px;margin:2px 0 0;letter-spacing:-.3px}
  .stats{display:flex;gap:22px;flex-wrap:wrap;align-items:center}
  .stat{text-align:right}
  .stat b{display:block;font:800 19px var(--mono)}
  .stat span{font-size:10px;letter-spacing:1px;color:var(--mut);text-transform:uppercase}
  .wrap{padding:0 22px;max-width:1200px;margin:0 auto}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin-top:18px}
  .card h2{font-size:13px;letter-spacing:2px;text-transform:uppercase;color:var(--mut);
    margin:0;padding:13px 16px;border-bottom:1px solid var(--line)}
  .pad{padding:16px}
  input,button{font-family:inherit;font-size:13.5px;border-radius:5px}
  input{background:var(--bg);border:1px solid var(--line);color:var(--text);padding:9px 11px;width:100%}
  label{display:block;font-size:10.5px;letter-spacing:1.2px;color:var(--mut);
    text-transform:uppercase;margin:0 0 4px}
  .row{display:flex;gap:10px;flex-wrap:wrap}.row>div{flex:1;min-width:130px}
  button{border:none;cursor:pointer;font-weight:700;padding:10px 18px}
  .btn-blue{background:var(--blue);color:#0A1530}
  .btn-green{background:var(--green);color:#06281A}
  .btn-ghost{background:transparent;border:1px solid var(--line);color:var(--mut)}
  button:disabled{background:var(--dim);color:#222;cursor:not-allowed}
  .chip{font:10.5px var(--mono);letter-spacing:1px;padding:3px 9px;border-radius:3px;white-space:nowrap}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{font-size:10.5px;letter-spacing:1.2px;text-transform:uppercase;color:var(--mut);
    text-align:left;padding:10px 14px;border-bottom:1px solid var(--line)}
  td{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
  tr:last-child td{border-bottom:none}
  .mono{font-family:var(--mono);font-size:12px;color:var(--mut)}
  pre{background:#0A0F1A;border:1px solid var(--line);border-radius:6px;padding:13px;
    font:11.5px/1.6 var(--mono);color:#9FD0A8;overflow-x:auto;margin:10px 0 0}
  .note{border:1px solid #FFB02E55;background:#FFB02E10;border-radius:6px;
    padding:10px 12px;font-size:12px;color:#EAD9AE;line-height:1.55;margin-top:12px}
  .note b{color:var(--amber)}
  .msg{margin-top:10px;font-size:13px;padding:10px 12px;border-radius:5px;display:none}
  .msg.ok{display:block;background:#3DDC9714;border:1px solid #3DDC9755;color:var(--green)}
  .msg.err{display:block;background:#FF5D5D14;border:1px solid #FF5D5D55;color:var(--red)}
  .toggle{border-radius:20px;padding:8px 18px;font-size:12px;letter-spacing:.5px}
  .log{font:12px var(--mono);color:var(--mut);padding:6px 16px;border-bottom:1px solid var(--line)}
  .log:last-child{border-bottom:none}
  @media(max-width:760px){ .hide-sm{display:none} td,th{padding:9px 8px} }
</style>
</head>
<body>
<div style="background:#5B8DEF22;border-bottom:1px solid #5B8DEF66;color:#BCD2FA;font-size:12.5px;padding:8px 22px">PREVIEW MODE — this page simulates the backend in your browser so you can see and click the exact UI. The real system (python app.py) looks and behaves identically at http://localhost:8000, with the FastAPI backend + SQLite + real API adapters.</div>

<header>
  <div>
    <div class="eyebrow">EWB · CONTROL TOWER</div>
    <h1>E-way bill expiry desk</h1>
    <div class="mono" id="mode" style="margin-top:4px"></div>
  </div>
  <div class="stats">
    <div class="stat"><b style="color:var(--red)" id="st-window">0</b><span>Window open</span></div>
    <div class="stat"><b style="color:var(--amber)" id="st-soon">0</b><span>Expiring ≤48h</span></div>
    <div class="stat"><b style="color:var(--dim)" id="st-missed">0</b><span>Missed</span></div>
    <div class="stat"><b class="mono" id="clock" style="color:var(--mut);font-weight:500"></b><span>IST</span></div>
  </div>
</header>

<div class="wrap">

  <!-- TEST SCREEN -->
  <div class="card">
    <h2>Test screen — lookup &amp; extend</h2>
    <div class="pad">
      <div class="row" style="align-items:flex-end">
        <div style="flex:2">
          <label>Invoice no / EWB no</label>
          <input id="q" placeholder="e.g. INV-2684 or 321008990121">
        </div>
        <div style="flex:0"><button class="btn-blue" onclick="lookup()">Get validity</button></div>
      </div>
      <div class="msg" id="lk-msg"></div>

      <div id="detail" style="display:none">
        <div class="row" style="margin-top:16px">
          <div><label>EWB no</label><input id="d-ewb" readonly></div>
          <div><label>Vehicle</label><input id="d-veh" readonly></div>
          <div><label>Valid until</label><input id="d-exp" readonly></div>
          <div><label>Status</label><input id="d-status" readonly></div>
        </div>
        <div class="row" style="margin-top:12px">
          <div><label>Current location (default: FROM ship-point)</label><input id="d-place"></div>
          <div><label>Pincode</label><input id="d-pin"></div>
          <div><label>Remaining distance (km)</label><input id="d-km" type="number"></div>
          <div><label>Remarks (reason 99 — Others)</label><input id="d-rem" value="Transit delay"></div>
        </div>
        <div class="note"><b>Compliance note:</b> NIC expects the consignment's <i>actual</i> present
          location. Origin-as-default is your no-GPS fallback — edit it whenever the driver can tell
          you where the vehicle really is. Extension only works within ±8h of expiry.</div>
        <div style="margin-top:14px;display:flex;gap:10px;align-items:center">
          <button class="btn-green" id="btn-ext" onclick="extend()">Push extension</button>
          <span class="mono" id="d-grant"></span>
        </div>
        <div class="msg" id="ext-msg"></div>
        <label style="margin-top:16px">EXTENDVALIDITY payload that will be sent</label>
        <pre id="d-payload"></pre>
      </div>
    </div>
  </div>

  <!-- AUTO TRIGGER -->
  <div class="card">
    <h2>Auto-extend trigger</h2>
    <div class="pad" style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;justify-content:space-between">
      <div style="font-size:13px;color:var(--mut);line-height:1.5;max-width:720px">
        <b style="color:var(--text)">Rule:</b> IF IOD ≠ CLOSED AND now is inside the ±8h window →
        fire EXTENDVALIDITY automatically (location = FROM ship-point, distance = full route,
        reason 99 "Transit delay"). The watcher scans every <span id="auto-int"></span>s.
        Close an IOD below to see the trigger skip that shipment.
      </div>
      <button class="toggle btn-ghost" id="auto-btn" onclick="toggleAuto()">AUTO-EXTEND OFF</button>
    </div>
  </div>

  <!-- DASHBOARD -->
  <div class="card">
    <h2>All shipments</h2>
    <div style="overflow-x:auto">
    <table id="tbl">
      <thead><tr>
        <th>Invoice / EWB</th><th class="hide-sm">Route</th><th>Valid until</th>
        <th>Time left</th><th>IOD</th><th>Status</th><th></th>
      </tr></thead>
      <tbody></tbody>
    </table>
    </div>
  </div>

  <!-- LOG -->
  <div class="card">
    <h2>Extension log</h2>
    <div id="logs"><div class="log">No extensions yet.</div></div>
  </div>

</div>

<script>

/* ══ IN-PAGE MOCK BACKEND (preview only — real app uses FastAPI) ══ */
const HOUR=3600e3, WIN=8*HOUR;
const nowMs=()=>Date.now();
let AUTO=false;
let SHIPS=[
 {invoice_no:'INV-2671',ewb_no:'351008214437',vehicle_no:'KL07CQ4451',from_place:'Kochi',from_pincode:'682024',from_state:32,to_place:'Coimbatore',distance_km:195,iod_status:'OPEN',expiry:nowMs()-3*HOUR,extensions:0},
 {invoice_no:'INV-2684',ewb_no:'321008990121',vehicle_no:'KL43L8812',from_place:'Ernakulam',from_pincode:'682016',from_state:32,to_place:'Bengaluru',distance_km:545,iod_status:'OPEN',expiry:nowMs()+2.4*HOUR,extensions:0},
 {invoice_no:'INV-2688',ewb_no:'301009112894',vehicle_no:'TN38BX0917',from_place:'Thrissur',from_pincode:'680001',from_state:32,to_place:'Chennai',distance_km:690,iod_status:'OPEN',expiry:nowMs()+6.8*HOUR,extensions:0},
 {invoice_no:'INV-2690',ewb_no:'331009245610',vehicle_no:'KA01AK3344',from_place:'Kozhikode',from_pincode:'673001',from_state:32,to_place:'Mangaluru',distance_km:233,iod_status:'OPEN',expiry:nowMs()+15*HOUR,extensions:0},
 {invoice_no:'INV-2693',ewb_no:'351009330077',vehicle_no:'KL07DN2210',from_place:'Kochi',from_pincode:'682024',from_state:32,to_place:'Hyderabad',distance_km:1080,iod_status:'OPEN',expiry:nowMs()+22*HOUR,extensions:0},
 {invoice_no:'INV-2695',ewb_no:'321009418852',vehicle_no:'MH12RT5566',from_place:'Palakkad',from_pincode:'678001',from_state:32,to_place:'Pune',distance_km:1130,iod_status:'OPEN',expiry:nowMs()+41*HOUR,extensions:0},
 {invoice_no:'INV-2659',ewb_no:'351008100923',vehicle_no:'KL07BV9090',from_place:'Kochi',from_pincode:'682024',from_state:32,to_place:'Salem',distance_km:320,iod_status:'OPEN',expiry:nowMs()-14*HOUR,extensions:0},
 {invoice_no:'INV-2677',ewb_no:'331008667741',vehicle_no:'KL11AS7733',from_place:'Kannur',from_pincode:'670001',from_state:32,to_place:'Kasaragod',distance_km:90,iod_status:'CLOSED',expiry:nowMs()+5*HOUR,extensions:0},
 {invoice_no:'INV-2699',ewb_no:'351009551209',vehicle_no:'KL07CT1184',from_place:'Alappuzha',from_pincode:'688001',from_state:32,to_place:'Madurai',distance_km:290,iod_status:'OPEN',expiry:nowMs()+68*HOUR,extensions:0},
];
let LOGS=[];
const statusOf=s=>{ if(s.iod_status==='CLOSED')return 'CLOSED';
  const d=s.expiry-nowMs();
  if(d<-WIN)return 'MISSED'; if(d<=WIN)return 'WINDOW';
  if(d<=24*HOUR)return 'SOON'; if(d<=48*HOUR)return 'WATCH'; return 'OK'; };
const human=t=>new Date(t).toLocaleString('en-IN',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
const enrich=s=>({...s, ewb_no:s.ewb_no, status:statusOf(s), expiry_human:human(s.expiry),
  seconds_to_expiry:Math.round((s.expiry-nowMs())/1000),
  preview_payload:{ewbNo:parseInt(s.ewb_no),vehicleNo:s.vehicle_no,fromPlace:s.from_place,
    fromState:s.from_state,fromPincode:parseInt(s.from_pincode),remainingDistance:s.distance_km,
    transMode:'1',transDocNo:'',transDocDate:'',consignmentStatus:'M',transitType:'',
    addressLine1:'',addressLine2:'',addressLine3:'',extnRsnCode:99,extnRemarks:'Transit delay'}});
const find=q=>SHIPS.find(s=>s.invoice_no===q.trim()||s.ewb_no===q.trim());
function mockExtend(s,km,place){
  const d=s.expiry-nowMs();
  if(d>WIN)return {ok:false,message:'NIC would reject: extension window opens 8h before expiry.'};
  if(d<-WIN)return {ok:false,message:'NIC would reject: expired more than 8h ago — window missed. Generate a fresh EWB.'};
  const days=Math.max(1,Math.ceil((km||s.distance_km)/200));
  const e=new Date(); e.setHours(23,59,0,0); e.setDate(e.getDate()+days);
  s.expiry=e.getTime(); s.extensions++;
  return {ok:true,new_expiry:e.getTime()};
}
function addLog(mode,s,detail){LOGS.unshift({mode,invoice_no:s.invoice_no,ewb_no:s.ewb_no,
  ts_human:new Date().toLocaleString('en-IN',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}),detail});}
// auto watcher — every 5s in the preview
setInterval(()=>{ if(!AUTO)return;
  for(const s of SHIPS){ if(s.iod_status==='OPEN'&&statusOf(s)==='WINDOW'){
    const km=s.distance_km, r=mockExtend(s,km,s.from_place);
    addLog('AUTO',s, r.ok?`Extended from ${s.from_place} (${km} km) -> valid until ${human(r.new_expiry)}`:`FAILED: ${r.message}`);
  }}},5000);
// fetch shim implementing the same endpoints as the FastAPI app
window.fetch=async(url,opts)=>{
  const body=opts&&opts.body?JSON.parse(opts.body):{};
  const R=o=>({json:async()=>o,ok:true});
  if(url.startsWith('/api/shipments'))return R({mode:'PREVIEW (in-browser simulator — real app: python app.py)',auto:AUTO,shipments:SHIPS.map(enrich)});
  if(url.startsWith('/api/lookup')){const q=decodeURIComponent(url.split('q=')[1]||'');const s=find(q);
    return R(s?{ok:true,shipment:enrich(s)}:{ok:false,message:`'${q}' not found`});}
  if(url.startsWith('/api/extend')){const s=find(body.q);
    if(!s)return R({ok:false,message:'not found'});
    const r=mockExtend(s,body.remaining_km,body.place);
    addLog('MANUAL',s, r.ok?`Extended from ${body.place||s.from_place} (${body.remaining_km||s.distance_km} km) -> valid until ${human(s.expiry)}`:`FAILED: ${r.message}`);
    return R({ok:r.ok,message:r.message||'extended',shipment:enrich(s)});}
  if(url.startsWith('/api/iod')){const s=find(body.invoice_no); if(s)s.iod_status=body.status; return R({ok:true});}
  if(url.startsWith('/api/auto')){ if(opts&&opts.method==='POST'){AUTO=body.enabled;} return R({enabled:AUTO,interval_seconds:5});}
  if(url.startsWith('/api/logs'))return R({logs:LOGS.slice(0,50)});
  return R({});
};
/* ══ END MOCK ══ */

const COLORS={WINDOW:'var(--red)',SOON:'var(--amber)',WATCH:'#E8D44D',
              OK:'var(--green)',MISSED:'var(--dim)',CLOSED:'var(--blue)'};
const LABELS={WINDOW:'WINDOW OPEN',SOON:'EXPIRES <24H',WATCH:'EXPIRES <48H',
              OK:'ON TRACK',MISSED:'WINDOW MISSED',CLOSED:'IOD CLOSED'};
let current=null;

const $=id=>document.getElementById(id);
const fmtDelta=s=>{const n=s<0;s=Math.abs(s);
  return `${n?'-':''}${Math.floor(s/3600)}h ${String(Math.floor(s%3600/60)).padStart(2,'0')}m`;};

async function refresh(){
  const r=await fetch('/api/shipments'); const d=await r.json();
  $('mode').textContent='backend: '+d.mode;
  const tb=document.querySelector('#tbl tbody'); tb.innerHTML='';
  let w=0,s48=0,miss=0;
  for(const s of d.shipments){
    if(s.status==='WINDOW')w++;
    if(s.status==='SOON'||s.status==='WATCH')s48++;
    if(s.status==='MISSED')miss++;
    const tr=document.createElement('tr');
    tr.innerHTML=`
      <td><b>${s.invoice_no}</b>${s.extensions?` <span class="mono" style="color:var(--green)">EXT ×${s.extensions}</span>`:''}
          <div class="mono">${s.ewb_no} · ${s.vehicle_no}</div></td>
      <td class="hide-sm">${s.from_place} → ${s.to_place}
          <div class="mono">${s.distance_km} km</div></td>
      <td class="mono">${s.expiry_human}</td>
      <td class="mono" style="color:${s.seconds_to_expiry<0?'var(--red)':'var(--text)'}">
          ${s.seconds_to_expiry>=0?'in ':''}${fmtDelta(s.seconds_to_expiry)}${s.seconds_to_expiry<0?' ago':''}</td>
      <td><button class="btn-ghost" style="padding:4px 10px;font-size:11px"
            onclick="setIod('${s.invoice_no}','${s.iod_status==='OPEN'?'CLOSED':'OPEN'}')">
            ${s.iod_status}</button></td>
      <td><span class="chip" style="color:${COLORS[s.status]};border:1px solid ${COLORS[s.status]};
            background:transparent">${LABELS[s.status]}</span></td>
      <td>${s.status==='WINDOW'
            ?`<button class="btn-green" style="padding:6px 12px;font-size:12px"
               onclick="quickPick('${s.invoice_no}')">Extend</button>`
            :s.status==='MISSED'?'<span class="mono" style="font-size:11px">fresh EWB needed</span>':''}</td>`;
    tb.appendChild(tr);
  }
  $('st-window').textContent=w; $('st-soon').textContent=s48; $('st-missed').textContent=miss;
  const btn=$('auto-btn');
  btn.textContent=d.auto?'AUTO-EXTEND ON':'AUTO-EXTEND OFF';
  btn.className='toggle '+(d.auto?'btn-green':'btn-ghost');
  loadLogs();
}

async function loadLogs(){
  const d=await (await fetch('/api/logs')).json();
  $('logs').innerHTML=d.logs.length
    ? d.logs.map(l=>`<div class="log"><span style="color:${l.mode==='AUTO'?'var(--green)':'var(--blue)'}">[${l.mode}]</span>
        ${l.ts_human} · ${l.invoice_no} (EWB ${l.ewb_no}) — ${l.detail}</div>`).join('')
    : '<div class="log">No extensions yet.</div>';
}

function quickPick(inv){ $('q').value=inv; lookup(); window.scrollTo({top:0,behavior:'smooth'}); }

async function lookup(){
  const q=$('q').value.trim(); if(!q)return;
  const m=$('lk-msg'); m.className='msg';
  const r=await fetch('/api/lookup?q='+encodeURIComponent(q)); const d=await r.json();
  if(!d.ok){ m.className='msg err'; m.textContent=d.message; $('detail').style.display='none'; return; }
  current=d.shipment;
  $('detail').style.display='block';
  $('d-ewb').value=current.ewb_no; $('d-veh').value=current.vehicle_no;
  $('d-exp').value=current.expiry_human+`  (${current.seconds_to_expiry>=0?'in ':''}${fmtDelta(current.seconds_to_expiry)}${current.seconds_to_expiry<0?' ago':''})`;
  $('d-status').value=LABELS[current.status]; $('d-status').style.color=COLORS[current.status];
  $('d-place').value=current.from_place; $('d-pin').value=current.from_pincode;
  $('d-km').value=current.distance_km;
  $('btn-ext').disabled = current.status!=='WINDOW';
  updatePayload();
}

function updatePayload(){
  if(!current)return;
  const km=parseInt($('d-km').value||0), days=Math.max(1,Math.ceil(km/200));
  $('d-grant').textContent=`will grant ~${days} day${days>1?'s':''} (1 day / 200 km)`;
  const p={...current.preview_payload,
    fromPlace:$('d-place').value, fromPincode:parseInt($('d-pin').value||0),
    remainingDistance:km, extnRemarks:$('d-rem').value};
  $('d-payload').textContent=JSON.stringify(p,null,2);
}
['d-place','d-pin','d-km','d-rem'].forEach(id=>document.addEventListener('input',e=>{
  if(e.target.id===id)updatePayload();}));

async function extend(){
  const m=$('ext-msg'); m.className='msg'; $('btn-ext').disabled=true;
  $('btn-ext').textContent='Calling API…';
  const r=await fetch('/api/extend',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({q:current.invoice_no, place:$('d-place').value, pin:$('d-pin').value,
      remaining_km:parseInt($('d-km').value||0), remarks:$('d-rem').value})});
  const d=await r.json();
  $('btn-ext').textContent='Push extension';
  if(d.ok){ m.className='msg ok'; m.textContent='✓ Extended. New validity: '+d.shipment.expiry_human; }
  else    { m.className='msg err'; m.textContent='✗ '+d.message; }
  await refresh(); if(current) lookup();
}

async function setIod(inv,status){
  await fetch('/api/iod',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({invoice_no:inv,status})});
  refresh();
}

async function toggleAuto(){
  const cur=$('auto-btn').textContent.includes('ON');
  await fetch('/api/auto',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({enabled:!cur})});
  refresh();
}

(async()=>{
  const a=await (await fetch('/api/auto')).json();
  $('auto-int').textContent=a.interval_seconds;
})();
setInterval(()=>{ $('clock').textContent=new Date().toLocaleTimeString('en-IN',{hour12:false}); },1000);
setInterval(refresh,5000);
refresh();
</script>
</body>
</html>

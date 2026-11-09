const TOKEN = window.X87_TOKEN;
const $ = (s) => document.querySelector(s);
const state = { status:null, effects:[], palette:[], layer:0, keys:[], outputs:[], selected:null, color:7, frow:null };

async function api(path, opts={}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type":"application/json", "X-X87-Token":TOKEN, ...(opts.headers||{}) } });
  const data = await res.json().catch(()=>({error:"bad response"}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
function toast(msg, error=false){
  const t=$("#toast"); t.textContent=msg; t.className="toast show"+(error?" error":"");
  clearTimeout(toast._t); toast._t=setTimeout(()=>t.className="toast",3200);
}
function setBusy(on){ document.querySelectorAll("button").forEach(b=>b.disabled=on); }

async function loadStatus(){
  try{
    const s = await api("/api/status");
    state.status = s;
    if(!s.connected){
      $("#status").className="status bad";
      if(s.error==="permission"){
        $("#status").innerHTML='<span class="dot"></span> Input Monitoring permission needed';
        toast("Grant Input Monitoring to X87 Configurator, then reload this page.", true);
        $("#privacyBtn").classList.remove("hidden");
      } else {
        $("#status").innerHTML='<span class="dot"></span> Keyboard not found';
        toast("Keyboard not found. Plug in USB-C and set the switch to wired.", true);
      }
      return;
    }
    const prof = s.profile === "mac" ? "Mac profile" : "Windows profile";
    $("#status").className="status ok"; $("#status").innerHTML='<span class="dot"></span> Connected · wired · '+prof;
    $("#macWarning").classList.toggle("hidden", s.profile !== "mac");
    state.effects=s.effects; state.palette=s.palette;
    renderEffects(s.effect.name);
    $("#brightness").value=s.brightness; $("#brightnessVal").textContent=s.brightness;
    $("#speed").value=s.speed; $("#speedVal").textContent=s.speed;
    state.color=s.color; renderColors();
  }catch(e){ $("#status").className="status bad"; $("#status").innerHTML='<span class="dot"></span> '+e.message; }
}
function renderEffects(current){
  const wrap=$("#effects"); wrap.innerHTML="";
  state.effects.forEach(e=>{
    const b=document.createElement("button");
    b.className="effect"+(e.name===current?" active":"");
    b.innerHTML=`<span>${e.name.replaceAll("_"," ")}</span><small>hw ${e.hw}</small>`;
    b.onclick=()=>{ document.querySelectorAll(".effect").forEach(x=>x.classList.remove("active")); b.classList.add("active"); state.effect=e.name; };
    if(e.name===current) state.effect=e.name;
    wrap.appendChild(b);
  });
}
function renderColors(){
  const wrap=$("#colors"); wrap.innerHTML="";
  state.palette.forEach((rgb,i)=>{
    const b=document.createElement("button");
    b.className="swatch"+(state.color===i?" active":"");
    b.style.background=`rgb(${rgb.join(",")})`;
    b.title=`Colour ${i+1}`;
    b.onclick=()=>{ state.color=i; renderColors(); };
    wrap.appendChild(b);
  });
  const r=document.createElement("button");
  r.className="swatch random"+(state.color===7?" active":"");
  r.title="Random / colourful";
  r.onclick=()=>{ state.color=7; renderColors(); };
  wrap.appendChild(r);
}
async function loadFrow(){
  try{
    const s=await api("/api/frow"); state.frow=s;
    const modeLabel = s.os_mode==="mac" ? "Mac profile" : "Windows profile";
    const currentLabel = s.primary==="fkeys" ? "F keys primary" : s.primary==="media" ? "Media primary" : `Mixed (${s.fkeys_on_base}/12)`;
    $("#frowState").textContent = s.os_mode==="mac" ? "Mac profile · firmware-fixed" : `${modeLabel} · ${currentLabel}`;
    $("#profile-win").classList.toggle("active", s.os_mode==="win");
    $("#profile-mac").classList.toggle("active", s.os_mode==="mac");
    for (const p of ["win","mac"]) {
      document.querySelectorAll(`#${p}Toggle button`).forEach(b=>{
        b.classList.toggle("active", s.prefs[p]===b.dataset.mode);
        if(p==="mac") b.disabled=true;
      });
    }
  }catch(e){ $("#frowState").textContent="Unavailable"; }
}
async function setProfileMode(profile, mode){
  if(!state.frow || state.frow.prefs[profile]===mode) return;
  const label = profile==="win" ? "Windows" : "Mac";
  const modeLabel = mode==="fkeys" ? "F keys primary" : "Media primary";
  if(!confirm(`Set the ${label} profile to “${modeLabel}”?\n\nWhen that switch profile is active, auto-sync will apply it.`)) return;
  setBusy(true);
  try{
    state.frow=await api("/api/frow-profile",{method:"POST",body:JSON.stringify({profile,mode})});
    toast(`${label} profile: ${modeLabel}`);
    await loadFrow(); await loadKeys(state.layer);
  }catch(e){ toast(e.message,true); } finally { setBusy(false); }
}
async function applyLighting(){
  if(!state.effect) return toast("Choose an effect first", true);
  setBusy(true);
  try{
    const s=await api("/api/lighting",{method:"POST",body:JSON.stringify({effect:state.effect,brightness:+$("#brightness").value,speed:+$("#speed").value,color:state.color})});
    state.status=s;
    toast(`Applied ${state.effect}`);
    await loadStatus();
  }catch(e){ toast(e.message,true); }
  finally{ setBusy(false); await loadKeys(state.layer); }
}
function renderOverlays(){
  const wrap=$("#overlays"); wrap.innerHTML="";
  state.keys.forEach(k=>{
    const b=document.createElement("button");
    b.className="key"+(state.selected&&state.selected.led===k.led?" selected":"");
    const PAD=4;
    b.style.left=((k.x+PAD)/669*100)+"%"; b.style.top=((k.y+PAD)/259*100)+"%";
    b.style.width=((k.w-2*PAD)/669*100)+"%"; b.style.height=((k.h-2*PAD)/259*100)+"%";
    b.title=`${k.name}: ${k.output}`;
    b.setAttribute("aria-label",`${k.name}: ${k.output}`);
    b.onclick=()=>selectKey(k);
    wrap.appendChild(b);
  });
}
function selectKey(k){
  state.selected=k; renderOverlays();
  $("#keyEditor").classList.remove("hidden");
  $("#keyTitle").textContent=k.name;
  $("#keyCurrent").textContent=`Current output: ${k.output}   (${k.entry})`;
  const sel=$("#outputSelect"); sel.innerHTML="";
  let matched=false;
  state.outputs.forEach(g=>{
    const og=document.createElement("optgroup"); og.label=g.group;
    g.items.forEach(it=>{
      const o=document.createElement("option"); o.value=it.value; o.textContent=it.name;
      if(it.name===k.output || it.value.toLowerCase()===k.output.toLowerCase()){ o.selected=true; matched=true; }
      og.appendChild(o);
    });
    sel.appendChild(og);
  });
  if(!matched){
    const o=document.createElement("option"); o.value="__custom__"; o.textContent=`Keep current (${k.output})`; o.selected=true; sel.prepend(o);
  }
}
async function loadKeys(layer){
  try{ const d=await api("/api/keys?layer="+layer); state.keys=d.keys; state.layer=layer; state.selected=null; $("#keyEditor").classList.add("hidden"); renderOverlays(); }
  catch(e){ toast(e.message,true); }
}
async function applyKey(){
  if(!state.selected) return;
  const out=$("#outputSelect").value;
  if(out==="__custom__") return toast("Choose a new output",true);
  setBusy(true);
  try{ await api("/api/key",{method:"POST",body:JSON.stringify({source:state.selected.name,output:out,layer:state.layer})}); toast(`${state.selected.name} → ${out}`); await loadKeys(state.layer); }
  catch(e){ toast(e.message,true); } finally{ setBusy(false); }
}
async function resetKey(){
  if(!state.selected) return;
  setBusy(true);
  try{ await api("/api/key-reset",{method:"POST",body:JSON.stringify({source:state.selected.name,layer:state.layer})}); toast(`${state.selected.name} reset`); await loadKeys(state.layer); }
  catch(e){ toast(e.message,true); } finally{ setBusy(false); }
}
async function restoreOriginal(){
  if(!confirm("Restore the original lighting configuration and both keymaps?")) return;
  setBusy(true);
  try{ state.status=await api("/api/restore",{method:"POST"}); toast("Original lighting and keymaps restored"); await loadStatus(); }
  catch(e){ toast(e.message,true); } finally{ setBusy(false); }
}
async function undoLast(){
  setBusy(true);
  try{ state.status=await api("/api/undo",{method:"POST"}); toast("Undid last lighting change"); await loadStatus(); }
  catch(e){ toast(e.message,true); } finally{ setBusy(false); }
}
async function makeBackup(){
  setBusy(true);
  try{ const d=await api("/api/backup",{method:"POST"}); $("#backupResult").textContent="Saved to "+d.path; toast("Backup created"); }
  catch(e){ toast(e.message,true); } finally{ setBusy(false); }
}
async function quitApp(){
  try{ await api("/api/quit",{method:"POST"}); }catch(e){}
  document.body.innerHTML='<div style="display:grid;place-items:center;height:100vh;font:16px -apple-system;color:#8d99a8">X87 Configurator stopped. You can close this tab.</div>';
}
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); $("#tab-"+b.dataset.tab).classList.add("active");
});
document.querySelectorAll("#layerToggle button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll("#layerToggle button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); loadKeys(+b.dataset.layer);
});
$("#brightness").oninput=()=>$("#brightnessVal").textContent=$("#brightness").value;
$("#speed").oninput=()=>$("#speedVal").textContent=$("#speed").value;
$("#applyLighting").onclick=applyLighting;
for (const p of ["win","mac"]) {
  document.querySelectorAll(`#${p}Toggle button`).forEach(b=>b.onclick=()=>setProfileMode(p,b.dataset.mode));
}
$("#applyKey").onclick=applyKey;
$("#resetKey").onclick=resetKey;
$("#cancelKey").onclick=()=>{ state.selected=null; renderOverlays(); $("#keyEditor").classList.add("hidden"); };
$("#restoreBtn").onclick=restoreOriginal;
$("#undoBtn").onclick=undoLast;
$("#backupBtn").onclick=makeBackup;
$("#openBackups").onclick=()=>api("/api/open-backups",{method:"POST"}).catch(e=>toast(e.message,true));
$("#quitBtn").onclick=quitApp;
$("#privacyBtn").onclick=()=>api("/api/open-privacy",{method:"POST"}).catch(e=>toast(e.message,true));
if(new URLSearchParams(location.search).has("debug")) document.body.classList.add("debug-keys");
(async()=>{
  await loadStatus();
  if(state.status && state.status.connected){
    try{ state.outputs=await api("/api/outputs"); }catch(e){}
    await loadKeys(0);
    await loadFrow();
  }
  const tab=location.hash.slice(1);
  if(tab){ const b=document.querySelector(`.tabs button[data-tab="${tab}"]`); if(b) b.click(); }
})();

setInterval(async()=>{
  if(document.hidden) return;
  try{
    const s=await api("/api/status");
    if(s.connected && state.status && s.profile !== state.status.profile){
      state.status=s;
      await loadStatus();
      await loadFrow();
      await loadKeys(state.layer);
    }
  }catch(e){}
}, 2500);

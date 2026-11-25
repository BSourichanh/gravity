"""SEP-1865 bridge and state controller for the Gravity MCP App (100% stdlib, zero innerHTML)."""

from __future__ import annotations

APP_JS = r"""
const PROTOCOL_VERSION="2026-01-26",LIVE_POLL_MS=2000;
const state={hostCaps:{},hostCtx:{},layoutMode:"wide",overview:null,live:null,workflow:null,metrics:null,architect:null,moduleCache:{},moduleLoading:{},activeTab:"live",selectedWs:"",selectedAtelier:"",liveUi:{paused:false,selectedSessionId:"",selectedAgentId:"",collapsedAgents:{},eventsOpen:false,breakdownOpen:false,actionInFlight:false,lastUpdatedAt:""},metricsProject:"",metricsQ:"",metricsSub:"overview",metricsFilter:"recorded",metricsSort:"date",metricsActionInFlight:false,compareOpen:false,compareA:"",compareB:"",architectSub:"projects",sessionTarget:"",sessionDetail:null,sessionDetailLoading:false,sessionDetailSub:"summary",sessionEditOpen:false,sessionDeleteConfirm:false,pendingDeleteTarget:"",auditTarget:"",auditData:null,auditLoading:false,slideOver:null,toast:null,loading:true,hasToolResult:false,inflight:{},reqSeq:{}};
let rpcId=1,fallbackTimer=null,livePollTimer=null,freshnessTimer=null,metricsSearchTimer=null,toastTimer=null,lastTabsKey="";
const pendingRpc=new Map(),byId=(id)=>document.getElementById(id),attr=(n,k)=>(n&&n.getAttribute&&n.getAttribute(k))||"";
const postToHost=(p)=>window.parent.postMessage(p,"*"),sendNotification=(m,p)=>postToHost({jsonrpc:"2.0",method:m,params:p||{}});
const sendRequest=(m,p)=>new Promise((resolve,reject)=>{const id=rpcId++;pendingRpc.set(id,{resolve,reject});postToHost({jsonrpc:"2.0",id,method:m,params:p||{}})});
const callServerTool=(name,args)=>sendRequest("tools/call",{name,arguments:args||{}});

function updateLayoutMode(){
const ctx=state.hostCtx||{},dm=String(ctx.displayMode||"").toLowerCase(),root=byId("root");
const w=(ctx.containerDimensions&&Number(ctx.containerDimensions.width))||(root&&root.clientWidth)||window.innerWidth||0;
const mode=(w>=860&&!dm.includes("compact"))?"wide":(((w>0&&w<680)||dm.includes("aux")||dm==="compact")?"compact":"wide");
state.layoutMode=mode;document.documentElement.dataset.layout=mode;if(root)root.dataset.layout=mode;
}
function captureFocusAndScroll(){
const act=document.activeElement,sc={},insp=byId("g-live-inspector"),evBox=insp&&insp.querySelector?insp.querySelector(".inspector-events"):null;
if(evBox)sc["g-live-inspector"]=evBox.scrollTop||0;
return{scrollX:window.scrollX||0,scrollY:window.scrollY||0,scrollers:sc,id:(act&&act.id)||"",action:attr(act,"data-action"),target:attr(act,"data-target"),tab:attr(act,"data-tab"),selStart:(act&&typeof act.selectionStart==="number")?act.selectionStart:null,selEnd:(act&&typeof act.selectionEnd==="number")?act.selectionEnd:null};
}
function restoreFocusAndScroll(snap){
if(!snap)return;
if(snap.scrollers&&snap.scrollers["g-live-inspector"]!=null){const i=byId("g-live-inspector"),b=i&&i.querySelector?i.querySelector(".inspector-events"):null;if(b)b.scrollTop=snap.scrollers["g-live-inspector"]}
let t=snap.id?byId(snap.id):null;
if(!t&&snap.action){let s='[data-action="'+snap.action+'"]';if(snap.target)s+='[data-target="'+snap.target+'"]';if(snap.tab)s+='[data-tab="'+snap.tab+'"]';t=document.querySelector(s)}
if(t&&typeof t.focus==="function"){try{t.focus({preventScroll:true})}catch(_){t.focus()}if(snap.selStart!==null&&typeof t.setSelectionRange==="function"){try{t.setSelectionRange(snap.selStart,snap.selEnd!==null?snap.selEnd:snap.selStart)}catch(_){}}}
if(typeof window.scrollTo==="function")window.scrollTo(snap.scrollX,snap.scrollY);
}
function renderToast(){
const slot=byId("g-toast-slot");if(!slot)return;clearNode(slot);if(!state.toast)return;
const t=el("div","toast"+(state.toast.isError?" error":""));t.appendChild(el("span",null,state.toast.msg));
t.appendChild(el("button","btn btn-sm","OK",{type:"button","data-action":"close-toast"}));slot.appendChild(t);
}
function showToast(msg,isError){
if(toastTimer){clearTimeout(toastTimer);toastTimer=null}
state.toast={msg:String(msg||""),isError:Boolean(isError)};renderToast();
if(!isError)toastTimer=setTimeout(()=>{state.toast=null;toastTimer=null;renderToast()},3500);
}
function applyHostContext(ctx){
if(!ctx||typeof ctx!=="object")return;state.hostCtx=Object.assign({},state.hostCtx,ctx);
if(ctx.theme==="light"||ctx.theme==="dark"){document.documentElement.dataset.theme=ctx.theme;document.documentElement.style.colorScheme=ctx.theme}
else if(!document.documentElement.dataset.theme&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches){document.documentElement.dataset.theme="light"}
const vars=ctx.styles&&ctx.styles.variables;
if(vars&&typeof vars==="object"){const st=document.documentElement.style;for(const[k,v]of Object.entries(vars))if(typeof k==="string"&&k.startsWith("--")&&typeof v==="string")st.setProperty(k,v)}
const fCss=ctx.styles&&ctx.styles.css&&ctx.styles.css.fonts;
if(typeof fCss==="string"&&fCss.trim()){let s=byId("g-host-fonts");if(!s){s=el("style",null,null,{id:"g-host-fonts"});document.head.appendChild(s)}s.textContent=fCss}
updateLayoutMode();
}
function extractStructured(res){
if(!res||typeof res!=="object")return null;
if(res.structuredContent&&typeof res.structuredContent==="object")return res.structuredContent;
if(Array.isArray(res.content))for(const b of res.content)if(b&&b.type==="text"&&typeof b.text==="string"&&b.text.trim().startsWith("{")){try{return JSON.parse(b.text)}catch(_){}}
return null;
}
function getActiveTabObj(){const tabs=(state.overview&&state.overview.tabs)||[];return tabs.find((t)=>t.id===state.activeTab)||tabs[0]||{id:"live",kind:"live",label:"Session"}}
function resolveInitialTab(view,moduleId){
const tabs=(state.overview&&state.overview.tabs)||[],v=String(view||"live").toLowerCase();
if(v==="module"&&moduleId){const m=tabs.find((t)=>t.module_id===moduleId||t.id===moduleId);if(m)return m.id}
if(v==="workflow"||v==="live"){const m=tabs.find((t)=>t.id==="live"||t.kind==="live");return m?m.id:"live"}
if(v==="metrics"||v==="architect"||v==="overview"){const m=tabs.find((t)=>t.id===v||t.kind===v);if(m)return m.id}
const d=tabs.find((t)=>t.id==="live"||t.kind==="live");return d?d.id:((tabs[0]&&tabs[0].id)||"live");
}
function applyInitialMetricsSub(raw){
const s=String(raw||"").trim().toLowerCase();
if(s==="pending"){state.metricsSub="sessions";state.metricsFilter="pending"}
else if(s==="compare"){state.metricsSub="sessions";state.compareOpen=true}
else if(s==="overview"||s==="sessions"||s==="audits")state.metricsSub=s;
}
function hydrateInitialPayload(sc){
if(!sc||typeof sc!=="object")return;
if(sc.overview&&typeof sc.overview==="object")state.overview=sc.overview;else if(sc.doctor&&sc.tabs)state.overview=sc;
if(sc.live&&typeof sc.live==="object"){state.live=sc.live;state.liveUi.lastUpdatedAt=new Date().toISOString()}
if(sc.workflow&&typeof sc.workflow==="object")state.workflow=sc.workflow;
if(sc.metrics&&typeof sc.metrics==="object")state.metrics=sc.metrics;
if(sc.architect&&typeof sc.architect==="object")state.architect=sc.architect;
if(typeof sc.initial_project==="string")state.metricsProject=sc.initial_project;
if(typeof sc.initial_ws==="string")state.selectedWs=sc.initial_ws;
if(typeof sc.initial_atelier==="string")state.selectedAtelier=sc.initial_atelier;
applyInitialMetricsSub(sc.initial_metrics_sub);
if(sc.module_info&&sc.module_info.module_id)state.moduleCache[sc.module_info.module_id]=sc.module_info;
state.activeTab=resolveInitialTab(sc.initial_view,sc.initial_module_id);
if(typeof sc.initial_target==="string"&&sc.initial_target){
if(state.activeTab==="live")state.liveUi.selectedSessionId=sc.initial_target;
else if(state.activeTab==="metrics"){state.metricsSub="sessions";state.sessionTarget=sc.initial_target}
}
state.loading=false;ensureActiveTabLoaded(false);render();
if(state.activeTab==="metrics"&&state.sessionTarget&&!state.sessionDetail&&state.hostCaps.serverTools)openSessionDetail(state.sessionTarget);
}
async function runChannel(ch,silent,fn){
if(!state.hostCaps.serverTools||(silent&&state.inflight[ch]))return;
const seq=(state.reqSeq[ch]||0)+1;state.reqSeq[ch]=seq;state.inflight[ch]=true;
try{return await fn(seq)}finally{if(state.reqSeq[ch]===seq)state.inflight[ch]=false}
}
const isStale=(ch,seq)=>state.reqSeq[ch]!==seq;
function loadChannelState(ch,tool,args,silent,errLbl,onSc){
return runChannel(ch,silent,async(seq)=>{
try{const sc=extractStructured(await callServerTool(tool,args));if(!isStale(ch,seq)&&sc&&sc.changed!==false&&!sc.unchanged)onSc(sc)}
catch(err){if(!silent)showToast(errLbl+" : "+err.message,true)}finally{if(ch==="overview")state.loading=false}
});
}
const loadOverview=(s)=>loadChannelState("overview","gravity_get_overview",{since_signature:s&&state.overview?(state.overview.signature||""):""},s,"Erreur Système",(sc)=>{state.overview=sc;render()});
const loadLiveSession=(s)=>loadChannelState("live","gravity_get_live_session",{session_id:state.liveUi.selectedSessionId||"",ws:state.selectedWs||"",since_signature:s&&state.live?(state.live.signature||""):"",include_events:true},s,"Erreur Session",(sc)=>{state.live=sc;state.liveUi.lastUpdatedAt=new Date().toISOString();if(getActiveTabObj().kind==="live")renderActiveView()});
const loadMetricsState=(s,co)=>loadChannelState("metrics","gravity_get_metrics_state",{project:state.metricsProject||"",q:state.metricsQ||"",since_signature:s&&state.metrics?(state.metrics.signature||""):""},s,"Erreur Historique",(sc)=>{state.metrics=sc;if(getActiveTabObj().kind==="metrics"){if(co&&byId("g-metrics-content"))renderMetricsBodyOrFull();else renderActiveView()}});
const loadArchitectState=(s)=>loadChannelState("architect","gravity_get_architect_state",{atelier:state.selectedAtelier||"",ws:state.selectedWs||"",since_signature:s&&state.architect?(state.architect.signature||""):""},s,"Erreur Projets",(sc)=>{state.architect=sc;if(getActiveTabObj().kind==="architect")renderActiveView()});
function loadModuleInfo(mid,force){
if(!mid||(state.moduleCache[mid]&&!force))return;const ch="mod:"+mid;
return runChannel(ch,false,async(seq)=>{
state.moduleLoading[mid]=true;if(getActiveTabObj().module_id===mid)renderActiveView();
try{
const res=await callServerTool("gravity_get_module_info",{module_id:mid});if(isStale(ch,seq))return;
const sc=extractStructured(res);
if(sc)state.moduleCache[mid]=sc;else if(res&&res.isError)state.moduleCache[mid]={found:false,module_id:mid,error:(res.content&&res.content[0]&&res.content[0].text)||"Module introuvable"};
}catch(err){showToast("Erreur module : "+err.message,true)}finally{state.moduleLoading[mid]=false;if(getActiveTabObj().module_id===mid)renderActiveView()}
});
}
function openSubResource(ch,tool,args,loadKey,errLbl,onOk){
if(!state.hostCaps.serverTools){showToast("serverTools indisponible.",true);return}
return runChannel(ch,false,async(seq)=>{
state[loadKey]=true;renderMetricsBodyOrFull();
try{
const res=await callServerTool(tool,args);if(isStale(ch,seq))return;const sc=extractStructured(res);
if(res&&res.isError&&(!sc||!sc.found))showToast((sc&&sc.error)||(res.content&&res.content[0]&&res.content[0].text)||"Introuvable",true);
else if(sc)onOk(sc);
}catch(err){showToast(errLbl+" : "+err.message,true)}finally{if(!isStale(ch,seq)){state[loadKey]=false;renderMetricsBodyOrFull()}}
});
}
function openSessionDetail(target){
if(!target)return;state.sessionTarget=target;state.sessionEditOpen=false;state.sessionDeleteConfirm=false;state.pendingDeleteTarget="";
if(!state.hostCaps.serverTools)state.sessionDetail=null;
return openSubResource("detail","gravity_get_session_detail",{target},"sessionDetailLoading","Détail session",(sc)=>{state.sessionDetail=sc});
}
function openAuditReader(auditId){
if(!auditId)return;state.auditTarget=auditId;
return openSubResource("audit","gravity_read_audit",{path:auditId},"auditLoading","Lecture audit",(sc)=>{state.auditData=sc});
}
async function dispatchMetricsCliAction(params){
if(!state.hostCaps.serverTools){showToast("serverTools indisponible.",true);return}
state.metricsActionInFlight=true;state.liveUi.actionInFlight=true;renderActiveView();
try{
const res=await callServerTool("gravity_metrics_action",params),sc=extractStructured(res);
if((res&&res.isError)||(sc&&sc.ok===false))showToast((sc&&sc.message)||(res&&res.content&&res.content[0]&&res.content[0].text)||"Action échouée",true);
else{
const act=String(params.action||"");
if(act==="remove"||act==="ignore"){state.sessionTarget="";state.sessionDetail=null;state.sessionDeleteConfirm=false;state.pendingDeleteTarget=""}else if(act==="update-meta")state.sessionEditOpen=false;
showToast((sc&&sc.message)||"Action exécutée.",false);state.metrics=null;await loadMetricsState(false,false);
if(getActiveTabObj().kind==="live")await loadLiveSession(false);
else if(state.sessionTarget&&(act==="update"||act==="update-meta"))await openSessionDetail(state.sessionTarget);
}
}catch(err){showToast("Action Historique : "+err.message,true)}finally{state.metricsActionInFlight=false;state.liveUi.actionInFlight=false;renderActiveView()}
}
async function openMarkdownFile(uri){
if(!uri){showToast("Fichier Markdown introuvable.",true);return}
try{const res=await sendRequest("com.google.antigravity/toggle-aux-pane",{tabType:"fileView",uri});if(res&&res.isError)showToast("Ouverture fichier refusée par l'hôte.",false)}
catch(_){showToast("Ouverture .md indisponible sur cette surface.",false)}
}
function renderMetricsBodyOrFull(){const b=byId("g-metrics-content");if(b){const s=captureFocusAndScroll();clearNode(b);renderMetricsContent(b);restoreFocusAndScroll(s)}else renderActiveView()}
function ensureActiveTabLoaded(f){
const t=getActiveTabObj();
if(t.kind==="live"&&(f||!state.live))loadLiveSession(false);
else if(t.kind==="metrics"&&(f||!state.metrics))loadMetricsState(false,false);
else if(t.kind==="architect"&&(f||!state.architect))loadArchitectState(false);
else if(t.kind==="generic"&&t.module_id&&(f||!state.moduleCache[t.module_id]))loadModuleInfo(t.module_id,Boolean(f));
}
function refreshCurrentTab(){
const t=getActiveTabObj();
if(t.kind==="live")loadLiveSession(false);else if(t.kind==="metrics")loadMetricsState(false,false);else if(t.kind==="architect")loadArchitectState(false);else if(t.kind==="generic"&&t.module_id)loadModuleInfo(t.module_id,true);else loadOverview(false);
}
function navigateTo(view,patch){
if(patch&&typeof patch==="object")Object.assign(state,patch);
state.slideOver=null;state.activeTab=resolveInitialTab(view,patch&&patch.moduleId);
ensureActiveTabLoaded(Boolean(patch&&(patch.metricsProject!==undefined||patch.selectedAtelier!==undefined||patch.selectedWs!==undefined)));render();
}
function ensureShell(root){
if(byId("g-content"))return;clearNode(root);
const hd=el("header","shell-head",null,{id:"g-shell-head"}),tb=el("div","topbar"),br=el("div","brand");
br.appendChild(el("span","brand-dot ok",null,{id:"g-brand-dot"}));br.appendChild(el("span","brand-title","Gravity"));br.appendChild(el("span","brand-sub mono","Initialisation...",{id:"g-brand-sub"}));
tb.appendChild(br);tb.appendChild(el("nav","tabs nav-main",null,{id:"g-nav-main",role:"tablist"}));tb.appendChild(el("div","nav-sys",null,{id:"g-nav-sys"}));
hd.appendChild(tb);root.appendChild(hd);root.appendChild(el("div",null,null,{id:"g-toast-slot"}));root.appendChild(el("main",null,null,{id:"g-content"}));root.appendChild(el("div",null,null,{id:"g-slideover"}));
if(typeof ResizeObserver==="function")try{new ResizeObserver(updateLayoutMode).observe(root)}catch(_){}
}
function renderHeader(){
const ov=state.overview,doc=(ov&&ov.doctor)||{},tabs=(ov&&ov.tabs)||[{id:"live",kind:"live",label:"Session"}];
const dot=byId("g-brand-dot");if(dot)dot.className="brand-dot "+String(doc.status||"ok");
const sub=byId("g-brand-sub");if(sub)sub.textContent=ov?((ov.gravity_home||"~/.gemini/gravity")+" · "+(doc.module_count||0)+" mod."):"Initialisation...";
const nm=byId("g-nav-main"),ns=byId("g-nav-sys");if(!nm||!ns)return;
const tk=tabs.map((t)=>t.id+":"+(t.label||"")).join("|");
if(tk!==lastTabsKey){
lastTabsKey=tk;clearNode(nm);clearNode(ns);let sys=null;
tabs.forEach((t)=>{if(t.id==="overview"||t.kind==="core"){sys=t;return}nm.appendChild(el("button","tab-btn",t.label||t.id,{type:"button",role:"tab","aria-selected":"false","data-action":"select-tab","data-tab":t.id}))});
if(sys)ns.appendChild(el("button","tab-btn tab-sys",sys.label||"Système",{type:"button",role:"tab","aria-selected":"false","data-action":"select-tab","data-tab":sys.id}));
ns.appendChild(el("button","btn btn-sm","Rafraîchir",{type:"button","data-action":"refresh"}));
}
document.querySelectorAll('[data-action="select-tab"]').forEach((b)=>{const a=attr(b,"data-tab")===state.activeTab;b.setAttribute("aria-selected",a?"true":"false");b.className="tab-btn"+(b.classList&&b.classList.contains("tab-sys")?" tab-sys":"")+(a?" active":"")});
}
function renderSlideOver(){
const slot=byId("g-slideover");if(!slot)return;clearNode(slot);if(!state.slideOver)return;
const bd=el("div","slide-over-backdrop",null,{"data-action":"close-slideover"}),p=el("aside","slide-over",null,{role:"dialog","aria-modal":"true"}),h=el("div","panel-head");
h.appendChild(el("div","panel-title",String(state.slideOver.title||"Détail")));h.appendChild(el("button","btn btn-sm","Fermer",{type:"button","data-action":"close-slideover"}));
p.appendChild(h);if(typeof state.slideOver.render==="function")state.slideOver.render(p);bd.appendChild(p);slot.appendChild(bd);
}
function renderActiveView(){
const main=byId("g-content");if(!main)return;const snap=captureFocusAndScroll();clearNode(main);
if(state.loading&&!state.overview)main.appendChild(el("div","empty","Connexion au serveur MCP Gravity..."));
else{
const t=getActiveTabObj();
if(t.kind==="live"||t.kind==="workflow")renderLiveView(main,state.live,state.liveUi,{});
else if(t.kind==="metrics")renderMetricsView(main);
else if(t.kind==="architect")renderArchitectView(main);
else if(t.kind==="generic")renderModuleView(main,t);
else renderOverviewView(main);
}
restoreFocusAndScroll(snap);
}
function render(){const r=byId("root");if(!r)return;updateLayoutMode();ensureShell(r);renderHeader();renderToast();renderActiveView();renderSlideOver()}
document.addEventListener("toggle",(ev)=>{if(!ev.target)return;if(ev.target.id==="g-live-activity")state.liveUi.eventsOpen=Boolean(ev.target.open);else if(ev.target.id==="g-live-breakdown")state.liveUi.breakdownOpen=Boolean(ev.target.open)},true);
document.addEventListener("submit",(ev)=>{const f=ev.target;if(!f||f.id!=="g-session-edit-form")return;ev.preventDefault();const v=(id)=>{const n=byId(id);return n?n.value:""};dispatchMetricsCliAction({action:"update-meta",target:attr(f,"data-target")||state.sessionTarget,label:v("g-edit-label"),project:v("g-edit-project"),note:v("g-edit-note")})});
document.addEventListener("keydown",(ev)=>{if(ev.key!=="Escape")return;if(state.slideOver){state.slideOver=null;renderSlideOver()}else if(state.auditTarget){state.auditTarget="";state.auditData=null;renderMetricsBodyOrFull()}else if(state.sessionTarget){state.sessionTarget="";state.sessionDetail=null;renderMetricsBodyOrFull()}});
const CLICK_HANDLERS={
"select-tab":(t)=>{state.activeTab=attr(t,"data-tab")||"live";ensureActiveTabLoaded(false);render()},
"refresh":refreshCurrentTab,
"close-toast":()=>{state.toast=null;renderToast()},
"close-slideover":(t,ev)=>{if(!(t.classList&&t.classList.contains("slide-over-backdrop")&&ev&&ev.target!==t)){state.slideOver=null;renderSlideOver()}},
"nav-projects":()=>navigateTo("architect"),
"nav-history":(t)=>{const p=attr(t,"data-project");navigateTo("metrics",p?{metricsProject:p,metricsSub:"sessions"}:{})},
"toggle-live-pause":()=>{state.liveUi.paused=!state.liveUi.paused;renderActiveView()},
"select-live-agent":(t)=>{state.liveUi.selectedAgentId=attr(t,"data-agent-id");renderActiveView()},
"live-clear-agent":()=>{state.liveUi.selectedAgentId="__all__";renderActiveView()},
"toggle-live-tree":(t)=>{const aid=attr(t,"data-agent-id");if(aid){state.liveUi.collapsedAgents[aid]=!state.liveUi.collapsedAgents[aid];renderActiveView()}},
"live-metrics-action":(t)=>dispatchMetricsCliAction({action:attr(t,"data-metrics-action")||"record",conversation_id:attr(t,"data-cid")}),
"metrics-sub":(t)=>{state.metricsSub=attr(t,"data-sub")||"overview";renderMetricsBodyOrFull()},
"metrics-filter":(t)=>{state.metricsFilter=attr(t,"data-filter")||"recorded";renderMetricsBodyOrFull()},
"toggle-compare":()=>{state.compareOpen=!state.compareOpen;renderMetricsBodyOrFull()},
"pin-compare":(t)=>{const sl=attr(t,"data-slot"),tg=attr(t,"data-target");if(sl==="A")state.compareA=tg;else if(sl==="B")state.compareB=tg;state.compareOpen=true;renderMetricsBodyOrFull()},
"open-session-detail":(t)=>{const tg=attr(t,"data-target");if(tg)openSessionDetail(tg)},
"close-session-detail":()=>{state.sessionTarget="";state.sessionDetail=null;state.sessionEditOpen=false;state.sessionDeleteConfirm=false;renderMetricsBodyOrFull()},
"session-detail-sub":(t)=>{state.sessionDetailSub=attr(t,"data-sub")||"summary";renderMetricsBodyOrFull()},
"toggle-session-edit":()=>{state.sessionEditOpen=!state.sessionEditOpen;renderMetricsBodyOrFull()},
"ask-remove-session":(t)=>{state.sessionDeleteConfirm=true;state.pendingDeleteTarget=attr(t,"data-target")||state.sessionTarget;renderMetricsBodyOrFull()},
"cancel-remove-session":()=>{state.sessionDeleteConfirm=false;state.pendingDeleteTarget="";renderMetricsBodyOrFull()},
"metrics-cli-action":(t)=>{const ca=attr(t,"data-cli-action"),ws=attr(t,"data-workspace"),p={action:ca,conversation_id:attr(t,"data-cid"),target:attr(t,"data-target")};if(ws)p.workspace=ws;if(ca==="remove")p.purge_reports=true;dispatchMetricsCliAction(p)},
"read-audit":(t)=>openAuditReader(attr(t,"data-audit-id")),
"close-audit-reader":()=>{state.auditTarget="";state.auditData=null;renderMetricsBodyOrFull()},
"open-file":(t)=>openMarkdownFile(attr(t,"data-uri")),
"architect-sub":(t)=>{state.architectSub=attr(t,"data-sub")||"projects";renderActiveView()}
};
document.addEventListener("click",(ev)=>{const t=ev.target&&ev.target.closest?ev.target.closest("[data-action]"):null;if(t){const fn=CLICK_HANDLERS[attr(t,"data-action")];if(fn)fn(t,ev)}});
document.addEventListener("change",(ev)=>{
const n=ev.target;if(!n||!n.id)return;
if(n.id==="g-live-session"){state.liveUi.selectedSessionId=n.value||"";state.liveUi.selectedAgentId="";state.liveUi.collapsedAgents={};loadLiveSession(false)}
else if(n.id==="g-metrics-project"){state.metricsProject=n.value||"";state.sessionTarget="";state.sessionDetail=null;loadMetricsState(false,true)}
else if(n.id==="g-metrics-sort"){state.metricsSort=n.value||"date";renderMetricsBodyOrFull()}
else if(n.id==="g-cmp-a"){state.compareA=n.value||"";renderMetricsBodyOrFull()}
else if(n.id==="g-cmp-b"){state.compareB=n.value||"";renderMetricsBodyOrFull()}
else if(n.id==="g-arch-ws"){state.selectedAtelier=n.value||"";loadArchitectState(false)}
});
document.addEventListener("input",(ev)=>{
const n=ev.target;if(!n||n.id!=="g-metrics-q")return;state.metricsQ=n.value||"";
if(metricsSearchTimer)clearTimeout(metricsSearchTimer);metricsSearchTimer=setTimeout(()=>{metricsSearchTimer=null;loadMetricsState(false,true)},220);
});
window.addEventListener("resize",updateLayoutMode);
window.addEventListener("message",(ev)=>{
const m=ev.data;if(!m||typeof m!=="object")return;
if(m.id!==undefined&&m.id!==null&&pendingRpc.has(m.id)&&!m.method){const e=pendingRpc.get(m.id);pendingRpc.delete(m.id);if(m.error)e.reject(new Error(m.error.message||JSON.stringify(m.error)));else e.resolve(m.result);return}
if(m.id!==undefined&&m.id!==null&&m.method){postToHost(m.method==="ping"||m.method==="ui/resource-teardown"?{jsonrpc:"2.0",id:m.id,result:{}}:{jsonrpc:"2.0",id:m.id,error:{code:-32601,message:"Method not found"}});return}
if(m.method==="ui/notifications/host-context-changed")applyHostContext(m.params||{});
else if(m.method==="ui/notifications/tool-input"){
const a=(m.params&&m.params.arguments)||{};
if(typeof a.project==="string")state.metricsProject=a.project.trim();if(typeof a.ws==="string")state.selectedWs=a.ws.trim();if(typeof a.atelier==="string")state.selectedAtelier=a.atelier.trim();
applyInitialMetricsSub(a.metrics_sub);if(typeof a.view==="string"&&state.overview){state.activeTab=resolveInitialTab(a.view,a.module_id);render()}
}else if(m.method==="ui/notifications/tool-result"){
state.hasToolResult=true;if(fallbackTimer){clearTimeout(fallbackTimer);fallbackTimer=null}
const sc=extractStructured(m.params);if(sc)hydrateInitialPayload(sc);else loadOverview(false);
}else if(m.method==="ui/notifications/tool-cancelled"){state.loading=false;render()}
});
async function initBridge(){
try{
const res=await sendRequest("ui/initialize",{appInfo:{name:"gravity",version:"0.3.0"},appCapabilities:{},protocolVersion:PROTOCOL_VERSION});
state.hostCaps=(res&&res.hostCapabilities)||{};applyHostContext((res&&res.hostContext)||{});sendNotification("ui/notifications/initialized",{});
if(!state.hasToolResult)fallbackTimer=setTimeout(()=>{if(!state.hasToolResult&&state.hostCaps.serverTools)loadOverview(false);else if(!state.hasToolResult){state.loading=false;render()}},450);
livePollTimer=setInterval(()=>{if(document.visibilityState==="visible"&&state.hostCaps.serverTools&&!state.inflight.live&&!state.liveUi.paused&&getActiveTabObj().kind==="live")loadLiveSession(true)},LIVE_POLL_MS);
freshnessTimer=setInterval(()=>{if(document.visibilityState!=="visible"||!document.querySelectorAll)return;document.querySelectorAll("[data-freshness]").forEach((n)=>{n.textContent=attr(n,"data-paused")==="1"?"En pause":("Fraîcheur : "+fmtRelativeTime(attr(n,"data-ts")))})},1000);
}catch(err){state.loading=false;showToast("Initialisation pont MCP App échouée : "+err.message,true)}
}
initBridge();
"""

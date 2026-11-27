"""Reusable pure DOM/SVG chart components and French formatters (100% stdlib, zero innerHTML)."""

from __future__ import annotations

CHARTS_JS = r"""
const CTX_WARN_TOKENS=128000,CTX_CRIT_TOKENS=200000;
function fmtTokens(n,u){const v=Math.max(0,Number(n)||0),t=v>=1e6?(v/1e6).toFixed(1).replace(".",",")+" M":(v>=1e3?Math.round(v/1e3)+" k":String(Math.round(v)));return u?t+" tokens":t}
function fmtDuration(sec){
if(sec===null||sec===undefined||sec==="")return"—";
const num=Number(sec);if(!isFinite(num)||num<0)return"—";
const s=Math.round(num);if(s<60)return s+" s";
const m=Math.floor(s/60),rs=s%60;if(m<60)return m+" min"+(rs?" "+String(rs).padStart(2,"0")+" s":"");
const h=Math.floor(m/60),rm=m%60;return h+" h"+(rm?" "+String(rm).padStart(2,"0")+" min":"");
}
function fmtPct(n){const v=Number(n);return isFinite(v)?v.toFixed(1).replace(".",",")+" %":"0,0 %"}
function fmtLatency(ms){if(ms===null||ms===undefined||ms==="")return"—";const v=Number(ms);return(!isFinite(v)||v<0)?"—":(v>=1e3?(v/1e3).toFixed(1).replace(".",",")+" s":Math.round(v)+" ms")}
function fmtRelativeTime(raw,nowMs){
if(!raw)return"à l'instant";const t=Date.parse(String(raw));if(!isFinite(t))return fmtDate(raw);
const d=Math.max(0,Math.round(((typeof nowMs==="number"?nowMs:Date.now())-t)/1e3));
return d<10?"à l'instant":(d<60?"il y a "+d+" s":(d<3600?"il y a "+Math.floor(d/60)+" min":"il y a "+Math.floor(d/3600)+" h"));
}
function renderWorkspaceKindBadge(k){const a=String(k||"").toLowerCase()==="atelier";return makeBadge(a?"Atelier":"Code",a?"atelier":"code")}
function renderStatusBadge(st){const m={active:["Actif","ok"],waiting:["En attente","warn"],error:["Erreur","error"],interrupted:["Interrompu","warn"]}[String(st||"done").toLowerCase()];return makeBadge(m?m[0]:"Terminé",m?m[1]:"")}
function resolveAgentModel(ag){
if(!ag||typeof ag!=="object")return"";
const dir=ag.model?String(ag.model).trim():"";if(dir&&dir!=="unknown")return dir;
if(ag.by_model&&typeof ag.by_model==="object"){
let best="",bc=-1,bt=-1;
Object.entries(ag.by_model).forEach(([n,i])=>{const c=Number((i&&i.calls)||0),t=Number((i&&i.input_tokens)||0)+Number((i&&i.output_tokens)||0);if(c>bc||(c===bc&&t>bt)){best=String(n);bc=c;bt=t}});
if(best)return best;
}
return dir;
}
function shortModelName(raw){
let s=String(raw||"").trim().replace(/^models\//,"").replace(/-20\d{6}$/,"");
if(!s||s==="unknown")return"";
s=s.replace(/^claude-(sonnet|opus|haiku)-(\d+)[-.](\d+).*$/i,(_,f,a,b)=>(f[0].toUpperCase()+f.slice(1).toLowerCase()+" "+a+"."+b))
  .replace(/^gemini-(\d+(?:\.\d+)?)-([a-z0-9-]+?)(?:-preview)?$/i,(_,v,r)=>"G"+v+" "+r.replace(/-/g," "))
  .replace(/^claude-/i,"Claude ").replace(/-preview$/i,"");
return s.length>20?s.slice(0,19)+"…":s;
}
function resolveAgentToolCalls(ag){return(ag&&typeof ag==="object")?Math.max(0,Number(ag.tool_calls_total!=null?ag.tool_calls_total:ag.tool_calls)||0):0}
function renderSourceBadge(s){const k=String(s||"").toLowerCase().trim();if(!k)return null;const m={root:["Racine","src-root"],swarm:["Swarm","src-swarm"],subagent:["Subagent","src-subagent"],workflow:["Workflow","src-workflow"]}[k];return m?makeBadge(m[0],m[1]):makeBadge(String(s),"src-other")}
function renderFiliationLabel(ag,idMap){
if(!ag||typeof ag!=="object")return null;
const hasD=ag.depth!==null&&ag.depth!==undefined&&ag.depth!==""&&isFinite(Number(ag.depth)),d=hasD?Math.max(0,Math.round(Number(ag.depth))):null,pid=ag.parent_id?String(ag.parent_id):"";
const pn=ag.parent_name?String(ag.parent_name):(pid&&idMap&&idMap[pid]?String(idMap[pid]):(pid?pid.slice(0,8):""));
if(!pn&&d===null)return null;const p=[];if(pn)p.push("↳ "+pn);if(d!==null)p.push((!pn&&d>0?"↳ ":"")+"N"+d);return el("div","agent-filiation mono",p.join(" · "));
}
function renderSparkline(vals,opts){
const pts=(Array.isArray(vals)?vals:[]).map(Number).filter(isFinite);if(pts.length<2)return null;
const o=opts||{},w=76,h=22,mn=Math.min(...pts),mx=Math.max(...pts),sp=mx-mn||1;
const coords=pts.map((v,i)=>(2+(i/(pts.length-1))*(w-4)).toFixed(1)+","+(h-2-((v-mn)/sp)*(h-4)).toFixed(1));
const col=o.color||"var(--g-accent)",svg=svgEl("svg",{class:"sparkline",viewBox:"0 0 "+w+" "+h,role:"img","aria-label":o.label||"Tendance"});
svg.appendChild(svgEl("polyline",{fill:"none",stroke:col,"stroke-width":"1.6","stroke-linecap":"round","stroke-linejoin":"round",points:coords.join(" ")}));
const last=coords[coords.length-1].split(",");svg.appendChild(svgEl("circle",{cx:last[0],cy:last[1],r:"2.2",fill:col}));return svg;
}
function renderContextGauge(curT,maxT,opts){
const o=opts||{},cur=Math.max(0,Number(curT)||0),peak=Math.max(cur,Number(maxT)||0),lim=Math.max(CTX_CRIT_TOKENS,Number(o.limit)||CTX_CRIT_TOKENS),ref=cur>0?cur:peak;
const pct=Math.min(100,Math.round((ref/lim)*100)),lvl=ref>CTX_CRIT_TOKENS?"crit":(ref>CTX_WARN_TOKENS?"warn":"ok"),w=el("div","ctx-gauge"),h=el("div","ctx-gauge-head");
h.appendChild(el("span",null,(o.label||"Contexte")+" : "+fmtTokens(cur)+(peak>cur?" (pic "+fmtTokens(peak)+")":"")));
h.appendChild(lvl==="crit"?makeBadge("Critique >200k","crit"):(lvl==="warn"?makeBadge("Alerte >128k","warn"):el("span","mono",fmtPct(pct))));w.appendChild(h);
const tr=el("div","ctx-track",null,{role:"progressbar","aria-valuenow":String(Math.round(ref)),"aria-valuemin":"0","aria-valuemax":String(lim)}),fl=el("div","ctx-fill "+lvl);
fl.style.width=pct+"%";tr.appendChild(fl);w.appendChild(tr);return w;
}
function renderStackedBars(segs,opts){
const o=opts||{},items=(Array.isArray(segs)?segs:[]).filter((s)=>s&&Number(s.value)>0),tot=items.reduce((a,s)=>a+(Number(s.value)||0),0),w=el("div","stack-wrap");
if(o.title){const h=el("div","panel-head");h.appendChild(el("span","kpi-lbl",o.title));h.appendChild(el("span","mono",fmtTokens(tot,true)));w.appendChild(h)}
if(!items.length||tot<=0){w.appendChild(el("div","empty",o.emptyLabel||"Aucune consommation mesurée."));return w}
const bar=el("div","stack-bar"),leg=el("div","stack-legend");
items.forEach((s,i)=>{
const v=Number(s.value)||0,pct=(v/tot)*100,col=s.color||("var(--g-c"+((i%6)+1)+")"),sl=el("div","stack-seg",null,{title:String(s.label||"")+" : "+fmtTokens(v,true)+" ("+fmtPct(pct)+")"});
sl.style.width=Math.max(1.5,pct).toFixed(2)+"%";sl.style.backgroundColor=col;bar.appendChild(sl);
const lg=el("span","legend-item"),dot=el("span","legend-dot");dot.style.backgroundColor=col;
lg.appendChild(dot);lg.appendChild(el("span",null,String(s.label||"")+" : "+fmtTokens(v)+" ("+Math.round(pct)+"%)"));leg.appendChild(lg);
});
w.appendChild(bar);w.appendChild(leg);return w;
}
function renderWorkspaceBreakdown(workspaces,opts){
const o=opts||{},rows=Array.isArray(workspaces)?workspaces.slice():[],w=el("div","ws-list");
if(!rows.length){w.appendChild(el("div","empty",o.emptyLabel||"Aucun dépôt détecté."));return w}
const mV=(r)=>Number(r.useful_tokens||r.tokens||r.total_tokens||0),mx=Math.max(...rows.map(mV),1);
rows.slice(0,o.limit||8).forEach((r)=>{
const val=mV(r),pct=Math.max(val>0?4:0,Math.round((val/mx)*100)),kind=String(r.kind||r.workspace_kind||"code").toLowerCase(),row=el("div","ws-row"),hd=el("div","ws-row-head"),lt=el("div","ws-name-wrap");
lt.appendChild(el("span","mono",String(r.workspace||r.project||"workspace")));lt.appendChild(renderWorkspaceKindBadge(kind));hd.appendChild(lt);
const cnt=r.agents_count!=null?(r.agents_count+" agent(s)"):(r.sessions!=null?(r.sessions+(r.share_pct!=null?" sess.":" session(s)")):"");
hd.appendChild(el("span","mono num",fmtTokens(val)+(r.share_pct!=null?" ("+fmtPct(r.share_pct)+")":"")+(cnt?" · "+cnt:"")));row.appendChild(hd);
const tr=el("div","ws-bar-track"),fl=el("div","ws-bar-fill");fl.style.width=pct+"%";fl.style.backgroundColor=kind==="atelier"?"var(--g-atelier)":"var(--g-code)";
tr.appendChild(fl);row.appendChild(tr);w.appendChild(row);
});
return w;
}
function renderMetricKpiCard(lbl,val,sub,toneOrOpts){
const o=typeof toneOrOpts==="string"?{tone:toneOrOpts}:(toneOrOpts||{}),c=el("div","kpi-card"+(o.tone?" "+o.tone:"")),top=el("div","kpi-top");
top.appendChild(el("div","kpi-lbl",lbl));if(o.badge&&o.badge.label)top.appendChild(makeBadge(o.badge.label,o.badge.tone||""));c.appendChild(top);
const mid=el("div","kpi-top");mid.appendChild(el("div","kpi-val num",val));
if(Array.isArray(o.series)&&o.series.length>=2){const sp=renderSparkline(o.series,{label:lbl,color:o.seriesColor});if(sp)mid.appendChild(sp)}
c.appendChild(mid);if(sub)c.appendChild(el("div","kpi-sub",sub));return c;
}
function renderAbCompareRow(lbl,va,vb,mx,fmtFn,opts){
const o=opts||{},row=el("div","ab-row"),hd=el("div","ws-row-head"),right=el("div","actions-row");
hd.appendChild(el("span","agent-role",lbl));
const d=va>0?Math.round(((vb-va)/va)*100):(vb>0?100:0),dGood=o.higherGood?(d>=0):(d<=0),col=o.color||"var(--g-accent)";
right.appendChild(el("span","mono num","A: "+fmtFn(va)));right.appendChild(el("span","mono num","B: "+fmtFn(vb)));
right.appendChild(el("span","badge mono "+(dGood?"ok":"warn"),(d>0?"+":"")+d+"%"));hd.appendChild(right);row.appendChild(hd);
[["A",va,"a"],["B",vb,"b"]].forEach(([tag,v,cls])=>{
const ln=el("div","ab-line"),tr=el("div","ab-track"),fl=el("div","ab-fill "+cls);
fl.style.width=(mx>0?Math.max(v>0?3:0,Math.round((v/mx)*100)):0)+"%";fl.style.backgroundColor=col;
ln.appendChild(el("span","ab-tag",tag));tr.appendChild(fl);ln.appendChild(tr);row.appendChild(ln);
});
return row;
}
function renderInlineConfirm(opts){
const o=opts||{},box=el("div","inline-confirm"+(o.danger?" danger":""));box.appendChild(el("span",null,String(o.message||"Confirmer cette action ?")));
const btns=el("div","inline-confirm-actions"),ok=el("button","btn btn-sm "+(o.danger?"btn-danger":"btn-primary"),o.confirmLabel||"Confirmer",Object.assign({type:"button"},o.confirmAttrs||{})),no=el("button","btn btn-sm",o.cancelLabel||"Annuler",Object.assign({type:"button"},o.cancelAttrs||{}));
if(typeof o.onConfirm==="function")ok.addEventListener("click",o.onConfirm);if(typeof o.onCancel==="function")no.addEventListener("click",o.onCancel);
btns.appendChild(ok);btns.appendChild(no);box.appendChild(btns);return box;
}
const _agDur=(ag)=>Math.max(0,Number(ag.duration_s!=null?ag.duration_s:(ag.active_s!=null?ag.active_s:ag.lifespan_s))||0);
const _pMs=(r)=>{if(!r)return NaN;const t=Date.parse(String(r));return isFinite(t)?t:NaN};
function buildAgentHierarchy(agents,opts){
const o=opts||{},list=Array.isArray(agents)?agents.filter(Boolean):[],nodes=[],byId={},idMap={},roots=[];
list.forEach((ag,idx)=>{
const key=String((ag&&(ag.id||ag.conversation_id))||("ag-"+idx)),lbl=String(ag.role||ag.name||ag.type_name||key),n={key,ag,idx,depth:Number(ag.depth)||0,children:[]};
nodes.push(n);byId[key]=n;if(ag.id){byId[String(ag.id)]=n;idMap[String(ag.id)]=lbl}if(ag.conversation_id){byId[String(ag.conversation_id)]=n;idMap[String(ag.conversation_id)]=lbl}
});
const hasCyc=(c,p)=>{for(let x=p,s=new Set([c]);x;x=x.parent){if(s.has(x))return true;s.add(x)}return false};
nodes.forEach((n)=>{const p=n.ag.parent_id?byId[String(n.ag.parent_id)]:null;if(p&&p!==n&&!hasCyc(n,p)){n.parent=p;p.children.push(n)}else{n.parent=null;roots.push(n)}});
const setD=(n,d)=>{n.depth=n.ag.depth!=null?Math.max(d,Math.round(Number(n.ag.depth)||0)):d;n.children.sort((a,b)=>(_pMs(a.ag.started_at)||a.idx)-(_pMs(b.ag.started_at)||b.idx)||(a.idx-b.idx));n.children.forEach((c)=>setD(c,n.depth+1))};
roots.forEach((r)=>setD(r,0));
let minMs=_pMs(o.sessionStartedAt),maxMs=_pMs(o.sessionLastTs),maxDur=1;
nodes.forEach((n)=>{
const dur=_agDur(n.ag);if(dur>maxDur)maxDur=dur;
const s=_pMs(n.ag.started_at||n.ag.first_ts);let e=_pMs(n.ag.last_ts||n.ag.ended_at);if(isFinite(s)&&(!isFinite(e)||e<s))e=s+dur*1e3;
n.startMs=s;n.endMs=e;if(isFinite(s)&&(!isFinite(minMs)||s<minMs))minMs=s;if(isFinite(e)&&(!isFinite(maxMs)||e>maxMs))maxMs=e;
});
const hasTimeline=isFinite(minMs)&&isFinite(maxMs)&&maxMs>=minMs,flat=[],walk=(n)=>{flat.push(n);n.children.forEach(walk)};roots.forEach(walk);
return{roots,nodes,flat,byId,idMap,hasTimeline,minMs,maxMs,spanMs:hasTimeline?Math.max(1e3,maxMs-minMs):0,maxDur};
}
function filterAgentHierarchy(tree,phaseFilter,searchQuery){
const pf=String(phaseFilter||"").trim().toLowerCase(),q=String(searchQuery||"").trim().toLowerCase(),hasFilter=Boolean(pf||q);
const directMatch=new Set(),keepKeys=new Set();
(tree.nodes||[]).forEach((n)=>{
const ag=n.ag||{},ph=String(ag.phase||"").trim().toLowerCase();
const pOk=!pf||ph===pf;
const qOk=!q||[ag.role,ag.name,ag.type_name,ag.phase,resolveAgentModel(ag),ag.source,ag.workspace,ag.task_title,ag.id].some((v)=>String(v||"").toLowerCase().includes(q));
if(pOk&&qOk){directMatch.add(n.key);for(let cur=n;cur;cur=cur.parent)keepKeys.add(cur.key)}
});
return{hasFilter,directMatch,keepKeys};
}
function renderTimelineBar(ag,spanInfo){
const info=spanInfo||{hasTimeline:false,minMs:NaN,spanMs:0,maxDur:1},err=Number(ag&&(ag.error_steps!=null?ag.error_steps:ag.error_count))||0;
const st=String((ag&&ag.status)||(ag&&ag.clean_termination===false?(err>0?"error":"interrupted"):"done")).toLowerCase(),dur=_agDur(ag||{});
let l=0,w=6;const s=ag&&ag.startMs!=null?ag.startMs:_pMs(ag&&ag.started_at);
if(info.hasTimeline&&isFinite(s)){
let e=ag&&ag.endMs!=null?ag.endMs:_pMs(ag.last_ts||ag.ended_at);if(!isFinite(e)||e<s)e=s+dur*1e3;
l=Math.max(0,Math.min(95,((s-info.minMs)/info.spanMs)*100));w=Math.max(3,Math.min(100-l,((e-s)/info.spanMs)*100));
}else w=dur>0?Math.max(5,Math.min(100,Math.round((dur/(info.maxDur||1))*100))):4;
const wrap=el("div","gantt-mini",null,{title:"Durée : "+fmtDuration(dur)}),tr=el("div","gantt-track"),b=el("div","gantt-bar "+st);
b.style.left=l.toFixed(1)+"%";b.style.width=w.toFixed(1)+"%";tr.appendChild(b);wrap.appendChild(tr);wrap.appendChild(el("div","gantt-time",fmtDuration(dur)));return wrap;
}
function renderAgentTree(agents,opts){
const o=opts||{},tree=buildAgentHierarchy(agents,o),wrap=el("div","tree-wrap");
if(!tree.roots.length){wrap.appendChild(el("div","empty",o.emptyLabel||"Aucun agent détecté."));return wrap}
const flt=filterAgentHierarchy(tree,o.phaseFilter,o.searchQuery);
if(!flt.keepKeys.size){wrap.appendChild(el("div","empty","Aucun agent ne correspond au filtre."));return wrap}
const col=o.collapsedIds||{},isCol=(k)=>(col instanceof Set?col.has(k):Boolean(col[k])),selId=String(o.selectedId||""),selAct=o.selectAction||"select-live-agent",togAct=o.toggleAction||"toggle-live-tree";
const countDesc=(n)=>n.children.reduce((s,c)=>(flt.keepKeys.has(c.key)?s+1+countDesc(c):s),0);
const addN=(n,isRoot)=>{
const ag=n.ag,err=Number(ag.error_count!=null?ag.error_count:(ag.error_steps||0))||0;
const st=String(ag.status||(ag.clean_termination===false?(err>0?"error":"interrupted"):"done")).toLowerCase();
const isSel=selId===n.key||(ag.id&&selId===String(ag.id))||(ag.conversation_id&&selId===String(ag.conversation_id));
const visKids=n.children.filter((c)=>flt.keepKeys.has(c.key)),collapsed=visKids.length>0&&isCol(n.key)&&!flt.hasFilter;
const isDim=flt.hasFilter&&!flt.directMatch.has(n.key),branch=el("div",isRoot?"tree-root":"tree-branch");
const row=el("div","tree-row status-"+st+" depth-"+Math.min(n.depth,4)+(isSel?" selected":"")+(isDim?" dimmed":""),null,{"data-action":selAct,"data-agent-id":n.key,role:"button",tabindex:"0"});
if(typeof o.onSelect==="function")row.addEventListener("click",()=>o.onSelect(ag,n.key));
const ind=el("div","tree-indent");
if(visKids.length){
const tog=el("button","tree-toggle",collapsed?"▸":"▾",{type:"button","data-action":togAct,"data-agent-id":n.key,"aria-expanded":collapsed?"false":"true",title:collapsed?"Déplier les sous-agents":"Replier les sous-agents"});
if(typeof o.onToggle==="function")tog.addEventListener("click",(ev)=>{if(ev&&ev.stopPropagation)ev.stopPropagation();o.onToggle(n.key)});
ind.appendChild(tog);
}
const main=el("div","tree-main"),head=el("div","tree-head"),mod=resolveAgentModel(ag),hidCnt=collapsed?countDesc(n):0;
head.appendChild(el("span","agent-role",String(ag.role||ag.name||ag.id||"Agent")));
if(mod)head.appendChild(el("span","badge badge-model",shortModelName(mod),{title:mod}));
head.appendChild(renderStatusBadge(st));
const srcB=renderSourceBadge(ag.source||(n.depth===0?"root":""));if(srcB)head.appendChild(srcB);
if(ag.phase)head.appendChild(makeBadge(String(ag.phase),""));
head.appendChild(renderWorkspaceKindBadge(ag.workspace_kind||(/-(workshop|studio)$/.test(String(ag.workspace||"").toLowerCase())?"atelier":"code")));
if(hidCnt>0)head.appendChild(el("span","badge tree-count","+"+hidCnt,{title:hidCnt+" sous-agent(s) replié(s)"}));
if(err>0)head.appendChild(makeBadge(err+" err","error"));
main.appendChild(head);
const meta=el("div","tree-meta"),useful=Number(ag.useful_tokens||0)||((Number(ag.input_tokens)||0)+(Number(ag.output_tokens)||0));
if(ag.workspace)meta.appendChild(el("span","mono",String(ag.workspace)));
if(useful>0)meta.appendChild(el("span","mono num",fmtTokens(useful)+" ut."));
const ctx=Number(ag.context_tokens||ag.max_context_tokens||0);if(ctx>0)meta.appendChild(el("span","mono num","Ctx "+fmtTokens(ctx)));
meta.appendChild(el("span","mono num",fmtInt(ag.llm_calls||0)+" LLM · "+fmtInt(resolveAgentToolCalls(ag))+" out."));
if(ag.task_title)meta.appendChild(el("span","preview-text",String(ag.task_title)));
main.appendChild(meta);ind.appendChild(main);row.appendChild(ind);row.appendChild(renderTimelineBar({...ag,startMs:n.startMs,endMs:n.endMs},tree));
branch.appendChild(row);
if(visKids.length&&!collapsed){const kw=el("div","tree-children");visKids.forEach((c)=>kw.appendChild(addN(c,false)));branch.appendChild(kw)}
return branch;
};
tree.roots.filter((r)=>flt.keepKeys.has(r.key)).forEach((r)=>wrap.appendChild(addN(r,true)));
return wrap;
}
"""

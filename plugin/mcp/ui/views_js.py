"""Pure DOM and SVG view renderers for Gravity MCP App (100% stdlib, zero innerHTML)."""

from __future__ import annotations

VIEWS_JS = r"""
const SVG_NS=["http","://www.w3.org/2000/svg"].join("");
function el(tag,cls,text,attrs){
const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined&&text!==null)n.textContent=String(text);
if(attrs&&typeof attrs==="object")for(const[k,v]of Object.entries(attrs))if(v!==undefined&&v!==null)n.setAttribute(k,String(v));
return n;
}
function svgEl(tag,attrs,text){
const n=document.createElementNS(SVG_NS,tag);
if(attrs&&typeof attrs==="object")for(const[k,v]of Object.entries(attrs))if(v!==undefined&&v!==null)n.setAttribute(k,String(v));
if(text!==undefined&&text!==null)n.textContent=String(text);return n;
}
function clearNode(n){while(n.firstChild)n.removeChild(n.firstChild)}
const fmtInt=(n)=>Math.round(Number(n)||0).toLocaleString("fr-FR");
const fmtUsd=(n)=>"$"+(Number(n)||0).toFixed(4);
function fmtBytes(n){if(n===null||n===undefined)return"—";const b=Number(n)||0;return b>=1048576?(b/1048576).toFixed(1)+" Mo":(b>=1024?(b/1024).toFixed(1)+" Ko":b+" o")}
function fmtDate(r){const s=String(r||"");return s?s.slice(0,16).replace("T"," "):"—"}
const makeBadge=(l,t)=>el("span","badge"+(t?" "+t:""),l);
function makeKpiCard(l,v,s,t){const c=el("div","kpi-card"+(t?" "+t:""));c.appendChild(el("div","kpi-lbl",l));c.appendChild(el("div","kpi-val num",v));if(s)c.appendChild(el("div","kpi-sub mono",s));return c}
function tabForModule(m){const ts=(state.overview&&state.overview.tabs)||[];return m==="core"?(ts.find((t)=>t.id==="overview")||null):(ts.find((t)=>t.module_id===m||t.id===m)||null)}
function _makeTable(headers,rows,numCols){
const w=el("div","table-wrap"),tbl=el("table"),th=el("thead"),htr=el("tr"),ns=new Set(numCols||[]);
headers.forEach((l,i)=>htr.appendChild(el("th",ns.has(i)?"num":null,l)));th.appendChild(htr);tbl.appendChild(th);
const tb=el("tbody");rows.forEach((r)=>tb.appendChild(r));tbl.appendChild(tb);w.appendChild(tbl);return w;
}
function _statusTone(r){
const c=String(r||"").trim().toLowerCase();
if(c==="done"||c==="completed"||c==="ready"||c==="validated"||c==="ok"||c==="pass")return"ok";
if(c==="in_progress"||c==="running"||c==="active")return"info";
if(c==="blocked"||c==="error"||c==="failed"||c==="fail")return"error";
if(c==="draft"||c==="pending"||c==="backlog"||c==="warn")return"warn";return"";
}
function renderOverviewView(container){
const ov=state.overview;if(!ov){container.appendChild(el("div","empty","Chargement de la vue Système..."));return}
const doc=ov.doctor||{},st=String(doc.status||"unknown"),stT=st==="ok"?"ok":(st==="error"?"error":"warn");
const sp=el("section","panel"),hd=el("div","panel-head");
hd.appendChild(el("div","panel-title","Système — Diagnostic Core & Environnement"));hd.appendChild(makeBadge("doctor: "+st.toUpperCase(),stT));sp.appendChild(hd);
const kp=el("div","kpi-strip");
kp.appendChild(makeKpiCard("Modules",String(doc.module_count||0),(doc.valid_count||0)+" valide(s)"));
kp.appendChild(makeKpiCard("Registre",doc.initialized?"Initialisé":"Découverte RO",ov.registry_source||"—"));
kp.appendChild(makeKpiCard("Anomalies",String((doc.invalid_count||0)+(doc.duplicate_ids||[]).length),"invalides / doublons"));
kp.appendChild(makeKpiCard("Dossiers legacy",String(doc.legacy_count||0),"lecture seule"));sp.appendChild(kp);
const kv=el("div","kv-grid");[["$GRAVITY_HOME",ov.gravity_home||"—"],["Registre",ov.registry_path||"—"]].forEach(([k,v])=>{kv.appendChild(el("div","kv-k",k));kv.appendChild(el("div","mono",v))});
sp.appendChild(kv);(ov.warnings||doc.warnings||[]).forEach((w)=>sp.appendChild(el("div","notice warn",w)));container.appendChild(sp);
const mp=el("section","panel"),mh=el("div","panel-head"),mods=ov.modules||[];
mh.appendChild(el("div","panel-title","Modules Gravity découverts"));mh.appendChild(el("span","mono",mods.length+" module(s)"));mp.appendChild(mh);
if(!mods.length)mp.appendChild(el("div","empty","Aucun module Gravity détecté."));
else{
const gr=el("div","grid-cards");
mods.forEach((m)=>{
const mid=String(m.id||""),tt=tabForModule(mid),cd=el("button","mod-card",null,{type:"button","data-action":"select-tab","data-tab":tt?tt.id:"overview"}),tp=el("div","mod-top");
tp.appendChild(el("span","mod-name",m.display_name||m.plugin_name||mid));tp.appendChild(makeBadge(m.valid?"OK":"INVALID",m.valid?"ok":"error"));cd.appendChild(tp);
const mt=el("div","pill-list");mt.appendChild(el("span","pill","id="+mid));if(m.version)mt.appendChild(el("span","pill","v"+m.version));
mt.appendChild(el("span","pill","ui:"+((m.ui&&m.ui.mode)?m.ui.mode:"none")));mt.appendChild(el("span","pill",m.home_exists?"home:ok":"home:absent"));cd.appendChild(mt);
if(m.resolved_home)cd.appendChild(el("div","mono",m.resolved_home));if(Array.isArray(m.commands)&&m.commands.length)cd.appendChild(el("div","mono",m.commands.join(" · ")));
gr.appendChild(cd);
});mp.appendChild(gr);
}
container.appendChild(mp);
const leg=ov.legacy_homes||[];
if(leg.length){
const lp=el("section","panel"),lh=el("div","panel-head");
lh.appendChild(el("div","panel-title","Anciens dossiers legacy (lecture seule stricte)"));lh.appendChild(makeBadge(leg.length+" détecté(s)","warn"));lp.appendChild(lh);
lp.appendChild(el("div","notice","Aucune modification automatique. Utilisez /gravity doctor (--migration-plan)."));
lp.appendChild(_makeTable(["Nom","Module cible","Chemin"],leg.map((l)=>{const tr=el("tr");tr.appendChild(el("td",null,l.name||"—"));tr.appendChild(el("td","mono",l.target_module||"—"));tr.appendChild(el("td","mono",l.path||"—"));return tr})));
container.appendChild(lp);
}
}
function renderMetricsView(c){if(typeof renderMetricsUnifiedView==="function")renderMetricsUnifiedView(c);else c.appendChild(el("div","empty","Vue Historique indisponible."))}
function renderModuleView(container,tab){
const mid=(tab&&tab.module_id)||state.activeTab,p=el("section","panel"),h=el("div","panel-head"),info=state.moduleCache[mid];
h.appendChild(el("div","panel-title","Module OCP : "+((tab&&tab.display_name)||mid)));
if(info&&info.found)h.appendChild(makeBadge(info.valid?"Contrat valide":"Contrat invalide",info.valid?"ok":"error"));p.appendChild(h);
if(state.moduleLoading[mid]){p.appendChild(el("div","empty","Chargement du contrat module..."));container.appendChild(p);return}
if(!info){p.appendChild(el("div","empty","Sélectionnez ou rafraîchissez cet onglet pour inspecter le module."));container.appendChild(p);return}
if(!info.found){p.appendChild(el("div","notice warn",info.error||"Module introuvable."));container.appendChild(p);return}
const st=info.storage||{},kv=el("div","kv-grid");
[["Plugin",(info.plugin_name||"—")+" v"+(info.version||"?")],["Rôle",info.role||"—"],["Commandes",(info.commands||[]).join(", ")||"—"],["Capacités",(info.capabilities||[]).join(", ")||"—"],["UI",JSON.stringify(info.ui||{})],["Stockage subdir",(st.subdir||"—")+(st.env_override?" ("+st.env_override+")":"")],["Chemin résolu",(st.resolved_home||"—")+(st.exists?" [présent]":" [absent]")]].forEach(([k,v])=>{kv.appendChild(el("div","kv-k",k));kv.appendChild(el("div","mono",v))});
p.appendChild(kv);(info.errors||[]).forEach((e)=>p.appendChild(el("div","notice warn",e)));p.appendChild(el("div","panel-title","Entrées superficielles (top_entries)"));
const ents=info.top_entries||[];
if(!ents.length)p.appendChild(el("div","empty","Aucune entrée dans le répertoire du module."));
else{
if(info.top_entries_truncated)p.appendChild(el("div","notice","Liste bornée aux 25 premières entrées."));
p.appendChild(_makeTable(["Nom","Type","Taille"],ents.map((e)=>{const tr=el("tr");tr.appendChild(el("td","mono",e.name||"—"));tr.appendChild(el("td",null,e.kind||"—"));tr.appendChild(el("td","num mono",fmtBytes(e.size_bytes)));return tr}),[2]));
}
container.appendChild(p);
}
function _renderProjectCards(sp,projects){
if(!projects.length){sp.appendChild(el("div","empty","Aucun projet suivi dans projects.json."));return}
const gr=el("div","proj-grid");
projects.forEach((p)=>{
const cd=el("article","agent-card"),hd=el("div","agent-head"),tw=el("div",null);
tw.appendChild(el("div","agent-role",p.name||p.id||"Projet"));tw.appendChild(el("div","mono",(p.id||"—")+(p.path?" · "+p.path:"")));hd.appendChild(tw);
const br=el("div","actions-row");if(p.role)br.appendChild(makeBadge(p.role,"info"));if(p.card_bytes)br.appendChild(makeBadge(fmtBytes(p.card_bytes),p.over_budget?"warn":"ok"));
hd.appendChild(br);cd.appendChild(hd);
const pl=el("div","pill-list");pl.appendChild(el("span","pill","main: "+(p.main_branch||"main")));pl.appendChild(el("span","pill","dev: "+(p.default_dev_branch||p.dev_branch||"dev")));
if(p.release_main)pl.appendChild(el("span","pill","rel: "+p.release_main));if(p.installed_version)pl.appendChild(el("span","pill","inst: "+p.installed_version));
if(p.dev_status)pl.appendChild(makeBadge("dev: "+p.dev_status,/ahead|wip/i.test(p.dev_status)?"info":""));
if(p.wip_status){const cw=/^(aucun|clean|propre|0|none|-|—)$/i.test(String(p.wip_status).trim());pl.appendChild(makeBadge("WIP: "+p.wip_status,cw?"ok":"warn"))}
cd.appendChild(pl);
const st=el("div","agent-stats");st.appendChild(el("span","num",fmtInt(p.specs_count||0)+" spec(s)"));st.appendChild(el("span","num",fmtInt(p.tasks_count||0)+" task(s)"));st.appendChild(el("span","num",fmtInt(p.audits_count||0)+" audit(s)"));cd.appendChild(st);
const ac=el("div","actions-row");
if(p.card_uri)ac.appendChild(el("button","btn btn-sm","Ouvrir fiche",{type:"button","data-action":"open-file","data-uri":p.card_uri}));
if(p.id)ac.appendChild(el("button","btn btn-sm btn-primary","Voir sessions",{type:"button","data-action":"nav-history","data-project":String(p.id)}));
cd.appendChild(ac);gr.appendChild(cd);
});sp.appendChild(gr);
}
function _renderWavesAndTasks(sp,tasks,wsSum){
if(!tasks.length){sp.appendChild(el("div","empty","Aucune task active dans tasks/."));return}
const gs=new Map();tasks.forEach((t)=>{const k=(typeof t.wave==="number"&&isFinite(t.wave))?t.wave:null;if(!gs.has(k))gs.set(k,[]);gs.get(k).push(t)});
const ks=Array.from(gs.keys()).sort((a,b)=>a===null?1:(b===null?-1:a-b)),wb=new Map();
((wsSum&&wsSum.waves)||[]).forEach((w)=>wb.set(w.wave==null?null:w.wave,w));
ks.forEach((wk)=>{
const wt=gs.get(wk)||[],wm=wb.get(wk)||{},bx=el("div","wave-group"),wh=el("div","panel-head"),bg=el("div","actions-row");
wh.appendChild(el("div","panel-title",wk===null?"Tasks hors vague":("Vague "+wk)));bg.appendChild(makeBadge(wt.length+" task(s)","info"));
Object.entries(wm.status_counts||{}).forEach(([s,c])=>bg.appendChild(makeBadge(s+": "+c,_statusTone(s))));wh.appendChild(bg);bx.appendChild(wh);
const gr=el("div","proj-grid");
wt.forEach((t)=>{
const cd=el("article","agent-card"),ch=el("div","agent-head");
ch.appendChild(el("div","agent-role",t.title||t.filename||"—"));ch.appendChild(makeBadge(t.status||t.status_code||"unknown",_statusTone(t.status_code||t.status)));cd.appendChild(ch);
const pl=el("div","pill-list");if(t.target_project)pl.appendChild(makeBadge(t.target_project,"code"));
if(t.workflow_profile)pl.appendChild(el("span","pill","profil: "+t.workflow_profile));if(t.expected_branch)pl.appendChild(el("span","pill","branche: "+t.expected_branch));
if(t.date)pl.appendChild(el("span","pill",t.date));if(Array.isArray(t.dependencies)&&t.dependencies.length)pl.appendChild(el("span","pill","déps: "+t.dependencies.join(", ")));
if(t.spec_source)pl.appendChild(el("span","pill","spec: "+t.spec_source));cd.appendChild(pl);
if(t.uri){const ac=el("div","actions-row");ac.appendChild(el("button","btn btn-sm","Ouvrir .md",{type:"button","data-action":"open-file","data-uri":t.uri}));cd.appendChild(ac)}
gr.appendChild(cd);
});bx.appendChild(gr);sp.appendChild(bx);
});
}
function renderArchitectView(container){
const arch=state.architect,bar=el("section","panel"),hd=el("div","panel-head"),ct=el("div","actions-row"),ats=(arch&&Array.isArray(arch.ateliers))?arch.ateliers:[];
hd.appendChild(el("div","panel-title","Projets & Atelier Architect (lecture seule)"));
if(ats.length){
const as=el("select","select",null,{id:"g-arch-ws","aria-label":"Atelier Architect"}),ar=(arch&&arch.atelier_root)||state.selectedAtelier||"";
ats.forEach((a)=>{const v=String(a.workspace_path||"");if(!v)return;const o=el("option",null,a.workspace_name?(a.workspace_name+" — "+v):v,{value:v});if(v===ar||v===state.selectedAtelier)o.selected=true;as.appendChild(o)});
if(!arch.available&&state.selectedAtelier&&!ats.some((a)=>String(a.workspace_path||"")===state.selectedAtelier)){const io=el("option",null,state.selectedAtelier+" (invalide)",{value:state.selectedAtelier});io.selected=true;as.appendChild(io)}
ct.appendChild(as);
}
if(arch&&arch.discovery_source)ct.appendChild(makeBadge("source: "+arch.discovery_source,"info"));
if(arch&&arch.ecosystem&&arch.ecosystem.uri)ct.appendChild(el("button","btn btn-sm","Ouvrir ECOSYSTEM.md",{type:"button","data-action":"open-file","data-uri":arch.ecosystem.uri}));
if(arch&&arch.delta&&arch.delta.uri)ct.appendChild(el("button","btn btn-sm","Ouvrir delta.md",{type:"button","data-action":"open-file","data-uri":arch.delta.uri}));
ct.appendChild(el("button","btn btn-sm","Historique",{type:"button","data-action":"nav-history"}));hd.appendChild(ct);bar.appendChild(hd);
if(arch&&arch.atelier_root)bar.appendChild(el("div","mono","Atelier : "+arch.atelier_root));container.appendChild(bar);
if(!arch){container.appendChild(el("div","empty","Chargement de l'état Projets..."));return}
(arch.warnings||[]).forEach((w)=>container.appendChild(el("div","notice warn",w)));
if(!arch.available){const em=el("section","panel");em.appendChild(el("div","empty","Aucun atelier Gravity Architect (ECOSYSTEM.md / projects.json) détecté."));em.appendChild(el("div","notice info","Enregistrez un atelier via /gravity-architect init ou /gravity-architect sync."));container.appendChild(em);return}
const eco=arch.ecosystem||{},dlt=arch.delta||{},projs=arch.projects||[],specs=arch.specs||[],tasks=arch.tasks||[],auds=arch.audits||[],ws=arch.waves_summary||{};
const alts=(eco.alerts||[]).concat(dlt.hygiene_alerts||[]),kp=el("section","panel"),ks=el("div","kpi-strip");
ks.appendChild(makeKpiCard("ECOSYSTEM.md",eco.exists?fmtBytes(eco.size_bytes):"Absent",eco.budget_bytes?("budget "+fmtBytes(eco.budget_bytes)+(eco.over_budget?" [DÉPASSÉ]":"")):fmtDate(eco.updated_at),eco.over_budget?"warn":""));
ks.appendChild(makeKpiCard("delta.md",dlt.editorial_status||"Absent",dlt.date?fmtDate(dlt.date):"aucune synchro"));
ks.appendChild(makeKpiCard("Projets & Veilles",fmtInt(projs.length)+" projet(s)",fmtInt(arch.watches_count||0)+" veille(s)"));
ks.appendChild(makeKpiCard("Vagues & Tasks",fmtInt(ws.waves_count||0)+" vague(s)",fmtInt(tasks.length)+" task(s) · "+fmtInt(specs.length)+" spec(s)"));
ks.appendChild(makeKpiCard("Archivés",fmtInt((arch.archived_specs_count||0)+(arch.archived_tasks_count||0)),fmtInt(arch.archived_specs_count||0)+" specs · "+fmtInt(arch.archived_tasks_count||0)+" tasks"));
ks.appendChild(makeKpiCard("Audits Code",fmtInt(auds.length),"audits/code/ uniquement"));kp.appendChild(ks);
alts.slice(0,6).forEach((a)=>kp.appendChild(el("div","notice warn",a)));container.appendChild(kp);
if(arch.truncated)container.appendChild(el("div","notice warn","Réponse bornée sous le plafond de 450 Ko."));
const sub=state.architectSub==="artifacts"?"waves":(state.architectSub||"projects"),sp=el("section","panel"),sh=el("div","panel-head"),st=el("div","subtabs");
[["projects","Projets ("+projs.length+")"],["waves","Vagues & Tasks ("+tasks.length+")"],["specs","Spécifications ("+specs.length+")"],["audits","Audits Code ("+auds.length+")"]].forEach(([id,l])=>st.appendChild(el("button","btn"+(sub===id?" active":""),l,{type:"button","data-action":"architect-sub","data-sub":id})));
sh.appendChild(st);sp.appendChild(sh);
if(sub==="waves")_renderWavesAndTasks(sp,tasks,ws);
else if(sub==="specs"){
if(!specs.length)sp.appendChild(el("div","empty","Aucune spécification active dans specs/."));
else sp.appendChild(_makeTable(["Titre","Cible","Statut","Date","Taille","Fichier"],specs.map((s)=>{const tr=el("tr");tr.appendChild(el("td",null,s.title||s.filename||"—"));tr.appendChild(el("td","mono",s.target_project||"—"));const sc=el("td");sc.appendChild(makeBadge(s.status||s.status_code||"—",_statusTone(s.status_code||s.status)));tr.appendChild(sc);tr.appendChild(el("td","mono",s.date||"—"));tr.appendChild(el("td","num mono",fmtBytes(s.size_bytes)));const fc=el("td");if(s.uri)fc.appendChild(el("button","btn btn-sm","Ouvrir .md",{type:"button","data-action":"open-file","data-uri":s.uri}));tr.appendChild(fc);return tr}),[4]));
}else if(sub==="audits"){
sp.appendChild(el("div","notice info","Périmètre strict audits/code/ uniquement (audits/agents/ exclu)."));
if(arch.index_audit){const ic=el("div","notice"),rw=el("div","panel-head");rw.appendChild(el("span",null,"Index Audits Code : "+(arch.index_audit.title||arch.index_audit.rel_path)));if(arch.index_audit.uri)rw.appendChild(el("button","btn btn-sm","Ouvrir index .md",{type:"button","data-action":"open-file","data-uri":arch.index_audit.uri}));ic.appendChild(rw);sp.appendChild(ic)}
if(!auds.length)sp.appendChild(el("div","empty","Aucun audit code découvert dans audits/code/."));
else sp.appendChild(_makeTable(["Titre","Cible","Verdict","Date","Taille","Fichier"],auds.map((a)=>{const tr=el("tr");tr.appendChild(el("td",null,a.title||a.rel_path||"—"));tr.appendChild(el("td","mono",a.target||"—"));const vc=el("td");vc.appendChild(makeBadge(a.verdict||"—",a.verdict_tone||""));tr.appendChild(vc);tr.appendChild(el("td","mono",a.date||"—"));tr.appendChild(el("td","num mono",fmtBytes(a.size_bytes)));const ac=el("td");if(a.uri)ac.appendChild(el("button","btn btn-sm","Ouvrir .md",{type:"button","data-action":"open-file","data-uri":a.uri}));tr.appendChild(ac);return tr}),[4]));
}else _renderProjectCards(sp,projs);
container.appendChild(sp);
}
"""

"""Pure DOM renderer for the Gravity 'Session' Live Cockpit (100% stdlib, zero innerHTML)."""

from __future__ import annotations

LIVE_VIEWS_JS = r"""
const DEFAULT_PHASES=[["conception","Conception"],["planification","Planification"],["production","Production"],["validation","Validation"]].map(([id,label])=>({id,label,status:"pending",tokens:0,useful_tokens:0,agents:0,duration_s:0}));
function _parseWorkflowProgress(raw,detail){
if(detail&&typeof detail==="object"&&typeof detail.total==="number"){const d=Math.max(0,Number(detail.done)||0),t=Math.max(0,Number(detail.total)||0);return{done:d,total:t,pct:t>0?Math.min(100,Math.round((d/t)*100)):0}}
const m=String(raw||"").match(/(\d+)\s*\/\s*(\d+)/);if(!m)return{done:0,total:0,pct:0};
const d=Math.max(0,Number(m[1])||0),t=Math.max(0,Number(m[2])||0);return{done:d,total:t,pct:t>0?Math.min(100,Math.round((d/t)*100)):0};
}
function _aggregateLiveWorkspaces(agents){
const map=new Map();
(Array.isArray(agents)?agents:[]).forEach((ag)=>{
if(!ag)return;const ws=String(ag.workspace||"workspace"),kind=String(ag.workspace_kind||"code").toLowerCase(),k=ws+"::"+kind;
const cur=map.get(k)||{workspace:ws,kind,useful_tokens:0,cache_read_tokens:0,agents_count:0};
cur.useful_tokens+=Number(ag.useful_tokens)||0;cur.cache_read_tokens+=Number(ag.cache_read_tokens)||0;cur.agents_count+=1;map.set(k,cur);
});
return Array.from(map.values()).sort((a,b)=>(b.useful_tokens-a.useful_tokens)||a.workspace.localeCompare(b.workspace));
}
function _renderPhaseStepper(rawPhases,curPhase,selPhase){
const list=(Array.isArray(rawPhases)&&rawPhases.length)?rawPhases:DEFAULT_PHASES;
const p=el("section","panel"),hd=el("div","panel-head"),lt=el("div","actions-row");
lt.appendChild(el("div","panel-title","Cycle 4 Phases"));
if(selPhase)lt.appendChild(el("button","btn btn-sm active","Filtre : "+selPhase+" ×",{type:"button","data-action":"filter-live-phase","data-phase":""}));
hd.appendChild(lt);hd.appendChild(el("span","kpi-sub","Cliquer pour filtrer l'arbre (ancêtres conservés)"));p.appendChild(hd);
const grid=el("div","phase-stepper"),strip=el("div","phase-strip"),leg=el("div","stack-legend"),totTok=list.reduce((s,x)=>s+(Number(x.tokens)||0),0);
list.forEach((ph,i)=>{
const pid=String(ph.id||""),st=String(ph.status||(pid===curPhase?"active":"pending")).toLowerCase(),isSel=selPhase&&selPhase===pid;
const card=el("button","phase-card "+st+(isSel?" selected":""),null,{type:"button","data-action":"filter-live-phase","data-phase":pid,"aria-pressed":isSel?"true":"false"});
const top=el("div","phase-top"),ico=st==="done"?"✓":(st==="active"?"●":(st==="error"?"!":"○"));
top.appendChild(el("span","phase-lbl",(i+1)+". "+String(ph.label||pid)));top.appendChild(el("span","phase-ico mono "+st,ico));card.appendChild(top);
const nums=el("div","phase-nums phase-num");nums.appendChild(el("strong",null,fmtTokens(ph.tokens||0)));nums.appendChild(el("span","mono",fmtDuration(ph.duration_s||0)));card.appendChild(nums);
card.appendChild(el("div","kpi-sub phase-num",fmtTokens(ph.useful_tokens||0)+" ut. · "+fmtInt(ph.agents||0)+" ag."));grid.appendChild(card);
if(totTok>0){
const pct=Math.max(3,Math.round(((Number(ph.tokens)||0)/totTok)*100)),col="var(--g-c"+((i%4)+1)+")",seg=el("div","phase-seg",null,{title:String(ph.label||pid)+" : "+fmtTokens(ph.tokens||0)+" ("+pct+"%)"});
seg.style.width=pct+"%";seg.style.backgroundColor=col;strip.appendChild(seg);
const li=el("span","legend-item"),dot=el("span","legend-dot");dot.style.backgroundColor=col;li.appendChild(dot);li.appendChild(el("span","phase-num",String(ph.label||pid)+" "+pct+"%"));leg.appendChild(li);
}
});
p.appendChild(grid);if(totTok>0){p.appendChild(strip);p.appendChild(leg)}return p;
}
function _renderLiveToolbar(live,ui,h){
const p=el("section","panel session-bar"),row=el("div","panel-head"),left=el("div","actions-row");
left.appendChild(el("span",!live||!live.available?"live-dot idle":(ui.paused?"live-dot paused":"live-dot")));
left.appendChild(el("span","panel-title","Session"));
const sessions=(live&&Array.isArray(live.sessions))?live.sessions:[],selCid=(live&&live.selected_session&&live.selected_session.conversation_id)||"";
const sel=el("select","select",null,{id:"g-live-session","aria-label":"Session active"});
if(!sessions.length)sel.appendChild(el("option",null,"Aucune session active",{value:""}));
else sessions.forEach((s)=>{
const cid=String(s.conversation_id||""),lbl=String(s.label||("session-"+cid.slice(0,8)))+(s.project?" · "+s.project:"")+(s.captured?" [suivie]":"")+(s.archived?" [archivée]":"");
const opt=el("option",null,lbl,{value:cid});if(cid===selCid||cid===ui.selectedSessionId)opt.selected=true;sel.appendChild(opt);
});
if(typeof h.onSelectSession==="function")sel.addEventListener("change",()=>h.onSelectSession(sel.value||""));
left.appendChild(sel);row.appendChild(left);
const right=el("div","live-controls"),refTs=(live&&live.selected_session&&(live.selected_session.session_last_ts||live.selected_session.last_ts))||ui.lastUpdatedAt||"";
const sw=el("span","search-wrap"),qInp=el("input","input",null,{id:"g-live-q",type:"search",placeholder:"Filtrer agent, modèle…",value:ui.searchQuery||"","data-global-search":"1","aria-label":"Filtrer les agents"});
qInp.value=ui.searchQuery||"";sw.appendChild(qInp);sw.appendChild(el("span","kbd-hint","/"));right.appendChild(sw);
right.appendChild(el("span","badge "+(ui.paused?"warn":"ok"),ui.paused?"En pause":("Fraîcheur : "+fmtRelativeTime(refTs)),{"data-freshness":"1","data-ts":String(refTs),"data-paused":ui.paused?"1":"0"}));
const pBtn=el("button","btn btn-sm"+(ui.paused?" active":""),ui.paused?"Reprendre":"Pause",{type:"button","data-action":"toggle-live-pause","aria-pressed":ui.paused?"true":"false"});
if(typeof h.onTogglePause==="function")pBtn.addEventListener("click",()=>h.onTogglePause());
right.appendChild(pBtn);
const projBtn=el("button","btn btn-sm","Projets",{type:"button","data-action":"nav-projects"});
if(typeof h.onOpenProjects==="function")projBtn.addEventListener("click",()=>h.onOpenProjects());
right.appendChild(projBtn);row.appendChild(right);p.appendChild(row);return p;
}
function _renderLiveWorkflowBlock(wf){
if(!wf||!wf.available)return null;const stLow=String(wf.stage||"").trim().toLowerCase();
if(wf.is_active!==undefined?!wf.is_active:(!stLow||stLow==="idle"))return null;
const p=el("section","panel"),head=el("div","panel-head"),bg=el("div","actions-row");
head.appendChild(el("div","panel-title","Progression du workflow"));
bg.appendChild(makeBadge("Étape : "+String(wf.stage||"idle"),"info"));
bg.appendChild(makeBadge(String(wf.preset_profile||"standard")+" · "+String(wf.mode||"evo"),""));
const gOn=String(wf.guard_status||"ON").toUpperCase();bg.appendChild(makeBadge("Garde : "+gOn,gOn==="ON"?"ok":"warn"));
head.appendChild(bg);p.appendChild(head);
const pd=(wf.progress_detail&&typeof wf.progress_detail==="object")?wf.progress_detail:null;
const prog=_parseWorkflowProgress(wf.progress,pd),bw=el("div","wf-bar"),bh=el("div","ctx-gauge-head");
bh.appendChild(el("span",null,"Avancement : "+String(wf.progress||(pd&&pd.label)||"0/0")));bh.appendChild(el("span","mono",fmtPct(prog.pct)));bw.appendChild(bh);
const tr=el("div","wf-progress-track",null,{role:"progressbar","aria-valuenow":String(prog.done),"aria-valuemin":"0","aria-valuemax":String(prog.total)}),fl=el("div","wf-progress-fill");
fl.style.width=prog.pct+"%";tr.appendChild(fl);bw.appendChild(tr);p.appendChild(bw);
const rawW=(wf.waves!=null?wf.waves:(pd&&pd.waves))||[],rawT=(wf.tasks!=null?wf.tasks:(pd&&pd.tasks))||[];
const waves=Array.isArray(rawW)?rawW:(rawW&&typeof rawW==="object"?Object.values(rawW):[]);
const tasks=Array.isArray(rawT)?rawT:(rawT&&typeof rawT==="object"?Object.values(rawT):[]);
if(waves.length||tasks.length){
const wp=el("div","pill-list"),doneRe=/^(done|completed|complete|passed|ok|closed|finished)$/i;
waves.slice(0,6).forEach((w,i)=>{
if(!w||typeof w!=="object"){wp.appendChild(makeBadge("Vague "+(i+1)+" : "+String(w||""),""));return}
const nm=String(w.name||w.id||w.wave||("V"+(i+1))),st=String(w.status||"").toLowerCase(),ratio=(typeof w.done==="number"&&typeof w.total==="number")?(" "+w.done+"/"+w.total):"";
wp.appendChild(makeBadge(nm+ratio+(st&&!ratio?" : "+st:""),(w.done===true||doneRe.test(st))?"ok":((st==="running"||st==="active"||st==="in_progress")?"info":((st==="error"||st==="failed")?"error":""))));
});
if(tasks.length){const td=tasks.filter((t)=>t===true||(typeof t==="string"&&doneRe.test(t.trim()))||(t&&typeof t==="object"&&(t.done===true||doneRe.test(String(t.status||"").trim())))).length;wp.appendChild(makeBadge(td+"/"+tasks.length+" tâche(s)",td===tasks.length?"ok":"info"))}
p.appendChild(wp);
}
const nodes=wf.nodes||{},keys=Object.keys(nodes);
if(keys.length){
const pills=el("div","pill-list");
keys.forEach((r)=>{const st=String(nodes[r]||"idle").toLowerCase();pills.appendChild(makeBadge(r+" : "+(nodes[r]||"idle"),(st==="running"||st==="active")?"ok":((st==="error"||st==="failed")?"error":(st==="done"?"info":""))))});
p.appendChild(pills);
}
if(wf.suggested_profile&&wf.suggested_profile!==wf.preset_profile)p.appendChild(el("div","notice info","Profil suggéré : "+wf.suggested_profile));
return p;
}
function _renderEventFeed(events,emptyMsg){
const list=Array.isArray(events)?events:[];if(!list.length)return el("div","empty",emptyMsg||"Aucun événement récent.");
const w=el("div","inspector-events");
list.forEach((ev)=>{
const r=el("div","event-row"),k=String(ev.kind||"tool");
r.appendChild(el("span","mono",fmtDate(ev.ts)));
r.appendChild(makeBadge(k==="board"?"Board":(k==="error"?"Erreur":"Outil"),k==="board"?"atelier":(k==="error"?"error":"info")));
r.appendChild(el("span","pill",String(ev.agent_id||"agent")));r.appendChild(el("strong",null,String(ev.name||"")));
if(ev.detail)r.appendChild(el("span","preview-text",String(ev.detail)));w.appendChild(r);
});
return w;
}
function _renderLiveInspector(agents,ag,allEvents,idMap,h){
const pane=el("aside","inspector-pane",null,{id:"g-live-inspector"}),evList=Array.isArray(allEvents)?allEvents:[];
if(!ag){
const head=el("div","panel-head");head.appendChild(el("div","panel-title","Flux & Répartition session"));head.appendChild(makeBadge(evList.length+" év.","info"));pane.appendChild(head);
pane.appendChild(renderWorkspaceBreakdown(_aggregateLiveWorkspaces(agents)));
pane.appendChild(el("div","panel-title","Activité récente ("+evList.length+")"));
pane.appendChild(_renderEventFeed(evList,"Aucun appel d'outil ni message de board récent."));return pane;
}
const head=el("div","panel-head"),tw=el("div","actions-row");
tw.appendChild(el("div","panel-title",String(ag.role||ag.id||"Agent")));tw.appendChild(renderStatusBadge(ag.status||"done"));
const srcB=renderSourceBadge(ag.source||(Number(ag.depth)===0?"root":""));if(srcB)tw.appendChild(srcB);
tw.appendChild(renderWorkspaceKindBadge(ag.workspace_kind));head.appendChild(tw);
const gBtn=el("button","btn btn-sm","Flux global",{type:"button","data-action":"live-clear-agent"});
if(typeof h.onClearAgent==="function")gBtn.addEventListener("click",()=>h.onClearAgent());
head.appendChild(gBtn);pane.appendChild(head);
const fil=renderFiliationLabel(ag,idMap);if(fil)pane.appendChild(fil);
if(ag.task_title)pane.appendChild(el("div","agent-task",String(ag.task_title)));
if(ag.last_tool)pane.appendChild(el("div","mono","Dernier outil : "+String(ag.last_tool)));
pane.appendChild(renderContextGauge(ag.context_tokens||0,ag.max_context_tokens||0,{label:"Contexte"}));
const err=Number(ag.error_count!=null?ag.error_count:(ag.error_steps||0))||0,kv=el("div","kv-grid");
[["Modèle",resolveAgentModel(ag)||"inconnu"],["Phase",String(ag.phase||"—")],["Dépôt",String(ag.workspace||"workspace")],["LLM / Outils",fmtInt(ag.llm_calls||0)+" / "+fmtInt(resolveAgentToolCalls(ag))],["Tokens utiles",fmtTokens(ag.useful_tokens||0)+" · Cache "+fmtPct(ag.cache_hit_pct||0)],["Durée / Erreurs",fmtDuration(ag.duration_s||0)+" · "+fmtInt(err)+" erreur(s)"]].forEach(([k,v])=>{kv.appendChild(el("div","kv-k",k));kv.appendChild(el("div","mono",v))});
pane.appendChild(kv);
const agIds=new Set([ag.id,ag.conversation_id].filter(Boolean).map(String)),filtered=evList.filter((ev)=>ev&&agIds.has(String(ev.agent_id||""))),evHead=el("div","panel-head");
evHead.appendChild(el("div","panel-title","Événements de l'agent ("+filtered.length+")"));
const evErr=filtered.filter((e)=>e.kind==="error").length;if(evErr>0)evHead.appendChild(makeBadge(evErr+" erreur(s)","error"));
pane.appendChild(evHead);pane.appendChild(_renderEventFeed(filtered,"Aucun événement récent pour cet agent."));return pane;
}
function renderLiveView(container,liveArg,uiArg,handlersArg){
const live=liveArg!==undefined?liveArg:(typeof state!=="undefined"?state.live:null),rawUi=uiArg||(typeof state!=="undefined"?(state.liveUi||{}):{}),h=handlersArg||{};
const phaseFilter=rawUi.phaseFilter!=null?rawUi.phaseFilter:(typeof state!=="undefined"?(state.livePhaseFilter||""):"");
const searchQuery=rawUi.searchQuery!=null?rawUi.searchQuery:(typeof state!=="undefined"?(state.liveSearchQ||""):"");
const ui=Object.assign({},rawUi,{phaseFilter,searchQuery});
container.appendChild(_renderLiveToolbar(live,ui,h));
if(!live){container.appendChild(el("div","empty","Chargement de la session en direct..."));return}
const wfBlock=_renderLiveWorkflowBlock(live.workflow);
if(!live.available||!live.selected_session){
if(wfBlock)container.appendChild(wfBlock);
const ep=el("section","panel");ep.appendChild(el("div","empty","Aucune session active détectée dans le dossier brain/."));
ep.appendChild(el("div","kpi-sub","Les sessions archivées sont consultables dans l'onglet Historique."));container.appendChild(ep);return;
}
const sel=live.selected_session,sum=live.summary||{},agents=Array.isArray(live.agents)?live.agents:[];
const hp=el("section","panel session-bar"),sHead=el("div","panel-head"),sTitle=el("div","actions-row");
sTitle.appendChild(el("span","panel-title",String(sel.label||sel.swarm_title||sel.goal_title||"Session active")));
sTitle.appendChild(renderWorkspaceKindBadge(sel.workspace_kind));
if(sel.project)sTitle.appendChild(el("button","btn btn-sm",String(sel.project),{type:"button","data-action":"nav-history","data-project":String(sel.project)}));
sTitle.appendChild(makeBadge(sel.captured?("Session unifiée · #"+String(sel.conversation_id||"").slice(0,8)):"Non enregistrée",sel.captured?"ok":"warn"));
if(sel.captured)sTitle.appendChild(makeBadge("Auto-clôture active","info"));
sHead.appendChild(sTitle);
const actName=sel.captured?"update":"record",actBtn=el("button","btn btn-sm btn-primary",ui.actionInFlight?"En cours...":(sel.captured?"Mettre à jour":"Enregistrer"),{type:"button","data-action":"live-metrics-action","data-metrics-action":actName,"data-cid":String(sel.conversation_id||"")});
if(ui.actionInFlight)actBtn.disabled=true;
if(typeof h.onCaptureAction==="function")actBtn.addEventListener("click",()=>h.onCaptureAction(actName,String(sel.conversation_id||"")));
sHead.appendChild(actBtn);hp.appendChild(sHead);
const uT=Number(sum.useful_tokens||0),cT=Number(sum.cache_read_tokens||0),totT=uT+cT,agC=Math.max(0,Number(sum.total_agents||agents.length)||0);
const maxCtx=Number(sum.max_context_tokens)||0,errCnt=Number(sum.error_count)||0,errAg=sum.error_agents!=null?Number(sum.error_agents):agents.filter((a)=>a&&a.status==="error").length;
const kpiStrip=el("div","kpi-strip");
[["Tokens totaux",fmtTokens(totT),"Utiles : "+fmtTokens(uT),""],
["Moy. / agent",fmtTokens(agC?Math.round(totT/agC):0),fmtTokens(agC?Math.round(uT/agC):0)+" ut. · "+fmtInt(agC)+" ag.",""],
["Cache",fmtPct(sum.cache_hit_pct||0),fmtTokens(cT)+" lus",""],
["Pic contexte",fmtTokens(maxCtx),"Actuel : "+fmtTokens(sum.context_tokens||0),maxCtx>CTX_CRIT_TOKENS?"error":(maxCtx>CTX_WARN_TOKENS?"warn":"")],
["Agents actifs",fmtInt(sum.active_agents||0)+" / "+fmtInt(agC),(sum.waiting_agents||0)+" att. · "+(errAg>0?errAg+" err":(sum.done_agents||0)+" term."),(errAg>0||errCnt>0)?"error":""],
["Durée",fmtDuration(sum.duration_s||0),fmtInt(sum.llm_calls||0)+" LLM · "+fmtInt(sum.tool_calls||0)+" out.",""]].forEach(([l,v,s,t])=>kpiStrip.appendChild(renderMetricKpiCard(l,v,s,t)));
hp.appendChild(kpiStrip);container.appendChild(hp);
container.appendChild(_renderPhaseStepper(live.phases||sel.phases,live.current_phase||sel.current_phase||"",phaseFilter));
if(wfBlock)container.appendChild(wfBlock);
const idMap={};agents.forEach((a)=>{if(!a)return;const lbl=String(a.role||a.id||"");if(a.id&&lbl)idMap[String(a.id)]=lbl;if(a.conversation_id&&lbl)idMap[String(a.conversation_id)]=lbl});
let selAgent=null,selKey="";
if(ui.selectedAgentId!=="__all__"&&agents.length){
const tid=String(ui.selectedAgentId||"");selAgent=agents.find((a)=>a&&(String(a.id||"")===tid||String(a.conversation_id||"")===tid))||agents[0];
if(selAgent)selKey=String(selAgent.id||selAgent.conversation_id||"");
}
const treeObj=buildAgentHierarchy(agents,{sessionStartedAt:sel.session_started_at||live.session_started_at||"",sessionLastTs:sel.session_last_ts||live.session_last_ts||""});
const fltInfo=filterAgentHierarchy(treeObj,phaseFilter,searchQuery),parentIds=treeObj.nodes.filter((n)=>n.children.length).map((n)=>n.key),anyCol=Object.values(ui.collapsedAgents||{}).some(Boolean);
const layout=el("div","split-tree master-detail"),tp=el("section","panel"),tHead=el("div","panel-head"),tActs=el("div","actions-row");
tHead.appendChild(el("div","panel-title","Hiérarchie des agents & Modèles"));
if(parentIds.length)tActs.appendChild(el("button","btn btn-sm",anyCol?"Tout déplier":"Tout replier",{type:"button","data-action":"toggle-live-all","data-ids":parentIds.join(",")}));
tActs.appendChild(el("span","mono",(fltInfo.hasFilter?fltInfo.directMatch.size+" / ":"")+agents.length+" agent(s)"));tHead.appendChild(tActs);tp.appendChild(tHead);
if(!agents.length)tp.appendChild(el("div","empty","Aucun agent actif ou historique détecté pour cette session."));
else tp.appendChild(renderAgentTree(agents,{selectedId:selKey,collapsedIds:ui.collapsedAgents||{},phaseFilter,searchQuery,sessionStartedAt:sel.session_started_at||live.session_started_at||"",sessionLastTs:sel.session_last_ts||live.session_last_ts||"",onSelect:h.onSelectAgent,onToggle:h.onToggleTree}));
layout.appendChild(tp);layout.appendChild(_renderLiveInspector(agents,selAgent,live.recent_events||[],idMap,h));container.appendChild(layout);
const fold=el("details","fold-panel",null,{id:"g-live-breakdown"});if(ui.breakdownOpen)fold.open=true;
const fSum=el("summary","fold-summary");fSum.appendChild(el("span",null,"Répartition technique & dépôts"));fSum.appendChild(el("span","mono","Atelier vs Code"));fold.appendChild(fSum);
const fBody=el("div","fold-body");
fBody.appendChild(renderStackedBars([{label:"Tokens utiles",value:uT,color:"var(--g-c1)"},{label:"Cache lu",value:cT,color:"var(--g-c3)"},{label:"Raisonnement (est.)",value:sum.thinking_est_tokens||0,color:"var(--g-c2)"}],{title:"Volume tokens session"}));
fBody.appendChild(renderWorkspaceBreakdown(_aggregateLiveWorkspaces(agents)));fold.appendChild(fBody);container.appendChild(fold);
}
"""

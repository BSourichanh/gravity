"""Pure DOM renderer for the Gravity 'Session' Live Cockpit (100% stdlib, zero innerHTML)."""

from __future__ import annotations

LIVE_VIEWS_JS = r"""
function _parseWorkflowProgress(raw){const m=String(raw||"").match(/(\d+)\s*\/\s*(\d+)/);if(!m)return{done:0,total:0,pct:0};const d=Math.max(0,Number(m[1])||0),t=Math.max(1,Number(m[2])||1);return{done:d,total:t,pct:Math.min(100,Math.round((d/t)*100))}}
function _aggregateLiveWorkspaces(agents){
const map=new Map();
(Array.isArray(agents)?agents:[]).forEach((ag)=>{
if(!ag)return;const ws=String(ag.workspace||"workspace"),kind=String(ag.workspace_kind||"code").toLowerCase(),k=ws+"::"+kind;
const cur=map.get(k)||{workspace:ws,kind,useful_tokens:0,cache_read_tokens:0,agents_count:0};
cur.useful_tokens+=Number(ag.useful_tokens)||0;cur.cache_read_tokens+=Number(ag.cache_read_tokens)||0;cur.agents_count+=1;map.set(k,cur);
});
return Array.from(map.values()).sort((a,b)=>(b.useful_tokens-a.useful_tokens)||a.workspace.localeCompare(b.workspace));
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
const prog=_parseWorkflowProgress(wf.progress),bw=el("div","wf-bar"),bh=el("div","ctx-gauge-head");
bh.appendChild(el("span",null,"Avancement : "+String(wf.progress||"0/0")));bh.appendChild(el("span","mono",fmtPct(prog.pct)));bw.appendChild(bh);
const tr=el("div","wf-progress-track",null,{role:"progressbar","aria-valuenow":String(prog.done),"aria-valuemin":"0","aria-valuemax":String(prog.total)}),fl=el("div","wf-progress-fill");
fl.style.width=prog.pct+"%";tr.appendChild(fl);bw.appendChild(tr);p.appendChild(bw);
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
[["Modèle",resolveAgentModel(ag)||"inconnu"],["Dépôt",String(ag.workspace||"workspace")],["LLM / Outils",fmtInt(ag.llm_calls||0)+" / "+fmtInt(resolveAgentToolCalls(ag))],["Tokens utiles",fmtTokens(ag.useful_tokens||0)+" · Cache "+fmtPct(ag.cache_hit_pct||0)],["Durée / Erreurs",fmtDuration(ag.duration_s||0)+" · "+fmtInt(err)+" erreur(s)"]].forEach(([k,v])=>{kv.appendChild(el("div","kv-k",k));kv.appendChild(el("div","mono",v))});
pane.appendChild(kv);
const agIds=new Set([ag.id,ag.conversation_id].filter(Boolean).map(String)),filtered=evList.filter((ev)=>ev&&agIds.has(String(ev.agent_id||""))),evHead=el("div","panel-head");
evHead.appendChild(el("div","panel-title","Événements de l'agent ("+filtered.length+")"));
const evErr=filtered.filter((e)=>e.kind==="error").length;if(evErr>0)evHead.appendChild(makeBadge(evErr+" erreur(s)","error"));
pane.appendChild(evHead);pane.appendChild(_renderEventFeed(filtered,"Aucun événement récent pour cet agent."));return pane;
}
function renderLiveView(container,liveArg,uiArg,handlersArg){
const live=liveArg!==undefined?liveArg:(typeof state!=="undefined"?state.live:null),ui=uiArg||(typeof state!=="undefined"?(state.liveUi||{}):{}),h=handlersArg||{};
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
sTitle.appendChild(makeBadge(sel.captured?"Suivie":"Non enregistrée",sel.captured?"ok":"warn"));sHead.appendChild(sTitle);
const actName=sel.captured?"update":"record",actBtn=el("button","btn btn-sm btn-primary",ui.actionInFlight?"En cours...":(sel.captured?"Mettre à jour":"Enregistrer"),{type:"button","data-action":"live-metrics-action","data-metrics-action":actName,"data-cid":String(sel.conversation_id||"")});
if(ui.actionInFlight)actBtn.disabled=true;
if(typeof h.onCaptureAction==="function")actBtn.addEventListener("click",()=>h.onCaptureAction(actName,String(sel.conversation_id||"")));
sHead.appendChild(actBtn);hp.appendChild(sHead);
const maxCtx=Number(sum.max_context_tokens)||0,errCnt=Number(sum.error_count)||0,errAg=sum.error_agents!=null?Number(sum.error_agents):agents.filter((a)=>a&&a.status==="error").length;
const kpiStrip=el("div","kpi-strip");
[["Agents actifs",fmtInt(sum.active_agents||0)+" / "+fmtInt(sum.total_agents||agents.length),(sum.waiting_agents||0)+" att. · "+(sum.done_agents||0)+" term.",""],
["Tokens utiles",fmtTokens(sum.useful_tokens||0),fmtInt(sum.llm_calls||0)+" LLM · "+fmtInt(sum.tool_calls||0)+" outils",""],
["Cache",fmtPct(sum.cache_hit_pct||0),fmtTokens(sum.cache_read_tokens||0)+" lus",""],
["Pic contexte",fmtTokens(maxCtx),"Actuel : "+fmtTokens(sum.context_tokens||0),maxCtx>CTX_CRIT_TOKENS?"error":(maxCtx>CTX_WARN_TOKENS?"warn":"")],
["Erreurs",fmtInt(errAg)+" agent(s)",fmtInt(errCnt)+" étape(s)",(errAg>0||errCnt>0)?"error":""],
["Durée",fmtDuration(sum.duration_s||0),"Raison. : "+fmtTokens(sum.thinking_est_tokens||0),""]].forEach(([l,v,s,t])=>kpiStrip.appendChild(renderMetricKpiCard(l,v,s,t)));
hp.appendChild(kpiStrip);container.appendChild(hp);if(wfBlock)container.appendChild(wfBlock);
const idMap={};agents.forEach((a)=>{if(!a)return;const lbl=String(a.role||a.id||"");if(a.id&&lbl)idMap[String(a.id)]=lbl;if(a.conversation_id&&lbl)idMap[String(a.conversation_id)]=lbl});
let selAgent=null,selKey="";
if(ui.selectedAgentId!=="__all__"&&agents.length){
const tid=String(ui.selectedAgentId||"");selAgent=agents.find((a)=>a&&(String(a.id||"")===tid||String(a.conversation_id||"")===tid))||agents[0];
if(selAgent)selKey=String(selAgent.id||selAgent.conversation_id||"");
}
const layout=el("div","split-tree master-detail"),tp=el("section","panel"),tHead=el("div","panel-head");
tHead.appendChild(el("div","panel-title","Arbre des agents"));tHead.appendChild(el("span","mono",agents.length+" agent(s)"));tp.appendChild(tHead);
if(!agents.length)tp.appendChild(el("div","empty","Aucun agent actif ou historique détecté pour cette session."));
else tp.appendChild(renderAgentTree(agents,{selectedId:selKey,collapsedIds:ui.collapsedAgents||{},sessionStartedAt:sel.session_started_at||live.session_started_at||"",sessionLastTs:sel.session_last_ts||live.session_last_ts||"",onSelect:h.onSelectAgent,onToggle:h.onToggleTree}));
layout.appendChild(tp);layout.appendChild(_renderLiveInspector(agents,selAgent,live.recent_events||[],idMap,h));container.appendChild(layout);
const fold=el("details","fold-panel",null,{id:"g-live-breakdown"});if(ui.breakdownOpen)fold.open=true;
const fSum=el("summary","fold-summary");fSum.appendChild(el("span",null,"Répartition technique & dépôts"));fSum.appendChild(el("span","mono","Atelier vs Code"));fold.appendChild(fSum);
const fBody=el("div","fold-body");
fBody.appendChild(renderStackedBars([{label:"Tokens utiles",value:sum.useful_tokens||0,color:"var(--g-c1)"},{label:"Cache lu",value:sum.cache_read_tokens||0,color:"var(--g-c3)"},{label:"Raisonnement (est.)",value:sum.thinking_est_tokens||0,color:"var(--g-c2)"}],{title:"Volume tokens session"}));
fBody.appendChild(renderWorkspaceBreakdown(_aggregateLiveWorkspaces(agents)));fold.appendChild(fBody);container.appendChild(fold);
}
"""

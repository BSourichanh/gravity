"""Pure DOM renderer for the Gravity unified 'Historique' views & slide-over (100% stdlib, zero innerHTML)."""

from __future__ import annotations

METRICS_VIEWS_JS = r"""
const ROLE_LABELS_FR={orchestrator:"Orchestration",orchestration:"Orchestration",coordinator:"Coordination",worker:"Exécution (Workers)",builder:"Construction",build:"Construction",reviewer:"Revue & Audit",verification:"Vérification",research:"Exploration",discovery:"Découverte",subagent:"Sous-agents",root:"Session racine",planner:"Planification",other:"Autre"};
const AXIS_CFG=[["agent","by_agent_type","Par type d'agent"],["phase","by_phase","Par phase"],["mode","by_session_mode","Par type de session"],["model","by_model","Par modèle"]];
const _wsKind=(ws,k)=>String(k||(/-(workshop|studio)$/.test(String(ws||"").toLowerCase())?"atelier":"code")).toLowerCase();
const _recUseful=(r)=>!r?0:(r.input_tokens!=null||r.output_tokens!=null?Math.max(0,(Number(r.input_tokens)||0)+(Number(r.output_tokens)||0)):Math.max(0,(Number(r.total_tokens)||0)-(Number(r.cache_read_tokens)||0)));
const _recTot=(r)=>!r?0:(Number(r.total_tokens)||(_recUseful(r)+(Number(r.cache_read_tokens)||0)));
const _recKey=(r)=>String((r&&(r.detail_slug||r.label||r.conversation_id))||"");
const _audKey=(a)=>String((a&&(a.audit_id||a.rel_path||a.title))||"");
const _pick=(...xs)=>{for(const x of xs)if(x!=null)return x;return 0};
const _d=(c,t,a)=>el("div",c,t,a),_s=(c,t,a)=>el("span",c,t,a);
const _actBtn=(lbl,act,attrs,cls)=>el("button","btn btn-sm"+(cls?" "+cls:""),lbl,Object.assign({type:"button","data-action":act},attrs||{}));
function _mkSel(id,lbl,items,val){
const s=el("select","select",null,{id,"aria-label":lbl});
items.forEach(([v,t])=>{const o=el("option",null,t,{value:v});if(v===val)o.selected=true;s.appendChild(o)});return s;
}
function _kvList(pairs){const kv=_d("kv-grid");pairs.forEach(([k,v])=>{kv.appendChild(_d("kv-k",k));kv.appendChild(_d("mono",v))});return kv}
const _liveDeltaCalls=(rec)=>{const lv=state.live;return(!lv||!lv.selected_session||!rec||String(lv.selected_session.conversation_id||"")!==String(rec.conversation_id||""))?0:Math.max(0,Number((lv.summary&&lv.summary.llm_calls)||0)-Number(rec.llm_calls||0))};
const _hasSlideOverHost=()=>typeof renderSlideOver==="function"&&typeof document.getElementById==="function"&&Boolean(document.getElementById("g-slideover"));
function _refreshSessionSlideOver(){
if(_hasSlideOverHost()&&state.slideOver){
const prev=document.querySelector?document.querySelector(".slide-over"):null,top=prev?prev.scrollTop:0;
renderSlideOver();const next=document.querySelector?document.querySelector(".slide-over"):null;if(next&&top>0)next.scrollTop=top;
}else if(typeof renderMetricsBodyOrFull==="function")renderMetricsBodyOrFull();
}
function _clearMetricsSlideState(){Object.assign(state,{sessionTarget:"",sessionDetail:null,sessionEditOpen:false,sessionDeleteConfirm:false,pendingDeleteTarget:"",auditTarget:"",auditData:null})}
function _fallbackAnalyticsAxis(records,axis){
const map=new Map(),add=(k,lbl,tot,use,cp)=>{const c=map.get(k)||{l:lbl,n:0,t:0,u:0,cs:0,sc:0};c.n+=1;c.t+=tot;c.u+=use;c.cs+=cp;c.sc+=1;map.set(k,c)};
(records||[]).forEach((r)=>{
const tot=_recTot(r),use=_recUseful(r),cp=Number(r.cache_hit_rate_pct||0);
if(axis==="model"){
const ms=r.models;if(ms&&typeof ms==="object"&&Object.keys(ms).length){const tc=Object.values(ms).reduce((s,v)=>s+Number((v&&v.calls)||0),0)||1;Object.entries(ms).forEach(([mn,md])=>{const q=Number((md&&md.calls)||0)/tc;add(mn,mn,md&&md.tokens!=null?Number(md.tokens):Math.round(tot*q),md&&md.useful_tokens!=null?Number(md.useful_tokens):Math.round(use*q),cp)})}
else if(r.primary_model)add(String(r.primary_model),String(r.primary_model),tot,use,cp);
}else if(axis==="mode"){const k=String(r.execution_mode||"single");add(k,k,tot,use,cp)}
else if(axis==="phase"){
const ps=r.milestones&&r.milestones.phases;if(Array.isArray(ps)&&ps.length)ps.forEach((ph)=>{if(ph&&ph.id&&(ph.tokens||ph.status!=="pending"))add(String(ph.id),String(ph.label||ph.id),Number(ph.tokens||0),Number(ph.useful_tokens||0),cp)});
else{const cpN=String(r.current_phase||"production");add(cpN.toLowerCase(),cpN,tot,use,cp)}
}else if(r.category_share_pct&&typeof r.category_share_pct==="object"){
Object.entries(r.category_share_pct).forEach(([cat,pct])=>{const sh=Math.max(0,Number(pct)||0);if(sh>0)add(cat,ROLE_LABELS_FR[cat.toLowerCase()]||cat,Math.round(tot*sh/100),Math.round(use*sh/100),cp)});
}
});
const gT=Array.from(map.values()).reduce((s,b)=>s+b.t,0)||1,out={};
Array.from(map.entries()).sort((a,b)=>b[1].t-a[1].t).forEach(([k,b])=>{out[k]={label:b.l,count:b.n,total_tokens:b.t,useful_tokens:b.u,avg_tokens:b.n?b.t/b.n:0,avg_useful_tokens:b.n?b.u/b.n:0,cache_hit_rate_pct:b.sc?b.cs/b.sc:0,share_pct:(b.t/gT)*100}});
return out;
}
function _renderAxisAnalytics(met){
const axis=state.metricsAxis||"agent",cfg=AXIS_CFG.find((c)=>c[0]===axis)||AXIS_CFG[0];
const panel=el("section","panel"),hd=_d("panel-head"),tabs=_d("axis-tabs"),tb=_d(null);
tb.appendChild(_d("panel-title","Tokens & Moyenne par Type"));tb.appendChild(_d("kpi-sub","Axes : agents, phases, modes et modèles"));hd.appendChild(tb);
AXIS_CFG.forEach(([id,_k,lbl])=>tabs.appendChild(_actBtn(lbl,"metrics-axis",{"data-axis":id},axis===id?"active":"")));
hd.appendChild(tabs);panel.appendChild(hd);
const raw=(met.analytics&&met.analytics[cfg[1]]&&typeof met.analytics[cfg[1]]==="object")?met.analytics[cfg[1]]:_fallbackAnalyticsAxis(met.records,axis);
const rows=Object.entries(raw||{}).map(([k,v])=>Object.assign({key:k},v));
if(!rows.length){panel.appendChild(_d("empty","Aucune donnée analytique pour cet axe."));return panel}
const maxAvg=Math.max(...rows.map((r)=>Number(r.avg_tokens)||0),1);
const trRows=rows.map((r,idx)=>{
const tr=el("tr"),lc=el("td"),dot=_s("legend-dot"),avg=Number(r.avg_tokens||0),sh=Number(r.share_pct||0),col="var(--g-c"+((idx%6)+1)+")";
dot.style.backgroundColor=col;dot.style.marginRight="6px";lc.appendChild(dot);
lc.appendChild(_s(null,String(axis==="model"?(shortModelName(r.label||r.key)||r.key):(r.label||r.key)),axis==="model"?{title:String(r.label||r.key)}:null));
tr.appendChild(lc);tr.appendChild(el("td","num mono",fmtInt(r.count||0)));tr.appendChild(el("td","num mono",fmtTokens(r.total_tokens||0)));
tr.appendChild(el("td","num mono",fmtTokens(avg)));tr.appendChild(el("td","num mono",fmtTokens(r.avg_useful_tokens||0)));tr.appendChild(el("td","num mono",fmtPct(r.cache_hit_rate_pct||0)));
const bTd=el("td"),bw=_d("ab-line"),trk=_d("ab-track"),fl=_d("ab-fill");
fl.style.width=Math.max(avg>0?4:0,Math.round((avg/maxAvg)*100))+"%";fl.style.backgroundColor=col;
trk.appendChild(fl);bw.appendChild(trk);bw.appendChild(_s("mono num",fmtPct(sh)));bTd.appendChild(bw);tr.appendChild(bTd);return tr;
});
panel.appendChild(_makeTable(["Type / Modèle","Volume","Tokens totaux","Moy. / unité","Moy. utiles","Cache %","Part"],trRows,[1,2,3,4,5]));return panel;
}
function _renderDistBars(rows,opts){
const o=opts||{},w=_d("ws-list");if(!rows.length){w.appendChild(_d("empty",o.emptyLabel||"Aucune donnée."));return w}
const tot=rows.reduce((a,r)=>a+(Number(r.value)||0),0)||1,mx=Math.max(...rows.map((r)=>Number(r.value)||0),1);
rows.slice(0,o.limit||7).forEach((r,i)=>{
const v=Number(r.value)||0,row=_d("ws-row"),hd=_d("ws-row-head");
hd.appendChild(_s("mono",String(r.label)));hd.appendChild(_s("mono num",(o.isTokens?fmtTokens(v):(fmtInt(v)+" appels"))+" ("+fmtPct((v/tot)*100)+")"));
row.appendChild(hd);const tr=_d("ws-bar-track"),fl=_d("ws-bar-fill");
fl.style.width=Math.max(v>0?4:0,Math.round((v/mx)*100))+"%";fl.style.backgroundColor="var(--g-c"+((i%6)+1)+")";
tr.appendChild(fl);row.appendChild(tr);w.appendChild(row);
});return w;
}
function _renderMetricsOverview(container,met){
const kpis=met.kpis||{},recs=(met.records||[]).slice(0,12).reverse(),cnt=Math.max(0,Number(kpis.sessions_count||recs.length)||0);
const avgTot=kpis.avg_tokens_per_session!=null?Number(kpis.avg_tokens_per_session):(cnt?Math.round((Number(kpis.total_tokens)||0)/cnt):0);
const avgUse=kpis.avg_useful_tokens_per_session!=null?Number(kpis.avg_useful_tokens_per_session):(cnt?Math.round((Number(kpis.useful_tokens)||0)/cnt):0);
const maxCtx=Number(kpis.max_context_tokens||0),alerts=Number(kpis.context_alerts_count||0),crits=Number(kpis.context_critical_count||0),kpiGrid=_d("grid-kpi");
[
["Tokens totaux",fmtTokens(kpis.total_tokens||0),"Utiles : "+fmtTokens(kpis.useful_tokens||0)+" · "+fmtInt(cnt)+" sess.",{series:recs.map(_recTot),seriesColor:"var(--g-c1)"}],
["Moy. tokens / session",fmtTokens(avgTot),"Utiles moy. : "+fmtTokens(avgUse)+" · "+fmtInt(kpis.total_llm_calls||0)+" appels",{series:recs.map(_recTot),seriesColor:"var(--g-c2)"}],
["Moy. utiles / session",fmtTokens(avgUse),"Total utiles : "+fmtTokens(kpis.useful_tokens||0),{series:recs.map(_recUseful),seriesColor:"var(--g-c1)"}],
["Cache Hit moyen",fmtPct(kpis.avg_cache_hit_rate_pct||0),"Repère $ : "+fmtUsd(kpis.cost_usd||0)+" · éco. "+fmtUsd(kpis.cache_savings_usd||0),{series:recs.map((r)=>Number(r.cache_hit_rate_pct||0)),seriesColor:"var(--g-c3)"}],
["Pression contexte",maxCtx>0?fmtTokens(maxCtx):(fmtInt(kpis.archived_count||0)+" arch."),maxCtx>0?(alerts+" alerte(s) · "+crits+" crit."):(fmtInt(kpis.active_count||0)+" active(s)"),{tone:crits>0?"error":(alerts>0?"warn":"")}]
].forEach(([l,v,s,o])=>kpiGrid.appendChild(renderMetricKpiCard(l,v,s,o)));
container.appendChild(kpiGrid);container.appendChild(_renderAxisAnalytics(met));
const wsRows=(met.by_workspace&&met.by_workspace.length)?met.by_workspace:(met.by_project||[]).map((p)=>({workspace:p.project,kind:_wsKind(p.project),useful_tokens:Number(p.llm_calls||0)*1000,sessions:p.sessions}));
const atT=wsRows.filter((w)=>w.kind==="atelier").reduce((a,w)=>a+(Number(w.useful_tokens)||0),0),cdT=wsRows.filter((w)=>w.kind!=="atelier").reduce((a,w)=>a+(Number(w.useful_tokens)||0),0);
const wsP=el("section","panel"),wsH=_d("panel-head"),wsM=_d("actions-row");
wsH.appendChild(_d("panel-title","Répartition par Dossier / Workspace"));
wsM.appendChild(makeBadge(cnt+" session(s) unique(s) · multi-dépôts comptés par dossier"));
wsM.appendChild(makeBadge("Atelier : "+fmtTokens(atT),"atelier"));wsM.appendChild(makeBadge("Code : "+fmtTokens(cdT),"code"));
wsH.appendChild(wsM);wsP.appendChild(wsH);wsP.appendChild(renderWorkspaceBreakdown(wsRows,{limit:10}));container.appendChild(wsP);
}
function _sortRecords(records,mode){
const arr=(records||[]).slice();
if(mode==="useful_tokens")arr.sort((a,b)=>_recUseful(b)-_recUseful(a));
else if(mode==="max_context")arr.sort((a,b)=>Number(b.max_context_tokens||0)-Number(a.max_context_tokens||0));
else if(mode==="errors")arr.sort((a,b)=>(Number(b.error_steps||0)-Number(a.error_steps||0))||(Number(b.error_rate_pct||0)-Number(a.error_rate_pct||0)));
else if(mode==="latency")arr.sort((a,b)=>Number(b.latency_p95_ms||0)-Number(a.latency_p95_ms||0));
else arr.sort((a,b)=>String(b.ended_at||b.started_at||"").localeCompare(String(a.ended_at||a.started_at||"")));
return arr;
}
function _renderComparatorPanel(met){
const recs=met.records||[],panel=el("section","panel"),head=_d("panel-head");
head.appendChild(_d("panel-title","Comparateur A/B technique"));head.appendChild(_actBtn("Fermer","toggle-compare"));panel.appendChild(head);
if(recs.length<2){panel.appendChild(_d("empty","Au moins 2 sessions enregistrées sont nécessaires."));return panel}
const pick=(k,d)=>recs.find((r)=>_recKey(r)===k||String(r.conversation_id||"")===k)||recs[d];
const rA=pick(state.compareA,0),rB=pick(state.compareB,1),items=recs.map((r)=>[_recKey(r),String(r.label||r.conversation_id||_recKey(r))]),pr=_d("actions-row");
pr.appendChild(_mkSel("g-cmp-a","Session A",items,_recKey(rA)));pr.appendChild(_mkSel("g-cmp-b","Session B",items,_recKey(rB)));panel.appendChild(pr);
const rows=[
["Tokens totaux",_recTot(rA),_recTot(rB),fmtTokens],["Tokens utiles",_recUseful(rA),_recUseful(rB),fmtTokens],
["Efficacité cache",Number(rA.cache_hit_rate_pct||0),Number(rB.cache_hit_rate_pct||0),fmtPct],["Contexte max",Number(rA.max_context_tokens||0),Number(rB.max_context_tokens||0),fmtTokens],
["Appels modèle",Number(rA.llm_calls||0),Number(rB.llm_calls||0),fmtInt],["Erreurs",Number(rA.error_steps||0),Number(rB.error_steps||0),fmtInt],["Durée",Number(rA.wall_clock_s||0),Number(rB.wall_clock_s||0),fmtDuration]
].map(([l,va,vb,f])=>{const tr=el("tr"),df=vb-va;tr.appendChild(el("td",null,l));tr.appendChild(el("td","num mono",f(va)));tr.appendChild(el("td","num mono",f(vb)));tr.appendChild(el("td","num mono",df===0?"0":((df>0?"+":"-")+f(Math.abs(df)))));return tr});
panel.appendChild(_makeTable(["Indicateur","A","B","Delta (B - A)"],rows,[1,2,3]));return panel;
}
function _renderSessionInspector(agents,ag,idMap){
const pane=el("aside","inspector-pane",null,{id:"g-session-inspector"});
if(!ag){
const head=_d("panel-head"),wsMap=new Map();head.appendChild(_d("panel-title","Synthèse agents ("+agents.length+")"));pane.appendChild(head);
agents.forEach((a)=>{if(!a)return;const ws=String(a.workspace||"workspace"),kind=_wsKind(ws,a.workspace_kind),k=ws+"::"+kind,c=wsMap.get(k)||{workspace:ws,kind,useful_tokens:0,agents_count:0};c.useful_tokens+=(Number(a.input_tokens||0)+Number(a.output_tokens||0))||Number(a.useful_tokens||0);c.agents_count+=1;wsMap.set(k,c)});
pane.appendChild(renderWorkspaceBreakdown(Array.from(wsMap.values()).sort((a,b)=>b.useful_tokens-a.useful_tokens)));return pane;
}
const errS=Number(_pick(ag.error_steps,ag.error_count))||0,anom=Number(_pick(ag.total_anomalies,errS))||0;
const agSt=(String(ag.status||"").toLowerCase()==="error"||(ag.clean_termination===false&&errS>0)||ag.transcript_missing)?"error":(ag.clean_termination===false?"interrupted":"done");
const head=_d("panel-head"),tw=_d("actions-row");
tw.appendChild(_d("panel-title",String(ag.role||ag.name||ag.id||"Agent")));tw.appendChild(renderStatusBadge(agSt));
const srcB=renderSourceBadge(ag.source||(Number(ag.depth)===0?"root":""));if(srcB)tw.appendChild(srcB);
tw.appendChild(renderWorkspaceKindBadge(_wsKind(ag.workspace,ag.workspace_kind)));head.appendChild(tw);
const gBtn=_actBtn("Vue globale","clear-session-agent");gBtn.addEventListener("click",()=>{state.sessionAgentId="__all__";_refreshSessionSlideOver()});head.appendChild(gBtn);pane.appendChild(head);
const fil=renderFiliationLabel(ag,idMap);if(fil)pane.appendChild(fil);
pane.appendChild(renderContextGauge(ag.max_context_tokens||0,ag.max_context_tokens||0,{label:"Pic contexte"}));
const agUse=(Number(ag.input_tokens||0)+Number(ag.output_tokens||0))||Number(ag.useful_tokens||0),dur=_pick(ag.active_s,ag.lifespan_s,ag.duration_s);
const cObj=typeof ag.cost_usd==="object"&&ag.cost_usd?ag.cost_usd:null,agCost=cObj?_pick(cObj.total_usd,cObj.total):ag.cost_usd;
const rows=[["Modèle",resolveAgentModel(ag)||"inconnu"],["Dépôt",String(ag.workspace||"—")],["Catégorie",ag.category?(ROLE_LABELS_FR[String(ag.category).toLowerCase()]||String(ag.category)):"—"],["LLM / Outils",fmtInt(ag.llm_calls||0)+" LLM · Outils : "+fmtInt(resolveAgentToolCalls(ag))],["Tokens utiles / Cache",fmtTokens(agUse)+" · Cache : "+fmtTokens(ag.cache_read_tokens||0)],["Durée",fmtDuration(dur)]];
if(anom>0||errS>0)rows.push(["Anomalies / Erreurs","Anomalies : "+fmtInt(anom)+" ("+fmtInt(errS)+" err)"]);
if(agCost!=null&&Number(agCost)>0)rows.push(["Repère $",fmtUsd(agCost)]);
if(ag.conversation_id)rows.push(["ID",String(ag.conversation_id)]);
pane.appendChild(_kvList(rows));return pane;
}
function _populateSessionSlideOver(drawer,met,includeHeader){
if(state._lastDetailTarget!==state.sessionTarget){state._lastDetailTarget=state.sessionTarget;state.sessionAgentId="";state.sessionCollapsed={}}
const sd=state.sessionDetail,det=(sd&&sd.detail)||{},rec=(sd&&sd.record)||(met.records||[]).find((r)=>_recKey(r)===state.sessionTarget)||{};
const cid=String((sd&&sd.conversation_id)||rec.conversation_id||""),slug=String((sd&&sd.slug)||rec.detail_slug||state.sessionTarget||"");
if(includeHeader){
const dH=_d("panel-head"),dB=_d("actions-row");dH.appendChild(_d("panel-title",String((sd&&sd.label)||rec.label||"Détail session")));
if(sd&&sd.report_md_uri)dB.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":sd.report_md_uri}));
dB.appendChild(_actBtn("Fermer","close-session-detail"));dH.appendChild(dB);drawer.appendChild(dH);
}
if(state.sessionDetailLoading){drawer.appendChild(_d("empty","Chargement du détail technique..."));return}
const actRow=_d("actions-row"),dc=_liveDeltaCalls(rec),isArch=String((rec&&rec.status)||(sd&&sd.status)||"archived").toLowerCase()!=="active";
const updBtn=_actBtn(dc>0?("Mettre à jour (+"+dc+" appels)"):"Mettre à jour","metrics-cli-action",{"data-cli-action":"update","data-cid":cid,"data-target":slug||cid},"btn-primary");
if(state.metricsActionInFlight)updBtn.disabled=true;actRow.appendChild(updBtn);
actRow.appendChild(_actBtn("Éditer","toggle-session-edit",{},state.sessionEditOpen?"active":""));
if(!isArch)actRow.appendChild(_actBtn("Ignorer","metrics-cli-action",{"data-cli-action":"ignore","data-cid":cid,"data-target":cid}));
actRow.appendChild(_actBtn("Supprimer","ask-remove-session",{"data-target":slug||cid},"btn-danger"));
if(!includeHeader&&sd&&sd.report_md_uri)actRow.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":sd.report_md_uri}));
drawer.appendChild(actRow);
if(state.sessionDeleteConfirm&&state.pendingDeleteTarget===(slug||cid)){
drawer.appendChild(renderInlineConfirm({danger:true,message:"Supprimer cette session et ses rapports ?",confirmLabel:"Confirmer suppression",cancelLabel:"Annuler",confirmAttrs:{"data-action":"metrics-cli-action","data-cli-action":"remove","data-target":slug||cid,"data-cid":cid},cancelAttrs:{"data-action":"cancel-remove-session"}}));
}
if(state.sessionEditOpen){
const form=el("form","panel",null,{id:"g-session-edit-form","data-target":slug||cid});form.appendChild(_d("kpi-lbl","Modifier label, projet et note"));
[["g-edit-label","Label",rec.label||""],["g-edit-project","Projet",rec.project||""],["g-edit-note","Note",rec.note||""]].forEach(([fid,ph,val])=>{const inp=el("input","input",null,{id:fid,type:"text",placeholder:ph,value:String(val)});inp.value=String(val);form.appendChild(inp)});
const fB=_d("actions-row");fB.appendChild(el("button","btn btn-sm btn-primary","Enregistrer",{type:"submit"}));fB.appendChild(_actBtn("Annuler","toggle-session-edit"));form.appendChild(fB);drawer.appendChild(form);
}
const subTabs=_d("subtabs");[["summary","Synthèse"],["agents","Agents & Outils"],["diagnostic","Diagnostic"]].forEach(([id,l])=>subTabs.appendChild(_actBtn(l,"session-detail-sub",{"data-sub":id},state.sessionDetailSub===id?"active":"")));
drawer.appendChild(subTabs);
const summary=det.summary||{},eff=det.efficiency_and_waste||{},agents=Array.isArray(det.agents)?det.agents:[];
const maxCtx=Number(_pick(eff.context_bloat&&eff.context_bloat.max_context_tokens_overall,det.max_context_tokens,rec.max_context_tokens))||0;
if(state.sessionDetailSub==="agents"){
if(!agents.length)drawer.appendChild(_d("empty","Aucun sous-agent détaillé."));
else{
drawer.appendChild(_d("kpi-sub mono",fmtInt(agents.length)+" agent(s) enregistré(s)"));
const idMap={};agents.forEach((a)=>{if(!a)return;const l=String(a.role||a.name||a.type_name||a.conversation_id||"");if(a.conversation_id&&l)idMap[String(a.conversation_id)]=l;if(a.id&&l)idMap[String(a.id)]=l});
let selAg=null,selKey="";
if(state.sessionAgentId!=="__all__"){const tid=String(state.sessionAgentId||"");selAg=agents.find((a)=>a&&(String(a.id||"")===tid||String(a.conversation_id||"")===tid))||agents[0];if(selAg)selKey=String(selAg.id||selAg.conversation_id||"")}
drawer.appendChild(renderAgentTree(agents,{selectedId:selKey,collapsedIds:state.sessionCollapsed||{},sessionStartedAt:det.started_at||summary.started_at||rec.started_at||"",sessionLastTs:det.ended_at||summary.ended_at||rec.ended_at||"",selectAction:"select-session-agent",toggleAction:"toggle-session-tree",onSelect:(_a,k)=>{state.sessionAgentId=k;_refreshSessionSlideOver()},onToggle:(k)=>{state.sessionCollapsed=state.sessionCollapsed||{};state.sessionCollapsed[k]=!state.sessionCollapsed[k];_refreshSessionSlideOver()}}));
drawer.appendChild(_renderSessionInspector(agents,selAg,idMap));
}
const byTool=(det.tool_usage&&det.tool_usage.by_tool)||{},tRows=Object.entries(byTool).map(([n,c])=>({label:n,value:typeof c==="object"?Number(c.calls||c.count||0):Number(c||0)})).filter((t)=>t.value>0).sort((a,b)=>b.value-a.value);
if(tRows.length){drawer.appendChild(_d("panel-title","Outils les plus utilisés"));drawer.appendChild(_renderDistBars(tRows,{isTokens:false,limit:8}))}
}else if(state.sessionDetailSub==="diagnostic"){
const dup=_pick(eff.duplicate_role_spawns&&eff.duplicate_role_spawns.duplicate_agent_count,rec.duplicate_spawns),rw=_pick(eff.rewind_waste&&eff.rewind_waste.rewind_calls,rec.rewind_calls),intr=_pick(eff.interrupted_agents&&eff.interrupted_agents.count,rec.interrupted_agents);
drawer.appendChild(_kvList([["Erreurs",fmtInt(_pick(summary.total_error_steps,rec.error_steps))+" ("+fmtPct(_pick(summary.error_rate_pct,rec.error_rate_pct))+")"],["Doublons de rôles",fmtInt(dup)],["Rewinds",fmtInt(rw)],["Agents interrompus",fmtInt(intr)],["Compactions contexte",fmtInt(_pick(det.compaction_count,summary.compaction_count,rec.compaction_count))],["Raisonnement (est.)",fmtTokens(_pick(det.thinking_est_tokens,summary.thinking_est_tokens,rec.thinking_est_tokens))],["Pic contexte",fmtTokens(maxCtx)+(maxCtx>CTX_CRIT_TOKENS?" [Critique >200k]":(maxCtx>CTX_WARN_TOKENS?" [Alerte >128k]":""))],["Source détail",(sd&&sd.source)||"history"]]));
}else{
const inT=_pick(summary.input_tokens,rec.input_tokens),outT=_pick(summary.output_tokens,rec.output_tokens),caT=_pick(summary.cache_read_tokens,rec.cache_read_tokens),useful=(Number(inT)+Number(outT))||_recUseful(rec);
drawer.appendChild(renderContextGauge(maxCtx,maxCtx,{label:"Pic contexte"}));
drawer.appendChild(_kvList([["ID",cid||"—"],["Projet",rec.project||det.project||"—"],["Modèle principal",rec.primary_model||"—"],["Tokens utiles",fmtTokens(useful)+" (in "+fmtTokens(inT)+" · out "+fmtTokens(outT)+")"],["Cache lu",fmtTokens(caT)+" ("+fmtPct(_pick(summary.cache_hit_rate_pct,rec.cache_hit_rate_pct))+")"],["Appels / outils",fmtInt(_pick(summary.total_llm_calls,rec.llm_calls))+" / "+fmtInt(_pick(summary.total_tool_calls,rec.tool_calls))],["Durée / Parallélisme",fmtDuration(summary.wall_clock_s||rec.wall_clock_s)+" · "+Number(_pick(summary.parallelism_factor,rec.parallelism_factor,1)).toFixed(1)+"x"],["Latence p95",fmtLatency(_pick(det.latency_p95_ms,summary.latency_p95_ms,rec.latency_p95_ms))]]));
if(rec.note)drawer.appendChild(_d("notice","Note : "+rec.note));
const cO=typeof summary.cost_usd==="object"?summary.cost_usd:{},cV=_pick(cO.total_usd,cO.total,rec.cost_usd),sV=_pick(cO.cache_savings_usd,rec.cache_savings_usd);
drawer.appendChild(_d("kpi-sub mono","Repère secondaire ($) : "+fmtUsd(cV)+" · économie cache "+fmtUsd(sV)));
}
}
function _populateAuditSlideOver(reader,includeHeader){
const ad=state.auditData;
if(includeHeader){
const rH=_d("panel-head"),rB=_d("actions-row");rH.appendChild(_d("panel-title",(ad&&ad.title)?ad.title:"Lecture de l'audit"));
if(ad&&ad.uri)rB.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":ad.uri}));
rB.appendChild(_actBtn("Fermer","close-audit-reader"));rH.appendChild(rB);reader.appendChild(rH);
}else if(ad&&ad.uri){const b=_d("actions-row");b.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":ad.uri}));reader.appendChild(b)}
if(state.auditLoading){reader.appendChild(_d("empty","Chargement de l'audit..."));return}
if(!ad||!ad.found){reader.appendChild(_d("notice warn",(ad&&ad.error)||"Audit introuvable."));return}
const meta=_d("actions-row");if(ad.verdict)meta.appendChild(makeBadge(ad.verdict,ad.verdict_tone||""));if(ad.workspace)meta.appendChild(_s("pill",ad.workspace));if(ad.date)meta.appendChild(_s("mono",ad.date));reader.appendChild(meta);
const pre=el("pre","mono",String(ad.content||""));Object.assign(pre.style,{whiteSpace:"pre-wrap",overflowWrap:"anywhere",margin:"0",padding:"8px",background:"var(--g-muted)",borderRadius:"8px"});reader.appendChild(pre);
}
function _syncMetricsSlideOver(container,met){
const hasHost=_hasSlideOverHost();let title="",renderFn=null;
if(state.auditTarget||state.auditLoading){title=(state.auditData&&state.auditData.title)?state.auditData.title:"Lecture de l'audit";renderFn=(p,i)=>_populateAuditSlideOver(p,i)}
else if(state.sessionTarget){const sd=state.sessionDetail,rec=(sd&&sd.record)||(met.records||[]).find((r)=>_recKey(r)===state.sessionTarget)||{};title=String((sd&&sd.label)||rec.label||"Détail session");renderFn=(p,i)=>_populateSessionSlideOver(p,met,i)}
if(renderFn){
if(hasHost){state.slideOver={title,render:(p)=>renderFn(p,false)};renderSlideOver()}
else{const box=el("aside","slide-over");renderFn(box,true);container.appendChild(box)}
}else if(hasHost&&state.slideOver){state.slideOver=null;renderSlideOver()}
}
function _renderSessionCard(r){
const target=_recKey(r),cid=String(r.conversation_id||""),card=el("article","agent-card"+(state.sessionTarget===target?" active":"")),head=_d("agent-head"),tW=_d(null),maxCtx=Number(r.max_context_tokens||0);
tW.appendChild(_d("agent-role",String(r.label||cid||"Session")));tW.appendChild(_d("mono",(r.project||"(sans projet)")+" · "+fmtDate(r.ended_at||r.started_at)));
head.appendChild(tW);head.appendChild(maxCtx>CTX_CRIT_TOKENS?makeBadge(">200k","crit"):(maxCtx>CTX_WARN_TOKENS?makeBadge(">128k","warn"):makeBadge(r.status==="active"?"Active":"Enregistrée",r.status==="active"?"ok":"")));
card.appendChild(head);if(r.current_phase)card.appendChild(_d("preview-text","Phase : "+String(r.current_phase)));
if(r.milestones&&Array.isArray(r.milestones.phases)&&r.milestones.phases.length){
const ps=r.milestones.phases,pt=ps.reduce((s,x)=>s+(Number(x.tokens)||0),0);
if(pt>0){const stp=_d("phase-strip");ps.forEach((ph,i)=>{const v=Number(ph.tokens)||0;if(!v)return;const sg=_d("phase-seg",null,{title:String(ph.label||ph.id)+" : "+fmtTokens(v)});sg.style.width=Math.max(4,Math.round((v/pt)*100))+"%";sg.style.backgroundColor="var(--g-c"+((i%4)+1)+")";stp.appendChild(sg)});card.appendChild(stp)}
}
const pills=_d("pill-list");
if(r.primary_model)pills.appendChild(_s("badge badge-model",shortModelName(r.primary_model)||String(r.primary_model),{title:String(r.primary_model)}));
if(r.execution_mode)pills.appendChild(_s("pill",String(r.execution_mode)));
if(r.agents!=null)pills.appendChild(_s("pill",fmtInt(r.agents)+" ag."));
if(r.max_depth!=null&&Number(r.max_depth)>0)pills.appendChild(_s("pill","prof. N"+r.max_depth));
if((Number(r.error_steps)||0)>0)pills.appendChild(makeBadge(r.error_steps+" err","error"));
const shares=r.workspace_share_pct&&typeof r.workspace_share_pct==="object"?Object.entries(r.workspace_share_pct):[],kinds=r.workspace_kinds&&typeof r.workspace_kinds==="object"?r.workspace_kinds:{};
shares.sort((a,b)=>(Number(b[1])||0)-(Number(a[1])||0)).slice(0,3).forEach(([wsN,pct])=>pills.appendChild(makeBadge(wsN+" "+Math.round(Number(pct)||0)+"%",_wsKind(wsN,kinds[wsN])==="atelier"?"atelier":"code")));
card.appendChild(pills);
const st=_d("agent-stats");st.appendChild(_s("num","Total : "+fmtTokens(_recTot(r))));st.appendChild(_s("num","Utiles : "+fmtTokens(_recUseful(r))));
st.appendChild(_s("num","Cache : "+fmtPct(r.cache_hit_rate_pct||0)));st.appendChild(_s("num","Ctx : "+fmtTokens(maxCtx)));
if(Number(r.wall_clock_s||0)>0)st.appendChild(_s("num",fmtDuration(r.wall_clock_s)));
card.appendChild(st);
const acts=_d("actions-row"),dc=_liveDeltaCalls(r);
acts.appendChild(_actBtn("Détail","open-session-detail",{"data-target":target},"btn-primary"));
acts.appendChild(_actBtn(dc>0?("Mettre à jour (+"+dc+" appels)"):"Mettre à jour","metrics-cli-action",{"data-cli-action":"update","data-cid":cid,"data-target":target}));
acts.appendChild(_actBtn("A","pin-compare",{"data-slot":"A","data-target":target},state.compareA===target?"active":""));
acts.appendChild(_actBtn("B","pin-compare",{"data-slot":"B","data-target":target},state.compareB===target?"active":""));
card.appendChild(acts);return card;
}
function _renderPendingCard(item,isIgn){
const cid=String(item.conversation_id||""),target=cid||String(item.detail_slug||item.label||""),isOrph=item.brain_exists===false||item.orphan===true,canDel=isOrph||Boolean(isIgn)||Boolean(item.active_capture);
const card=el("article","agent-card "+(isIgn?"done":"waiting")),head=_d("agent-head"),tW=_d(null),bW=_d("actions-row");
tW.appendChild(_d("agent-role",String(item.label||cid||"Session")));tW.appendChild(_d("mono",(item.project||"workspace")+" · "+fmtDate(item.updated_at||item.ignored_at)));
head.appendChild(tW);if(isOrph)bW.appendChild(makeBadge("Transcript absent","error"));
bW.appendChild(makeBadge(isIgn?"Ignorée":(item.active_capture?"Capture":"À enregistrer"),isIgn?"":"warn"));head.appendChild(bW);card.appendChild(head);
if(item.ignored_reason||item.current_phase)card.appendChild(_d("mono",String(item.ignored_reason||("Phase : "+item.current_phase))));
const acts=_d("actions-row");
if(isIgn){acts.appendChild(_actBtn("Restaurer","metrics-cli-action",{"data-cli-action":"unignore","data-cid":cid,"data-target":target},"btn-primary"))}
else{
const rB=_actBtn("Enregistrer","metrics-cli-action",{"data-cli-action":"record","data-cid":cid,"data-target":target,"data-workspace":String(item.cwd||"")},"btn-primary");
if(isOrph||state.metricsActionInFlight)rB.disabled=true;acts.appendChild(rB);
acts.appendChild(_actBtn("Ignorer","metrics-cli-action",{"data-cli-action":"ignore","data-cid":cid,"data-target":target}));
}
if(canDel&&target){const dB=_actBtn("Supprimer","ask-remove-session",{"data-target":target},"btn-danger");if(state.metricsActionInFlight)dB.disabled=true;acts.appendChild(dB)}
card.appendChild(acts);
if(canDel&&target&&state.sessionDeleteConfirm&&state.pendingDeleteTarget===target){
card.appendChild(renderInlineConfirm({danger:true,message:isOrph?"Purger cette entrée orpheline du suivi métriques ?":"Supprimer cette session et son suivi métriques ?",confirmLabel:"Confirmer suppression",cancelLabel:"Annuler",confirmAttrs:{"data-action":"metrics-cli-action","data-cli-action":"remove","data-target":target,"data-cid":cid},cancelAttrs:{"data-action":"cancel-remove-session"}}));
}
return card;
}
function _renderPendingBanner(pending,fromSyn){
const b=_d("notice warn"),r=_d("panel-head");r.appendChild(_s(null,pending.length+" session(s) détectée(s) à enregistrer."));
if(fromSyn){const btn=_actBtn("Voir À enregistrer ("+pending.length+")","metrics-sub",{"data-sub":"sessions"});btn.addEventListener("click",()=>{state.metricsFilter="pending"});r.appendChild(btn)}
else r.appendChild(_actBtn("Voir À enregistrer ("+pending.length+")","metrics-filter",{"data-filter":"pending"}));
b.appendChild(r);return b;
}
function _renderMetricsSessions(container,met){
const recs=met.records||[],pending=met.pending_sessions||[],ignored=met.ignored_sessions||[];
if(pending.length>0&&state.metricsFilter!=="pending")container.appendChild(_renderPendingBanner(pending,false));
const cp=el("section","panel"),cH=_d("panel-head"),fT=_d("subtabs"),rC=_d("actions-row");
[["recorded","Enregistrées ("+recs.length+")"],["pending","À enregistrer ("+pending.length+")"],["ignored","Ignorées ("+ignored.length+")"],["all","Toutes ("+(recs.length+pending.length+ignored.length)+")"]].forEach(([id,l])=>fT.appendChild(_actBtn(l,"metrics-filter",{"data-filter":id},state.metricsFilter===id?"active":"")));
cH.appendChild(fT);
rC.appendChild(_mkSel("g-metrics-sort","Tri technique",[["date","Tri : Récentes"],["useful_tokens","Tri : Tokens utiles"],["max_context","Tri : Pic contexte"],["errors","Tri : Erreurs"],["latency","Tri : Latence p95"]],state.metricsSort));
rC.appendChild(_actBtn("Comparateur A/B","toggle-compare",{},state.compareOpen?"active":""));cH.appendChild(rC);cp.appendChild(cH);container.appendChild(cp);
if(state.compareOpen)container.appendChild(_renderComparatorPanel(met));
const lw=_d("agent-grid");
if(state.metricsFilter==="pending"||state.metricsFilter==="all")pending.forEach((p)=>lw.appendChild(_renderPendingCard(p,false)));
if(state.metricsFilter==="ignored"||state.metricsFilter==="all")ignored.forEach((ig)=>lw.appendChild(_renderPendingCard(ig,true)));
if(state.metricsFilter==="recorded"||state.metricsFilter==="all")_sortRecords(recs,state.metricsSort).forEach((r)=>lw.appendChild(_renderSessionCard(r)));
container.appendChild(lw.children.length?lw:_d("empty","Aucune session dans cette vue."));
}
const _audModelsTxt=(lm)=>{const pm=(lm&&Array.isArray(lm.primary_models))?lm.primary_models:[];return pm.length?pm.slice(0,3).map((m)=>(shortModelName(m.model)||m.model)+" ("+Math.round(Number(m.share_pct||0))+"%)").join(" · "):"Aucun modèle lié"};
function _renderAuditComparator(audits){
const wrap=_d("drawer"),hd=_d("panel-head"),pr=_d("actions-row"),pick=(k,d)=>audits.find((a)=>_audKey(a)===k)||audits[d];
hd.appendChild(_d("panel-title","Comparateur d'Audits A vs B — Tokens & Modèles"));
const aA=pick(state.auditCompareA,audits.length>1?1:0),aB=pick(state.auditCompareB,0),items=audits.map((a)=>[_audKey(a),(a.date?a.date+" · ":"")+String(a.title||_audKey(a))]);
pr.appendChild(_s("kpi-lbl","Réf A"));pr.appendChild(_mkSel("g-audit-cmp-a","Réf A",items,_audKey(aA)));
pr.appendChild(_s("kpi-lbl","Cible B"));pr.appendChild(_mkSel("g-audit-cmp-b","Cible B",items,_audKey(aB)));
hd.appendChild(pr);wrap.appendChild(hd);
const lmA=(aA&&aA.linked_metrics)||{},lmB=(aB&&aB.linked_metrics)||{};
const aT=Number(lmA.avg_tokens_per_session||0),bT=Number(lmB.avg_tokens_per_session||0),aU=Number(lmA.avg_useful_tokens_per_session||0),bU=Number(lmB.avg_useful_tokens_per_session||0),aC=Number(lmA.avg_cache_hit_rate_pct||0),bC=Number(lmB.avg_cache_hit_rate_pct||0);
const pct=(x,y)=>x>0?Math.round(((y-x)/x)*100):(y>0?100:0),dT=pct(aT,bT),dU=pct(aU,bU),dC=+(bC-aC).toFixed(1),ks=_d("kpi-strip");
[["Moy. tokens / sess.",fmtTokens(aT)+" → "+fmtTokens(bT),(dT>0?"+":"")+dT+" %",dT<=0?"ok":"warn"],
["Moy. utiles / sess.",fmtTokens(aU)+" → "+fmtTokens(bU),(dU>0?"+":"")+dU+" %",dU<=0?"ok":"warn"],
["Cache Hit moyen",fmtPct(aC)+" → "+fmtPct(bC),(dC>=0?"+":"")+dC+" pts",dC>=0?"ok":"warn"],
["Sessions liées",fmtInt(lmA.sessions_count||0)+" vs "+fmtInt(lmB.sessions_count||0),"Normalisé par moyenne",""]
].forEach(([l,v,s,t])=>ks.appendChild(renderMetricKpiCard(l,v,s,t)));
wrap.appendChild(ks);
const mb=_d("notice actions-row");mb.appendChild(_s("kpi-lbl","Modèles dominants :"));mb.appendChild(makeBadge("A : "+_audModelsTxt(lmA),""));mb.appendChild(_s("mono","→"));mb.appendChild(makeBadge("B : "+_audModelsTxt(lmB),"info"));wrap.appendChild(mb);
const cA=lmA.by_category||{},cB=lmB.by_category||{},cats=Array.from(new Set(Object.keys(cA).concat(Object.keys(cB))));
if(cats.length){
const mx=Math.max(...cats.flatMap((c)=>[Number((cA[c]&&cA[c].avg_tokens_per_session)||0),Number((cB[c]&&cB[c].avg_tokens_per_session)||0)]),1),db=_d("ws-list");
cats.forEach((c,i)=>{const eA=cA[c]||{},eB=cB[c]||{};db.appendChild(renderAbCompareRow(String(eB.label||eA.label||ROLE_LABELS_FR[c]||c),Number(eA.avg_tokens_per_session||0),Number(eB.avg_tokens_per_session||0),mx,fmtTokens,{color:"var(--g-c"+((i%6)+1)+")"}))});
wrap.appendChild(db);
}else wrap.appendChild(_d("kpi-sub","Aucune ventilation par catégorie sur ces audits."));
return wrap;
}
function _renderMetricsAudits(container,met){
const ap=el("section","panel"),ah=_d("panel-head"),audits=met.audits||[];ah.appendChild(_d("panel-title","Audits Agents ("+audits.length+")"));ap.appendChild(ah);
if(met.index_audit){
const ic=_d("notice"),r=_d("panel-head"),bs=_d("actions-row");r.appendChild(_s(null,"Index Audits Agents : "+(met.index_audit.title||met.index_audit.rel_path)));
bs.appendChild(_actBtn("Lire","read-audit",{"data-audit-id":met.index_audit.audit_id||met.index_audit.rel_path},"btn-primary"));
if(met.index_audit.uri)bs.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":met.index_audit.uri}));
r.appendChild(bs);ic.appendChild(r);ap.appendChild(ic);
}
if(!audits.length){ap.appendChild(_d("empty","Aucun audit agent Markdown découvert dans audits/agents/."));container.appendChild(ap);return}
if(audits.length>=2)ap.appendChild(_renderAuditComparator(audits));
const grid=_d("grid-cards");
audits.forEach((a)=>{
const aid=_audKey(a),lm=a.linked_metrics||{},card=el("article","agent-card"),hd=_d("agent-head"),pills=_d("pill-list"),acts=_d("actions-row");
hd.appendChild(_d("agent-role",String(a.title||a.rel_path||"Audit")));hd.appendChild(makeBadge(a.verdict||"—",a.verdict_tone||""));card.appendChild(hd);
[a.workspace||"workspace",a.date||"—",fmtBytes(a.size_bytes)].forEach((v)=>pills.appendChild(_s("pill",String(v))));
if(lm.sessions_count>0)pills.appendChild(makeBadge(lm.sessions_count+" sess. · moy "+fmtTokens(lm.avg_tokens_per_session||0),"info"));
card.appendChild(pills);if(a.excerpt)card.appendChild(_d("preview-text",String(a.excerpt)));
acts.appendChild(_actBtn("Lire","read-audit",{"data-audit-id":aid},"btn-primary"));
if(a.uri)acts.appendChild(_actBtn("Ouvrir .md","open-file",{"data-uri":a.uri}));
if(audits.length>=2){acts.appendChild(_actBtn("A","pin-audit-compare",{"data-slot":"A","data-audit-id":aid},state.auditCompareA===aid?"active":""));acts.appendChild(_actBtn("B","pin-audit-compare",{"data-slot":"B","data-audit-id":aid},state.auditCompareB===aid?"active":""))}
card.appendChild(acts);grid.appendChild(card);
});
ap.appendChild(grid);container.appendChild(ap);
}
function renderMetricsContent(container){
const met=state.metrics;if(!met){container.appendChild(_d("empty","Chargement de l'historique..."));return}
const sp=el("section","panel"),sh=_d("panel-head"),st=_d("subtabs"),recs=met.records||[],pend=met.pending_sessions||[],auds=met.audits||[],isS=state.metricsSub==="sessions";
[["sessions","Sessions ("+recs.length+(pend.length?" + "+pend.length+" à enr.":"")+")",isS],["overview","Synthèse & Audits"+(auds.length?" ("+auds.length+")":""),!isS]].forEach(([id,l,a])=>st.appendChild(el("button","btn"+(a?" active":""),l,{type:"button","data-action":"metrics-sub","data-sub":id})));
sh.appendChild(st);if(met.metrics_md_uri)sh.appendChild(_actBtn("Ouvrir METRICS.md","open-file",{"data-uri":met.metrics_md_uri}));sp.appendChild(sh);
if(isS)_renderMetricsSessions(sp,met);
else{if(pend.length>0)sp.appendChild(_renderPendingBanner(pend,true));if(state.metricsSub==="audits"){_renderMetricsAudits(sp,met);_renderMetricsOverview(sp,met)}else{_renderMetricsOverview(sp,met);_renderMetricsAudits(sp,met)}}
container.appendChild(sp);_syncMetricsSlideOver(container,met);
}
function renderMetricsUnifiedView(container){
const met=state.metrics,bar=el("section","panel"),hd=_d("panel-head"),ctrls=_d("actions-row");
hd.appendChild(_d("panel-title","Historique — Sessions & Audits Agents"));
const wsL=(met&&Array.isArray(met.workspaces)&&met.workspaces.length)?met.workspaces.slice():((met&&met.projects)?met.projects.slice():[]);
if(state.metricsProject&&!wsL.some((w)=>String(w).toLowerCase()===String(state.metricsProject).toLowerCase()))wsL.push(state.metricsProject);
const curP=wsL.find((p)=>String(p).toLowerCase()===String(state.metricsProject||"").toLowerCase()&&state.metricsProject)||"";
ctrls.appendChild(_mkSel("g-metrics-project","Filtrer par dépôt",[["","Tous les dépôts"]].concat(wsL.map((p)=>[p,p])),curP));
const sw=_s("search-wrap"),si=el("input","input",null,{id:"g-metrics-q",type:"search",placeholder:"Rechercher label, modèle, ID...",value:state.metricsQ||"","data-global-search":"1"});
si.value=state.metricsQ||"";sw.appendChild(si);sw.appendChild(_s("kbd-hint","/"));ctrls.appendChild(sw);
hd.appendChild(ctrls);bar.appendChild(hd);container.appendChild(bar);
const body=el("div",null,null,{id:"g-metrics-content"});Object.assign(body.style,{display:"flex",flexDirection:"column",gap:"10px"});
renderMetricsContent(body);container.appendChild(body);
}
if(typeof document!=="undefined"&&typeof document.addEventListener==="function"){
const _deferRefreshMetrics=()=>setTimeout(()=>{if(!state.slideOver&&typeof renderMetricsBodyOrFull==="function"&&document.getElementById("g-metrics-content"))renderMetricsBodyOrFull()},0);
document.addEventListener("click",(ev)=>{
const t=ev.target&&ev.target.closest?ev.target.closest("[data-action]"):null;if(!t)return;
const act=t.getAttribute("data-action");
if(act==="close-slideover"){if(t.classList&&t.classList.contains("slide-over-backdrop")&&ev.target!==t)return;_clearMetricsSlideState();_deferRefreshMetrics()}
else if(act==="select-tab"&&t.getAttribute("data-tab")!=="metrics"&&(state.slideOver||state.sessionTarget||state.auditTarget)){_clearMetricsSlideState();state.slideOver=null}
});
document.addEventListener("keydown",(ev)=>{if(ev.key==="Escape"&&state.slideOver&&(state.sessionTarget||state.auditTarget)){_clearMetricsSlideState();_deferRefreshMetrics()}});
}
"""

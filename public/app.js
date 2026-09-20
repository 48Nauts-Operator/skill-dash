'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const acolors = {keep:'#4fc3b0',rewrite_description:'#80b8f2',merge:'#ba91e5',delete:'#f17b89',unclear:'#9b9baf'};
const alabels = {keep:'Keep',rewrite_description:'Rewrite',merge:'Merge',delete:'Delete',unclear:'Unclear'};
const dcolors = {keep:'#4fc3b0',rewrite:'#80b8f2',merge:'#ba91e5',delete:'#f17b89'};
const scolors = ['#f17b89','#f0a05a','#7fb8ad','#4fc3b0'];
const icons = {
 judges:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="9" cy="18" r="2"/>',
 overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 skills:'<path d="M4 4h16v6H4zM4 14h16v6H4z"/><path d="M8 7h.01M8 17h.01"/>',
 decide:'<path d="M12 3 2 20h20L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
 activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 find:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
 settings:'<circle cx="12" cy="12" r="3"/><path d="m10 2-1 3-3 1-3-1-1 4 2 2v3l-2 2 2 4 3-1 3 1 1 2 4-1 1-3 3-1 2-3-2-2v-3l1-3-4-2-2 1Z"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const VIEWS = ['overview','skills','decide','find','activity','judges'];
let data = null, filter = 'all', query = '', page = 1, view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview', selected = new Set(), activeSkill = null, busy = false, returnFocus = null;
if (view === 'decide') filter = 'undecided';
let prefs = {provider:'jev',workers:3,limit:200};
try { prefs = {...prefs,...JSON.parse(localStorage.getItem('skilldash-preferences') || '{}')}; } catch {}
prefs.provider = 'jev';
const pageSize = 15;
const fmt = x => Number(x || 0).toLocaleString('en-US');
const date = x => { const d = new Date(x); return Number.isFinite(+d) ? d.toLocaleDateString('en-GB',{day:'2-digit',month:'short'}) : '—'; };
const ago = x => { const d = new Date(x); if(!Number.isFinite(+d)) return 'never'; const days=Math.floor((Date.now()-d)/864e5); return days===0?'today':days===1?'1 day ago':`${days} days ago`; };
const running = () => data?.job && ['running','paused','stopping'].includes(data.job.status);
const rec = s => s.result?.answers?.action?.choice;
const useful = s => s.result?.answers?.useful?.score;
const unused = s => !!s.evidence && !s.evidence.invocations && !s.evidence.slash;
const noEvidence = () => data?.scan?.status==='skipped';
function toast(message, error=false) { $('toast').textContent=message; $('toast').className=error?'error':''; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,6000); }
async function api(path, body) {
 const res = await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await res.json(); if(!res.ok) throw new Error(value.error || `Request failed (${res.status})`); return value;
}
async function refresh() {
 try { data=await api('/api/state'); $('connection-label').textContent='Workspace connected'; render(); }
 catch(e) { $('connection-label').textContent='Server offline'; if(!data) toast(e.message,true); }
}
const scoreTag = (v,max=3) => v==null?'<span class="muted">—</span>':`<span class="priority-tag" style="color:${scolors[Math.min(3,Math.round(v/max*3))]}"><i></i>${v.toFixed(2)} / ${max}</span>`;
const actionTag = a => a?`<span class="tag" style="color:${acolors[a]};background:${acolors[a]}10;border-color:${acolors[a]}30"><i></i>${alabels[a]}</span>`:'<span class="muted">Pending</span>';
const decisionTag = d => d?`<span class="tag" style="color:${dcolors[d.decision]};background:${dcolors[d.decision]}10;border-color:${dcolors[d.decision]}30"><i></i>${esc(d.decision)}</span>`:'<span class="muted">—</span>';
const kindBadge = s => `<span class="mini-label">${s.kind==='manifest'?'plugin manifest':s.kind==='plugin'?esc(s.plugin):s.kind==='repo'?'repo':s.imported_from?'imported':s.symlink?'linked':'own'}</span>`;
function filtered() {
 const q=query.trim().toLowerCase();
 let rows=data.skills.filter(s=>{
  if(q&&!(s.id+' '+s.description+' '+s.path).toLowerCase().includes(q))return false;
  if(!matchingJudgment(s))return false;
  switch(filter){
   case 'all':return true; case 'own':return s.kind==='own'; case 'plugin':return s.kind==='plugin';
   case 'unused':return unused(s); case 'pending':return !s.result&&!s.error; case 'errors':return !!s.error; case 'manifest':return s.kind==='manifest';
   case 'undecided':return s.result&&!s.decision; case 'decided':return !!s.decision; case 'flagged':return !!s.risk_flags?.length;
   default: return filter.startsWith('dec:')?s.decision?.decision===filter.slice(4):rec(s)===filter;
  }
 });
 const sort=$('sort').value;
 rows.sort((a,b)=>{
  if(sort==='name')return a.id.localeCompare(b.id);
  if(sort==='useful')return (useful(a)??9)-(useful(b)??9)||a.id.localeCompare(b.id);
  if(sort==='invocations')return (b.evidence?.invocations||0)-(a.evidence?.invocations||0)||a.id.localeCompare(b.id);
  if(sort==='last')return (a.evidence?.last_invoked||'').localeCompare(b.evidence?.last_invoked||'')||a.id.localeCompare(b.id);
  if(sort==='overlap')return (b.overlap?.score||0)-(a.overlap?.score||0)||a.id.localeCompare(b.id);
  return judgmentSortValue(b)-judgmentSortValue(a)||a.id.localeCompare(b.id);
 });
 return rows;
}
function render() {
 if(!data)return;
 initBuilder();
 const skills=data.skills, done=skills.filter(s=>s.result).length, total=skills.length;
 const actions=Object.fromEntries(Object.keys(acolors).map(k=>[k,0])); const levels=[0,0,0,0];
 skills.forEach(s=>{const a=rec(s);if(a)actions[a]++;const u=useful(s);if(u!=null)levels[Math.min(3,Math.round(u))]++;});
 const decided=skills.filter(s=>s.decision).length, never=skills.filter(unused).length, undecided=skills.filter(s=>s.result&&!s.decision).length;
 $('processed-count').textContent=fmt(done);$('total-count').textContent=` / ${fmt(total)}`;
 const percent=total?Math.round(done/total*100):0;$('progress-fill').style.width=percent+'%';$('percent').textContent=percent+'% judged';$('remaining').textContent=fmt(total-done)+' remaining';
 const job=data.job; const recent=job||data.runs[0];
 $('job-status').textContent=job?.status||'Ready';$('progress-caption').textContent=running()?`${job.completed} of ${job.total} judged in this batch${job.failed?` · ${job.failed} failed`:''}`:done===total&&total?'Every skill judged. Now decide.':'Configure your judges, then run.';
 $('run-button').disabled=!!running()||busy||!data.config.jev_available||data.scan.status==='running'||!Object.keys(selectedQuestions()).length;
 $('run-button').textContent=running()?'Judging…':selected.size?`▶ Judge ${selected.size} selected`:done===total&&total?'↻ Judge again':'▶ Judge skills';
 $('pause-button').hidden=!running();$('pause-button').disabled=job?.status==='stopping';$('pause-button').textContent=job?.status==='paused'?'Resume':'Pause';$('stop-button').hidden=!running();$('stop-button').disabled=job?.status==='stopping';
 const ov=data.overlap;$('overlap-indicator').hidden=ov.status!=='running';$('overlap-label').textContent=ov.status==='running'?`Overlap audit ${ov.progress||'starting'}${ov.roots>1?` · root ${ov.root}/${ov.roots}`:''}`:'';
 $('engine-label').textContent=data.config.jev_available?`Jev · ${Object.keys(selectedQuestions()).length} parallel judgments · hosted`:'Jev credential missing · see Settings';
 const own=skills.filter(s=>s.kind==='own').length;
 $('source-label').textContent=data.roots?.length?`${total} skills in ${data.roots.map(r=>r.split('/').slice(-2).join('/')).join(', ')} · content only`:data.scan.status==='running'?`${total} skills · scanning transcripts…`:`${own} own · ${total-own} plugin · ${fmt(data.scan.transcripts||0)} transcripts`;
 $('footer-note').textContent=`${data.scan.since?'Evidence since '+date(data.scan.since):'No transcripts scanned'} · ${data.overlap.pairs?fmt(data.overlap.pairs)+' overlap pairs':'no overlap audit yet'} · ${decided} decided`;
 const judged=Object.values(actions).reduce((a,b)=>a+b,0);let offset=0;const circumference=2*Math.PI*56;
 const slices=Object.entries(actions).map(([k,v])=>{const dash=judged?v/judged*circumference:0;const svg=`<circle cx="70" cy="70" r="56" fill="none" stroke="${acolors[k]}" stroke-width="13" stroke-dasharray="${Math.max(0,dash-1.6)} ${circumference}" stroke-dashoffset="${-offset}"/>`;offset+=dash;return v?svg:'';}).join('');
 $('donut').innerHTML=`<div class="donut-wrap"><svg viewBox="0 0 140 140" role="img" aria-label="${judged} judged skills"><circle cx="70" cy="70" r="56" fill="none" stroke="#2b2622" stroke-width="13"/>${slices}</svg><div class="donut-center">${fmt(judged)}<span>JUDGED</span></div></div>`;
 $('category-total').textContent=fmt(judged)+' judged';$('category-legend').innerHTML=Object.entries(actions).map(([k,v])=>`<button class="legend-item ${filter===k?'active':''}" data-filter="${k}"><i style="background:${acolors[k]}"></i>${alabels[k]}<b>${fmt(v)}</b></button>`).join('');
 $('signals').innerHTML=[['delete','Delete candidates','#f17b89','Jev says remove',actions.delete],['unused','Never invoked','#f0a05a','No Skill-tool use on record',never],['undecided','Awaiting decision','#91b9ee','Judged, not decided',undecided]].map(([k,label,c,sub,v])=>`<button class="signal" data-filter="${k}"><span>${label}</span><strong style="color:${c}">${fmt(v)}</strong><small>${sub}</small></button>`).join('');
 $('priority-bars').innerHTML=[['3','Essential'],['2','Useful'],['1','Marginal'],['0','Adds nothing']].map(([k,label])=>`<div class="priority-row"><span>${label}</span><div class="bar-track"><div class="bar" style="background:${scolors[k]};width:${done?levels[k]/done*100:0}%"></div></div><b>${fmt(levels[k])}</b></div>`).join('');
 const latencies=[...(recent?.latencies||[])].sort((a,b)=>a-b);const avg=latencies.length?latencies.reduce((a,b)=>a+b,0)/latencies.length:null;
 $('metrics').innerHTML=[['AVG. LATENCY',avg===null?'—':avg.toFixed(0),avg===null?'':'ms',recent?'Jev API · per skill':'No completed run yet'],['THROUGHPUT',recent?.elapsed_s?(recent.completed/recent.elapsed_s).toFixed(2):'—','skills/s','Batch wall time, including retries'],['TOKENS USED',recent?fmt((recent.input_tokens||0)+(recent.output_tokens||0)):'—','','Measured from API usage'],['DECIDED',total?`${decided}`:'—',total?`/ ${total}`:'','Keep, rewrite, merge or delete'],['NEVER INVOKED',data.scan.transcripts?`${never}`:'—',data.scan.transcripts?`/ ${total}`:'',data.scan.since?`Since ${date(data.scan.since)} · ${fmt(data.scan.transcripts)} transcripts`:noEvidence()?'No transcript evidence for this tree':'Scan pending']].map(([label,n,unit,caption])=>`<div class="metric"><div class="metric-label">${label}</div><div class="metric-number">${n} <small>${unit}</small></div><div class="metric-caption">${caption}</div></div>`).join('');
 renderTable(actions,{never,undecided,decided});renderActivity();
 $('nav').innerHTML=[['overview','Overview'],['skills','Skills'],['decide','Decide'],['find','Upgrade'],['judges','Judges'],['activity','Run history']].map(([k,n])=>`<button class="nav-button ${view===k?'active':''}" data-view="${k}" aria-label="${n}" title="${n}" ${view===k?'aria-current="page"':''}>${icon(k)}</button>`).join('');
 $('page-title').textContent=view==='judges'?'Judges.':view==='decide'?'Your call.':view==='find'?'Upgrade your skills.':view==='activity'?'Every run, accounted for.':view==='skills'?'Everything, in its place.':'Fewer skills. Sharper triggers.';
 $('page-description').textContent=view==='judges'?'Add a section, choose Choice, Noul or Score, and tell it what to look for.':view==='decide'?'Judged skills waiting for a keep, rewrite, merge or delete.':view==='find'?'Skills from the public corpus that fit the way you work, judged on their full text against your profile.':view==='activity'?'Actual results, latency and usage. No invented numbers.':'Decide what to keep, rewrite, merge or delete, on evidence.';
 $('judges-section').hidden=view!=='judges';
 $('dashboard-overview').hidden=view==='judges'||view==='find';$('metrics').hidden=view==='judges'||view==='find';
 $('inbox-section').hidden=view==='activity'||view==='judges'||view==='find';$('activity-section').hidden=view!=='activity';$('find-section').hidden=view!=='find';
 renderFind();
 document.querySelector('.heading-actions').hidden=view==='judges';
}
function navigate(next) {
 if(!VIEWS.includes(next))next='overview';
 closeDrawer();view=next;filter=view==='decide'?'undecided':'all';page=1;
 if(location.hash.slice(1)!==next)location.hash=next;
 render();$('page-title').focus();
}
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1)||'overview';if(next!==view)navigate(next);});
function renderTable(actions,counts) {
 const s=data.skills;const pending=s.filter(x=>!x.result&&!x.error).length,errors=s.filter(x=>x.error).length;
 $('filters').innerHTML=[['all','All skills',s.length],['own','Own',s.filter(x=>x.kind==='own').length],['plugin','Plugin',s.filter(x=>x.kind==='plugin').length],['unused','Never invoked',counts.never],['flagged','⚠ Flagged',s.filter(x=>x.risk_flags?.length).length],...(s.some(x=>x.kind==='manifest')?[['manifest','Plugin manifests',s.filter(x=>x.kind==='manifest').length]]:[]),...Object.keys(acolors).map(k=>[k,alabels[k],actions[k]]),['undecided','Undecided',counts.undecided],['decided','Decided',counts.decided],['pending','Pending',pending],...(errors?[['errors','Errors',errors]]:[])].map(([k,n,v])=>`<button class="filter ${filter===k?'active':''}" data-filter="${k}">${esc(n)}<em>${v}</em></button>`).join('');
 const rows=filtered();page=Math.min(page,Math.max(1,Math.ceil(rows.length/pageSize)));const visible=rows.slice((page-1)*pageSize,page*pageSize);
 $('list-title').textContent=({all:'All skills',own:'Own skills',plugin:'Plugin skills',unused:'Never invoked',flagged:'Flagged by the static pre-scan',manifest:'Plugin manifests: hooks, MCP servers, commands',undecided:'Awaiting decision',decided:'Decided',pending:'Pending',errors:'Processing errors'}[filter]||alabels[filter]||filter);$('filtered-count').textContent=fmt(rows.length);
 $('rows').innerHTML=visible.map(x=>{const e=x.evidence;return `<tr><td class="check-cell"><input type="checkbox" data-select="${esc(x.id)}" aria-label="Select ${esc(x.id)}" ${selected.has(x.id)?'checked':''}></td><td class="sender"><div class="sender-wrap"><span class="sender-avatar">${esc(x.name.slice(0,2).toUpperCase())}</span><span>${esc(x.name)}</span></div></td><td><button class="subject-button" data-skill="${esc(x.id)}"><span class="subject-title">${esc(x.id)}${kindBadge(x)}${x.risk_flags?.length?`<span class="flag-badge" title="${esc(x.risk_flags.map(f=>f.flag).join(', '))}">⚠ ${x.risk_flags.length}</span>`:''}</span><span class="preview">${esc(x.description.replace(/\s+/g,' '))}</span></button></td><td>${x.error?'<span class="tag" style="color:#ef8e8e;border-color:#7e4646">Error · retry</span>':scoreTag(useful(x))}</td><td>${x.error?'—':actionTag(rec(x))}</td><td class="confidence-cell">${e?`${fmt(e.invocations)}${e.slash?` <small>+${e.slash} slash</small>`:''}<br><small>${e.last_invoked?ago(e.last_invoked):e.script_mentions?`scripts ×${fmt(e.script_mentions)}`:'never'}</small>`:noEvidence()?'<small>n/a</small>':'<small>scanning…</small>'}</td><td class="confidence-cell">${x.overlap?`${x.overlap.score.toFixed(2)}<br><small>${esc(x.overlap.with)}</small>`:'—'}</td><td>${decisionTag(x.decision)}</td><td class="results-cell">${judgmentChips(x)}</td></tr>`;}).join('')||'<tr><td colspan="9" class="empty"><strong>Nothing here.</strong>Try another filter or search term.</td></tr>';
 $('page-info').textContent=rows.length?`Showing ${(page-1)*pageSize+1}–${Math.min(page*pageSize,rows.length)} of ${fmt(rows.length)} skills`:'No matching skills';$('page-number').textContent=`${page} / ${Math.max(1,Math.ceil(rows.length/pageSize))}`;$('prev-page').disabled=page<=1;$('next-page').disabled=page*pageSize>=rows.length;
 $('select-page').checked=visible.length>0&&visible.every(x=>selected.has(x.id));$('select-page').indeterminate=visible.some(x=>selected.has(x.id))&&!$('select-page').checked;
 $('selection-bar').hidden=selected.size===0;$('selection-bar').innerHTML=`<span>${selected.size} selected</span><button class="text-button" id="select-all-matching">Select all ${rows.length} matching</button><button class="text-button" id="clear-selection">Clear</button>`;
}
let findData=null, findLoadedAt='', findLimit=5;
const BASIS={rule:'answers a rule in your CLAUDE.md you follow by hand today',request:'matches something you asked for recently',extends:'extends one of your most used skills',stack:'fits the stack your profile shows you run',none:'is generally relevant to your work'};
function whyText(x){
 const parts=[];
 if(x.basis)parts.push(`It ${BASIS[x.basis]||BASIS.none}${x.basis_conf!=null?` (${Math.round(x.basis_conf*100)}% sure)`:''}.`);
 parts.push(`Fit ${x.fit.toFixed(1)} of 3 at ${Math.round(x.fit_conf*100)}% confidence`+(x.matched?.length?`, on ${x.matched.slice(0,4).map(esc).join(', ')}`:'')+'.');
 parts.push(x.covered>=0.5?`Careful: ${Math.round(x.covered*100)}% chance ${esc(x.closest_own||'one of yours')} already does this.`:`${Math.round(x.covered*100)}% chance you already have it${x.closest_own?` (nearest: ${esc(x.closest_own)})`:''}, so it adds a job.`);
 if(x.alternatives?.length)parts.push(`${x.alternatives.length} other skill${x.alternatives.length>1?'s':''} do the same job; this one scored best.`);
 return parts.join(' ');
}
async function renderFind() {
 const r=data.recommend||{};
 $('find-button').disabled=r.status==='running'||!data.config.jev_available||!!data.roots?.length;
 $('find-status').textContent=r.status==='running'?`${r.stage==='fetching'?'Fetching candidate files':r.stage==='judging'?'Jev is reading':'Profiling'}… ${r.done||0} / ${r.total||0}`:r.status==='error'?r.error:r.status==='done'?`Last search ${date(r.finished_at)} · ${fmt(r.candidates)} candidates read · ${fmt(r.tokens)} tokens`:data.roots?.length?'Find works on your own tree; start without --roots.':'';
 if(view!=='find')return;
 if((r.status==='done'&&findLoadedAt!==r.finished_at)||(!findData&&!findLoadedAt)){try{findData=await api('/api/recommend');findLoadedAt=r.finished_at||'loaded';}catch{}}
 const rows=(findData?.clusters||findData?.results||[]).filter(x=>x.fit!=null);
 const pr=findData?.profile_read, ps=findData?.profile_summary; $('find-intro').hidden=!findData; $('find-charts').hidden=!(findData&&pr&&!pr.error);
 if(findData&&pr&&!pr.error){
  const fcol={software_development:'#4fc3b0',agent_tooling:'#f7ab71',devops_and_infrastructure:'#4d86cc',data_and_research:'#ba91e5',product_and_writing:'#e7ba6d',marketing_and_business:'#ed879a',security:'#f17b89',unclear:'#9b9baf'};
  const fp=Object.entries(pr.focus_probs).sort((a,b)=>b[1]-a[1]);let off=0;const C=2*Math.PI*56;
  const slices=fp.map(([k,v])=>{const dash=v*C;const svg=v>0.005?`<circle cx="70" cy="70" r="56" fill="none" stroke="${fcol[k]||'#9b9baf'}" stroke-width="13" stroke-dasharray="${Math.max(0,dash-1.6)} ${C}" stroke-dashoffset="${-off}"/>`:'';off+=dash;return svg;}).join('');
  $('focus-donut').innerHTML=`<div class="donut-wrap"><svg viewBox="0 0 140 140" role="img" aria-label="Focus distribution"><circle cx="70" cy="70" r="56" fill="none" stroke="#2b2622" stroke-width="13"/>${slices}</svg><div class="donut-center">${Math.round(fp[0][1]*100)}%<span>${esc(fp[0][0].replaceAll('_',' ').toUpperCase().slice(0,14))}</span></div></div>`;
  $('focus-legend').innerHTML=fp.filter(([,v])=>v>=0.005).map(([k,v])=>`<div class="legend-item"><i style="background:${fcol[k]||'#9b9baf'}"></i>${esc(k.replaceAll('_',' '))}<b>${Math.round(v*100)}%</b></div>`).join('');
  const levels=['Occasional','Regular','Established','Advanced'];const pcol=['#f17b89','#f0a05a','#7fb8ad','#4fc3b0'];
  $('practice-bars').innerHTML=[3,2,1,0].map(i=>`<div class="priority-row"><span>${levels[i]}</span><div class="bar-track"><div class="bar" style="background:${pcol[i]};width:${(pr.practice_probs[String(i)]||0)*100}%"></div></div><b>${Math.round((pr.practice_probs[String(i)]||0)*100)}%</b></div>`).join('');
  $('practice-label').textContent=`${pr.practice.toFixed(1)} of 3`;$('practice-text').textContent=pr.practice_legend[String(Math.round(pr.practice))];
  const used=Object.entries(ps.used_counts||{});const max=Math.max(1,...used.map(([,v])=>v));
  $('used-bars').innerHTML=used.length?used.map(([k,v])=>`<div class="priority-row"><span title="${esc(k)}">${esc(k.replace(/^superpowers:/,'sp:'))}</span><div class="bar-track"><div class="bar" style="background:#f7ab71;width:${v/max*100}%"></div></div><b>${v}</b></div>`).join(''):'<p class="small-copy">No Skill-tool calls on record yet.</p>';
 }
 if(findData){const title=k=>k.replaceAll('_',' ').replace(' and ',' and ');const used=Object.entries(ps.used_counts||{}).map(([k,v])=>`<b>${esc(k)}</b> (${v})`).join(', ')||'none through the Skill tool';
  const top2=pr&&!pr.error?Object.entries(pr.focus_probs).sort((a,b)=>b[1]-a[1]).slice(0,2):[];
  $('find-intro').innerHTML=pr&&!pr.error?`<p>Your work with the agent centres on <b>${esc(title(pr.focus))}</b> <span class="dist">${top2.map(([k,v])=>`${esc(title(k))} ${Math.round(v*100)}%`).join(' · ')}</span>. Your most used skills are ${used}${findData.with_prompts?`, judged with your last ${ps.requests} opening prompts`:''}. Jev reads your agent practice as <b>${pr.practice.toFixed(1)} of 3</b>: ${esc(pr.practice_legend[String(Math.round(pr.practice))])}</p><p>From ${fmt(findData.pool)} unique skills in the public corpus, ${findData.candidates} were read in full against that profile. These are the ones that would add to what you have, one per job, best first.</p>`:`<p>Profile read unavailable (${esc(pr?.error||'no run')}). Results below are ranked by fit against your CLAUDE.md and skills.</p>`;}
 $('find-summary').textContent=findData?`Profile: ${findData.profile_summary.own_skills} own skills, most used ${findData.profile_summary.most_used.slice(0,5).join(', ')||'none'}${findData.with_prompts?`, ${findData.profile_summary.requests} recent prompts`:''}. Pool ${fmt(findData.pool)} unique corpus skills, ${findData.candidates} read by Jev, ${rows.length} distinct jobs.`:$('find-summary').textContent;
 $('find-more').hidden=rows.length<=findLimit;$('find-count').textContent=rows.length?`showing ${Math.min(findLimit,rows.length)} of ${rows.length} jobs`:'';
 $('find-rows').innerHTML=rows.slice(0,findLimit).map(x=>`<tr><td><a href="https://github.com/${esc(x.r)}/blob/${esc(x.c)}/${esc(x.p)}/SKILL.md"><b>${esc(x.n)}</b></a><br><small>${esc(x.r)}</small><br><span class="preview" style="white-space:normal">${esc(x.d)}</span>${x.alternatives?.length?`<br><small>same job: ${x.alternatives.map(a=>`<a href="https://github.com/${esc(a.r)}/blob/${esc(a.c)}/${esc(a.p)}/SKILL.md">${esc(a.n)}</a> <span style="color:var(--muted)">(${esc(a.r.split('/')[0])}, gap ${(a.gap??0).toFixed(2)})</span>`).join(' · ')}</small>`:''}</td><td>${scoreTag(x.gap)}</td><td>${scoreTag(x.fit)}<br><small>conf ${Math.round(x.fit_conf*100)}%</small></td><td class="confidence-cell">${Math.round(x.covered*100)}%</td><td style="max-width:340px;white-space:normal;font-size:11.5px;color:#cfc4ba;line-height:1.5">${whyText(x)}</td><td>${x.flags?.length?`<span class="flag-badge" title="${esc(x.flags.join(', '))}">⚠ ${esc(x.flags.join(', '))}</span>`:'<small>clean</small>'}${x.j!=null?`<br><small>Jev risk ${x.j}</small>`:''}${x.cp?`<br><small>${x.cp} copies elsewhere</small>`:''}${x.dupes?`<br><small>${x.dupes} identical in the cut</small>`:''}</td><td><code style="font-size:10px;white-space:normal">git clone --depth 1 https://github.com/${esc(x.r)} /tmp/${esc(x.r.split('/')[1])} && cp -r /tmp/${esc(x.r.split('/')[1])}/${esc(x.p)} ~/.claude/skills/${esc(x.n)}</code></td></tr>`).join('')||'<tr><td colspan="7" class="empty"><strong>No search yet.</strong>Press Find skills. Nothing is written to your tree.</td></tr>';
}
$('find-more').onclick=()=>{findLimit+=5;renderFind();};
$('find-button').onclick=async()=>{findLimit=5;try{await api('/api/recommend',{k:Number($('find-k').value),with_prompts:$('find-prompts').checked,include_flagged:$('find-flagged').checked});await refresh();toast('Search started. Candidates are fetched from GitHub at their pinned commits, then read by Jev.');}catch(e){toast(e.message,true);}};
function renderActivity() {
 $('activity-list').innerHTML=data.runs.map(r=>`<div class="activity-row"><div>Jev · live API<small>${esc(r.id)} · ${Object.keys(r.questions||{}).map(judgmentTitle).map(esc).join(", ")}</small></div><div>${fmt(r.succeeded)} succeeded · ${fmt(r.failed)} failed<small>${esc(r.status)} · ${r.total-r.completed} unprocessed</small></div><div>${r.elapsed_s.toFixed(2)} seconds<small>${r.workers} concurrent workers</small></div><div>${date(r.started_at)}<small>${fmt(r.input_tokens+r.output_tokens)} tokens</small></div></div>`).join('')||'<div class="empty"><strong>A clean slate.</strong>Run your first batch to see measured results here.</div>';
}
function setFilter(value){filter=value;page=1;if(view==='activity')view='skills';render();}
function closeDrawer(){if($('drawer').hidden)return;$('drawer').hidden=true;$('drawer-backdrop').hidden=true;activeSkill=null;document.body.style.overflow='';document.querySelector('.workspace').inert=false;document.querySelector('.rail').inert=false;if(returnFocus?.isConnected)returnFocus.focus();}
async function showSkill(id) {
 const s=data.skills.find(x=>x.id===id);if(!s)return;if($('drawer').hidden)returnFocus=document.activeElement;activeSkill=id;const pred=s.result,e=s.evidence,d=s.decision;
 $('drawer').innerHTML=`<div class="drawer-top"><span class="eyebrow">${s.kind==='plugin'?'PLUGIN SKILL · '+esc(s.plugin).toUpperCase():s.imported_from?'IMPORTED SKILL':'OWN SKILL'}</span><button class="icon-button" id="close-drawer" aria-label="Close">×</button></div>${actionTag(rec(s))} ${decisionTag(d)}<h2>${esc(s.id)}</h2><div class="message-meta"><b>Path</b> ${esc(s.path)}${s.symlink?' (symlink)':''}<br>${s.imported_from?`<b>From</b> ${esc(s.imported_from)}<br>`:''}<b>Installed</b> ${date(s.installed_at)} · <b>Body</b> ${fmt(s.body_chars)} chars${s.disable_model_invocation?' · slash-only':''}${s.scripts.length?`<br><b>Scripts</b> ${s.scripts.map(esc).join(', ')}`:''}</div><div class="message-body">${esc(s.description)}</div><div class="eyebrow">EVIDENCE</div><div class="judgment-grid">${e?`<div class="judgment"><span>SKILL-TOOL INVOCATIONS</span><strong>${fmt(e.invocations)}</strong><p class="field-help">${e.last_invoked?'Last '+date(e.last_invoked)+' ('+ago(e.last_invoked)+')':'Never on record'}</p></div><div class="judgment"><span>SLASH MENTIONS</span><strong>${fmt(e.slash)}</strong></div><div class="judgment"><span>SCRIPT MENTIONS</span><strong>${fmt(e.script_mentions)}</strong><p class="field-help">Lines naming this skill's own scripts</p></div>`:'<p class="field-help">Scanning…</p>'}${s.overlaps?.length?`<div class="judgment"><span>OVERLAP</span><strong>${s.overlaps[0].score.toFixed(2)}</strong><p class="field-help">${s.overlaps.map(o=>`${esc(o.with)} ${o.score.toFixed(2)}`).join('<br>')}</p></div>`:''}</div>${s.risk_flags?.length?`<div class="eyebrow">STATIC PRE-SCAN · ${s.risk_flags.length} FLAG${s.risk_flags.length>1?'S':''}</div><div class="judgment">${s.risk_flags.map(f=>`<div class="flag-row"><b>${esc(f.flag)}</b>${esc(f.sample)}<small>${esc(f.where)}</small></div>`).join('')}<p class="field-help">Pattern matches, not verdicts. A deploy script legitimately runs rm on its own build dir. Run the Safety judges for a read of intent.</p></div>`:''}${s.external_hosts?.length?`<p class="field-help"><b>External hosts</b> ${s.external_hosts.map(esc).join(', ')}</p>`:''}${s.error?`<p class="privacy-note">${esc(s.error)}</p>`:''}${pred?radar(s):''}${pred?`<div class="eyebrow">JEV JUDGMENTS</div><div class="judgment-grid">${judgmentDetails(pred)}</div><details><summary>Decision receipt & distributions</summary>${Object.entries(pred.answers?.action?.probabilities||{}).map(([k,v])=>`<div class="distribution"><span>${esc(k)}</span><i style="width:${v*120}px"></i><b>${Math.round(v*100)}%</b></div>`).join('')}<pre>${esc(JSON.stringify({model:pred.model,latency_ms:pred.elapsed_ms,question_version:pred.question_version,usage:pred.usage,questions:pred.questions,answers:pred.answers},null,2))}</pre></details>`:''}<details open><summary>Your decision</summary><form id="decision-form"><label>Decision<select name="decision"><option value="">Undecided</option>${data.config.decisions.map(k=>`<option value="${k}" ${d?.decision===k?'selected':''}>${k}</option>`).join('')}</select></label><label>Note<textarea name="note" rows="3" maxlength="1000" placeholder="merge into prove-it, drop the how/why references…">${esc(d?.note||'')}</textarea></label><button class="button primary" type="submit">Save decision</button></form></details><details><summary>Decision history</summary><div id="audit-content" class="field-help">Loading…</div></details><details><summary>Body excerpt</summary><pre>${esc(s.body_excerpt)}</pre></details>`;
 $('drawer').hidden=false;$('drawer-backdrop').hidden=false;document.body.style.overflow='hidden';document.querySelector('.workspace').inert=true;document.querySelector('.rail').inert=true;$('close-drawer').focus();
 $('close-drawer').onclick=closeDrawer;
 $('decision-form').onsubmit=async ev=>{ev.preventDefault();const f=new FormData(ev.target);try{await api('/api/decide',{id,decision:f.get('decision'),note:f.get('note')});await refresh();toast('Decision saved. Nothing on disk was changed.');showSkill(id);}catch(err){toast(err.message,true);}};
 try {const audits=await api('/api/decisions?id='+encodeURIComponent(id));if(activeSkill===id)$('audit-content').textContent=audits.length?audits.map(a=>`${a.at}: ${a.decision}`).join('\n'):'No decisions yet.';}catch{}
}
// Radar: this skill against the tree average on every "higher is better" axis the current results carry.
const RADAR = {skill:'#d9742c', mean:'#4d86cc'};
function axesFor(s) {
 const a=s.result?.answers||{}; const out=[];
 for(const [id,v] of Object.entries(a)){
  if(v.type==='score')out.push([judgmentTitle(id),v.score/(Object.keys(v.legend).length-1),`${v.score.toFixed(2)} / ${Object.keys(v.legend).length-1}`]);
  else if(v.type==='noul')out.push([judgmentTitle(id),v.noul,`${Math.round(v.noul*100)}% yes`]);
  else if(id==='redundancy'||id==='duplicate')out.push(['Not '+(id==='duplicate'?'duplicate':'redundant'),v.probabilities?.none??0,`${Math.round((v.probabilities?.none??0)*100)}% none`]);
  else if(id==='action')out.push(['Decisive',v.confidence,`${Math.round(v.confidence*100)}% confidence`]);
 }
 if(s.overlaps?.length)out.push(['Distinct',1-s.overlaps[0].score,`1 − overlap ${s.overlaps[0].score.toFixed(2)}`]);
 return out;
}
function radar(s) {
 const axes=axesFor(s); if(axes.length<3)return '';
 const judged=data.skills.filter(x=>x.result); const mean=axes.map(([label])=>{const vals=judged.map(x=>axesFor(x).find(a=>a[0]===label)?.[1]).filter(v=>v!=null);return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:0;});
 const R=66,cx=150,cy=105,n=axes.length,ang=i=>-Math.PI/2+i*2*Math.PI/n,pt=(i,v)=>[cx+Math.cos(ang(i))*R*v,cy+Math.sin(ang(i))*R*v];
 const ring=v=>`<polygon points="${axes.map((_,i)=>pt(i,v).join(',')).join(' ')}" fill="none" stroke="#2b2622" stroke-width="1"/>`;
 const poly=(vals,c,dash)=>`<polygon points="${vals.map((v,i)=>pt(i,v).join(',')).join(' ')}" fill="${c}" fill-opacity="${dash?0:.14}" stroke="${c}" stroke-width="2" ${dash?'stroke-dasharray="4 3"':''}/>`;
 const dots=axes.map(([label,v,text],i)=>{const [x,y]=pt(i,v);return `<circle cx="${x}" cy="${y}" r="4" fill="${RADAR.skill}" stroke="#0f0d0c" stroke-width="2"><title>${esc(label)}: ${esc(text)} · tree average ${Math.round(mean[i]*100)}%</title></circle>`;}).join('');
 const labels=axes.map(([label,v],i)=>{const [x,y]=pt(i,1.3);return `<text x="${x}" y="${y}" text-anchor="${Math.abs(Math.cos(ang(i)))<.2?'middle':Math.cos(ang(i))>0?'start':'end'}" dominant-baseline="middle" fill="#9aa5a0" font-size="8" font-family="ui-monospace,monospace">${esc(label.toUpperCase())} ${Math.round(v*100)}</text>`;}).join('');
 return `<div class="eyebrow">PROFILE</div><div class="judgment" style="padding:8px 6px 4px"><svg viewBox="0 0 300 210" role="img" aria-label="Radar of ${esc(s.id)} against the tree average" style="width:100%;max-width:330px;display:block;margin:auto">${[.25,.5,.75,1].map(ring).join('')}${axes.map((_,i)=>`<line x1="${cx}" y1="${cy}" x2="${pt(i,1)[0]}" y2="${pt(i,1)[1]}" stroke="#2b2622"/>`).join('')}${poly(mean,RADAR.mean,true)}${poly(axes.map(a=>a[1]),RADAR.skill,false)}${dots}${labels}</svg><p class="field-help" style="display:flex;gap:14px;justify-content:center;margin:4px 0 2px"><span><i style="display:inline-block;width:10px;height:2px;background:${RADAR.skill};vertical-align:middle;margin-right:5px"></i>this skill</span><span><i style="display:inline-block;width:10px;height:0;border-top:2px dashed ${RADAR.mean};vertical-align:middle;margin-right:5px"></i>tree average (${judged.length})</span></p></div>`;
}
function openSettings() {
 $('workers').value=prefs.workers;$('limit').value=prefs.limit;
 $('key-status').textContent=data?.config.jev_available?'Jev is ready. The server-side credential never enters this browser.':'Jev needs TYPESAFE_API_KEY on the server or the macOS Keychain entry xnaut / plugin/typesafe/TYPESAFE_API_KEY.';
 const sc=data?.scan||{};$('scan-status').textContent=sc.status==='running'?'Scanning transcripts…':sc.status==='done'?`${fmt(sc.transcripts)} transcripts since ${date(sc.since)} · ${sc.rescanned_files} re-read on last scan · ${date(sc.scanned_at)}`:sc.error||'Not scanned yet';
 const ov=data?.overlap||{};$('overlap-status').textContent=ov.status==='running'?'Overlap audit running…':ov.pairs?`${fmt(ov.pairs)} pairs on file${ov.finished_at?' · '+date(ov.finished_at):''}`:ov.error||'No overlap audit yet';
 $('run-overlap').disabled=ov.status==='running';$('rescan-evidence').disabled=sc.status==='running';
 $('settings-dialog').showModal();
}
function download(value,filename){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('settings-nav').innerHTML=icon('settings');['settings-nav','settings-button','engine-settings'].forEach(id=>$(id).onclick=openSettings);
$('settings-form').onsubmit=e=>{e.preventDefault();prefs={provider:'jev',workers:Number($('workers').value),limit:Number($('limit').value)};localStorage.setItem('skilldash-preferences',JSON.stringify(prefs));$('settings-dialog').close();render();toast('Preferences saved. Applies to your next batch.');};
$('settings-judges').onclick=()=>{$('settings-dialog').close();navigate('judges');};
$('rescan-evidence').onclick=async()=>{try{await api('/api/rescan',{});$('settings-dialog').close();await refresh();toast('Rescan started. New or changed transcripts are re-read.');}catch(e){toast(e.message,true);}};
$('run-overlap').onclick=async()=>{if(!confirm('Run the pairwise overlap audit? About 1,600 Jev requests over a few minutes.'))return;try{await api('/api/overlap',{});$('settings-dialog').close();await refresh();toast('Overlap audit started in the background.');}catch(e){toast(e.message,true);}};
$('rescan-button').onclick=async()=>{try{await api('/api/rescan',{});await refresh();toast('Skill tree reloaded; evidence rescanning.');}catch(e){toast(e.message,true);}};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('run-button').onclick=async()=>{if(busy)return;for(const input of $('judgment-editor').querySelectorAll('input,textarea')){const card=input.closest('[data-index]');if(card&&!judgmentPlan[Number(card.dataset.index)].enabled)continue;if(!input.checkValidity()){navigate('judges');input.reportValidity();return;}}const reprocess=!selected.size&&data.skills.every(s=>s.result);if(reprocess&&!confirm(`Judge up to ${Math.min(prefs.limit,data.skills.length)} skills again with hosted Jev (API usage applies)?`))return;busy=true;render();try{await api('/api/run',{...prefs,questions:selectedQuestions(),ids:[...selected],reprocess});selected.clear();await refresh();toast('Jev batch started. Independent questions run together.');}catch(e){toast(e.message,true);}finally{busy=false;render();}};
$('pause-button').onclick=async()=>{try{await api('/api/control',{action:data.job.status==='paused'?'resume':'pause'});await refresh();}catch(e){toast(e.message,true);}};
$('stop-button').onclick=async()=>{try{await api('/api/control',{action:'stop'});await refresh();toast('Stopping after in-flight requests finish.');}catch(e){toast(e.message,true);}};
document.addEventListener('click',e=>{const f=e.target.closest('[data-filter]');if(f)setFilter(f.dataset.filter);const m=e.target.closest('[data-skill]');if(m)showSkill(m.dataset.skill);const n=e.target.closest('[data-view]');if(n)navigate(n.dataset.view);if(e.target.id==='clear-selection'){selected.clear();render();}if(e.target.id==='select-all-matching'){filtered().forEach(x=>selected.add(x.id));render();}});
document.addEventListener('change',e=>{if(e.target.dataset.select){e.target.checked?selected.add(e.target.dataset.select):selected.delete(e.target.dataset.select);render();}});
$('select-page').onchange=e=>{filtered().slice((page-1)*pageSize,page*pageSize).forEach(x=>e.target.checked?selected.add(x.id):selected.delete(x.id));render();};
$('search').oninput=e=>{query=e.target.value;page=1;render();};$('sort').onchange=()=>{page=1;render();};$('prev-page').onclick=()=>{page--;render();};$('next-page').onclick=()=>{page++;render();};
$('drawer-backdrop').onclick=closeDrawer;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();if(!$('drawer').hidden&&e.key==='Tab'){const items=[...$('drawer').querySelectorAll('button,input,select,textarea,summary,a[href]')].filter(el=>!el.disabled&&(!el.closest('details:not([open])')||el.tagName==='SUMMARY'));const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}if(e.key==='/'&&$('drawer').hidden&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){e.preventDefault();if(view==='judges'||view==='activity')navigate('skills');$('search').focus();}});
$('export-button').onclick=async()=>{try{download(await api('/api/export'),'skill-decisions.json');toast('Export includes evidence, judgments and your decisions.');}catch(e){toast(e.message,true);}};
document.addEventListener('DOMContentLoaded',refresh);setInterval(()=>{if(!document.hidden&&!busy)refresh();},1500);

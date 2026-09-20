'use strict';
// Judgment builder, ported from jev-inbox: cards for Choice / Noul / Score questions, saved in this browser.
let judgmentPlan = null;
try { judgmentPlan = JSON.parse(localStorage.getItem('skilldash-judgments')); } catch {}
if (!Array.isArray(judgmentPlan) || !judgmentPlan.length) judgmentPlan = null;
const judgmentTitle = id => id.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
function selectedQuestions() {
 return Object.fromEntries((judgmentPlan || []).filter(q=>q.enabled).map(q=>[q.id,q.spec]));
}
function initBuilder() {
 if (judgmentPlan === null) {
  judgmentPlan = Object.entries({...data.config.questions,...data.config.presets}).map(([id,spec])=>({id,spec:structuredClone(spec),enabled:id in data.config.questions}));
  renderBuilder();
 } else if (!$('judgment-cards').children.length) renderBuilder();
 const count=Object.keys(selectedQuestions()).length;
 $('configured-judgments').textContent=count?Object.keys(selectedQuestions()).map(judgmentTitle).join(' · '):'No judges enabled';
 $('judgment-summary').textContent=`${count} selected · independent questions run together per skill`;
 $('judgment-editor').disabled=!!running();
 renderJudgmentFilter();
}
function renderBuilder() {
 $('judgment-cards').innerHTML=judgmentPlan.map((q,i)=>{
 const policy=data.config.policy||'\u0000';
 const criteria=q.spec.type==='choice'?Object.entries(q.spec.criteria).map(([k,v])=>`${k}: ${v}`).join('\n'):(q.spec.criteria||[]).join('\n');
 return `<article class="judgment-card ${q.enabled?'enabled':''}" data-index="${i}"><div class="judgment-card-top"><label class="checkbox-label"><input type="checkbox" data-field="enabled" ${q.enabled?'checked':''}><strong>${esc(judgmentTitle(q.id))}</strong></label><span class="type-badge">${esc(q.spec.type==='noul'?'Noul':judgmentTitle(q.spec.type))}</span><button class="text-button" type="button" data-remove="${i}" aria-label="Remove ${esc(q.id)}">×</button></div><label>Result name<input data-field="id" value="${esc(q.id)}" maxlength="40" pattern="[a-z][a-z0-9_]*"></label><label>${q.spec.type==='noul'?'What should match? Ask a yes/no question.':'What should Jev judge?'}<textarea data-field="instructions" rows="3" maxlength="4000">${esc(q.spec.instructions.startsWith(policy)?q.spec.instructions.slice(policy.length):q.spec.instructions)}</textarea></label>${q.spec.type!=='noul'?`<details open><summary>${q.spec.type==='choice'?'Edit options':'Edit score levels · lowest first'}</summary><label>${q.spec.type==='choice'?'One key: description per line; include other, none or unclear.':'One concrete description per line. Output runs from 0 to the last level’s index.'}<textarea data-field="criteria" rows="6">${esc(criteria)}</textarea></label></details>`:'<p class="field-help">Returns a yes probability. Filter matching skills in the table; this is not an intensity score.</p>'}</article>`;
 }).join('');
}
function savePlan() { localStorage.setItem('skilldash-judgments',JSON.stringify(judgmentPlan)); }
function partnerName(a,s){return /^partner_\d$/.test(a.choice)?(s?.result?.candidates?.[a.choice]||a.choice):null;}
function resultText(a,s) {
 const p=a.type==='choice'?partnerName(a,s):null; if(p)return 'Duplicate of '+p;
 if(a.type==='noul')return `${a.noul>=.7?'Yes':a.noul<=.3?'No':'Uncertain'} · ${Math.round(a.noul*100)}% yes`;
 if(a.type==='score')return `${a.score.toFixed(2)} / ${Object.keys(a.legend).length-1}`;
 return judgmentTitle(a.choice);
}
function judgmentChips(s) {
 const answers=s.result?.answers||{};
 return Object.entries(answers).filter(([id])=>!['useful','action'].includes(id)).map(([id,a])=>`<span class="result-chip" title="${esc(s.result.questions?.[id]?.instructions||id)}">${esc(judgmentTitle(id))}: <b>${esc(resultText(a,s))}</b></span>`).join('') || '<span class="muted">—</span>';
}
function judgmentDetails(pred) {
 return Object.entries(pred.answers||{}).map(([id,a])=>`<div class="judgment"><span>${esc(judgmentTitle(id))} · ${esc(a.type)}</span><strong>${esc(resultText(a,{result:pred}))}</strong>${a.confidence!=null?`<p class="field-help">${Math.round(a.confidence*100)}% confidence in the distribution</p>`:''}<p class="field-help">${esc((pred.questions?.[id]?.instructions||'').replace(data.config.policy||'\u0000',''))}</p>${a.type==='score'?`<p class="field-help">${Object.entries(a.legend).map(([k,v])=>`${esc(k)}: ${esc(v)}`).join('<br>')}</p>`:''}</div>`).join('');
}
function resultDefinitions() {
 const defs={};
 data.skills.forEach(s=>Object.entries(s.result?.answers||{}).forEach(([id,a])=>{
  const spec=s.result.questions?.[id]||data.config.questions[id];
  const key=JSON.stringify([id,spec||a.type]);
  if(!defs[key])defs[key]={id,type:a.type,spec,versions:new Set()};
  defs[key].versions.add(s.result.question_version||'legacy');
 }));
 return defs;
}
function renderJudgmentFilter() {
 const select=$('judgment-filter'),previous=select.value,defs=resultDefinitions();
 const counts={};Object.values(defs).forEach(d=>counts[d.id]=(counts[d.id]||0)+1);
 select.innerHTML='<option value="">All judgment results</option>'+Object.entries(defs).map(([key,d])=>`<option value="${esc(key)}">${esc(judgmentTitle(d.id))} · ${d.type}${counts[d.id]>1?' · '+[...d.versions][0]:''}</option>`).join('');
 if(defs[previous])select.value=previous;
 const def=defs[select.value],wanted=$('judgment-value').value;
 $('judgment-value').hidden=def?.type!=='choice';$('judgment-min-label').hidden=!def||def.type==='choice';
 if(def?.type==='choice'){
  $('judgment-value').innerHTML='<option value="">Any choice</option>'+Object.keys(def.spec?.criteria||{}).map(k=>`<option value="${esc(k)}">${esc(judgmentTitle(k))}</option>`).join('');
  if([...$('judgment-value').options].some(o=>o.value===wanted))$('judgment-value').value=wanted;
 }
 $('judgment-min-caption').textContent=def?.type==='score'?'Minimum score':'Minimum yes probability';
 $('judgment-min').max=def?.type==='score'?def.spec.criteria.length-1:1;
}
function matchingJudgment(s) {
 const value=$('judgment-filter').value;if(!value)return true;
 const [id,spec]=JSON.parse(value),a=s.result?.answers?.[id];
 if(!a||JSON.stringify(s.result.questions?.[id]||data.config.questions[id]||a.type)!==JSON.stringify(spec))return false;
 return a.type==='choice'?(!$('judgment-value').value||a.choice===$('judgment-value').value):(a.type==='score'?a.score:a.noul)>=Number($('judgment-min').value);
}
function judgmentSortValue(s) {
 const value=$('judgment-filter').value;if(!value)return -1;
 const a=s.result?.answers?.[JSON.parse(value)[0]];return a?.score??a?.noul??-1;
}
$('judgment-cards').addEventListener('change',e=>{
 const card=e.target.closest('[data-index]'),field=e.target.dataset.field;if(!card||!field)return;
 const q=judgmentPlan[Number(card.dataset.index)];
 if(field==='enabled')q.enabled=e.target.checked;
 else if(field==='id'){
  const value=e.target.value.trim().toLowerCase().replace(/\s+/g,'_');
  if(!/^[a-z][a-z0-9_]{0,39}$/.test(value)||judgmentPlan.some(other=>other!==q&&other.id===value)){toast('Use a unique result name: letters, digits and underscores.',true);e.target.value=q.id;return;}
  q.id=value;
 } else if(field==='criteria') {
  const lines=e.target.value.split('\n').map(v=>v.trim()).filter(Boolean);
  if(q.spec.type==='score')q.spec.criteria=lines;
  else {
   const options={};e.target.setCustomValidity('');
   for(const line of lines){const split=line.indexOf(':');const key=line.slice(0,split).trim();if(split<1||options[key]){e.target.setCustomValidity('Use one unique key: description per line.');toast('Use one unique key: description per line.',true);return;}options[key]=line.slice(split+1).trim();}
   q.spec.criteria=options;
  }
 } else q.spec.instructions=e.target.value;
 savePlan();card.classList.toggle('enabled',q.enabled);card.querySelector('strong').textContent=judgmentTitle(q.id);render();
});
$('judgment-cards').addEventListener('click',e=>{const remove=e.target.closest('[data-remove]');if(!remove)return;judgmentPlan.splice(Number(remove.dataset.remove),1);savePlan();renderBuilder();render();});
$('content-preset').onclick=()=>{judgmentPlan=Object.entries(data.config.content_questions).map(([id,spec])=>({id,enabled:true,spec:structuredClone(spec)}));savePlan();renderBuilder();render();};
$('audit-preset').onclick=()=>{judgmentPlan=Object.entries(data.config.usage_questions).map(([id,spec])=>({id,enabled:true,spec:structuredClone(spec)}));savePlan();renderBuilder();render();};
$('extended-preset').onclick=()=>{judgmentPlan=Object.entries({...data.config.usage_questions,...data.config.content_questions,...data.config.presets}).map(([id,spec])=>({id,enabled:true,spec:structuredClone(spec)}));savePlan();renderBuilder();render();};
$('add-judgment').onclick=()=>{
 if(judgmentPlan.length>=12){toast('Up to 12 judgments per run.',true);return;}
 const type=$('new-judgment-type').value;let n=1;while(judgmentPlan.some(q=>q.id===`${type}_${n}`))n++;
 const spec=type==='choice'?{type,instructions:'Classify this skill.',criteria:{matches:'Matches the purpose described in the question.',other:'No match or insufficient evidence.'}}:structuredClone(data.config.presets[type==='noul'?'third_party_fit':'overlap_severity']);
 judgmentPlan.push({id:`${type}_${n}`,enabled:true,spec});savePlan();renderBuilder();render();
 $('judgment-cards').lastElementChild.querySelector('[data-field=id]').focus();
};
$('judgment-filter').onchange=()=>{$('judgment-min').value='0';$('judgment-value').value='';page=1;render();};
$('judgment-value').onchange=()=>{page=1;render();};$('judgment-min').oninput=()=>{page=1;render();};

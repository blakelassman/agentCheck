'use strict';
const $ = id => document.getElementById(id);
const state = {bootstrap:null, capture:null, run:null, selectedTest:'T01', selectedAgent:'vulnerable_agent', filter:'all', busy:false};
const STORAGE_KEY = 'agentcheck.capture.v1';
const MODE_LABELS = {manual:'MANUAL GEM CAPTURE', api:'API RECREATION', demo:'MOCK FIXTURES'};
let toastTimer;
function toast(message, error=false) {
  $('toast').textContent=message; $('toast').classList.toggle('error',error); $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,6500);
}
async function request(path, body) {
  const response=await fetch(path, body===undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-AgentCheck-Token':state.bootstrap.token},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || 'The request failed.');
  return data;
}
function currentCase(){return state.bootstrap.cases.find(c=>c.id===state.selectedTest);}
function findCapture(agent=state.selectedAgent, test=state.selectedTest){return state.capture.captures.find(c=>c.agent_id===agent&&c.test_id===test);}
function currentGrade(agent=state.selectedAgent,test=state.selectedTest){return state.run?.results.find(r=>r.agent_id===agent&&r.test_id===test);}
function newCapture(){return structuredClone(state.bootstrap.capture);}
function persist(){
  try {localStorage.setItem(STORAGE_KEY,JSON.stringify(state.capture));$('save-state').textContent='Saved in this browser';}
  catch{$('save-state').textContent='Browser storage unavailable';}
}
function updateEntry() {
  let item=findCapture();
  if(!item){item={agent_id:state.selectedAgent,test_id:state.selectedTest};state.capture.captures.push(item);}
  Object.assign(item,{raw_response:$('response-text').value,response_format:$('response-format').value,model:$('model-name').value.trim(),source_url:$('gem-url').value.trim(),captured_at:new Date().toISOString(),latency_ms:null});
  delete item.error; delete item.review;
  state.run=null; persist(); renderOverview(); renderGrade();
}
function setBusy(busy){
  state.busy=busy;
  $('report-button').disabled=busy||!state.run;
  for(const id of ['evaluate-button','demo-button','import-button','new-capture','review-pass','review-fail']) $(id).disabled=busy;
  $('api-run-button').disabled=busy||!state.bootstrap.api.ready;
  for(const id of ['response-text','model-name','gem-url','response-format']) $(id).disabled=busy||state.capture.source_mode==='api';
}
function buttonStatus(status,label){
  const b=document.createElement('button');b.className='status status-button '+status;b.textContent=status;b.setAttribute('aria-label',label);return b;
}
function renderOverview(){
  const results=state.run?.results||[];
  $('source-chip').textContent=MODE_LABELS[state.capture.source_mode];
  $('mock-banner').hidden=state.capture.source_mode!=='demo';$('api-banner').hidden=state.capture.source_mode!=='api';
  $('captured-count').textContent=String(state.capture.captures.filter(c=>c.raw_response?.trim()||c.error).length);
  $('captured-note').textContent=state.capture.source_mode==='demo'?'Hardcoded fixtures, not live model output':(state.run?.complete?'All ten case results recorded':'Fill both agents across all five tests');
  $('failed-count').textContent=String(results.filter(r=>r.evaluation_status==='FAIL').length);
  $('attention-count').textContent=String(results.filter(r=>['REVIEW','ERROR'].includes(r.evaluation_status)).length);
  $('test-rows').replaceChildren();
  let visible=0;
  for(const test of state.bootstrap.cases){
    const grades=state.bootstrap.agents.map(a=>currentGrade(a.id,test.id)?.evaluation_status||'PENDING');
    if(state.filter!=='all'&&!grades.includes(state.filter)) continue;
    visible++;
    const row=document.createElement('div');row.className='test-row';row.classList.toggle('selected',state.selectedTest===test.id);
    const info=document.createElement('div');const heading=document.createElement('div');heading.className='case-heading';
    const code=document.createElement('span');code.className='case-id';code.textContent=test.id;heading.append(code,document.createTextNode(test.title));
    const category=document.createElement('div');category.className='test-category';const dot=document.createElement('span');dot.className='severity';category.append(dot,document.createTextNode(`${test.category} · ${test.severity}`));info.append(heading,category);row.append(info);
    state.bootstrap.agents.forEach((agent,i)=>{
      const button=buttonStatus(grades[i],`${test.id} ${test.title}, ${agent.name}: ${grades[i]}`);
      button.setAttribute('aria-pressed',String(state.selectedTest===test.id&&state.selectedAgent===agent.id));
      button.addEventListener('click',()=>{state.selectedAgent=agent.id;state.selectedTest=test.id;renderOverview();renderInspector();});row.append(button);
    });$('test-rows').append(row);
  }
  if(!visible){const p=document.createElement('p');p.className='suite-footer';p.textContent='No results match this filter.';$('test-rows').append(p);}
  $('report-button').disabled=!state.run||state.busy;
  $('run-label').textContent=state.run ? `${state.run.complete?'Complete':'Incomplete'} · ${state.run.run_id}` : 'No current evaluation';
  $('run-detail').textContent=state.run ? 'New snapshot saved. Earlier runs remain in Run history.' : 'Capture responses, then evaluate to create a report.';
}
function renderInspector(){
  const test=currentCase(),item=findCapture();
  $('inspector-title').textContent=test.title;$('case-meta').textContent=`${test.id} · ${test.category}`;
  $('agent-select').value=state.selectedAgent;$('detail-prompt').textContent=test.prompt;
  $('response-text').value=item?.raw_response||'';$('response-format').value=item?.response_format||'text';
  $('model-name').value=item?.model||'';$('gem-url').value=item?.source_url||'';
  $('save-state').textContent=state.capture.source_mode==='api'?'Read-only API output':'Saved in this browser';
  setBusy(state.busy);renderGrade();
}
function renderGrade(){
  const grade=currentGrade(),status=grade?.evaluation_status||'PENDING';
  $('detail-status').className='status '+status;$('detail-status').textContent=status;
  $('grade-reason').textContent=grade ? grade.reason + (grade.review ? ` Human review: ${grade.review.note}`:'') : 'No current evaluation. Evaluate again after changing a response.';
  $('evidence').replaceChildren();
  const allEvidence=grade?.evidence||[];
  const extra=document.createElement('details');const extraSummary=document.createElement('summary');extraSummary.textContent=`${Math.max(0,allEvidence.length-5)} additional matches`;extra.append(extraSummary);
  for(const [index,evidence] of allEvidence.entries()){
    const block=document.createElement('div');block.className='evidence-item';
    const label=document.createElement('small');label.textContent=[evidence.sheet,evidence.record_id,evidence.field].filter(Boolean).join(' · ');
    const text=document.createElement('div');text.textContent=evidence.excerpt||'';block.append(label,text);(index<5?$('evidence'):extra).append(block);
  }
  if(allEvidence.length>5)$('evidence').append(extra);
  $('review-controls').hidden=grade?.automated_status!=='REVIEW';
  $('review-note').value=grade?.review?.note||'';
}
async function evaluateAll(){
  setBusy(true);
  try {state.run=await request('/api/evaluate',state.capture);renderOverview();renderGrade();toast('Evaluation saved. The HTML report is ready.');}
  catch(error){toast(error.message,true);}
  finally{setBusy(false);}
}
function download(name,text,type='application/json'){
  const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function showHistory(){
  $('suite-panel').hidden=true;$('history-panel').hidden=false;$('suite-nav').classList.remove('active');$('history-nav').classList.add('active');
  try{
    const runs=await request('/api/history');$('history-list').replaceChildren();
    if(!runs.length){const p=document.createElement('p');p.className='muted';p.textContent='No saved runs yet. Evaluate captured responses to create one.';$('history-list').append(p);}
    for(const run of runs){
      const card=document.createElement('article');card.className='history-card';const text=document.createElement('div');const title=document.createElement('strong');title.textContent=run.run_id;
      const detail=document.createElement('p');detail.textContent=`${MODE_LABELS[run.source_mode]} · ${run.complete?'All cases recorded':'Incomplete run'} · ${new Date(run.created_at).toLocaleString()}`;
      const summary=document.createElement('span');summary.textContent=Object.entries(run.summary).map(([agent,counts])=>`${agent==='vulnerable_agent'?'Vulnerable':'Protected'}: ${counts.PASS}/5 pass, ${counts.FAIL} fail, ${counts.ERROR} error, ${counts.REVIEW} review, ${counts.PENDING} pending`).join('   /   ');
      text.append(title,detail,summary);const a=document.createElement('a');a.textContent='Open HTML report ↗';a.href=`/reports/${run.run_id}.html`;a.target='_blank';a.rel='noopener noreferrer';card.append(text,a);$('history-list').append(card);
    }
  }catch(error){toast(error.message,true);}
}
function showSuite(){ $('suite-panel').hidden=false;$('history-panel').hidden=true;$('suite-nav').classList.add('active');$('history-nav').classList.remove('active'); }
async function startApiRun(){
  if(state.capture.captures.length&&!confirm('Start a separate API run? Export your current capture first if you want to keep editing it. Existing evaluated snapshots stay in Run history.'))return;
  state.capture=newCapture();state.capture.source_mode='api';state.run=null;setBusy(true);$('progress').hidden=false;
  try {
    let done=0;
    for(const agent of state.bootstrap.agents){for(const test of state.bootstrap.cases){
      $('progress').textContent=`Running ${done+1}/10 · ${agent.name} · ${test.title}`;
      const capture=await request('/api/run-case',{agent_id:agent.id,test_id:test.id});state.capture.captures.push(capture);done++;persist();renderOverview();renderInspector();
    }}
    state.run=await request('/api/evaluate',state.capture);$('progress').textContent='Run finished. Inspect errors and review cases before presenting.';toast('API run saved.');
  }catch(error){toast(error.message,true);$('progress').textContent='Run interrupted. Captured responses are retained. Evaluate them to save a partial report.';}
  finally {setBusy(false);renderOverview();renderInspector();}
}
async function boot(){
  try{
    state.bootstrap=await request('/api/bootstrap');state.capture=newCapture();
    try {const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');if(saved?.dataset_sha256===state.capture.dataset_sha256&&Array.isArray(saved.captures)&&MODE_LABELS[saved.source_mode])state.capture=saved;}catch{}
    $('dataset-label').textContent=`${state.bootstrap.dataset.version} · ${state.bootstrap.dataset.counts.Customers} customers`;
    $('api-state').textContent=state.bootstrap.api.ready?`API ready · ${state.bootstrap.api.model}`:'API not configured. Paste-in Gem capture is ready to use.';
    $('api-run-button').title=state.bootstrap.api.ready?'Send ten model requests using the configured API recreations':'Set API environment variables and add the partner instruction files, then restart the server.';
    $('agent-select').addEventListener('change',event=>{state.selectedAgent=event.target.value;renderOverview();renderInspector();});
    for(const id of ['response-text','response-format','model-name','gem-url'])$(id).addEventListener(id==='response-format'?'change':'input',updateEntry);
    $('copy-prompt').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(currentCase().prompt);toast('Prompt copied. Use a fresh chat in the selected Gem.');}catch{toast('Clipboard unavailable. Select and copy the prompt text above.',true);}});
    $('evaluate-button').addEventListener('click',evaluateAll);
    $('api-run-button').addEventListener('click',startApiRun);
    $('demo-button').addEventListener('click',async()=>{
      if(state.capture.captures.length&&!confirm('Load mock fixtures? Export your current capture first to keep editing it. Saved evaluations remain in Run history.'))return;
      setBusy(true);try{const data=await request('/api/demo',{});state.capture=data.capture;state.run=data.run;persist();showSuite();renderOverview();renderInspector();toast('Mock demo loaded. No model was called.');}catch(error){toast(error.message,true);}finally{setBusy(false);}
    });
    $('export-capture').addEventListener('click',()=>download(`agentcheck-${state.capture.source_mode}-capture.json`,JSON.stringify(state.capture,null,2)));
    $('import-button').addEventListener('click',()=>$('file-import').click());
    $('file-import').addEventListener('change',async event=>{
      const file=event.target.files[0];event.target.value='';if(!file)return;
      if(file.size>1000000){toast('Capture file exceeds 1 MB.',true);return;}
      if(state.capture.captures.length&&!confirm('Replace the current capture with this file? Saved evaluations remain in Run history.'))return;
      setBusy(true);
      try{const capture=JSON.parse(await file.text());const run=await request('/api/evaluate',capture);state.capture=capture;state.run=run;persist();showSuite();renderOverview();renderInspector();toast('Capture imported, evaluated and saved.');}catch(error){toast(error.message,true);}finally{setBusy(false);}
    });
    $('report-button').addEventListener('click',()=>{if(!state.run)return;const a=document.createElement('a');a.href=`/reports/${state.run.run_id}.html`;a.download=`AgentCheck-${state.run.run_id}.html`;document.body.append(a);a.click();a.remove();});
    for(const [id,status]of [['review-pass','PASS'],['review-fail','FAIL']])$(id).addEventListener('click',async()=>{
      const note=$('review-note').value.trim();if(note.length<8){toast('Add a review explanation of at least eight characters.',true);return;}
      const item=findCapture();if(!item)return;item.review={status,note};persist();await evaluateAll();
    });
    $('new-capture').addEventListener('click',()=>{if(state.capture.captures.length&&!confirm('Start an empty manual capture? Export the current capture first to keep editing it. Saved evaluations stay in Run history.'))return;state.capture=newCapture();state.run=null;persist();showSuite();renderOverview();renderInspector();});
    document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));renderOverview();}));
    $('history-nav').addEventListener('click',showHistory);$('refresh-history').addEventListener('click',showHistory);$('suite-nav').addEventListener('click',showSuite);
    $('setup-nav').addEventListener('click',()=>$('setup-dialog').showModal());$('close-setup').addEventListener('click',()=>$('setup-dialog').close());
    renderOverview();renderInspector();
  }catch(error){toast('Could not initialize AgentCheck: '+error.message,true);$('dataset-label').textContent='Server unavailable. Restart python -m agentcheck serve.';}
}
boot();

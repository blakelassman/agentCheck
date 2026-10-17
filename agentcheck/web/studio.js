'use strict';
const $=id=>document.getElementById(id);
const state={bootstrap:null,session:null,version:1,poll:null,busy:false,files:[]};
let toastTimer;
function toast(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
async function api(path,body){
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-AgentCheck-Token':state.bootstrap.token},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed.');return data;
}
const path=action=>`/api/studio/session/${state.session.id}${action?'/'+action:''}`;
function show(view){for(const name of ['upload','session','history'])$(name+'-view').hidden=name!==view;}
function active(){return state.session&&['scanning','refining'].includes(state.session.state);}
function selected(){return state.session.versions.find(v=>v.number===state.version)||state.session.versions.at(-1);}
function setBusy(value){state.busy=value;for(const id of ['start-button','demo-button','approve-button','reject-button','retry-button'])$(id).disabled=value;}
function connection(){const config=state.bootstrap.config;$('connection-label').textContent=config.ready?'Gemini · managed by AgentCheck':'Gemini · temporarily unavailable';$('connection-dot').classList.toggle('ready',config.ready);}
function renderFiles(){
  $('context-files').replaceChildren();
  state.files.forEach((file,index)=>{const row=textNode('div','','context-file');row.append(textNode('span',`${file.name} · ${(file.size/1024).toFixed(1)} KB`));const remove=textNode('button','Remove','text-button');remove.type='button';remove.setAttribute('aria-label','Remove '+file.name);remove.addEventListener('click',()=>{state.files.splice(index,1);renderFiles();});row.append(remove);$('context-files').append(row);});
}
async function attachments(){return Promise.all(state.files.map(async file=>{const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));return {name:file.name,data_base64:btoa(binary)};}));}
function textNode(tag,text,className){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;}
function remember(){try{localStorage.setItem('agentcheck.studio.last',state.session.id);}catch{}}
function render(){
  const session=state.session,version=selected(),latest=session.versions.at(-1),scan=version.scan;
  show('session');$('session-name').textContent=session.name;
  $('session-mode').textContent=session.is_mock?'OFFLINE DEMO':'GEMINI API SCAN';
  $('session-meta').textContent=`${scan.model||state.bootstrap.config.model} · ${session.pack==='bank'?'Fixed bank suite':'Generated task suite'} · ${(session.context_files||[]).length} context file(s)`;
  $('session-context').replaceChildren();for(const file of session.context_files||[])$('session-context').append(textNode('p',`${file.name} · ${file.characters.toLocaleString()} extracted characters · SHA256 ${file.sha256.slice(0,12)}`,'muted small'));
  $('mock-banner').hidden=!session.is_mock;
  $('session-error').hidden=!session.workflow_error;$('session-error').textContent=session.workflow_error||'';
  $('step-upload').classList.remove('active');$('step-scan').classList.toggle('active',active());$('step-decide').classList.toggle('active',!active());
  $('progress-panel').hidden=!active();
  $('progress-title').textContent=session.state==='refining'?'Refining instructions from your feedback…':'Running the test suite…';
  $('progress-description').textContent=session.state==='refining'?'The new version will automatically run the same tests.':`${latest.scan.results.length} of ${session.cases.length||6} cases recorded. Each test uses a fresh conversation.`;
  $('stat-version').textContent=version.number;$('stat-pass').textContent=scan.summary.PASS||0;$('stat-fail').textContent=scan.summary.FAIL||0;
  $('stat-attention').textContent=(scan.summary.ERROR||0)+(scan.summary.REVIEW||0);$('stat-progress').textContent=`${scan.results.length} / ${session.cases.length||6}`;
  $('results-title').textContent=`Version ${version.number} test results`;$('version-state').textContent=(version.decision?.status||scan.status).replaceAll('_',' ').toUpperCase();
  $('version-list').replaceChildren();
  for(const v of session.versions){const button=textNode('button','',`version-button${state.version===v.number?' selected':''}`);button.type='button';button.append(textNode('strong',`Version ${v.number}${session.accepted_version===v.number?' · Approved':''}`));button.append(textNode('span',`${v.scan.summary.PASS||0} pass · ${v.scan.summary.FAIL||0} fail · ${v.decision?.status?.replaceAll('_',' ')||v.scan.status.replaceAll('_',' ')}`));button.setAttribute('aria-pressed',String(v.number===state.version));button.addEventListener('click',()=>{state.version=v.number;render();});$('version-list').append(button);}
  const openTests=new Set([...$('results-list').querySelectorAll('details[open]')].map(d=>d.dataset.test));
  $('results-list').replaceChildren();
  for(const result of scan.results){
    const box=document.createElement('details');box.className='case';box.dataset.test=result.test_id;box.open=openTests.has(result.test_id)||result.evaluation_status==='FAIL'||result.evaluation_status==='ERROR';
    const summary=document.createElement('summary');summary.append(textNode('span',result.evaluation_status,'pill '+result.evaluation_status),textNode('span',result.test_id,'case-id'),textNode('span',result.title));box.append(summary);
    box.append(textNode('p',result.user_prompt),textNode('p','Expected: '+result.expected_behavior),textNode('pre',result.raw_response||'No response returned.'),textNode('p',result.reason));
    for(const evidence of result.evidence?.slice(0,5)||[])box.append(textNode('p',`${evidence.field}: ${evidence.excerpt}`,'evidence'));
    box.append(textNode('small',`${result.method==='independent_model'?(session.is_mock?'Mock judge fixture':'Independent Gemini judge'):result.method} · ${result.model} · ${result.latency_ms??'Unknown'} ms`));$('results-list').append(box);
  }
  if(!scan.results.length)$('results-list').append(textNode('p',active()?'The first response will appear here as soon as it is evaluated.':'No cases have been recorded.','muted'));
  const isCurrent=version.number===latest.number;
  const canDecide=isCurrent&&['ready','error'].includes(session.state)&&scan.status==='completed'&&(!version.decision||version.decision.status==='rejected');
  $('decision-panel').hidden=!canDecide;
  const attention=(scan.summary.ERROR||0)+(scan.summary.REVIEW||0),failures=scan.summary.FAIL||0;
  $('approve-button').textContent=failures?'Approve with exceptions ✓':'Approve instructions ✓';
  $('approve-button').disabled=state.busy||attention>0||version.decision!==null;
  $('reject-button').disabled=state.busy;
  $('reject-button').textContent=version.decision?.status==='rejected'?'Retry refinement ↻':'Reject and refine ↻';
  $('approval-help').textContent=attention?'Errors or review cases remain. Reject with feedback and rescan before approving.':failures?'Failed tests remain. Approval requires a written explanation and will be labeled approved with exceptions.':'Review the test evidence and prompt changes before approving.';
  $('approved-panel').hidden=session.accepted_version!==version.number;
  $('approved-title').textContent=version.decision?.status==='approved_with_exceptions'?'Approved with known exceptions':'Instructions approved';
  $('approved-note').textContent=version.decision?.note||'This exact version is available to download. Retest it on the destination platform with its real tools and knowledge.';
  $('download-instructions').disabled=session.accepted_version===null||active();
  const retryInterrupted=session.state==='error'&&scan.status==='interrupted';
  const retryErrorCases=scan.status==='completed'&&(scan.summary.ERROR||0)>0&&!version.decision;
  const retryPlan=session.state==='error'&&scan.status==='not_started';
  $('retry-button').hidden=!isCurrent||!(retryInterrupted||retryErrorCases||retryPlan);
  $('retry-button').textContent=retryErrorCases?'Rescan unchanged instructions':'Retry interrupted scan';
  $('version-instructions').textContent=version.instructions;$('prompt-version-label').textContent=`Version ${version.number} · ${version.instructions_sha256.slice(0,12)}`;
  $('change-summary').replaceChildren();
  if(version.changes.length){const list=document.createElement('ul');version.changes.forEach(change=>list.append(textNode('li',change)));$('change-summary').append(list);}
  $('diff-panel').hidden=version.number===1;
  if(version.number>1){
    const prior=session.versions.find(v=>v.number===version.number-1).instructions.split('\n'),current=version.instructions.split('\n');
    $('prompt-diff').replaceChildren();
    // Display removed/added whole lines; the complete versions remain inspectable above.
    for(const line of prior)if(!current.includes(line))$('prompt-diff').append(textNode('div','− '+line,'diff-remove'));
    for(const line of current)if(!prior.includes(line))$('prompt-diff').append(textNode('div','+ '+line,'diff-add'));
    if(!$('prompt-diff').children.length)$('prompt-diff').textContent='Line order or repeated lines changed. Compare the full versions for exact ordering.';
  }
}
function beginPolling(){clearTimeout(state.poll);if(!active())return;state.poll=setTimeout(async()=>{
  try{const previousLatest=state.session.versions.at(-1).number;state.session=await api(path());if(state.session.versions.at(-1).number>previousLatest)state.version=state.session.versions.at(-1).number;remember();render();if(active())beginPolling();else toast(state.session.state==='error'?'The scan stopped. Inspect the error and retry.':'Scan complete. Review the results before deciding.',state.session.state==='error');}
  catch(error){toast(error.message+' Reopen the saved session to resume viewing progress.',true);}
},700);}
async function openSession(id){clearTimeout(state.poll);state.session=await api('/api/studio/session/'+id);state.version=state.session.versions.at(-1).number;remember();$('feedback').value='';render();beginPolling();}
function download(action,filename){const a=document.createElement('a');a.href=path(action);a.download=filename;document.body.append(a);a.click();a.remove();}
async function history(){clearTimeout(state.poll);show('history');const sessions=await api('/api/studio/history');$('session-history').replaceChildren();if(!sessions.length)$('session-history').append(textNode('p','No saved sessions yet. Upload instructions or try the offline demo.','muted'));for(const session of sessions){const row=document.createElement('article');row.className='history-row';const label=document.createElement('div');label.append(textNode('strong',session.name),textNode('p',`${session.is_mock?'MOCK FIXTURE':'GEMINI API'} · ${session.state} · ${new Date(session.updated_at).toLocaleString()}`));const button=textNode('button','Open session ↗','button secondary');button.addEventListener('click',()=>openSession(session.id).catch(error=>toast(error.message,true)));row.append(label,button);$('session-history').append(row);}}
function updatePack(){const bank=$('test-pack').value==='bank';$('bank-note').hidden=!bank;$('scan-estimate').textContent=bank?'One scan · 5 tests · up to 10 Gemini calls':'First scan · 6 tests · up to 13 Gemini calls';}
async function loadFile(input,target,max){const file=input.files[0];input.value='';if(!file)return;if(file.size>max*4)throw new Error('File is too large. Use plain text up to '+max+' characters.');const text=await file.text();if(text.length>max||text.includes('\u0000'))throw new Error('Use a plain UTF-8 text file within the character limit.');$(target).value=text;if(target==='instructions'){$('instruction-name').textContent=file.name;$('character-count').textContent=text.length.toLocaleString()+' characters';}}
async function boot(){try{
  state.bootstrap=await api('/api/studio/bootstrap');$('expected-policy').value=state.bootstrap.default_policy;connection();
  $('instructions').addEventListener('input',()=>{$('character-count').textContent=$('instructions').value.length.toLocaleString()+' characters';});
  $('instruction-file').addEventListener('change',event=>loadFile(event.target,'instructions',100000).catch(error=>toast(error.message,true)));
  $('context-file').addEventListener('change',event=>{const incoming=[...event.target.files],combined=[...state.files,...incoming];event.target.value='';if(combined.length>10||combined.some(file=>file.size>5*1024*1024)||combined.reduce((sum,file)=>sum+file.size,0)>10*1024*1024){toast('Upload up to 10 files, 5 MB per file and 10 MB total.',true);return;}state.files=combined;renderFiles();});
  $('test-pack').addEventListener('change',updatePack);
  $('upload-form').addEventListener('submit',async event=>{event.preventDefault();if(!state.bootstrap.config.ready){toast('Gemini is temporarily unavailable. The AgentCheck operator needs to configure the server connection.',true);return;}setBusy(true);try{
    state.session=await api('/api/studio/sessions',{name:$('agent-name').value,instructions:$('instructions').value,pack:$('test-pack').value,policy:$('expected-policy').value,context:$('knowledge-context').value,context_files:await attachments()});state.version=1;$('feedback').value='';remember();render();beginPolling();
  }catch(error){toast(error.message,true);}finally{setBusy(false);if(state.session)render();}});
  $('demo-button').addEventListener('click',async()=>{setBusy(true);try{state.session=await api('/api/studio/demo',{});state.version=1;$('feedback').value='';remember();render();beginPolling();}catch(error){toast(error.message,true);}finally{setBusy(false);}});
  $('reject-button').addEventListener('click',async()=>{const feedback=$('feedback').value.trim();if(feedback.length<8){toast('Describe what should change using at least eight characters.',true);return;}setBusy(true);try{state.session=await api(path('reject'),{version:selected().number,feedback});state.version=state.session.versions.at(-1).number;$('feedback').value='';render();beginPolling();}catch(error){toast(error.message,true);}finally{setBusy(false);}});
  $('approve-button').addEventListener('click',async()=>{const version=selected(),note=$('feedback').value.trim();if(version.scan.summary.FAIL&&note.length<12){toast('Explain why you accept the failed tests. This approval will retain the exceptions.',true);return;}setBusy(true);try{state.session=await api(path('approve'),{version:version.number,note});render();toast('Version approved. Download the tested instructions and report.');}catch(error){toast(error.message,true);}finally{setBusy(false);}});
  $('retry-button').addEventListener('click',async()=>{setBusy(true);try{const action=selected().scan.status==='completed'?'rescan':'scan';state.session=await api(path(action),{version:selected().number});state.version=state.session.versions.at(-1).number;render();beginPolling();}catch(error){toast(error.message,true);}finally{setBusy(false);}});
  $('download-report').addEventListener('click',()=>download('report',`AgentCheck-${state.session.is_mock?'MOCK-':''}${state.session.id}.html`));
  $('download-instructions').addEventListener('click',()=>download('instructions',`AgentCheck-${state.session.is_mock?'MOCK-':''}instructions-v${state.session.accepted_version}.txt`));
  $('history-button').addEventListener('click',()=>history().catch(error=>toast(error.message,true)));$('refresh-history').addEventListener('click',()=>history().catch(error=>toast(error.message,true)));
  $('new-session').addEventListener('click',()=>{clearTimeout(state.poll);state.session=null;show('upload');$('step-upload').classList.add('active');$('step-scan').classList.remove('active');$('step-decide').classList.remove('active');});
  let last;try{last=localStorage.getItem('agentcheck.studio.last');}catch{}if(last&&/^[a-f0-9]{32}$/.test(last)){try{await openSession(last);}catch{show('upload');}}
}catch(error){toast('Could not start AgentCheck: '+error.message,true);}}
boot();

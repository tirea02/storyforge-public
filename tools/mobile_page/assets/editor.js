<script id="editor-js">
(()=>{
// 회차 원고 탭: 읽기·편집·저장(db drafts/epN). 저장본 base가 이 판과 다르면 경고.
const CLS=JSON.parse(document.getElementById('notation-data').textContent);
const BREATH=CLS.__breath||3,SCENE=CLS.__scene||'＊＊＊';
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function render(t){const out=[];let blank=0;for(const ln of t.split('\n')){if(!ln.trim()){blank++;continue}
 if(blank>=BREATH)out.push('<div class="breath" aria-hidden="true">· · ·</div>');else if(blank>=1)out.push('<div class="gap"></div>');blank=0;
 const s=ln.trim();if(s===SCENE){out.push('<div class="scene">'+esc(SCENE)+'</div>');continue}
 let c='';for(const o of Object.keys(CLS)){if(!o.startsWith('__')&&s.startsWith(o)){c=CLS[o];break}}
 out.push(c?`<p class="${c}">${esc(s)}</p>`:`<p>${esc(s)}</p>`)}return out.join('\n')}
function fmt(iso){try{return new Date(iso).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}catch(e){return iso}}
const dbp=(async()=>{try{return await window.claude?.use?.('db')}catch(e){return null}})();
document.querySelectorAll('[data-ep-editor]').forEach(box=>{
 const N=box.dataset.epEditor,BASE=box.dataset.base,DOC='drafts/ep'+N,LS='ed'+N+'draft-'+BASE;
 const q=s=>box.querySelector(s);
 const ta=q('.edtext'),view=q('.ms'),st=q('.edst'),bT=q('.ed-toggle'),bS=q('.ed-save'),bC=q('.ed-copy'),bR=q('.ed-reset');
 const ORIG=ta.value;let db=null,editing=false,lastSaved=null,saveAt=null,timer=null;
 const draftGet=()=>{try{return localStorage.getItem(LS)}catch(e){return null}};
 const draftSet=v=>{try{v==null?localStorage.removeItem(LS):localStorage.setItem(LS,v)}catch(e){}};
 const refresh=()=>{view.innerHTML=render(ta.value)};
 const dirty=()=>ta.value!==(lastSaved??ORIG);
 function status(){if(editing&&dirty())st.textContent='고친 내용 있음 · 아직 저장 안 됨'+(db?'':' (이 화면에서는 저장 불가 — 전체 복사로 채팅에 붙여 주세요)');
  else if(lastSaved!=null)st.textContent='저장본을 보고 있습니다 · '+fmt(saveAt);else st.textContent='원본(파일 기준 '+BASE+')을 보고 있습니다.'}
 bT.addEventListener('click',()=>{editing=!editing;ta.hidden=!editing;view.hidden=editing;bT.textContent=editing?'미리보기':'편집';
  bS.hidden=!(editing&&db);bC.hidden=!editing;bR.hidden=!editing;if(!editing)refresh();status()});
 ta.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{draftSet(ta.value);status()},400)});
 bC.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(ta.value);st.textContent='복사했습니다.'}catch(e){ta.hidden=false;ta.focus();ta.select();st.textContent='선택했습니다. 길게 눌러 복사하세요.'}});
 bR.addEventListener('click',()=>{if(bR.dataset.armed){ta.value=lastSaved??ORIG;draftSet(null);delete bR.dataset.armed;bR.textContent='원본으로 되돌리기';refresh();status()}
  else{bR.dataset.armed='1';bR.textContent='한 번 더 누르면 되돌림';setTimeout(()=>{delete bR.dataset.armed;bR.textContent='원본으로 되돌리기'},3000)}});
 async function put(v){const at=new Date().toISOString();await db.doc(DOC).set({text:v,savedAt:at,base:BASE});lastSaved=v;saveAt=at;draftSet(null)}
 bS.addEventListener('click',async()=>{if(!db)return;bS.disabled=true;st.textContent='저장 중…';
  try{await put(ta.value);status()}
  catch(e){st.textContent='저장 실패('+(e&&e.code||'오류')+'). 잠시 뒤 다시 누르거나, 전체 복사로 채팅에 붙여 주세요.'}
  finally{bS.disabled=false}});
 const d=draftGet();if(d&&d!==ORIG){ta.value=d;refresh();st.textContent='저장 안 한 고친 내용을 불러왔습니다.'}
 window['ed'+N]={text:()=>ta.value,ready:()=>!!db,async save(v){await put(v);ta.value=v;refresh();status()}};
 dbp.then(async x=>{db=x;if(!db)return;if(editing)bS.hidden=false;
  try{const snap=await db.doc(DOC).get();if(snap.exists){const r=snap.data();lastSaved=r.text;saveAt=r.savedAt;
   if(!draftGet()){ta.value=r.text;refresh()}status();
   if(r.base&&r.base!==BASE){const w=document.createElement('p');w.className='note warn';
    w.textContent='⚠ 이 저장본은 이전 판('+r.base+') 기준입니다. 그 뒤 Claude가 고친 내용이 빠져 있을 수 있어요. 고치기 전에 채팅에 알려 주세요.';st.after(w)}}}catch(e){}});
});
})();
</script>

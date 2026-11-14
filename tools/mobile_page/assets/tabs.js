<script id="tabs-js">
(()=>{
// 탭 전환(마지막 탭 기억) + 결정 카드(choices/<DEC_KEY>, 저장 버튼).
const tabs=[...document.querySelectorAll('.tab')];
const LS='tab-'+document.body.dataset.page;
function show(id){tabs.forEach(b=>{const on=b.dataset.panel===id;b.setAttribute('aria-selected',String(on));document.getElementById(b.dataset.panel).hidden=!on});window.scrollTo(0,0);try{localStorage.setItem(LS,id)}catch(e){}}
tabs.forEach(b=>b.addEventListener('click',()=>show(b.dataset.panel)));
const def=document.body.dataset.current;let saved=null;try{saved=localStorage.getItem(LS)}catch(e){}
const pv=document.body.dataset.pageRev;let pvSeen=null;try{pvSeen=localStorage.getItem(LS+'-rev');localStorage.setItem(LS+'-rev',pv)}catch(e){}
// 새 판이 올라오면 지금 작업 중인 탭부터, 아니면 마지막에 보던 탭
show(pvSeen===pv&&saved&&document.getElementById(saved)?saved:def);
const decs=[...document.querySelectorAll('.dec')];if(!decs.length)return;
const KEY=document.getElementById('p-dec').dataset.key;
const st={picks:{},notes:{}};
const btn=document.getElementById('dec-save'),msgEl=document.getElementById('dec-note');
const msg=s=>{msgEl.textContent=s};
function paint(){decs.forEach(c=>{const k=c.dataset.key;c.querySelectorAll('.opt').forEach(b=>b.setAttribute('aria-pressed',String(st.picks[k]===b.dataset.k)));const m=c.querySelector('.memo');if(document.activeElement!==m)m.value=st.notes[k]||''})}
decs.forEach(c=>{const k=c.dataset.key;
 c.querySelectorAll('.opt').forEach(b=>b.addEventListener('click',()=>{if(st.picks[k]===b.dataset.k)delete st.picks[k];else st.picks[k]=b.dataset.k;paint();msg('저장 안 됨 — 아래 저장을 눌러 주세요.')}));
 c.querySelector('.memo').addEventListener('input',e=>{st.notes[k]=e.target.value;msg('저장 안 됨 — 아래 저장을 눌러 주세요.')})});
let db=null;
btn.addEventListener('click',async()=>{if(!db){msg('이 화면에서는 저장이 안 됩니다.');return}
 btn.disabled=true;msg('저장 중…');
 try{await db.doc('choices/'+KEY).set({picks:st.picks,notes:st.notes,savedAt:new Date().toISOString()});msg('저장했습니다. Claude에게 "골랐어"라고 알려 주세요.')}
 catch(e){msg('저장 실패('+(e&&e.code||'오류')+'). 잠시 뒤 다시 눌러 주세요.')}
 finally{btn.disabled=false}});
(async()=>{try{db=await window.claude?.use?.('db')}catch(e){db=null}
 if(!db){msg('이 화면에서는 저장이 안 됩니다.');return}
 try{const s=await db.doc('choices/'+KEY).get();if(s.exists){const x=s.data()||{};st.picks=x.picks||{};st.notes=x.notes||{};paint();if(x.savedAt)msg('저장된 선택을 불러왔습니다.')}}catch(e){}
})();
})();
</script>

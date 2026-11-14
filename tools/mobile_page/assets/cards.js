<script id="cards-js">
(()=>{
// 검토 카드: 고르면 원고 탭의 문장을 바꿔 저장(drafts/epN), 고른 것은 choices/epN-기준커밋에.
// 카드마다 작가 메모와 작가가 쓴 새 선택지는 cardx/epN-기준커밋 {notes:{카드:글}, custom:{카드:[글|null,…]}}.
// 새 선택지 번호 = 기존 선택지 수 + 순서(지워도 자리는 null로 남겨 번호가 안 밀림).
// 카드 번호는 회차마다 1부터라 회차별로 나눠 둔다(합치면 다른 화의 같은 번호가 덮어씀).
// choices 값: -1 = 원본 유지(결정), 0.. = 선택지. 키가 없으면 보류(아직 안 고름) — '보류' 버튼으로 되돌림(작가 요청 2026-11-07).
const DATA=Object.fromEntries([...document.querySelectorAll('script[id^="rev-data-"]')].map(s=>[s.id.slice(9),JSON.parse(s.textContent)]));
const KEYS=JSON.parse(document.getElementById('rev-keys').textContent);
let db=null,choices={},xs={},busy=false;
const cards=[...document.querySelectorAll('[data-card]')];
const X=ep=>xs[ep]||(xs[ep]={notes:{},custom:{}});
const base=c=>(DATA[c.dataset.ep]||{})[c.dataset.card]||[];
const orig=c=>{const b=base(c);return b[0]&&b[0][0]?b[0][0].find:''};
const custom=c=>X(c.dataset.ep).custom[c.dataset.card]||[];
function allOpts(c){const f=orig(c);return base(c).concat(custom(c).map(t=>t==null?null:[{find:f,repl:t}]))}
function el(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e}
const cur=c=>(choices[c.dataset.ep]||{})[c.dataset.card];
function label(c,v){if(v===undefined)return '보류 — 아직 고르지 않았습니다.';if(+v<0)return '원본 유지로 골랐습니다.';
 const b=c.querySelector('.ch[data-k="'+v+'"]');return (b?b.textContent:'선택')+' — 원고에 반영했습니다.'}
function paint(){cards.forEach(c=>{const v=cur(c);
 c.querySelectorAll('.ch').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.k==='h'?v===undefined:(v!==undefined&&String(v)===b.dataset.k))));
 c.classList.toggle('held',v===undefined);note(c,label(c,v))})}
function note(c,s){c.querySelector('.chst').textContent=s}
function xnote(c,s){c.querySelector('.cxst').textContent=s}
async function saveX(ep){await db.doc('cardx/'+KEYS[ep]).set({...X(ep),savedAt:new Date().toISOString()})}
async function pick(c,k){if(busy)return;const id=c.dataset.card,ep=c.dataset.ep,opts=allOpts(c),ed=window['ed'+ep];
 if(!db||!ed||!ed.ready()){note(c,'이 화면에서는 저장이 안 됩니다. 채팅에 카드 번호로 알려 주세요.');return}
 const mine=choices[ep]||(choices[ep]={});const raw=mine[id],hold=k==='h';
 if(hold?raw===undefined:(raw!==undefined&&+raw===+k))return;
 const prev=raw===undefined?-1:+raw,nk=hold?-1:+k;
 let t=ed.text();const t0=t;
 if(prev!==nk){
  if(prev>=0&&opts[prev]){for(const e of opts[prev]){if(!t.includes(e.repl)){note(c,'원고에서 이전 선택 문장을 못 찾았습니다(직접 고치셨나요?). 채팅으로 알려 주세요.');return}t=t.replace(e.repl,()=>e.find)}}
  if(nk>=0){for(const e of opts[nk]){if(!t.includes(e.find)){note(c,'원고에서 원본 문장을 못 찾았습니다(직접 고치셨나요?). 채팅으로 알려 주세요.');return}t=t.replace(e.find,()=>e.repl)}}}
 busy=true;note(c,'저장 중…');
 try{if(t!==t0)await ed.save(t);if(hold)delete mine[id];else mine[id]=nk;
  await db.doc('choices/'+KEYS[ep]).set({...mine,savedAt:new Date().toISOString()});paint()}
 catch(e){note(c,'저장 실패('+(e&&e.code||'오류')+'). 잠시 뒤 다시 눌러 주세요.')}
 finally{busy=false}}
// 작가 선택지: 블록(본문) + 고르기 버튼
function drawCustom(c){c.querySelectorAll('.cu').forEach(e=>e.remove());const n=base(c).length,row=c.querySelector('.row'),st=c.querySelector('.chst'),pair=c.querySelector('.pair');
 custom(c).forEach((t,i)=>{if(t==null)return;const k=n+i,name='작가 '+(i+1);
  const b=el('div','blk new cu');const h=el('b',null,name);const del=el('button','linkbtn','지우기');del.type='button';
  del.addEventListener('click',()=>delCustom(c,i));h.append(' ',del);b.append(h,el('span','ms-inline cu-t',t));pair.append(b);
  const btn=el('button','edbtn ch cu',name);btn.type='button';btn.dataset.k=String(k);row.insertBefore(btn,st)});paint()}
async function addCustom(c,t){const ep=c.dataset.ep,id=c.dataset.card,x=X(ep);(x.custom[id]||(x.custom[id]=[])).push(t);
 try{await saveX(ep);drawCustom(c);xnote(c,'새 선택지를 저장했습니다. 아래 버튼으로 고르면 원고에 들어갑니다.');return true}
 catch(e){x.custom[id].pop();xnote(c,'저장 실패('+(e&&e.code||'오류')+').');return false}}
async function delCustom(c,i){const ep=c.dataset.ep,id=c.dataset.card,k=base(c).length+i,cur=(choices[ep]||{})[id];
 if(cur!==undefined&&+cur===k){xnote(c,'지금 고른 선택지입니다. 먼저 다른 것(보류·원본 유지 등)을 고른 뒤 지워 주세요.');return}
 const arr=X(ep).custom[id],old=arr[i];arr[i]=null;
 try{await saveX(ep);drawCustom(c);xnote(c,'지웠습니다.')}catch(e){arr[i]=old;xnote(c,'지우기 실패('+(e&&e.code||'오류')+').')}}
// 카드 아래: 새 선택지 쓰기 + 메모
function build(c){const box=el('div','cx');
 const neww=el('button','edbtn','+ 새 선택지');neww.type='button';
 const ed=el('div','cx-ed');ed.hidden=true;
 const fill=el('div','row');const ta=el('textarea','memo cx-new');ta.rows=6;ta.placeholder='원고에 들어갈 문장만 쓰거나 붙여 넣으세요. 설명은 아래 메모에.';
 const put=(lab,txt)=>{const b=el('button','linkbtn',lab);b.type='button';b.addEventListener('click',()=>{ta.value=txt;ta.focus()});fill.append(b)};
 fill.append(el('span','memo-l','불러오기:'));put('원본',orig(c));base(c).forEach((o,i)=>{const lab=(c.querySelector('.ch[data-k="'+i+'"]')||{}).textContent||String.fromCharCode(65+i);put(lab,o.map(e=>e.repl).join('\n'))});
 const act=el('div','row');const sv=el('button','save','선택지로 저장');sv.type='button';const cancel=el('button','edbtn','취소');cancel.type='button';act.append(sv,cancel);
 ed.append(fill,ta,act);
 neww.addEventListener('click',()=>{ed.hidden=false;neww.hidden=true;ta.focus()});
 cancel.addEventListener('click',()=>{ed.hidden=true;neww.hidden=false;ta.value=''});
 sv.addEventListener('click',async()=>{const t=ta.value.replace(/\r\n/g,'\n');if(!t.trim()){xnote(c,'빈 선택지는 저장하지 않습니다.');return}
  sv.disabled=true;if(await addCustom(c,t)){ta.value='';ed.hidden=true;neww.hidden=false}sv.disabled=false});
 const ml=el('label','memo-l','이 카드에 메모');const m=el('textarea','memo cx-memo');m.rows=2;m.placeholder='피드백, 이유, Claude에게 할 말';ml.append(m);
 const ms=el('button','edbtn','메모 저장');ms.type='button';
 ms.addEventListener('click',async()=>{const ep=c.dataset.ep,id=c.dataset.card,x=X(ep),old=x.notes[id];const v=m.value.trim();if(v)x.notes[id]=v;else delete x.notes[id];
  ms.disabled=true;try{await saveX(ep);xnote(c,v?'메모를 저장했습니다.':'메모를 지웠습니다.')}catch(e){if(old===undefined)delete x.notes[id];else x.notes[id]=old;xnote(c,'저장 실패('+(e&&e.code||'오류')+').')}ms.disabled=false});
 const r=el('div','row');r.append(neww,ms,el('span','note cxst'));
 box.append(ed,ml,r);c.append(box)}
cards.forEach(c=>c.addEventListener('click',e=>{const b=e.target.closest('.ch');if(b&&c.contains(b))pick(c,b.dataset.k==='h'?'h':+b.dataset.k)}));
(async()=>{try{db=await window.claude?.use?.('db')}catch(e){db=null}
 if(!db){cards.forEach(c=>note(c,'이 화면에서는 저장이 안 됩니다.'));return}
 cards.forEach(build);
 for(const ep of Object.keys(KEYS)){
  try{const s=await db.doc('choices/'+KEYS[ep]).get();if(s.exists){const x={...s.data()};delete x.savedAt;choices[ep]=x}}catch(e){}
  try{const s=await db.doc('cardx/'+KEYS[ep]).get();if(s.exists){const x=s.data()||{};xs[ep]={notes:x.notes||{},custom:x.custom||{}}}}catch(e){}}
 cards.forEach(c=>{drawCustom(c);const v=X(c.dataset.ep).notes[c.dataset.card];if(v)c.querySelector('.cx-memo').value=v});
 paint()})();
})();
</script>

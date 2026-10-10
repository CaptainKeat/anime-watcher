"use strict";
const $=id=>document.getElementById(id), video=$('video');
let csrf='', catalog=[], category='Anime', currentSeries=null, rows=[], currentEpisode=null, stream=null;
let requestNumber=0, info=null, savedAt=0, loaded=false, pollTimer=null, dragging=false;
const fmt=n=>{n=Math.max(0,Math.floor(n||0));return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`};
function message(text=''){ $('message').textContent=text; }
function node(tag,text='',cls=''){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
function image(id){const img=document.createElement('img');img.src=`/art/${id}`;img.alt='';img.loading='lazy';img.onerror=()=>{img.removeAttribute('src');};return img;}
async function api(path,body){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json','X-Phone-CSRF':csrf}:{},method:body?'POST':'GET',body:body?JSON.stringify(body):undefined});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Connection lost. Keep Anime Watcher open on the Ally.');return data;
}
function view(name){for(const id of ['pairing','library','series','player'])$(id).hidden=id!==name;message();window.scrollTo(0,0);}
async function connect(){
  try{
    const key=new URLSearchParams(location.hash.slice(1)).get('pair')||$('paircode').value.trim();
    let session;
    if(key){session=await api('/api/pair',{key});history.replaceState(null,'','/');}
    else session=await api('/api/session');
    csrf=session.csrf;requestNumber=Math.max(requestNumber,session.generation||0);
    catalog=await api('/api/library');view('library');renderLibrary();
  }catch(error){view('pairing');message(error.message);}
}
function renderLibrary(){
  $('anime').classList.toggle('selected',category==='Anime');$('youtube').classList.toggle('selected',category==='YouTube');
  const cards=$('cards');cards.replaceChildren();const search=$('search').value.toLocaleLowerCase();
  const found=catalog.filter(row=>row.library_type===category&&row.title.toLocaleLowerCase().includes(search));
  for(const row of found){
    const card=node('button','',`seriescard ${category==='YouTube'?'youtube':''}`);card.append(image(row.id));
    const unit=category==='YouTube'?'video':'episode';
    const caption=node('div','','caption');caption.append(node('strong',row.title),node('small',`${row.year||'Year unavailable'} · ${row.episode_count} ${unit}${row.episode_count===1?'':'s'}`));card.append(caption);card.onclick=()=>openSeries(row);cards.append(card);
  }
  if(!found.length)cards.append(node('p','No matching series in this tab.'));
}
function options(select,entries,selected){select.replaceChildren();for(const [value,label] of entries){const option=node('option',label);option.value=value;select.append(option);}if(selected!==undefined)select.value=selected;}
async function openSeries(row){
  try{currentSeries=row;rows=await api(`/api/series/${row.id}`);view('series');
    const head=$('serieshead');head.replaceChildren();const intro=node('div','','seriesintro');intro.append(image(row.id));const title=node('div');title.append(node('h1',row.title),node('p',String(row.year||'Year unavailable')));intro.append(title);head.append(intro);if(row.synopsis)head.append(node('p',row.synopsis,'synopsis'));
    options($('season'),[...new Set(rows.map(e=>e.season))].map(n=>[n,`Season ${n}`]));
    options($('language'),[['all','All versions'],...[...new Set(rows.map(e=>e.language))].map(n=>[n,n])]);renderEpisodes();
  }catch(error){message(error.message);}
}
function renderEpisodes(){
  const list=$('episodes');list.replaceChildren();const groups=new Map();
  for(const episode of rows){if(String(episode.season)!==$ ('season').value||($('language').value!=='all'&&episode.language!==$('language').value))continue;const key=String(episode.episode);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(episode);}
  for(const versions of groups.values()){
    const first=versions[0], card=node('div','','episode'), row=node('div','','row');row.append(node('strong',`Episode ${first.episode}`));const play=node('button','▶ Play');row.append(play);card.append(row);
    const select=document.createElement('select');select.setAttribute('aria-label',`Episode ${first.episode} version`);options(select,versions.map(e=>[e.id,`${e.language}${versions.filter(v=>v.language===e.language).length>1?` · Copy ${versions.indexOf(e)+1}`:''}`]));card.append(select);
    const percentage=Math.max(...versions.map(e=>e.duration_ms>0?Math.min(100,Math.round(e.progress_ms/e.duration_ms*100)):0)), done=versions.some(e=>e.completed);
    const progress=node('div','',`progress${done?' done':''}`), bar=node('span');bar.style.width=`${percentage}%`;progress.append(bar);card.append(progress,node('small',done?'Watched':percentage?`${percentage}% watched`:'Ready to watch'));
    play.onclick=()=>openEpisode(versions.find(e=>String(e.id)===select.value));list.append(card);
  }
  if(!groups.size)list.append(node('p','No episodes for this season and language.'));
}
async function openEpisode(episode){
  const token=++requestNumber;
  try{
    view('player');currentEpisode=episode;loaded=false;stream=null;video.removeAttribute('src');video.load();
    $('playingtitle').textContent=`${currentSeries.title} · Episode ${episode.episode} · ${episode.language}`;
    $('playstatus').textContent='Checking video and available tracks…';$('tapplay').hidden=true;
    info=await api(`/api/info/${episode.id}`);if(token!==requestNumber)return;
    options($('audio'),info.audio.length?info.audio.map(t=>[t.id,t.label]):[[0,'No audio track']]);
    const english=info.subtitles.find(t=>/\b(eng|english|en)\b/i.test(t.label));
    options($('subtitles'),[['off','Off'],...info.subtitles.map(t=>[t.id,t.label])],episode.language==='Sub'&&english?english.id:'off');
    $('compatible').checked=false;$('seek').max=info.duration;$('seek').value=info.position;
    await startPlayback(info.position,token);
  }catch(error){if(token===requestNumber){$('playstatus').textContent='Unable to start';message(error.message);}}
}
async function startPlayback(offset,token=++requestNumber){
  loaded=false;video.pause();clearTimeout(pollTimer);$('tapplay').hidden=true;$('playstatus').textContent='Preparing playback…';message();
  try{
    const next=await api('/api/play',{episode:currentEpisode.id,offset,generation:token,audio:Number($('audio').value),subtitle:$('subtitles').value,compatible:$('compatible').checked});
    if(token!==requestNumber)return;stream=next;savedAt=0;
    let ready=false;
    for(let attempt=0;attempt<90;attempt++){
      if(token!==requestNumber)return;const status=await api(`/api/status/${stream.id}`);if(status.error)throw new Error(status.error);if(status.ready){ready=true;break;}await new Promise(resolve=>setTimeout(resolve,1000));
    }
    if(!ready)throw new Error('This stream is taking too long. Try Compatibility mode without subtitles, or choose another version.');
    if(token!==requestNumber)return;
    video.src=stream.url;video.load();$('playstatus').textContent=stream.label;$('seek').value=offset;
    try{await video.play();}catch(_error){$('tapplay').hidden=false;}
    monitor(token);
  }catch(error){if(token===requestNumber){message(error.message);$('playstatus').textContent='Playback needs attention';}}
}
function position(){return stream?Math.min(stream.duration,video.currentTime+(stream.mode==='hls'?stream.offset:0)):0;}
video.addEventListener('loadedmetadata',()=>{
  if(!stream)return;if(stream.mode==='direct')video.currentTime=stream.offset;loaded=true;
});
video.addEventListener('timeupdate',()=>{if(!loaded||!stream)return;const pos=position();if(!dragging)$('seek').value=pos;$('time').textContent=`${fmt(pos)} / ${fmt(stream.duration)}`;if(Date.now()-savedAt>10000)saveProgress();});
video.addEventListener('pause',()=>{if(loaded)saveProgress();});
video.addEventListener('ended',()=>{if(loaded)saveProgress();$('playstatus').textContent='Episode finished · progress saved';});
video.addEventListener('error',()=>{if(stream)message('Safari could not play this stream. Turn on Compatibility mode and apply playback options.');});
async function saveProgress(){if(!stream||!loaded)return;savedAt=Date.now();try{await api('/api/progress',{stream:stream.id,position:position()});}catch(error){message(`Progress was not saved: ${error.message}`);}}
function monitor(token){pollTimer=setTimeout(async()=>{if(token!==requestNumber||!stream)return;try{const status=await api(`/api/status/${stream.id}`);if(status.error)throw new Error(status.error);monitor(token);}catch(error){message(error.message);}},15000);}
async function seekTo(pos){if(!stream)return;pos=Math.max(0,Math.min(stream.duration-.1,pos));if(stream.mode==='direct'){video.currentTime=pos;}else{await saveProgress();await startPlayback(pos);}}
async function leavePlayer(){++requestNumber;clearTimeout(pollTimer);await saveProgress();loaded=false;video.pause();video.removeAttribute('src');video.load();stream=null;try{await api('/api/stop',{generation:requestNumber});await openSeries(currentSeries);}catch(error){message(error.message);}}
$('anime').onclick=()=>{category='Anime';renderLibrary();};$('youtube').onclick=()=>{category='YouTube';renderLibrary();};$('search').oninput=renderLibrary;
$('refresh').onclick=async()=>{try{catalog=await api('/api/library');renderLibrary();message();}catch(error){message(error.message);}};
$('season').onchange=renderEpisodes;$('language').onchange=renderEpisodes;$('back').onclick=()=>{view('library');renderLibrary();};$('backepisodes').onclick=leavePlayer;
$('tapplay').onclick=async()=>{try{await video.play();$('tapplay').hidden=true;}catch(error){message(error.message);}};
$('apply').onclick=async()=>{await saveProgress();await startPlayback(position());};$('restart').onclick=()=>seekTo(0);$('rewind').onclick=()=>seekTo(position()-10);$('forward').onclick=()=>seekTo(position()+10);
$('seek').oninput=()=>{dragging=true;$('time').textContent=`${fmt(Number($('seek').value))} / ${fmt(stream?.duration)}`;};$('seek').onchange=()=>{dragging=false;seekTo(Number($('seek').value));};
$('reconnect').onclick=connect;document.addEventListener('visibilitychange',()=>{if(document.hidden)saveProgress();});
window.addEventListener('pagehide',()=>{if(stream&&loaded)fetch('/api/progress',{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json','X-Phone-CSRF':csrf},body:JSON.stringify({stream:stream.id,position:position()})}).catch(()=>{});});
connect();

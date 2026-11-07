const $ = id => document.getElementById(id);
const bytes = n => {const units=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<units.length-1){n/=1024;i++;}return `${n.toFixed(i?1:0)} ${units[i]}`;};
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function card(label,value,detail){const node=el('article',undefined,'card');node.append(el('div',label,'label'),el('div',value,'value'),el('div',detail,'detail'));return node;}
async function fetchJSON(url){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);try{const response=await fetch(url,{cache:'no-store',signal:controller.signal});const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;}catch(error){if(error.name==='AbortError')throw new Error('讀取逾時，請稍後重試');throw error;}finally{clearTimeout(timer);}}
let busy=false;
async function refreshSystem(){try{const d=await fetchJSON('/api/system');$('identity').textContent=`${d.hostname} · ${d.model} · ${d.os} · Linux ${d.kernel}`;
const days=Math.floor(d.uptime_seconds/86400),hours=Math.floor(d.uptime_seconds%86400/3600),minutes=Math.floor(d.uptime_seconds%3600/60);
let throttle='無法取得';if(d.throttled.available){const flag=parseInt(d.throttled.output.split('=')[1],16);const flags=[[1,'目前欠壓'],[2,'目前頻率受限'],[4,'目前降頻'],[8,'目前軟性溫度限制'],[65536,'曾欠壓'],[131072,'曾頻率受限'],[262144,'曾降頻'],[524288,'曾軟性溫度限制']];throttle=flag===0?'無欠壓／降頻紀錄':flags.filter(([bit])=>(flag&bit)!==0).map(([,s])=>s).join('、')||d.throttled.output;}
$('metrics').replaceChildren(card('CPU 使用率',`${d.cpu.percent}%`,`${d.cpu.count} 核心 · 負載 ${d.cpu.load_average.map(n=>n.toFixed(2)).join(' / ')}`),card('記憶體',`${(d.memory.used/d.memory.total*100).toFixed(1)}%`,`${bytes(d.memory.used)} / ${bytes(d.memory.total)} · Swap ${bytes(d.memory.swap_total-d.memory.swap_free)}`),card('溫度',d.temperatures.length?`${d.temperatures[0].celsius.toFixed(1)} °C`:'未提供',throttle),card('運作時間',`${days} 天 ${hours} 時`,`${minutes} 分 · ${d.timestamp}`));
$('disks').replaceChildren(...d.disks.map(disk=>{const node=el('div',undefined,'disk'),top=el('div',undefined,'disk-top'),bar=el('progress');top.append(el('strong',disk.label),el('span',`已用 ${bytes(disk.used)} / ${bytes(disk.total)} · 剩餘 ${bytes(disk.free)}`));bar.max=disk.total;bar.value=disk.used;node.append(top,el('p',disk.path),bar);return node;}));
$('network').replaceChildren(...d.network.map(n=>{const row=el('tr');[n.name,n.state,bytes(n.rx_bytes),bytes(n.tx_bytes)].forEach(v=>row.append(el('td',v)));return row;}));$('status').textContent=`● 已連線 · 更新於 ${new Date().toLocaleTimeString()}`;$('status').className='';
}catch(error){$('status').textContent=`更新失敗：${error.message}`;$('status').className='error';}}
let logLines=[];
function renderLogs(){const query=$('filter').value.toLowerCase();const visible=logLines.filter(line=>line.toLowerCase().includes(query));$('log').textContent=visible.join('\n')||'沒有符合的日誌';}
async function logs(){$('logs').disabled=true;try{const d=await fetchJSON(`/api/dmesg?lines=${$('lines').value}`);logLines=d.lines;renderLogs();$('log-status').textContent=`已讀取最後 ${d.lines.length} 行／目前緩衝區共 ${d.total_lines} 行 · ${new Date().toLocaleTimeString()}`;}catch(error){$('log-status').textContent=`讀取失敗：${error.message}`;}finally{$('logs').disabled=false;}}
function rows(target, data){$(target).replaceChildren(...data.map(values=>{const row=el('tr');values.forEach(value=>row.append(el('td',value)));return row;}));}
function sectionStatus(id,message,kind=''){const node=$(id);node.textContent=message;node.className=kind;}
async function refreshSection(url,statusId,targets,render){try{const data=await fetchJSON(url);render(data);}catch(error){targets.forEach(target=>$(target).replaceChildren());sectionStatus(statusId,`無法取得：${error.message}`,'error');}}
function refreshNetwork(){return refreshSection('/api/network','network-detail-status',['network-details'],d=>{
rows('network-details',d.interfaces.map(n=>[n.name,n.addresses.join('\n')||'未配置 IP',n.signal_dbm===null?'—':`${n.signal_dbm} dBm`]));
for(const row of $('network-details').children)row.children[1].className='addresses';
const signals=d.interfaces.filter(n=>n.signal_dbm!==null).length;
sectionStatus('network-detail-status',d.wifi_available?`Wi-Fi 訊號讀取：${signals} 個介面 · dBm 越接近 0，訊號越強`:`IP 已更新；Wi-Fi 訊號無法取得：${d.wifi_error||'系統未提供'}`,d.wifi_available?'':'warning');});}
function refreshServices(){return refreshSection('/api/services','services-status',['services'],d=>{
rows('services',d.units.map(u=>[u.name,u.load,u.active,u.sub,u.description]));
sectionStatus('services-status',d.units.length?`偵測到 ${d.units.length} 個失敗服務`:'目前沒有處於 failed 的系統服務；未啟動的服務與應用程式健康不在此檢查範圍',d.units.length?'warning':'');});}
function refreshProcesses(){return refreshSection('/api/processes','processes-status',['cpu-processes','memory-processes'],d=>{
rows('cpu-processes',d.cpu_top.map(p=>[p.pid,p.name,`${p.cpu_percent.toFixed(1)}%`,`${p.memory_percent.toFixed(1)}%`]));
rows('memory-processes',d.memory_top.map(p=>[p.pid,p.name,`${p.memory_percent.toFixed(1)}%`,bytes(p.rss_bytes)]));
sectionStatus('processes-status',`可見程序共 ${d.total} 個 · RSS 為常駐實體記憶體 · 僅顯示程序名稱`);});}
function refreshUSB(){return refreshSection('/api/usb','usb-status',['usb'],d=>{
rows('usb',d.devices.map(u=>[`${u.bus||'—'} / ${u.device||'—'}`,`${u.vendor_id}:${u.product_id}`,[u.manufacturer,u.product].filter(Boolean).join(' / ')||u.path,u.speed_mbps===null?'—':`${u.speed_mbps} Mbps`]));
sectionStatus('usb-status',`已偵測 ${d.devices.length} 個 USB 裝置 · 速率為裝置協商連線速率，非即時傳輸量${d.error?' · 部分資料無法讀取：'+d.error:''}`,d.error?'warning':'');});}
async function refresh(){if(busy)return;busy=true;$('refresh').disabled=true;try{await Promise.allSettled([refreshSystem(),refreshNetwork(),refreshServices(),refreshProcesses(),refreshUSB()]);}finally{busy=false;$('refresh').disabled=false;}}
$('refresh').addEventListener('click',refresh);$('logs').addEventListener('click',logs);$('filter').addEventListener('input',renderLogs);setInterval(()=>{if($('auto').checked&&!document.hidden)refresh();},5000);refresh();

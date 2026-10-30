let literatureCatalog = {subjects:[],document_types:[],documents:[]};
let literatureBaseUrl = '';
const literatureKeys = ['q','subject','type','author','language','tag','composer'];
const literatureBaseTitle = '音乐文献 | 征集网站名字中';

function litEscape(value) { return String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;'); }
function litNormalize(value) { return String(value || '').normalize('NFKC').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim(); }
function literatureState(url = window.location.href) { const params = new URL(url).searchParams; return Object.fromEntries(literatureKeys.map(key=>[key,params.get(key)||''])); }
function literatureUrl(changes = {}, clear = false) {
    const url = new URL('literature.html',window.location.href);
    if (!clear) { const old = new URL(window.location.href); literatureKeys.forEach(key=>{if(old.searchParams.get(key))url.searchParams.set(key,old.searchParams.get(key));}); }
    Object.entries(changes).forEach(([key,value])=>{if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);});
    url.hash='literatureResults'; return url;
}
function literaturePdfUrl(doc) {
    const key=String(doc.storage_key||'');
    if (!/^literature\/[0-9a-f]{2}\/[0-9a-f-]{36}\.pdf$/.test(key) || !/^https:\/\//.test(literatureBaseUrl)) return '';
    return literatureBaseUrl.replace(/\/+$/,'')+'/'+key;
}
function filterLiterature(documents,state) {
    const words=litNormalize(state.q).split(' ').filter(Boolean);
    return documents.filter(doc=> {
        const text=litNormalize([doc.title,doc.original_title,doc.summary,doc.publisher,doc.year,doc.edition,
            ...doc.authors.map(p=>p.name),...doc.translators.map(p=>p.name),...doc.tags,...doc.related_composers.map(p=>p.name),
            ...doc.subjects.map(id=>literatureCatalog.subjects.find(s=>s.id===id)?.label||id)].join(' '));
        return words.every(word=>text.includes(word)) && (!state.subject||doc.subjects.includes(state.subject)) &&
            (!state.type||doc.document_type===state.type) && (!state.author||doc.authors.some(p=>p.id===state.author)) &&
            (!state.language||doc.languages.includes(state.language)) && (!state.tag||doc.tags.includes(state.tag)) &&
            (!state.composer||[...doc.related_composers,...doc.authors].some(p=>p.id===state.composer));
    });
}
function litPeople(people) { return people.map(person=>`<a class="lit-author" href="${litEscape(literatureUrl({author:person.id},true))}">${litEscape(person.name)}</a>`).join('、'); }
function litTags(doc) { return doc.tags.map(tag=>`<a class="lit-pill" href="${litEscape(literatureUrl({tag}))}">${litEscape(tag)}</a>`).join(''); }
function literatureCard(doc) {
    const detail=literatureUrl({document:doc.id});
    const type=literatureCatalog.document_types.find(t=>t.id===doc.document_type)?.label||doc.document_type;
    return `<article class="lit-book"><a class="lit-cover" href="${litEscape(detail)}" data-document-id="${litEscape(doc.id)}" aria-label="查看 ${litEscape(doc.title)} 的文献详情"><img src="${litEscape(doc.cover)}" alt="${litEscape(doc.title)} 封面" loading="lazy" width="112"></a>
    <div><div class="lit-book-heading"><span class="lit-kind">${litEscape(type)}</span>${doc.is_translation?'<span class="lit-pill">译本</span>':''}<span class="lit-bibliography">${litEscape(doc.purpose)}</span></div>
    <h3><a href="${litEscape(detail)}" data-document-id="${litEscape(doc.id)}">${litEscape(doc.title)}</a></h3>
    <div class="lit-bibliography">${litPeople(doc.authors)}${doc.translators.length?`<br>${doc.translators.map(p=>`${litEscape(p.name)}（${litEscape(p.role||'译者')}）`).join('、')}`:''}<br>${litEscape(doc.publisher ?? '出版机构未核')} · ${litEscape(doc.year ?? '年份未核')} · ${doc.languages.map(litEscape).join('／')}</div>
    <p class="lit-summary">${litEscape(doc.summary)}</p><div class="lit-tags">${litTags(doc)}</div>
    <div class="lit-book-footer"><span class="lit-file">PDF · ${doc.page_count.toLocaleString()} 页 · ${(doc.file_size/1024**2).toFixed(1)} MiB</span><a class="lit-action" href="${litEscape(detail)}" data-document-id="${litEscape(doc.id)}">文献详情</a><a class="lit-action" href="${litEscape(literaturePdfUrl(doc))}" target="_blank" rel="noopener">打开 PDF ↗</a></div></div></article>`;
}
function renderLiterature() {
    const state=literatureState();
    const docs=literatureCatalog.documents;
    const result=filterLiterature(docs,state);
    const subjects=[{id:'',label:'全部文献'},...literatureCatalog.subjects];
    document.getElementById('literatureSubjects').innerHTML=subjects.map(s=>`<button class="lit-subject ${state.subject===s.id?'is-active':''}" type="button" data-subject="${litEscape(s.id)}" aria-pressed="${state.subject===s.id}"><span>${litEscape(s.label)}</span><small>${s.id?docs.filter(d=>d.subjects.includes(s.id)).length:docs.length}</small></button>`).join('');
    document.getElementById('literatureSearch').value=state.q;
    [['literatureType','type'],['literatureAuthor','author'],['literatureLanguage','language'],['literatureTag','tag']].forEach(([id,key])=>{document.getElementById(id).value=state[key];});
    const subject=literatureCatalog.subjects.find(s=>s.id===state.subject);
    const person=docs.flatMap(d=>[...d.authors,...d.related_composers]).find(p=>p.id===state.composer);
    const author=docs.flatMap(d=>d.authors).find(p=>p.id===state.author);
    document.getElementById('literatureResultsTitle').textContent=state.composer?`${person?.name||'当前作曲家'} · 相关文献`:state.author?`${author?.name||'当前作者'} · 著作`:subject?.label||'全部文献';
    document.getElementById('literatureCount').textContent=`${result.length} 份文献`;
    document.getElementById('literatureList').innerHTML=result.length?result.map(literatureCard).join(''):'<div class="lit-empty"><h3>当前条件下暂无文献</h3><p>这个方向会继续收录。也可以清除筛选，查看现有书架。</p><button class="lit-action" type="button" data-reset>查看全部文献</button></div>';
    const labels={q:'关键词',subject:'方向',type:'类型',author:'作者',language:'语言',tag:'标签',composer:'相关人物'};
    document.getElementById('literatureActive').innerHTML=literatureKeys.filter(key=>state[key]).map(key=>{
        const label=key==='subject'?subject?.label:key==='author'?author?.name:key==='composer'?person?.name:key==='type'?literatureCatalog.document_types.find(t=>t.id===state.type)?.label:state[key];
        return `<button class="lit-pill" type="button" data-remove-filter="${key}" aria-label="移除${labels[key]}筛选">${labels[key]}：${litEscape(label||state[key])} ×</button>`;
    }).join('');
    document.getElementById('literatureReset').hidden=!literatureKeys.some(k=>state[k]);
    document.title=literatureBaseTitle;
}
function navigateLiterature(changes={},clear=false) { window.history.pushState({},'',literatureUrl(changes,clear)); renderLiterature(); }
function showLiteratureDetail(id,push=false) {
    const doc=literatureCatalog.documents.find(d=>d.id===id);
    if(!doc)return;
    const url=literatureUrl({document:id});
    if(push)window.history.pushState({},'',url);
    const pdf=literaturePdfUrl(doc);
    const fields=[['作者',litPeople(doc.authors)],['译者／译释',doc.translators.map(p=>`${litEscape(p.name)}（${litEscape(p.role||'译者')}）`).join('、')||'—'],
        ['出版机构',litEscape(doc.publisher ?? '未核')],['出版年份',litEscape(doc.year ?? '未核')],['版本',litEscape(doc.edition)],['ISBN',litEscape(doc.isbn||'未载')],['语言',doc.languages.map(litEscape).join('／')],
        ['文件',`PDF，${doc.page_count}页，${(doc.file_size/1024**2).toFixed(1)} MiB`],['文本状况',litEscape(doc.text_status)],['收录用途',litEscape(doc.purpose)]];
    document.getElementById('literatureDetailBody').innerHTML=`<div class="lit-detail-grid"><div class="lit-cover"><img src="${litEscape(doc.cover)}" alt="${litEscape(doc.title)} 封面"></div><div><h2 id="literatureDetailTitle">${litEscape(doc.title)}</h2>${doc.original_title?`<p class="lit-bibliography">原题：${litEscape(doc.original_title)}</p>`:''}<dl class="lit-details">${fields.map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl><div class="lit-tags">${litTags(doc)}</div><div class="lit-book-footer"><a class="lit-action" href="${litEscape(pdf)}" target="_blank" rel="noopener">打开 PDF ↗</a><a class="lit-action" href="${litEscape(pdf)}" download="${litEscape(doc.title)}.pdf" target="_blank" rel="noopener">下载 PDF</a></div>
    <section class="lit-detail-section"><h3>内容与文件范围</h3><p>${litEscape(doc.summary)}</p><p>${litEscape(doc.notes)}</p></section>
    <section class="lit-detail-section"><h3>学科方向</h3><div class="lit-tags">${doc.subjects.map(id=>`<a class="lit-pill" href="${litEscape(literatureUrl({subject:id},true))}">${litEscape(literatureCatalog.subjects.find(s=>s.id===id)?.label||id)}</a>`).join('')}</div></section>
    ${doc.related_composers.length?`<section class="lit-detail-section"><h3>相关作曲家与作品研究</h3><div class="lit-tags">${doc.related_composers.map(p=>`<a class="lit-pill" href="${litEscape(literatureUrl({composer:p.id},true))}">${litEscape(p.name)} · 文献</a>${p.has_scores?`<a class="lit-pill" href="index.html?composer=${encodeURIComponent(p.id)}#mainContentArea">${litEscape(p.name)} · 乐谱 ↗</a>`:''}`).join('')}</div></section>`:''}
    <section class="lit-detail-section"><h3>文件定位</h3><ul>${doc.contents.map(c=>`<li>${litEscape(c.title)} · <a href="${litEscape(pdf)}#page=${c.pdf_page}" target="_blank" rel="noopener">PDF ${c.pdf_page}</a></li>`).join('')}</ul><p class="lit-bibliography">这里使用文件的实际 PDF 页码，可能与书内印刷页码不同。</p></section></div></div>`;
    document.title=doc.title+' | 音乐文献';
    const dialog=document.getElementById('literatureDetail');
    if(!dialog.open)dialog.showModal();
}
function restoreLiteratureLocation() { renderLiterature(); const id=new URL(window.location.href).searchParams.get('document'); const dialog=document.getElementById('literatureDetail'); if(id)showLiteratureDetail(id);else if(dialog.open)dialog.close(); }
function closeLiteratureDetail() { const url=new URL(window.location.href);url.searchParams.delete('document');window.history.replaceState(window.history.state,'',url);document.getElementById('literatureDetail').close();document.title=literatureBaseTitle; }

window.addEventListener('load',async()=>{
    const theme=localStorage.getItem('theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
    document.documentElement.dataset.theme=theme;
    document.getElementById('literatureTheme').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;localStorage.setItem('theme',next);});
    try {
        const [catalogResponse,configResponse]=await Promise.all([fetch('literature.json',{cache:'no-cache'}),fetch('site-config.json',{cache:'no-cache'})]);
        if(!catalogResponse.ok||!configResponse.ok)throw new Error('书目或存储配置加载失败');
        literatureCatalog=await catalogResponse.json();
        literatureBaseUrl=(await configResponse.json()).scoreStorage.baseUrl;
        document.getElementById('literatureStats').innerHTML=`<span><strong>${literatureCatalog.documents.length}</strong>份文献</span><span><strong>${literatureCatalog.subjects.length}</strong>个学科方向</span><span><strong>${literatureCatalog.documents.reduce((n,d)=>n+d.page_count,0).toLocaleString()}</strong>页资料</span>`;
        function options(id,items){const select=document.getElementById(id);items.forEach(([value,label])=>select.add(new Option(label,value)));}
        options('literatureType',literatureCatalog.document_types.map(t=>[t.id,t.label]));
        options('literatureAuthor',[...new Map(literatureCatalog.documents.flatMap(d=>d.authors).map(p=>[p.id,p.name]))].sort((a,b)=>a[1].localeCompare(b[1])));
        options('literatureLanguage',[...new Set(literatureCatalog.documents.flatMap(d=>d.languages))].sort().map(v=>[v,v]));
        options('literatureTag',[...new Set(literatureCatalog.documents.flatMap(d=>d.tags))].sort().map(v=>[v,v]));
        restoreLiteratureLocation();
        document.getElementById('literatureSearchForm').addEventListener('submit',e=>{e.preventDefault();navigateLiterature({q:document.getElementById('literatureSearch').value.trim()});});
        [['literatureType','type'],['literatureAuthor','author'],['literatureLanguage','language'],['literatureTag','tag']].forEach(([id,key])=>document.getElementById(id).addEventListener('change',e=>navigateLiterature({[key]:e.target.value})));
        document.getElementById('literatureReset').addEventListener('click',()=>navigateLiterature({},true));
        document.getElementById('literatureClose').addEventListener('click',closeLiteratureDetail);
        document.getElementById('literatureDetail').addEventListener('cancel',e=>{e.preventDefault();closeLiteratureDetail();});
        window.addEventListener('popstate',restoreLiteratureLocation);
        document.addEventListener('click',e=>{
            const button=e.target.closest('[data-subject],[data-reset],[data-remove-filter]');
            if(button){if(button.hasAttribute('data-reset'))navigateLiterature({},true);else if(button.hasAttribute('data-subject'))navigateLiterature({subject:button.dataset.subject});else navigateLiterature({[button.dataset.removeFilter]:''});return;}
            const link=e.target.closest('a');
            if(!link||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
            if(link.dataset.documentId){e.preventDefault();showLiteratureDetail(link.dataset.documentId,true);return;}
            const target=new URL(link.href);
            if(target.origin===window.location.origin&&target.pathname===new URL('literature.html',window.location.href).pathname){e.preventDefault();window.history.pushState({},'',target);document.getElementById('literatureDetail').close();restoreLiteratureLocation();}
        });
    } catch(error) { document.getElementById('literatureList').innerHTML='<div class="lit-empty"><h3>文献暂时未能加载</h3><p>请刷新页面重试。</p></div>';console.error(error); }
});

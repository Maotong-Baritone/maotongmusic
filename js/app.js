
// 全局变量
let musicData = [];
let changeLog = [];
let filters = { category: 'all', composer: '', language: 'all', voice: '', search: '' };
let sortType = 'date_desc';
let currentPage = 1;
const itemsPerPage = 15;
let currentLyricsId = null;

const composerAliases = {
    "Mozart": "莫扎特 Wolfgang Amadeus 沃尔夫冈 阿玛迪乌斯", "Dvořák": "Dvorak 德沃夏克 Antonin 安东宁",
    "Bach": "巴赫 J.S.Bach Johann Sebastian", "Beethoven": "贝多芬 Ludwig van 路德维希",
    "Schubert": "舒伯特 Franz 弗朗茨", "Schumann": "舒曼 Robert 罗伯特",
    "Tchaikovsky": "柴可夫斯基 Pyotr Ilyich", "Rachmaninoff": "拉赫玛尼诺夫 Rachmaninov Sergey",
    "Fauré": "Faure 福雷 Gabriel", "Debussy": "德彪西 Claude", "Verdi": "威尔第 Giuseppe",
    "Puccini": "普契尼 Giacomo", "Wagner": "瓦格纳 Richard", "Mahler": "马勒 Gustav", "Strauss": "施特劳斯 Richard Johann"
};

const categoryMap = { 
    '歌剧咏叹调': 'bg-opera', 
    '歌剧重唱': 'bg-opera-ens',
    '宗教声乐作品': 'bg-oratorio', 
    '音乐会咏叹调/世俗康塔塔': 'bg-solo',
    '艺术歌曲': 'bg-artsong', 
    '艺术歌曲重唱': 'bg-artsong-ens',
    '音乐剧选段': 'bg-musical',
    '音乐剧重唱': 'bg-musical-ens',
    '独唱片段/选段': 'bg-solo',
    '合唱作品': 'bg-choral', 
    '声乐套曲': 'bg-cycle', 
    '乐谱书': 'bg-book', 
    '乐谱书/曲集': 'bg-book',
    '器乐独奏': 'bg-inst-solo', 
    '室内乐': 'bg-chamber', 
    '歌剧总谱': 'bg-score-opera', 
    '管弦乐/交响曲': 'bg-score-orch', 
    '协奏曲总谱': 'bg-score-con', 
    '宗教声乐作品总谱': 'bg-score-sac',
    '其他': 'bg-other'
};

// 初始化
window.addEventListener('load', () => {
    loadData();
    document.getElementById('searchInput').addEventListener('keypress', (e) => { if(e.key === 'Enter') performSearch(); });
});

async function loadData() {
    const listSection = document.getElementById('recentList');
    listSection.innerHTML = '<div class="alert alert-light w-100 text-center font-serif">正在加载数据...</div>';

    try {
        const [dataRes, logRes] = await Promise.all([
            fetch('data.json?v=' + new Date().getTime()),
            fetch('logs.json?v=' + new Date().getTime())
        ]);

        if (!dataRes.ok) throw new Error("无法加载乐谱数据");
        musicData = await dataRes.json();
        
        if (logRes.ok) {
            changeLog = await logRes.json();
        }

        initStatsAndDropdowns(); 
        renderRecent(); 
        applyFilters();

    } catch (error) {
        console.error(error);
        listSection.innerHTML = `<div class="alert alert-danger w-100 text-center">数据加载失败: ${error.message}<br>请检查 data.json 文件是否存在。</div>`;
    }
}

function normalizeStr(str) { if (!str) return ""; return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function performSearch() { const val = document.getElementById('searchInput').value; filters.search = val; if(val.length > 0) { document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); } applyFilters(); }

function initStatsAndDropdowns() {
    document.getElementById('statTotal').innerText = musicData.length;
    const composers = [...new Set(musicData.map(m => m.composer).filter(c => c))].sort((a, b) => a.localeCompare(b));
    const languages = [...new Set(musicData.map(m => m.language).filter(l => l))].sort();
    const voiceTypes = [...new Set(musicData.map(m => m.voice_types).filter(v => v))].sort();
    document.getElementById('statComposer').innerText = composers.length;
    
    const composerDataList = document.getElementById('composerOptions'); 
    composerDataList.innerHTML = ''; // 清空
    composers.forEach(c => { composerDataList.innerHTML += `<option value="${c}">`; });
    
    const langSelect = document.getElementById('languageSelect'); 
    // 保留第一个option
    langSelect.innerHTML = '<option value="all">🌐 语言</option>';
    languages.forEach(l => { langSelect.innerHTML += `<option value="${l}">${l}</option>`; });
    
    const voiceDataList = document.getElementById('voiceOptions'); 
    voiceDataList.innerHTML = '';
    voiceTypes.forEach(v => { voiceDataList.innerHTML += `<option value="${v}">`; });
    
    document.querySelectorAll('.count-badge').forEach(badge => { const cat = badge.getAttribute('data-cat'); const count = musicData.filter(m => m.category === cat).length; badge.innerText = count; if(count === 0) badge.classList.add('opacity-25'); });
}

function applyFilters() {
    filters.composer = document.getElementById('composerInput').value; filters.language = document.getElementById('languageSelect').value;
    filters.voice = document.getElementById('voiceInput').value; sortType = document.getElementById('sortSelect').value;
    const searchBase = normalizeStr(filters.search); const searchComposer = normalizeStr(filters.composer); const searchVoice = normalizeStr(filters.voice);

    let result = musicData.filter(item => {
        const itemTitle = normalizeStr(item.title); const itemComposer = normalizeStr(item.composer); const itemWork = normalizeStr(item.work); const itemVoice = normalizeStr(item.voice_types); const itemDesc = normalizeStr(item.description);
        let composerKeywords = itemComposer; if (composerAliases[item.composer]) { composerKeywords += " " + normalizeStr(composerAliases[item.composer]); }
        const fullSearchableText = `${itemTitle} ${composerKeywords} ${itemWork} ${itemDesc}`;
        return (filters.category === 'all' || item.category === filters.category) && (filters.language === 'all' || item.language === filters.language) && (filters.composer === '' || composerKeywords.includes(searchComposer)) && (filters.voice === '' || (item.voice_types && itemVoice.includes(searchVoice))) && (filters.search === '' || fullSearchableText.includes(searchBase));
    });

    result.sort((a, b) => {
        if (sortType === 'date_desc') return b.id - a.id; if (sortType === 'date_asc') return a.id - b.id;
        if (sortType === 'title_asc') return a.title.localeCompare(b.title); if (sortType === 'composer_asc') return a.composer.localeCompare(b.composer); return 0;
    });
    renderPaginationTable(result);
    document.getElementById('recentSection').style.display = (filters.search || filters.composer || filters.language !== 'all' || filters.voice || filters.category !== 'all') ? 'none' : 'block';
}

function getCategoryClass(cat) { for (const key in categoryMap) { if (cat.includes(key)) return categoryMap[key]; } return 'bg-other'; }

function renderPaginationTable(data) {
    const total = data.length; const pages = Math.ceil(total / itemsPerPage);
    if (currentPage > pages) currentPage = pages || 1; if (currentPage < 1) currentPage = 1;
    const start = (currentPage - 1) * itemsPerPage; const pageData = data.slice(start, start + itemsPerPage);
    const tbody = document.getElementById('mainTableBody'); document.getElementById('filteredCount').innerText = total + ' 首乐谱';
    
    const noResult = document.getElementById('noResult');
    const nav = document.getElementById('paginationNav');
    
    if (total === 0) { 
        tbody.innerHTML = ''; 
        nav.style.display = 'none'; 
        noResult.style.display = 'block'; 
        
        const searchVal = document.getElementById('searchInput').value.trim();
        if (searchVal) {
            noResult.innerHTML = `
                <div class="fs-1 mb-3">🧐</div>
                <h4 class="font-serif mb-3">本地暂无相关乐谱</h4>
                <p class="text-muted mb-4">您可以尝试点击下方按钮，去国际数据库搜索 "<strong>${searchVal}</strong>"：</p>
                <div class="d-flex justify-content-center flex-wrap gap-3" style="max-width: 800px; margin: 0 auto;">
                    <a href="https://imslp.org/index.php?title=Special:Search&fulltext=Search&search=${encodeURIComponent(searchVal)}" target="_blank" class="btn btn-outline-dark rounded-pill px-4 shadow-sm">🎼 搜 IMSLP</a>
                    <a href="https://www.google.com/search?q=site:opera-arias.com+${encodeURIComponent(searchVal)}" target="_blank" class="btn btn-outline-danger rounded-pill px-4 shadow-sm">🎭 搜 Opera-Arias</a>
                    <a href="https://www.google.com/search?q=site:theoperadatabase.com+${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" class="btn btn-outline-info rounded-pill px-4 shadow-sm">📂 搜 Opera Database</a>
                    <a href="https://www.oxfordsong.org/search?q=${encodeURIComponent(searchVal)}" target="_blank" class="btn btn-outline-success rounded-pill px-4 shadow-sm">📜 搜 Oxford Song</a>
                    <a href="https://www.google.com/search?q=${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" class="btn btn-outline-primary rounded-pill px-4 shadow-sm">🔍 搜 Google (PDF)</a>
                </div>
                <p class="mt-4 small text-muted">💡 提示：使用作品原名搜索成功率更高</p>
            `;
        } else {
            noResult.innerHTML = '<div class="fs-1 mb-3">🧐</div><h4 class="font-serif">未找到相关乐谱</h4><p>请尝试调整筛选条件。</p>';
        }
        return; 
    }
    noResult.style.display = 'none'; nav.style.display = 'block';

    let html = '';
    pageData.forEach(item => {
        let badgeClass = getCategoryClass(item.category);
        let tonalityBadge = item.tonality ? `<span class="badge bg-light text-dark border ms-2" style="font-size:0.7rem; opacity: 0.7;">${item.tonality}</span>` : '';
        let voiceBadge = item.voice_types ? `<span class="badge bg-secondary ms-1" style="font-size:0.7rem; opacity: 0.8;">${item.voice_types}</span>` : '';
        let lyricIcon = item.has_lyrics ? `<span class="badge bg-info text-dark ms-1" style="font-size:0.6rem" title="包含歌词/剧本">📖</span>` : '';
        let subBadge = item.sub_category ? `<span class="badge bg-light text-secondary border ms-1" style="font-size:0.7rem;">${item.sub_category}</span>` : '';

        html += `<tr onclick="openDetail(${item.id})" class="hover-row"><td class="ps-4"><div class="fw-bold text-dark" style="font-family: 'Noto Sans SC', sans-serif;">${item.title} ${tonalityBadge} ${voiceBadge} ${lyricIcon}</div>${item.work ? `<small class="text-muted fst-italic">选自: ${item.work}</small>` : ''}</td><td><span class="fw-medium text-secondary">${item.composer}</span></td><td>${item.language ? `<span class="text-muted small">${item.language}</span>` : '-'}</td><td><span class="badge badge-custom ${badgeClass}">${item.category}</span>${subBadge}</td><td class="text-end pe-4"><button class="btn btn-sm btn-outline-primary rounded-pill px-3 shadow-sm">查看</button></td></tr>`;
    });
    tbody.innerHTML = html; renderPaginationControls(pages);
}

function renderPaginationControls(pages) {
    const ul = document.getElementById('paginationUl');
    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}"><a class="page-link border-0 bg-transparent" href="#" onclick="changePage(1); return false;">首页</a></li>`;
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}"><a class="page-link border-0 bg-transparent" href="#" onclick="changePage(${currentPage - 1}); return false;">上一页</a></li>`;
    html += `<li class="page-item disabled"><span class="page-link border-0 bg-transparent fw-bold text-dark" style="white-space: nowrap;">${currentPage} / ${pages}</span></li>`;
    html += `<li class="page-item ${currentPage === pages ? 'disabled' : ''}"><a class="page-link border-0 bg-transparent" href="#" onclick="changePage(${currentPage + 1}); return false;">下一页</a></li>`;
    html += `<li class="page-item ${currentPage === pages ? 'disabled' : ''}"><a class="page-link border-0 bg-transparent" href="#" onclick="changePage(${pages}); return false;">尾页</a></li>`;
    if (pages > 1) {
        html += `<li class="page-item ms-3 d-flex align-items-center"><input type="number" id="jumpInput" class="form-control form-control-sm text-center" style="width: 50px; border-top-right-radius: 0; border-bottom-right-radius: 0;" min="1" max="${pages}" placeholder="页" onkeypress="if(event.key==='Enter') jumpToPage()"><button class="btn btn-sm btn-outline-secondary" style="border-top-left-radius: 0; border-bottom-left-radius: 0;" onclick="jumpToPage()">Go</button></li>`;
    }
    ul.innerHTML = html;
}

window.jumpToPage = function() {
    const input = document.getElementById('jumpInput');
    if (!input) return;
    let page = parseInt(input.value);
    if (!isNaN(page) && page > 0) { changePage(page); }
}

window.changePage = (p) => { currentPage = p; applyFilters(); document.getElementById('listSection').scrollIntoView({ behavior: 'smooth' }); };

function renderRecent() {
    const list = document.getElementById('recentList'); const recents = musicData.slice(0, 3); let html = '';
    recents.forEach(item => { html += `<div class="col"><div class="card h-100 border-0 shadow-sm cursor-pointer hover-card" style="border-radius: 12px; overflow:hidden;" onclick="openDetail(${item.id})"><div class="card-body bg-white"><span class="badge bg-light text-muted mb-2 border">${item.category}</span><h6 class="card-title text-truncate fw-bold text-dark font-serif" style="font-size: 1.1rem;">${item.title}</h6><p class="card-text small text-secondary mb-0">${item.composer}</p></div><div class="card-footer bg-white border-0 pt-0"><small class="text-muted" style="font-size: 0.75rem">上传于: ${item.date}</small></div></div></div>`; }); list.innerHTML = html;
}

window.filterCategory = (cat, btn) => { 
    currentPage = 1; filters.category = cat; 
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat')); 
    if (cat !== 'all') btn.classList.add('active-cat'); 
    document.getElementById('listTitle').innerText = cat === 'all' ? '📚 乐谱目录' : `📂 ${cat}`; 
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); applyFilters(); 
};

window.resetFilters = () => { 
    currentPage = 1; filters = { category: 'all', composer: '', language: 'all', voice: '', search: '' }; 
    document.getElementById('searchInput').value = ''; document.getElementById('composerInput').value = ''; 
    document.getElementById('languageSelect').value = 'all'; document.getElementById('voiceInput').value = ''; 
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat')); 
    document.getElementById('listTitle').innerText = '📚 乐谱目录'; 
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); applyFilters(); 
};

window.showLogModal = () => { const body = document.getElementById('logBody'); if (typeof changeLog === 'undefined' || changeLog.length === 0) { body.innerHTML = '<p class="text-muted text-center my-4">暂无动态记录</p>'; } else { let html = '<ul class="list-group list-group-flush">'; changeLog.forEach(log => { let badgeClass = log.type === 'add' ? 'bg-success' : (log.type === 'update' ? 'bg-primary' : 'bg-danger'); let typeText = log.type === 'add' ? '添加' : (log.type === 'update' ? '更新' : '删除'); html += `<li class="list-group-item d-flex justify-content-between align-items-start px-0"><div class="ms-2 me-auto"><div class="fw-bold small text-muted mb-1">${log.date}</div>${log.msg}</div><span class="badge ${badgeClass} rounded-pill">${typeText}</span></li>`; }); html += '</ul>'; body.innerHTML = html; } new bootstrap.Modal(document.getElementById('logModal')).show(); };

window.openDetail = function(id) {
    const item = musicData.find(m => m.id === id); if (!item) return;
    document.getElementById('mTitle').innerText = item.title; document.getElementById('mWork').innerText = item.work || '-'; document.getElementById('mComposer').innerText = item.composer; document.getElementById('mCategory').innerText = item.category; document.getElementById('mLanguage').innerText = item.language || '-'; document.getElementById('mDate').innerText = item.date || '-'; document.getElementById('mTonality').innerText = item.tonality || '-';
    let voiceInfo = '-'; if(item.voice_count || item.voice_types) voiceInfo = `${item.voice_count || ''} ${item.voice_types ? '('+item.voice_types+')' : ''}`; document.getElementById('mVoice').innerText = voiceInfo;
    document.getElementById('mSubCat').innerText = item.sub_category || '-';
    document.getElementById('mDownload').href = `scores/${item.filename}`;
    
    const descCard = document.getElementById('descCard');
    const descText = document.getElementById('mDescription');
    if (item.description && item.description.trim() !== '') {
        descText.innerText = item.description;
        descCard.style.display = 'block';
    } else {
        descCard.style.display = 'none';
    }

    const btn = document.getElementById('btnReadLyrics');
    if (item.has_lyrics) {
        btn.style.display = 'block';
        currentLyricsId = id;
    } else {
        btn.style.display = 'none';
        currentLyricsId = null;
    }

    const previewFrame = document.getElementById('mPreview'); const noPreview = document.getElementById('noPreview');
    if (item.filename.toLowerCase().endsWith('.pdf')) { previewFrame.src = `scores/${item.filename}`; previewFrame.style.display = 'block'; noPreview.style.display = 'none'; } else { previewFrame.style.display = 'none'; noPreview.style.display = 'flex'; }
    new bootstrap.Modal(document.getElementById('detailModal')).show();
}

window.openLyricsReader = function() {
    if (!currentLyricsId) return;
    const item = musicData.find(m => m.id === currentLyricsId);
    document.getElementById('readerTitle').innerText = item.title;
    document.getElementById('readerComposer').innerText = item.composer;
    document.getElementById('readerOriginalText').innerText = '加载中...';
    document.getElementById('readerTransText').innerText = '加载中...';
    new bootstrap.Modal(document.getElementById('readerModal')).show();

    fetch(`lyrics/${currentLyricsId}.json?v=${new Date().getTime()}`)
        .then(response => { if (!response.ok) throw new Error("Lyrics not found"); return response.json(); })
        .then(data => {
            document.getElementById('readerOriginalText').innerText = data.original || '暂无原文。';
            document.getElementById('readerTransText').innerText = data.translation || '暂无翻译。';
        })
        .catch(err => {
            document.getElementById('readerOriginalText').innerText = '无法加载内容。';
            document.getElementById('readerTransText').innerText = '';
        });
}

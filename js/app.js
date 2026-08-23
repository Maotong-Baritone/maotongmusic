// 全局变量
let musicData = [];
let changeLog = [];
let filters = { category: 'all', composer: '', language: 'all', voice: '', search: '', favoritesOnly: false };
let sortType = 'date_desc';
let currentPage = 1;
const itemsPerPage = 15;
let currentLyricsId = null;
let fuseInstance = null; // Fuse.js 实例
let favorites = loadStoredFavorites();

function loadStoredFavorites() {
    try {
        const stored = JSON.parse(localStorage.getItem('favorites') || '[]');
        return new Set(Array.isArray(stored) ? stored.map(String) : []);
    } catch (error) {
        console.warn('收藏数据已损坏，已自动重置。', error);
        localStorage.removeItem('favorites');
        return new Set();
    }
}

function getStableId(item) {
    return String(item.public_id || item.id);
}

function persistFavorites() {
    localStorage.setItem('favorites', JSON.stringify([...favorites]));
}

function migrateLegacyFavorites() {
    const migrated = new Set();
    favorites.forEach(storedId => {
        const directMatch = musicData.find(item => getStableId(item) === storedId);
        const legacyMatch = musicData.find(item => String(item.id) === storedId);
        const match = directMatch || legacyMatch;
        if (match) migrated.add(getStableId(match));
    });
    favorites = migrated;
    persistFavorites();
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

const composerAliases = {
    "Mozart": "莫扎特 Wolfgang Amadeus 沃尔夫冈 阿玛迪乌斯", "Dvořák": "Dvorak 德沃夏克 Antonin 安东宁",
    "Bach": "巴赫 J.S.Bach Johann Sebastian", "Beethoven": "贝多芬 Ludwig van 路德维希",
    "Schubert": "舒伯特 Franz 弗朗茨", "Schumann": "舒曼 Robert 罗伯特",
    "Tchaikovsky": "柴可夫斯基 Pyotr Ilyich", "Rachmaninoff": "拉赫玛尼诺夫 Rachmaninov Sergey",
    "Fauré": "Faure 福雷 Gabriel", "Debussy": "德彪西 Claude", "Verdi": "威尔第 Giuseppe",
    "Puccini": "普契尼 Giacomo", "Wagner": "瓦格纳 Richard", "Mahler": "马勒 Gustav", "Strauss": "施特劳斯 Richard Johann"
};

function composerSearchText(composer) {
    const normalizedComposer = normalizeStr(composer);
    const aliases = Object.entries(composerAliases)
        .filter(([name]) => normalizedComposer.includes(normalizeStr(name)))
        .map(([, value]) => value);
    return `${composer || ''} ${aliases.join(' ')}`.trim();
}

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
    initTheme(); // 初始化主题
    loadData();
    document.getElementById('searchInput').addEventListener('keypress', (e) => { if(e.key === 'Enter') performSearch(); });
});

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
        document.documentElement.setAttribute('data-theme', 'dark');
        updateThemeIcon(true);
    }
}

window.toggleTheme = function() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme === 'dark');
}

function updateThemeIcon(isDark) {
    const btn = document.getElementById('themeToggleBtn');
    if (btn) btn.innerHTML = isDark ? '☀️' : '🌙';
}

window.toggleFavorite = function(id, event) {
    if (event) event.stopPropagation();
    id = String(id);
    
    if (favorites.has(id)) {
        favorites.delete(id);
    } else {
        favorites.add(id);
    }
    persistFavorites();
    
    // 如果当前正在查看收藏夹，移除后需要刷新列表
    if (filters.favoritesOnly) {
        applyFilters();
    } else {
        // 否则只更新按钮状态（避免整页重绘）
        const btn = document.getElementById(`fav-btn-${id}`);
        if (btn) {
            btn.innerHTML = favorites.has(id) ? '❤️' : '🤍';
            btn.classList.toggle('text-danger', favorites.has(id));
            btn.classList.toggle('text-muted', !favorites.has(id));
        }
    }
}

window.showFavorites = function() {
    resetFilters();
    filters.favoritesOnly = true;
    document.getElementById('listTitle').innerText = '❤️ 我的收藏';
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' });
    applyFilters();
}

async function loadData() {
    const listSection = document.getElementById('recentList');
    listSection.innerHTML = '<div class="alert alert-light w-100 text-center font-serif">正在加载数据...</div>';

    try {
        const [dataRes, logRes] = await Promise.all([
            fetch('data.json', { cache: 'no-cache' }),
            fetch('logs.json', { cache: 'no-cache' })
        ]);

        if (!dataRes.ok) throw new Error("无法加载乐谱数据");
        musicData = await dataRes.json();
        
        // 初始化 Fuse.js
        if (typeof Fuse !== 'undefined') {
            const fuseOptions = {
                keys: [
                    { name: 'title', weight: 0.4 },
                    { name: 'composer', weight: 0.3 },
                    { name: 'work', weight: 0.2 },
                    { name: 'description', weight: 0.1 }
                ],
                threshold: 0.3, // 模糊阈值，越低越精确
                ignoreLocation: true
            };
            // 预处理数据：将别名加入到 composer 字段中以便搜索
            const searchableData = musicData.map(item => {
                return { ...item, _search_composer_alias: composerSearchText(item.composer) };
            });
            // 更新 keys 以包含别名
            fuseOptions.keys.push({ name: '_search_composer_alias', weight: 0.3 });
            
            fuseInstance = new Fuse(searchableData, fuseOptions);
        }
        
        if (logRes.ok) {
            changeLog = await logRes.json();
        }

        migrateLegacyFavorites();
        initStatsAndDropdowns(); 
        renderRecent(); 
        applyFilters();

    } catch (error) {
        console.error(error);
        listSection.innerHTML = `<div class="alert alert-danger w-100 text-center">数据加载失败: ${escapeHtml(error.message)}<br>请检查 data.json 文件是否存在。</div>`;
    }
}

function normalizeStr(str) { if (!str) return ""; return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function compareByDateDesc(a, b) {
    const dateCompare = String(b.date || '').localeCompare(String(a.date || ''));
    return dateCompare || Number(b.id) - Number(a.id);
}
function compareByDateAsc(a, b) {
    const dateCompare = String(a.date || '').localeCompare(String(b.date || ''));
    return dateCompare || Number(a.id) - Number(b.id);
}
function performSearch() { const val = document.getElementById('searchInput').value; filters.search = val; if(val.length > 0) { document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); } applyFilters(); }

function initStatsAndDropdowns() {
    document.getElementById('statTotal').innerText = musicData.length;
    const composers = [...new Set(musicData.map(m => m.composer).filter(c => c))].sort((a, b) => a.localeCompare(b));
    const languages = [...new Set(musicData.map(m => m.language).filter(l => l))].sort();
    const voiceTypes = [...new Set(musicData.map(m => m.voice_types).filter(v => v))].sort();
    document.getElementById('statComposer').innerText = composers.length;
    
    const composerDataList = document.getElementById('composerOptions');
    composerDataList.replaceChildren(...composers.map(value => new Option('', value)));
    
    const langSelect = document.getElementById('languageSelect'); 
    // 保留第一个option
    langSelect.replaceChildren(new Option('🌐 语言', 'all'));
    languages.forEach(value => langSelect.add(new Option(value, value)));
    
    const voiceDataList = document.getElementById('voiceOptions'); 
    voiceDataList.replaceChildren(...voiceTypes.map(value => new Option('', value)));
    
    document.querySelectorAll('.count-badge').forEach(badge => { const cat = badge.getAttribute('data-cat'); const count = musicData.filter(m => m.category === cat).length; badge.innerText = count; if(count === 0) badge.classList.add('opacity-25'); });
}

function renderRecent() {
    const recentContainer = document.getElementById('recentList');
    if (!recentContainer) return;

    const recentItems = [...musicData].sort(compareByDateDesc).slice(0, 6);

    let html = '';
    recentItems.forEach(item => {
        let badgeClass = getCategoryClass(item.category);
        const stableId = getStableId(item);
        const isFav = favorites.has(stableId);
        const favIcon = isFav ? '❤️' : '🤍';
        const favClass = isFav ? 'text-danger' : 'text-muted';

        html += `
        <div class="col">
            <div class="card h-100 shadow-sm hover-card border-0" onclick="openDetail('${stableId}')" style="cursor: pointer; transition: transform 0.2s;">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <span class="badge ${badgeClass}">${escapeHtml(item.category)}</span>
                        <small class="text-muted" style="font-size: 0.75rem;">${escapeHtml(item.date || '')}</small>
                    </div>
                    <h6 class="card-title fw-bold text-dark mb-1 font-serif text-truncate" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h6>
                    <div class="text-secondary small mb-2 text-truncate" title="${escapeHtml(item.composer)}">${escapeHtml(item.composer)}</div>
                    ${item.work ? `<div class="small text-muted fst-italic text-truncate" title="${escapeHtml(item.work)}">选自: ${escapeHtml(item.work)}</div>` : ''}
                </div>
                <div class="card-footer bg-white border-0 d-flex justify-content-between align-items-center">
                    <button class="btn btn-sm btn-link text-decoration-none p-0 ${favClass}" onclick="toggleFavorite('${stableId}', event)" title="收藏" aria-label="收藏 ${escapeHtml(item.title)}">${favIcon}</button>
                    <span class="badge bg-light text-secondary border">${escapeHtml(item.language || '-')}</span>
                </div>
            </div>
        </div>
        `;
    });

    recentContainer.innerHTML = html;
}

function applyFilters() {
    filters.composer = document.getElementById('composerInput').value; 
    filters.language = document.getElementById('languageSelect').value;
    filters.voice = document.getElementById('voiceInput').value; 
    sortType = document.getElementById('sortSelect').value;
    
    let result = musicData;
    
    // 0. 收藏夹过滤
    if (filters.favoritesOnly) {
        result = result.filter(item => favorites.has(getStableId(item)));
    }

    // 1. 如果有搜索词，优先使用 Fuse.js 进行模糊搜索
    if (filters.search && fuseInstance) {
        const fuseResults = fuseInstance.search(filters.search);
        result = fuseResults.map(r => r.item);
        // 如果同时在看收藏夹，需要取交集
        if (filters.favoritesOnly) {
             result = result.filter(item => favorites.has(getStableId(item)));
        }
    } else if (filters.search) {
        // Fallback: 如果 Fuse 未加载，使用旧的简单搜索
        const searchBase = normalizeStr(filters.search);
        result = result.filter(item => {
             const itemTitle = normalizeStr(item.title); 
             const itemComposer = normalizeStr(item.composer); 
             const itemWork = normalizeStr(item.work); 
             const itemDesc = normalizeStr(item.description);
             let composerKeywords = normalizeStr(composerSearchText(item.composer));
             const fullSearchableText = `${itemTitle} ${composerKeywords} ${itemWork} ${itemDesc}`;
             return fullSearchableText.includes(searchBase);
        });
    }

    // 2. 应用其他过滤器 (精确匹配)
    const searchComposer = normalizeStr(filters.composer);
    const searchVoice = normalizeStr(filters.voice);
    
    result = result.filter(item => {
        let composerKeywords = normalizeStr(composerSearchText(item.composer));
        const itemVoice = normalizeStr(item.voice_types);

        return (filters.category === 'all' || item.category === filters.category) && 
               (filters.language === 'all' || item.language === filters.language) && 
               (filters.composer === '' || composerKeywords.includes(searchComposer)) && 
               (filters.voice === '' || (item.voice_types && itemVoice.includes(searchVoice)));
    });

    // 3. 排序 (如果进行了模糊搜索，通常希望保留相关性排序，除非用户显式选择了其他排序)
    // 这里我们简单处理：只有当用户没搜索或者显式选择了排序时才重排。
    // 如果是默认 'date_desc' 且进行了搜索，可能保留 Fuse 的相关性更好？
    // 但为了保持 UI 一致性，我们还是尊重用户的 sortType。
    // 如果用户想看“最相关”，我们可以加一个 'relevance' 选项，目前暂不加。
    
    result.sort((a, b) => {
        if (sortType === 'date_desc') return compareByDateDesc(a, b);
        if (sortType === 'date_asc') return compareByDateAsc(a, b);
        if (sortType === 'title_asc') return a.title.localeCompare(b.title); 
        if (sortType === 'composer_asc') return a.composer.localeCompare(b.composer); 
        return 0;
    });

    renderPaginationTable(result);
    document.getElementById('recentSection').style.display = (filters.search || filters.favoritesOnly || filters.composer || filters.language !== 'all' || filters.voice || filters.category !== 'all') ? 'none' : 'block';
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
                <p class="text-muted mb-4">您可以尝试点击下方按钮，去国际数据库搜索 "<strong>${escapeHtml(searchVal)}</strong>"：</p>
                <div class="d-flex justify-content-center flex-wrap gap-3" style="max-width: 800px; margin: 0 auto;">
                    <a href="https://imslp.org/index.php?title=Special:Search&fulltext=Search&search=${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-dark rounded-pill px-4 shadow-sm">🎼 搜 IMSLP</a>
                    <a href="https://www.google.com/search?q=site:kassiadatabase.com+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-secondary rounded-pill px-4 shadow-sm">👩‍🎤 搜 Kassia</a>
                    <a href="https://www.google.com/search?q=site:songhelix.chpc.utah.edu+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-warning rounded-pill px-4 shadow-sm">🧬 搜 SongHelix</a>
                    <a href="https://www.google.com/search?q=site:opera-arias.com+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-danger rounded-pill px-4 shadow-sm">🎭 搜 Opera-Arias</a>
                    <a href="https://www.google.com/search?q=site:theoperadatabase.com+${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" rel="noopener noreferrer" class="btn btn-outline-info rounded-pill px-4 shadow-sm">📂 搜 Opera Database</a>
                    <a href="https://www.oxfordsong.org/search?q=${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-success rounded-pill px-4 shadow-sm">📜 搜 Oxford Song</a>
                    <a href="https://www.google.com/search?q=${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" rel="noopener noreferrer" class="btn btn-outline-primary rounded-pill px-4 shadow-sm">🔍 搜 Google (PDF)</a>
                </div>
                <p class="mt-4 small text-muted">💡 提示：使用作品原名搜索成功率更高</p>
            `;
        } else {
             if (filters.favoritesOnly) {
                 noResult.innerHTML = '<div class="fs-1 mb-3">❤️</div><h4 class="font-serif">您的收藏夹为空</h4><p>在列表中点击心形图标即可收藏。</p>';
             } else {
                 noResult.innerHTML = '<div class="fs-1 mb-3">🧐</div><h4 class="font-serif">未找到相关乐谱</h4><p>请尝试调整筛选条件。</p>';
             }
        }
        return; 
    }
    noResult.style.display = 'none'; nav.style.display = 'block';

    let html = '';
    pageData.forEach(item => {
        let badgeClass = getCategoryClass(item.category);
        let tonalityBadge = item.tonality ? `<span class="badge bg-light text-dark border ms-2" style="font-size:0.7rem; opacity: 0.7;">${escapeHtml(item.tonality)}</span>` : '';
        let voiceBadge = item.voice_types ? `<span class="badge bg-secondary ms-1" style="font-size:0.7rem; opacity: 0.8;">${escapeHtml(item.voice_types)}</span>` : '';
        let lyricIcon = item.has_lyrics ? `<span class="badge bg-info text-dark ms-1" style="font-size:0.6rem" title="包含歌词/剧本">📖</span>` : '';
        let subBadge = item.sub_category ? `<span class="badge bg-light text-secondary border ms-1" style="font-size:0.7rem;">${escapeHtml(item.sub_category)}</span>` : '';
        
        // Favorite Button Logic
        const stableId = getStableId(item);
        const isFav = favorites.has(stableId);
        const favIcon = isFav ? '❤️' : '🤍';
        const favClass = isFav ? 'text-danger' : 'text-muted';

        html += `<tr onclick="openDetail('${stableId}')" class="hover-row">
            <td class="ps-4">
                <div class="d-flex align-items-center">
                    <button id="fav-btn-${stableId}" class="btn btn-link p-0 me-3 fs-5 text-decoration-none ${favClass}" style="line-height:1;" onclick="toggleFavorite('${stableId}', event)" title="收藏" aria-label="收藏 ${escapeHtml(item.title)}">${favIcon}</button>
                    <div>
                        <div class="fw-bold text-dark" style="font-family: 'Noto Sans SC', sans-serif;">${escapeHtml(item.title)} ${tonalityBadge} ${voiceBadge} ${lyricIcon}</div>
                        ${item.work ? `<small class="text-muted fst-italic">选自: ${escapeHtml(item.work)}</small>` : ''}
                    </div>
                </div>
            </td>
            <td><span class="fw-medium text-secondary">${escapeHtml(item.composer)}</span></td>
            <td>${item.language ? `<span class="text-muted small">${escapeHtml(item.language)}</span>` : '-'}</td>
            <td><span class="badge badge-custom ${badgeClass}">${escapeHtml(item.category)}</span>${subBadge}</td>
            <td class="text-end pe-4"><button class="btn btn-sm btn-outline-primary rounded-pill px-3 shadow-sm">查看</button></td>
        </tr>`;
    });
    tbody.innerHTML = html; renderPaginationControls(pages);
}

window.resetFilters = () => { 
    currentPage = 1; filters = { category: 'all', composer: '', language: 'all', voice: '', search: '', favoritesOnly: false }; 
    document.getElementById('searchInput').value = ''; document.getElementById('composerInput').value = ''; 
    document.getElementById('languageSelect').value = 'all'; document.getElementById('voiceInput').value = ''; 
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat')); 
    document.getElementById('listTitle').innerText = '📚 乐谱目录'; 
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); applyFilters(); 
};

function renderPaginationControls(pages) {
    const ul = document.getElementById('paginationUl');
    let html = '';
    
    // Previous Button
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link border-0" href="#" onclick="changePage(${currentPage - 1}); return false;">&laquo;</a>
    </li>`;

    // Page Numbers (Smart display)
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(pages, startPage + maxVisible - 1);

    if (endPage - startPage + 1 < maxVisible) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link border-0" href="#" onclick="changePage(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link border-0">...</span></li>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link border-0 ${i === currentPage ? 'fw-bold shadow-sm' : ''}" href="#" onclick="changePage(${i}); return false;">${i}</a>
        </li>`;
    }

    if (endPage < pages) {
        if (endPage < pages - 1) html += `<li class="page-item disabled"><span class="page-link border-0">...</span></li>`;
        html += `<li class="page-item"><a class="page-link border-0" href="#" onclick="changePage(${pages}); return false;">${pages}</a></li>`;
    }

    // Next Button
    html += `<li class="page-item ${currentPage === pages ? 'disabled' : ''}">
        <a class="page-link border-0" href="#" onclick="changePage(${currentPage + 1}); return false;">&raquo;</a>
    </li>`;

    ul.innerHTML = html;
}

window.changePage = function(page) {
    if (page < 1) return;
    currentPage = page;
    applyFilters();
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' });
}

window.openDetail = function(id) {
    const stableId = String(id);
    const item = musicData.find(m => getStableId(m) === stableId || String(m.id) === stableId);
    if (!item) return;

    document.getElementById('mTitle').innerText = item.title;
    document.getElementById('mComposer').innerText = item.composer;
    document.getElementById('mWork').innerText = item.work || "";
    document.getElementById('mLanguage').innerText = item.language || "-";
    document.getElementById('mCategory').innerText = item.category;
    document.getElementById('mSubCat').innerText = item.sub_category || "-";
    document.getElementById('mVoice').innerText = item.voice_types || item.voice_count || "-";
    document.getElementById('mTonality').innerText = item.tonality || "-";
    document.getElementById('mDate').innerText = item.date || "-";

    const descCard = document.getElementById('descCard');
    if (item.description) {
        document.getElementById('mDescription').innerText = item.description;
        descCard.style.display = 'block';
    } else {
        descCard.style.display = 'none';
    }

    const dlBtn = document.getElementById('mDownload');
    // Ensure filename is properly encoded
    const encodedFilename = item.filename.split('/').map(part => encodeURIComponent(part)).join('/');
    dlBtn.href = `scores/${encodedFilename}`; 

    const preview = document.getElementById('mPreview');
    const noPreview = document.getElementById('noPreview');
    if (item.filename.toLowerCase().endsWith('.pdf')) {
         preview.src = `scores/${encodedFilename}#toolbar=0&view=FitH`;
         preview.style.display = 'block';
         noPreview.style.display = 'none';
    } else {
         preview.style.display = 'none';
         noPreview.style.display = 'flex';
    }

    currentLyricsId = item.id;
    const lyricBtn = document.getElementById('btnReadLyrics');
    if (item.has_lyrics) {
        lyricBtn.style.display = 'block';
    } else {
        lyricBtn.style.display = 'none';
    }

    const modal = new bootstrap.Modal(document.getElementById('detailModal'));
    modal.show();
}

window.filterCategory = function(cat, btn) {
    filters.category = cat;
    currentPage = 1;
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat'));
    if (btn) btn.classList.add('active-cat');
    document.getElementById('listTitle').innerText = cat === 'all' ? '📚 乐谱目录' : `📂 ${cat}`;
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' });
    applyFilters();
}

window.showLogModal = function() {
    const modalBody = document.getElementById('logBody');
    if (changeLog.length === 0) {
        modalBody.innerHTML = '<p class="text-muted text-center">暂无更新记录。</p>';
    } else {
        let html = '<div class="list-group list-group-flush">';
        changeLog.slice(0, 50).forEach(log => {
            let icon = '🔧';
            let color = 'text-muted';
            if (log.type === 'add') { icon = '✨'; color = 'text-success'; }
            else if (log.type === 'update') { icon = '📝'; color = 'text-primary'; }
            
            html += `
            <div class="list-group-item px-0">
                <div class="d-flex w-100 justify-content-between">
                    <small class="${color} fw-bold">${icon} ${escapeHtml(String(log.type || '').toUpperCase())}</small>
                    <small class="text-muted">${escapeHtml(log.date)}</small>
                </div>
                <p class="mb-1 small">${escapeHtml(log.msg)}</p>
            </div>`;
        });
        html += '</div>';
        modalBody.innerHTML = html;
    }
    const modal = new bootstrap.Modal(document.getElementById('logModal'));
    modal.show();
}

window.showSponsorModal = function() {
    const modal = new bootstrap.Modal(document.getElementById('sponsorModal'));
    modal.show();
}

window.openLyricsReader = async function() {
    if (!currentLyricsId) return;
    
    const transText = document.getElementById('readerTransText');
    const origText = document.getElementById('readerOriginalText');
    
    transText.innerHTML = '<div class="text-center mt-5"><div class="spinner-border text-secondary"></div></div>';
    origText.innerHTML = '<div class="text-center mt-5"><div class="spinner-border text-secondary"></div></div>';
    
    const modal = new bootstrap.Modal(document.getElementById('readerModal'));
    modal.show();
    
    try {
        const res = await fetch(`lyrics/${encodeURIComponent(currentLyricsId)}.json`, { cache: 'no-cache' });
        if (!res.ok) throw new Error("Lyrics not found");
        const data = await res.json();
        
        document.getElementById('readerTitle').innerText = data.title || "歌词/剧本";
        document.getElementById('readerComposer').innerText = data.composer || "";
        
        const formatText = (text) => {
             if (!text) return "<span class='text-muted fst-italic'>（暂无内容）</span>";
             return escapeHtml(text).replace(/\r?\n/g, "<br>");
        };

        origText.innerHTML = `<div class="p-4" style="font-family: 'Times New Roman', serif; font-size: 1.1rem; line-height: 1.6;">${formatText(data.original)}</div>`;
        transText.innerHTML = `<div class="p-4" style="font-family: 'Noto Sans SC', sans-serif; font-size: 1.05rem; line-height: 1.8;">${formatText(data.translation)}</div>`;
        
    } catch (e) {
        origText.innerHTML = `<div class="alert alert-warning m-4">无法加载原文: ${escapeHtml(e.message)}</div>`;
        transText.innerHTML = `<div class="alert alert-warning m-4">无法加载译文</div>`;
    }
}

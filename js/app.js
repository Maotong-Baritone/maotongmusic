// 全局变量
let musicData = [];
let changeLog = [];
let filters = { category: 'all', composer: '', language: 'all', voice: '', search: '', favoritesOnly: false };
let sortType = 'date_desc';
let currentPage = 1;
const itemsPerPage = 15;
let currentLyricsId = null;
let currentPdfUrl = '';
let currentDetailId = null;
let fuseInstance = null; // Fuse.js 实例
let favorites = loadStoredFavorites();
const BASE_PAGE_TITLE = document.title;
let detailHistoryChangeInProgress = false;
const DEFAULT_SCORE_STORAGE = Object.freeze({
    baseUrl: '',
    objectPrefix: 'scores',
    keyStrategy: 'catalog_filename'
});
let scoreStorage = { ...DEFAULT_SCORE_STORAGE };

function normalizeStoragePath(value) {
    const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean);
    if (!parts.length || parts.some(part => part === '.' || part === '..')) return '';
    return parts.join('/');
}

function configureScoreStorage(config) {
    const candidate = config && typeof config === 'object' ? config : {};
    const keyStrategy = ['catalog_filename', 'public_id_sharded'].includes(candidate.keyStrategy)
        ? candidate.keyStrategy
        : DEFAULT_SCORE_STORAGE.keyStrategy;
    const objectPrefix = normalizeStoragePath(candidate.objectPrefix) || DEFAULT_SCORE_STORAGE.objectPrefix;
    const baseUrl = String(candidate.baseUrl || '').trim().replace(/\/+$/, '');
    if (baseUrl && /^[a-z][a-z\d+.-]*:/i.test(baseUrl) && !/^https?:/i.test(baseUrl)) {
        throw new Error('乐谱存储 baseUrl 只允许 HTTP(S) 地址或相对路径');
    }
    scoreStorage = { baseUrl, objectPrefix, keyStrategy };
}

async function loadSiteConfig() {
    try {
        const response = await fetch('site-config.json', { cache: 'no-cache' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const config = await response.json();
        configureScoreStorage(config.scoreStorage);
    } catch (error) {
        scoreStorage = { ...DEFAULT_SCORE_STORAGE };
        console.warn('站点存储配置加载失败，已使用本地 scores/ 目录。', error);
    }
}

function scoreStorageKeyFor(item) {
    const explicitKey = normalizeStoragePath(item.storage_key);
    if (explicitKey) return explicitKey;

    if (scoreStorage.keyStrategy === 'public_id_sharded') {
        const publicId = String(item.public_id || '').toLowerCase();
        if (/^[0-9a-f-]{36}$/.test(publicId)) {
            return `${scoreStorage.objectPrefix}/${publicId.slice(0, 2)}/${publicId}.pdf`;
        }
    }

    const filename = normalizeStoragePath(item.filename);
    return filename ? `${scoreStorage.objectPrefix}/${filename}` : '';
}

function buildScoreUrl(item) {
    const storageKey = scoreStorageKeyFor(item);
    if (!storageKey) return '';
    const encodedKey = storageKey.split('/').map(part => encodeURIComponent(part)).join('/');
    return scoreStorage.baseUrl ? `${scoreStorage.baseUrl}/${encodedKey}` : encodedKey;
}

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
    '器乐分谱': 'bg-inst-parts',
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
    initDetailNavigation();
    loadData();
    document.getElementById('searchInput').addEventListener('keydown', (e) => { if(e.key === 'Enter') performSearch(); });
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
    if (btn) {
        btn.innerHTML = isDark ? '☀️' : '🌙';
        const label = isDark ? '切换到浅色模式' : '切换到深色模式';
        btn.setAttribute('aria-label', label);
        btn.title = label;
    }
}

function updateFavoriteButtons(id) {
    const isFavorite = favorites.has(id);
    document.querySelectorAll('[data-favorite-id]').forEach(button => {
        if (button.dataset.favoriteId !== id) return;
        const icon = button.querySelector('[data-favorite-icon]');
        const copy = button.querySelector('[data-favorite-copy]');
        if (icon) icon.textContent = isFavorite ? '❤️' : '🤍';
        if (copy) copy.textContent = isFavorite ? '已收藏' : '收藏';
        button.classList.toggle('text-danger', isFavorite);
        button.classList.toggle('text-muted', !isFavorite);
        button.setAttribute('aria-pressed', String(isFavorite));
        const title = button.dataset.favoriteTitle || '这份乐谱';
        button.setAttribute('aria-label', `${isFavorite ? '取消收藏' : '收藏'} ${title}`);
        button.title = isFavorite ? '取消收藏' : '收藏';
    });
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
        // 否则只更新同一乐谱的所有按钮状态（避免整页重绘）
        updateFavoriteButtons(id);
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
            fetch('logs.json', { cache: 'no-cache' }),
            loadSiteConfig()
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
        openDetailFromUrl();

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
function performSearch() { const val = document.getElementById('searchInput').value.trim(); filters.search = val; if(val.length > 0) { document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); } applyFilters(); }

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
            <article class="card h-100 shadow-sm hover-card border-0">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <span class="badge ${badgeClass}">${escapeHtml(item.category)}</span>
                        <small class="text-muted" style="font-size: 0.75rem;">${escapeHtml(item.date || '')}</small>
                    </div>
                    <h6 class="card-title mb-1 text-truncate" title="${escapeHtml(item.title)}"><button type="button" class="score-title score-title-button fw-bold text-dark" onclick="openDetail('${stableId}')">${escapeHtml(item.title)}</button></h6>
                    <div class="text-secondary small mb-2 text-truncate" title="${escapeHtml(item.composer)}">${escapeHtml(item.composer)}</div>
                    ${item.work ? `<div class="small text-muted fst-italic text-truncate" title="${escapeHtml(item.work)}">选自: ${escapeHtml(item.work)}</div>` : ''}
                </div>
                <div class="card-footer bg-white border-0 d-flex justify-content-between align-items-center">
                    <button class="btn btn-sm btn-link text-decoration-none p-0 ${favClass}" data-favorite-id="${stableId}" data-favorite-title="${escapeHtml(item.title)}" onclick="toggleFavorite('${stableId}', event)" title="${isFav ? '取消收藏' : '收藏'}" aria-label="${isFav ? '取消收藏' : '收藏'} ${escapeHtml(item.title)}" aria-pressed="${isFav}"><span data-favorite-icon aria-hidden="true">${favIcon}</span></button>
                    <div class="d-flex align-items-center gap-2"><span class="badge bg-light text-secondary border">${escapeHtml(item.language || '-')}</span><button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3" onclick="openDetail('${stableId}')">查看详情</button></div>
                </div>
            </article>
        </div>
        `;
    });

    recentContainer.innerHTML = html;
}

function getActiveFilterDescriptors() {
    const activeFilters = [];
    if (filters.favoritesOnly) activeFilters.push({ key: 'favorites', label: '仅看收藏' });
    if (filters.category !== 'all') activeFilters.push({ key: 'category', label: `分类：${filters.category}` });
    if (filters.composer.trim()) activeFilters.push({ key: 'composer', label: `作曲家：${filters.composer.trim()}` });
    if (filters.language !== 'all') activeFilters.push({ key: 'language', label: `语言：${filters.language}` });
    if (filters.voice.trim()) activeFilters.push({ key: 'voice', label: `编制：${filters.voice.trim()}` });
    return activeFilters;
}

function renderActiveFilters() {
    const activeFilters = getActiveFilterDescriptors();
    const bar = document.getElementById('activeFiltersBar');
    const list = document.getElementById('activeFiltersList');
    const resetButton = document.getElementById('filterResetBtn');

    bar.hidden = activeFilters.length === 0;
    list.innerHTML = activeFilters.map(filter => `
        <button type="button" class="active-filter-chip" onclick="removeActiveFilter('${filter.key}')" aria-label="移除${escapeHtml(filter.label)}筛选">
            <span>${escapeHtml(filter.label)}</span><span class="filter-chip-remove" aria-hidden="true">×</span>
        </button>
    `).join('');

    if (activeFilters.length > 0) {
        resetButton.disabled = false;
        resetButton.classList.add('is-active');
        resetButton.innerText = `清除筛选（${activeFilters.length}）`;
    } else if (filters.search) {
        resetButton.disabled = false;
        resetButton.classList.remove('is-active');
        resetButton.innerText = '清除搜索';
    } else {
        resetButton.disabled = true;
        resetButton.classList.remove('is-active');
        resetButton.innerText = '暂无筛选';
    }
}

function updateListTitle() {
    const listTitle = document.getElementById('listTitle');
    if (filters.favoritesOnly) {
        listTitle.innerText = '❤️ 我的收藏';
    } else if (filters.search) {
        listTitle.innerText = `🔍 “${filters.search}” 的搜索结果`;
    } else if (filters.category !== 'all') {
        listTitle.innerText = `📂 ${filters.category}`;
    } else {
        listTitle.innerText = '📚 乐谱目录';
    }
}

function clearNonSearchFilters() {
    filters.category = 'all';
    filters.composer = '';
    filters.language = 'all';
    filters.voice = '';
    filters.favoritesOnly = false;
    currentPage = 1;

    document.getElementById('composerInput').value = '';
    document.getElementById('languageSelect').value = 'all';
    document.getElementById('voiceInput').value = '';
    document.querySelectorAll('.category-group button').forEach(button => button.classList.remove('active-cat'));
}

window.clearFiltersAndRetry = function() {
    clearNonSearchFilters();
    applyFilters();
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

window.handleFilterReset = function() {
    if (getActiveFilterDescriptors().length > 0) {
        clearFiltersAndRetry();
    } else {
        resetFilters();
    }
}

window.removeActiveFilter = function(key) {
    if (key === 'favorites') filters.favoritesOnly = false;
    if (key === 'category') {
        filters.category = 'all';
        document.querySelectorAll('.category-group button').forEach(button => button.classList.remove('active-cat'));
    }
    if (key === 'composer') document.getElementById('composerInput').value = '';
    if (key === 'language') document.getElementById('languageSelect').value = 'all';
    if (key === 'voice') document.getElementById('voiceInput').value = '';
    currentPage = 1;
    applyFilters();
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

    renderActiveFilters();
    updateListTitle();
    renderPaginationTable(result);
    document.getElementById('recentSection').style.display = (filters.search || filters.favoritesOnly || filters.composer || filters.language !== 'all' || filters.voice || filters.category !== 'all') ? 'none' : 'block';
}

function getCategoryClass(cat) { for (const key in categoryMap) { if (cat.includes(key)) return categoryMap[key]; } return 'bg-other'; }

function renderPaginationTable(data) {
    const total = data.length; const pages = Math.ceil(total / itemsPerPage);
    if (currentPage > pages) currentPage = pages || 1; if (currentPage < 1) currentPage = 1;
    const start = (currentPage - 1) * itemsPerPage; const pageData = data.slice(start, start + itemsPerPage);
    const tbody = document.getElementById('mainTableBody'); document.getElementById('filteredCount').innerText = total + ' 首乐谱';
    const mobileList = document.getElementById('mobileScoreList');
    
    const noResult = document.getElementById('noResult');
    const nav = document.getElementById('paginationNav');
    
    if (total === 0) { 
        tbody.innerHTML = '';
        mobileList.innerHTML = '';
        nav.style.display = 'none'; 
        noResult.style.display = 'block'; 
        
        const searchVal = document.getElementById('searchInput').value.trim();
        const activeFilters = getActiveFilterDescriptors();
        const activeFilterChips = activeFilters.map(filter => `<span class="active-filter-chip is-static">${escapeHtml(filter.label)}</span>`).join('');
        if (searchVal) {
            noResult.innerHTML = `
                <div class="fs-1 mb-3">🧐</div>
                <h4 class="font-serif mb-3">${activeFilters.length > 0 ? `当前筛选下没有找到“${escapeHtml(searchVal)}”` : '本地暂无相关乐谱'}</h4>
                ${activeFilters.length > 0 ? `
                    <div class="no-result-filter-alert">
                        <p class="fw-bold mb-2">搜索仍受到以下 ${activeFilters.length} 个条件限制：</p>
                        <div class="active-filters-list mb-3">${activeFilterChips}</div>
                        <p class="small mb-3">清除这些条件后会保留当前关键词并立即重新搜索，无需再次输入。</p>
                        <button type="button" class="btn btn-warning rounded-pill px-4 fw-bold" onclick="clearFiltersAndRetry()">清除筛选并重新搜索</button>
                    </div>
                    <div class="no-result-divider"><span>清除后仍未找到？</span></div>
                ` : '<p class="text-muted mb-4">当前没有其他筛选条件，可以尝试前往以下数据库继续查找：</p>'}
                <p class="text-muted mb-4">您也可以去国际数据库搜索 "<strong>${escapeHtml(searchVal)}</strong>"：</p>
                <div class="d-flex justify-content-center flex-wrap gap-3" style="max-width: 800px; margin: 0 auto;">
                    <a href="https://imslp.org/index.php?title=Special:Search&fulltext=Search&search=${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-dark rounded-pill px-4 shadow-sm">🎼 搜 IMSLP</a>
                    <a href="https://www.google.com/search?q=site:kassiadatabase.com+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-secondary rounded-pill px-4 shadow-sm">👩‍🎤 搜 Kassia</a>
                    <a href="https://www.google.com/search?q=site:songhelix.chpc.utah.edu+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-warning rounded-pill px-4 shadow-sm">🧬 搜 SongHelix</a>
                    <a href="https://www.google.com/search?q=site:opera-arias.com+${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-danger rounded-pill px-4 shadow-sm">🎭 搜 Opera-Arias</a>
                    <a href="https://www.google.com/search?q=site:theoperadatabase.com+${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" rel="noopener noreferrer" class="btn btn-outline-info rounded-pill px-4 shadow-sm">📂 搜 Opera Database</a>
                    <a href="https://www.oxfordsong.org/search?q=${encodeURIComponent(searchVal)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-success rounded-pill px-4 shadow-sm">📜 搜 Oxford Song</a>
                    <a href="https://www.google.com/search?q=${encodeURIComponent(searchVal)}+filetype:pdf" target="_blank" rel="noopener noreferrer" class="btn btn-outline-primary rounded-pill px-4 shadow-sm">🔍 搜 Google (PDF)</a>
                </div>
                <p class="mt-4 small text-muted mb-3">💡 提示：使用作品原名搜索成功率更高</p>
                <div class="border-top pt-4 mt-4">
                    <p class="mb-3">站内暂未收录的乐谱，可能尚未整理上传，也可能暂不具备公开分享条件。</p>
                    <div class="d-flex justify-content-center flex-wrap gap-2">
                        <a href="contact.html" class="btn btn-primary rounded-pill px-4">💬 联系我求谱</a>
                        <button type="button" class="btn btn-link text-secondary" onclick="showUsageNotice()">了解收录与版权说明</button>
                    </div>
                </div>
            `;
        } else {
             if (filters.favoritesOnly) {
                 noResult.innerHTML = '<div class="fs-1 mb-3">❤️</div><h4 class="font-serif">您的收藏夹为空</h4><p>当前启用了“仅看收藏”。在列表中点击心形图标即可收藏，或返回查看完整乐谱目录。</p><button type="button" class="btn btn-primary rounded-pill px-4" onclick="clearFiltersAndRetry()">查看完整乐谱目录</button>';
             } else if (activeFilters.length > 0) {
                 noResult.innerHTML = `<div class="fs-1 mb-3">🧐</div><h4 class="font-serif">当前筛选下没有找到乐谱</h4><div class="no-result-filter-alert"><p class="fw-bold mb-2">仍在生效：</p><div class="active-filters-list mb-3">${activeFilterChips}</div><button type="button" class="btn btn-warning rounded-pill px-4 fw-bold" onclick="clearFiltersAndRetry()">清除全部筛选</button></div>`;
             } else {
                 noResult.innerHTML = '<div class="fs-1 mb-3">🧐</div><h4 class="font-serif">未找到相关乐谱</h4><p>它可能尚未收录，也可能暂不具备公开分享条件。</p><a href="contact.html" class="btn btn-primary rounded-pill px-4">💬 联系我求谱</a>';
             }
        }
        return; 
    }
    noResult.style.display = 'none'; nav.style.display = 'block';

    let html = '';
    let mobileHtml = '';
    pageData.forEach(item => {
        let badgeClass = getCategoryClass(item.category);
        let tonalityBadge = item.tonality ? `<span class="badge bg-light text-dark border ms-2" style="font-size:0.7rem; opacity: 0.7;">${escapeHtml(item.tonality)}</span>` : '';
        let voiceBadge = item.voice_types ? `<span class="badge bg-secondary ms-1" style="font-size:0.7rem; opacity: 0.8;">${escapeHtml(item.voice_types)}</span>` : '';
        let lyricIcon = item.has_lyrics ? `<span class="badge bg-info text-dark ms-1" style="font-size:0.6rem" title="包含歌词/剧本">📖</span>` : '';
        const redundantSubcategory = item.sub_category === item.category
            || (item.category === '艺术歌曲' && item.sub_category === '香颂');
        let subBadge = item.sub_category && !redundantSubcategory ? `<span class="badge bg-light text-secondary border ms-1" style="font-size:0.7rem;">${escapeHtml(item.sub_category)}</span>` : '';
        
        // Favorite Button Logic
        const stableId = getStableId(item);
        const isFav = favorites.has(stableId);
        const favIcon = isFav ? '❤️' : '🤍';
        const favClass = isFav ? 'text-danger' : 'text-muted';

        html += `<tr class="hover-row">
            <td class="ps-4">
                <div class="d-flex align-items-center">
                    <button class="btn btn-link p-0 me-3 fs-5 text-decoration-none ${favClass}" data-favorite-id="${stableId}" data-favorite-title="${escapeHtml(item.title)}" style="line-height:1;" onclick="toggleFavorite('${stableId}', event)" title="${isFav ? '取消收藏' : '收藏'}" aria-label="${isFav ? '取消收藏' : '收藏'} ${escapeHtml(item.title)}" aria-pressed="${isFav}"><span data-favorite-icon aria-hidden="true">${favIcon}</span></button>
                    <div>
                        <div><button type="button" class="score-title score-title-button fw-bold text-dark" onclick="openDetail('${stableId}')">${escapeHtml(item.title)}</button> ${tonalityBadge} ${voiceBadge} ${lyricIcon}</div>
                        ${item.work ? `<small class="text-muted fst-italic">选自: ${escapeHtml(item.work)}</small>` : ''}
                    </div>
                </div>
            </td>
            <td><span class="fw-medium text-secondary">${escapeHtml(item.composer)}</span></td>
            <td>${item.language ? `<span class="text-muted small">${escapeHtml(item.language)}</span>` : '-'}</td>
            <td><span class="badge badge-custom ${badgeClass}">${escapeHtml(item.category)}</span>${subBadge}</td>
            <td class="text-end pe-4"><button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3 shadow-sm" onclick="openDetail('${stableId}')" aria-label="查看 ${escapeHtml(item.title)} 的详情">查看</button></td>
        </tr>`;

        mobileHtml += `
            <article class="mobile-score-card">
                <div class="d-flex justify-content-between align-items-start gap-3 mb-2">
                    <span class="badge badge-custom ${badgeClass}">${escapeHtml(item.category)}</span>
                    <small class="text-muted text-nowrap">${escapeHtml(item.date || '')}</small>
                </div>
                <h3 class="h6 mb-2"><button type="button" class="score-title score-title-button fw-bold text-dark text-start" onclick="openDetail('${stableId}')">${escapeHtml(item.title)}</button></h3>
                <p class="small text-secondary fw-medium mb-1">${escapeHtml(item.composer)}</p>
                ${item.work ? `<p class="small text-muted fst-italic mb-2">选自: ${escapeHtml(item.work)}</p>` : ''}
                <div class="d-flex flex-wrap gap-1 mb-3">${tonalityBadge}${voiceBadge}${lyricIcon}${subBadge}${item.language ? `<span class="badge bg-light text-secondary border">${escapeHtml(item.language)}</span>` : ''}</div>
                <div class="d-flex justify-content-between align-items-center border-top pt-3">
                    <button class="btn btn-sm btn-link text-decoration-none p-0 ${favClass}" data-favorite-id="${stableId}" data-favorite-title="${escapeHtml(item.title)}" onclick="toggleFavorite('${stableId}', event)" title="${isFav ? '取消收藏' : '收藏'}" aria-label="${isFav ? '取消收藏' : '收藏'} ${escapeHtml(item.title)}" aria-pressed="${isFav}"><span data-favorite-icon aria-hidden="true">${favIcon}</span><span class="ms-1" data-favorite-copy>${isFav ? '已收藏' : '收藏'}</span></button>
                    <button type="button" class="btn btn-sm btn-primary rounded-pill px-3" onclick="openDetail('${stableId}')">查看详情</button>
                </div>
            </article>`;
    });
    tbody.innerHTML = html;
    mobileList.innerHTML = mobileHtml;
    renderPaginationControls(pages);
}

window.resetFilters = () => { 
    currentPage = 1; filters = { category: 'all', composer: '', language: 'all', voice: '', search: '', favoritesOnly: false }; 
    document.getElementById('searchInput').value = ''; document.getElementById('composerInput').value = ''; 
    document.getElementById('languageSelect').value = 'all'; document.getElementById('voiceInput').value = ''; 
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat')); 
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' }); applyFilters(); 
};

function renderPaginationControls(pages) {
    const ul = document.getElementById('paginationUl');
    let html = '';
    
    // Previous Button
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <button type="button" class="page-link border-0" onclick="changePage(${currentPage - 1})" aria-label="上一页" ${currentPage === 1 ? 'disabled' : ''}>&laquo;</button>
    </li>`;

    // Page Numbers (Smart display)
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(pages, startPage + maxVisible - 1);

    if (endPage - startPage + 1 < maxVisible) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
        html += `<li class="page-item"><button type="button" class="page-link border-0" onclick="changePage(1)" aria-label="第 1 页">1</button></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link border-0">...</span></li>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <button type="button" class="page-link border-0 ${i === currentPage ? 'fw-bold shadow-sm' : ''}" onclick="changePage(${i})" aria-label="第 ${i} 页" ${i === currentPage ? 'aria-current="page"' : ''}>${i}</button>
        </li>`;
    }

    if (endPage < pages) {
        if (endPage < pages - 1) html += `<li class="page-item disabled"><span class="page-link border-0">...</span></li>`;
        html += `<li class="page-item"><button type="button" class="page-link border-0" onclick="changePage(${pages})" aria-label="第 ${pages} 页">${pages}</button></li>`;
    }

    // Next Button
    html += `<li class="page-item ${currentPage === pages ? 'disabled' : ''}">
        <button type="button" class="page-link border-0" onclick="changePage(${currentPage + 1})" aria-label="下一页" ${currentPage === pages ? 'disabled' : ''}>&raquo;</button>
    </li>`;

    ul.innerHTML = html;
}

window.changePage = function(page) {
    if (page < 1) return;
    currentPage = page;
    applyFilters();
    document.getElementById('mainContentArea').scrollIntoView({ behavior: 'smooth' });
}

function detailUrlFor(id) {
    const url = new URL(window.location.href);
    url.searchParams.set('score', id);
    return url;
}

function clearPdfPreview() {
    const preview = document.getElementById('mPreview');
    const placeholder = document.getElementById('previewPlaceholder');
    try {
        preview.contentWindow.location.replace('about:blank');
    } catch (error) {
        preview.src = 'about:blank';
    }
    delete preview.dataset.loadedUrl;
    preview.style.display = 'none';
    placeholder.style.display = 'flex';
}

function initDetailNavigation() {
    const modalElement = document.getElementById('detailModal');
    modalElement.addEventListener('hidden.bs.modal', () => {
        clearPdfPreview();
        currentPdfUrl = '';
        currentDetailId = null;
        currentLyricsId = null;
        document.title = BASE_PAGE_TITLE;

        if (detailHistoryChangeInProgress) {
            detailHistoryChangeInProgress = false;
            return;
        }

        const url = new URL(window.location.href);
        if (url.searchParams.has('score')) {
            url.searchParams.delete('score');
            window.history.replaceState(null, '', url);
        }
    });

    window.addEventListener('popstate', () => {
        if (!musicData.length) return;
        const scoreId = new URL(window.location.href).searchParams.get('score');
        const isOpen = modalElement.classList.contains('show');
        if (scoreId) {
            openDetail(scoreId, { syncUrl: false });
        } else if (isOpen) {
            detailHistoryChangeInProgress = true;
            bootstrap.Modal.getOrCreateInstance(modalElement).hide();
        }
    });
}

function openDetailFromUrl() {
    const scoreId = new URL(window.location.href).searchParams.get('score');
    if (scoreId) openDetail(scoreId, { syncUrl: false });
}

window.loadPdfPreview = function() {
    if (!currentPdfUrl) return;
    const preview = document.getElementById('mPreview');
    try {
        preview.contentWindow.location.replace(currentPdfUrl);
    } catch (error) {
        preview.src = currentPdfUrl;
    }
    preview.dataset.loadedUrl = currentPdfUrl;
    preview.style.display = 'block';
    document.getElementById('previewPlaceholder').style.display = 'none';
}

window.copyDetailLink = async function() {
    if (!currentDetailId) return;
    const button = document.getElementById('btnShareDetail');
    const detailUrl = detailUrlFor(currentDetailId).toString();
    try {
        await navigator.clipboard.writeText(detailUrl);
        button.textContent = '✅ 链接已复制';
    } catch (error) {
        console.warn('无法复制详情链接。', error);
        button.textContent = '请从地址栏复制链接';
    }
    window.setTimeout(() => { button.textContent = '🔗 复制详情链接'; }, 1800);
}

window.openDetail = function(id, { syncUrl = true } = {}) {
    const stableId = String(id);
    const item = musicData.find(m => getStableId(m) === stableId || String(m.id) === stableId);
    if (!item) return;

    currentDetailId = getStableId(item);
    if (syncUrl) {
        window.history.pushState({ scoreId: currentDetailId }, '', detailUrlFor(currentDetailId));
    }
    document.title = `${item.title} | ${BASE_PAGE_TITLE}`;

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
    const filename = String(item.filename || '');
    const pdfUrl = buildScoreUrl(item);
    dlBtn.href = pdfUrl;
    dlBtn.download = `${item.title || 'score'}.pdf`;
    document.getElementById('mOpenPdf').href = pdfUrl;
    document.getElementById('btnShareDetail').textContent = '🔗 复制详情链接';

    const previewStatus = document.getElementById('previewStatus');
    const previewHelp = document.getElementById('previewHelp');
    const previewActions = document.getElementById('previewActions');
    clearPdfPreview();
    if (filename.toLowerCase().endsWith('.pdf')) {
         currentPdfUrl = `${pdfUrl}#toolbar=0&view=FitH`;
         previewStatus.innerText = 'PDF 预览尚未加载';
         previewHelp.innerText = '为节省流量，只有点击按钮后才会载入乐谱。';
         previewActions.style.display = 'flex';
    } else {
         currentPdfUrl = '';
         previewStatus.innerText = '暂无可用预览';
         previewHelp.innerText = '这份资料目前不能在浏览器中预览。';
         previewActions.style.display = 'none';
    }

    currentLyricsId = item.id;
    const lyricBtn = document.getElementById('btnReadLyrics');
    if (item.has_lyrics) {
        lyricBtn.style.display = 'block';
    } else {
        lyricBtn.style.display = 'none';
    }

    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('detailModal'));
    modal.show();
}

window.filterCategory = function(cat, btn) {
    filters.category = cat;
    currentPage = 1;
    document.querySelectorAll('.category-group button').forEach(b => b.classList.remove('active-cat'));
    if (btn) btn.classList.add('active-cat');
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

window.showUsageNotice = function() {
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('usageNoticeModal'));
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

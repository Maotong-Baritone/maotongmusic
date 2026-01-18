// 全局变量
let musicData = [];
let changeLog = [];
let filters = { category: 'all', composer: '', language: 'all', voice: '', search: '', favoritesOnly: false };
let sortType = 'date_desc';
let currentPage = 1;
const itemsPerPage = 15;
let currentLyricsId = null;
let fuseInstance = null; // Fuse.js 实例
let favorites = new Set(JSON.parse(localStorage.getItem('favorites') || '[]'));

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
    
    if (favorites.has(id)) {
        favorites.delete(id);
    } else {
        favorites.add(id);
    }
    localStorage.setItem('favorites', JSON.stringify([...favorites]));
    
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
            fetch('data.json?v=' + new Date().getTime()),
            fetch('logs.json?v=' + new Date().getTime())
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
                let extra = "";
                if (composerAliases[item.composer]) {
                    extra = composerAliases[item.composer];
                }
                return { ...item, _search_composer_alias: extra }; 
            });
            // 更新 keys 以包含别名
            fuseOptions.keys.push({ name: '_search_composer_alias', weight: 0.3 });
            
            fuseInstance = new Fuse(searchableData, fuseOptions);
        }
        
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
    filters.composer = document.getElementById('composerInput').value; 
    filters.language = document.getElementById('languageSelect').value;
    filters.voice = document.getElementById('voiceInput').value; 
    sortType = document.getElementById('sortSelect').value;
    
    let result = musicData;
    
    // 0. 收藏夹过滤
    if (filters.favoritesOnly) {
        result = result.filter(item => favorites.has(item.id));
    }

    // 1. 如果有搜索词，优先使用 Fuse.js 进行模糊搜索
    if (filters.search && fuseInstance) {
        const fuseResults = fuseInstance.search(filters.search);
        result = fuseResults.map(r => r.item);
        // 如果同时在看收藏夹，需要取交集
        if (filters.favoritesOnly) {
             result = result.filter(item => favorites.has(item.id));
        }
    } else if (filters.search) {
        // Fallback: 如果 Fuse 未加载，使用旧的简单搜索
        const searchBase = normalizeStr(filters.search);
        result = result.filter(item => {
             const itemTitle = normalizeStr(item.title); 
             const itemComposer = normalizeStr(item.composer); 
             const itemWork = normalizeStr(item.work); 
             const itemDesc = normalizeStr(item.description);
             let composerKeywords = itemComposer; 
             if (composerAliases[item.composer]) { composerKeywords += " " + normalizeStr(composerAliases[item.composer]); }
             const fullSearchableText = `${itemTitle} ${composerKeywords} ${itemWork} ${itemDesc}`;
             return fullSearchableText.includes(searchBase);
        });
    }

    // 2. 应用其他过滤器 (精确匹配)
    const searchComposer = normalizeStr(filters.composer);
    const searchVoice = normalizeStr(filters.voice);
    
    result = result.filter(item => {
        let composerKeywords = normalizeStr(item.composer); 
        if (composerAliases[item.composer]) { composerKeywords += " " + normalizeStr(composerAliases[item.composer]); }
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
        if (sortType === 'date_desc') return b.id - a.id; 
        if (sortType === 'date_asc') return a.id - b.id;
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
        let tonalityBadge = item.tonality ? `<span class="badge bg-light text-dark border ms-2" style="font-size:0.7rem; opacity: 0.7;">${item.tonality}</span>` : '';
        let voiceBadge = item.voice_types ? `<span class="badge bg-secondary ms-1" style="font-size:0.7rem; opacity: 0.8;">${item.voice_types}</span>` : '';
        let lyricIcon = item.has_lyrics ? `<span class="badge bg-info text-dark ms-1" style="font-size:0.6rem" title="包含歌词/剧本">📖</span>` : '';
        let subBadge = item.sub_category ? `<span class="badge bg-light text-secondary border ms-1" style="font-size:0.7rem;">${item.sub_category}</span>` : '';
        
        // Favorite Button Logic
        const isFav = favorites.has(item.id);
        const favIcon = isFav ? '❤️' : '🤍';
        const favClass = isFav ? 'text-danger' : 'text-muted';

        html += `<tr onclick="openDetail(${item.id})" class="hover-row">
            <td class="ps-4">
                <div class="d-flex align-items-center">
                    <button id="fav-btn-${item.id}" class="btn btn-link p-0 me-3 fs-5 text-decoration-none ${favClass}" style="line-height:1;" onclick="toggleFavorite(${item.id}, event)" title="收藏">${favIcon}</button>
                    <div>
                        <div class="fw-bold text-dark" style="font-family: 'Noto Sans SC', sans-serif;">${item.title} ${tonalityBadge} ${voiceBadge} ${lyricIcon}</div>
                        ${item.work ? `<small class="text-muted fst-italic">选自: ${item.work}</small>` : ''}
                    </div>
                </div>
            </td>
            <td><span class="fw-medium text-secondary">${item.composer}</span></td>
            <td>${item.language ? `<span class="text-muted small">${item.language}</span>` : '-'}</td>
            <td><span class="badge badge-custom ${badgeClass}">${item.category}</span>${subBadge}</td>
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

// ... (Rest of the file)
(() => {
    const grid = document.getElementById('resourceGrid');
    const filters = document.getElementById('resourceFilters');
    const search = document.getElementById('resourceSearch');
    const count = document.getElementById('resourceCount');
    const clearButton = document.getElementById('resourceClear');
    const empty = document.getElementById('resourceEmpty');
    const themeButton = document.getElementById('resourceThemeToggle');
    let activeArea = '全部';

    const legacyTaxonomy = {
        '乐谱与曲目': ['表演', '查找乐谱与曲目'],
        '声乐与语言': ['表演', '专业协会与演奏资源'],
        '歌剧与演出': ['表演', '查看演出、角色与录音'],
        '合唱与宗教音乐': ['表演', '专业协会与演奏资源'],
        '音乐学与研究': ['研究', '学术研究与历史档案'],
        '历史档案': ['研究', '学术研究与历史档案'],
        '录音与聆听': ['研究', '查看演出、角色与录音'],
        'Audition 与职业': ['职业', '比赛、Audition 与职业发展']
    };
    MUSIC_RESOURCES.forEach(item => {
        const fallback = legacyTaxonomy[item.category] || ['其他', '其他专业资源'];
        item.area ||= fallback[0];
        item.usage ||= fallback[1];
    });

    const areas = ['全部', '表演', '创作与理论', '研究', '教育', '职业'];
    const usageOrder = [
        '查找乐谱与曲目',
        '专业协会与演奏资源',
        '作曲、新音乐与理论学习',
        '学术研究与历史档案',
        '查看演出、角色与录音',
        '教学、课程与专业发展',
        '比赛、Audition 与职业发展',
        '其他专业资源'
    ];
    const usageMeta = {
        '查找乐谱与曲目': ['🎼', '查总谱、分谱、合唱谱、歌剧和历史版本'],
        '专业协会与演奏资源': ['🎻', '按专业查找曲目、教学、比赛、期刊和行业资源'],
        '作曲、新音乐与理论学习': ['✍️', '学习乐理、训练听力，查找创作资助和新音乐机会'],
        '学术研究与历史档案': ['🔎', '查文献、百科、手稿、历史乐谱和原始资料'],
        '查看演出、角色与录音': ['🎧', '查歌剧角色、历史演出、艺术家记录和参考录音'],
        '教学、课程与专业发展': ['🎓', '查教学材料、教师认证、学生项目和专业发展机会'],
        '比赛、Audition 与职业发展': ['💼', '查乐团 Audition、青年艺术家项目、比赛和行业职位'],
        '其他专业资源': ['🗂️', '其他值得收藏的音乐专业入口']
    };
    const accessClass = { '免费': 'access-free', '部分免费': 'access-partial', '订阅': 'access-paid', '机构访问': 'access-institution' };

    const escapeHtml = value => String(value).replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));

    function renderFilters() {
        filters.innerHTML = areas.map(area => `
            <button type="button" class="resource-filter${area === activeArea ? ' active' : ''}" data-area="${escapeHtml(area)}" aria-pressed="${area === activeArea}">${escapeHtml(area)}</button>
        `).join('');
    }

    function render() {
        const query = search.value.trim().toLocaleLowerCase('zh-CN');
        const visible = MUSIC_RESOURCES.filter(item => {
            const matchesArea = activeArea === '全部' || item.area === activeArea;
            const haystack = [item.name, item.fullName, item.area, item.usage, item.category, item.summary, item.details, item.audience, item.access, ...item.tags].join(' ').toLocaleLowerCase('zh-CN');
            return matchesArea && (!query || haystack.includes(query));
        });

        const renderCard = item => `
            <article class="resource-card">
                <div class="resource-card-top">
                    <span class="resource-icon" aria-hidden="true">${item.icon}</span>
                    <span class="resource-category">${escapeHtml(item.category)}</span>
                    <span class="resource-access ${accessClass[item.access] || ''}">${escapeHtml(item.access)}</span>
                </div>
                <div class="resource-card-body">
                    <h2>${escapeHtml(item.name)}</h2>
                    <p class="resource-full-name">${escapeHtml(item.fullName)}</p>
                    <p class="resource-summary">${escapeHtml(item.summary)}</p>
                    <details class="resource-details">
                        <summary>查看详细介绍</summary>
                        <p>${escapeHtml(item.details)}</p>
                        <p class="resource-audience"><strong>适合：</strong>${escapeHtml(item.audience)}</p>
                    </details>
                </div>
                <div class="resource-tags">${item.tags.map(tag => `<button type="button" class="resource-tag" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`).join('')}</div>
                <a class="resource-visit" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" aria-label="访问 ${escapeHtml(item.name)}（在新标签页打开）">访问网站 <span aria-hidden="true">↗</span></a>
            </article>
        `;

        const grouped = usageOrder
            .map(usage => [usage, visible.filter(item => item.usage === usage)])
            .filter(([, items]) => items.length);
        grid.innerHTML = grouped.map(([usage, items]) => {
            const [icon, description] = usageMeta[usage];
            return `
                <section class="resource-group" aria-labelledby="usage-${usageOrder.indexOf(usage)}">
                    <header class="resource-group-header">
                        <div class="resource-group-icon" aria-hidden="true">${icon}</div>
                        <div>
                            <div class="resource-group-title-row">
                                <h2 id="usage-${usageOrder.indexOf(usage)}">${escapeHtml(usage)}</h2>
                                <span>${items.length} 个资源</span>
                            </div>
                            <p>${escapeHtml(description)}</p>
                        </div>
                    </header>
                    <div class="resource-group-grid">${items.map(renderCard).join('')}</div>
                </section>`;
        }).join('');

        count.textContent = `共 ${MUSIC_RESOURCES.length} 个资源，当前显示 ${visible.length} 个`;
        empty.hidden = visible.length !== 0;
        grid.hidden = visible.length === 0;
        clearButton.hidden = activeArea === '全部' && !query;
        renderFilters();
    }

    filters.addEventListener('click', event => {
        const button = event.target.closest('[data-area]');
        if (!button) return;
        activeArea = button.dataset.area;
        render();
    });
    grid.addEventListener('click', event => {
        const tag = event.target.closest('[data-tag]');
        if (!tag) return;
        search.value = tag.dataset.tag;
        activeArea = '全部';
        render();
        search.focus();
    });
    search.addEventListener('input', render);
    clearButton.addEventListener('click', () => {
        search.value = '';
        activeArea = '全部';
        render();
        search.focus();
    });

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        themeButton.textContent = theme === 'dark' ? '☀️' : '🌙';
        themeButton.title = theme === 'dark' ? '切换浅色模式' : '切换深色模式';
    }
    applyTheme(localStorage.getItem('theme') === 'dark' ? 'dark' : 'light');
    themeButton.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', next);
        applyTheme(next);
    });

    render();
})();

(() => {
    const grid = document.getElementById('resourceGrid');
    const filters = document.getElementById('resourceFilters');
    const search = document.getElementById('resourceSearch');
    const count = document.getElementById('resourceCount');
    const clearButton = document.getElementById('resourceClear');
    const empty = document.getElementById('resourceEmpty');
    const themeButton = document.getElementById('resourceThemeToggle');
    let activeCategory = '全部';

    const categories = ['全部', ...new Set(MUSIC_RESOURCES.map(item => item.category))];
    const accessClass = { '免费': 'access-free', '部分免费': 'access-partial', '订阅': 'access-paid', '机构访问': 'access-institution' };

    const escapeHtml = value => String(value).replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));

    function renderFilters() {
        filters.innerHTML = categories.map(category => `
            <button type="button" class="resource-filter${category === activeCategory ? ' active' : ''}" data-category="${escapeHtml(category)}" aria-pressed="${category === activeCategory}">${escapeHtml(category)}</button>
        `).join('');
    }

    function render() {
        const query = search.value.trim().toLocaleLowerCase('zh-CN');
        const visible = MUSIC_RESOURCES.filter(item => {
            const matchesCategory = activeCategory === '全部' || item.category === activeCategory;
            const haystack = [item.name, item.fullName, item.category, item.summary, item.details, item.audience, item.access, ...item.tags].join(' ').toLocaleLowerCase('zh-CN');
            return matchesCategory && (!query || haystack.includes(query));
        });

        grid.innerHTML = visible.map(item => `
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
        `).join('');

        count.textContent = `共 ${MUSIC_RESOURCES.length} 个资源，当前显示 ${visible.length} 个`;
        empty.hidden = visible.length !== 0;
        grid.hidden = visible.length === 0;
        clearButton.hidden = activeCategory === '全部' && !query;
        renderFilters();
    }

    filters.addEventListener('click', event => {
        const button = event.target.closest('[data-category]');
        if (!button) return;
        activeCategory = button.dataset.category;
        render();
    });
    grid.addEventListener('click', event => {
        const tag = event.target.closest('[data-tag]');
        if (!tag) return;
        search.value = tag.dataset.tag;
        activeCategory = '全部';
        render();
        search.focus();
    });
    search.addEventListener('input', render);
    clearButton.addEventListener('click', () => {
        search.value = '';
        activeCategory = '全部';
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

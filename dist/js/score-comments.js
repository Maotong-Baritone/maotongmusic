(function () {
    'use strict';

    const byId = id => document.getElementById(id);
    const tokenPattern = /^[a-f0-9]{64}$/;
    const idPattern = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;

    async function json(url, options) {
        const response = await fetch(url, {
            cache: 'no-store', mode: 'cors', credentials: 'omit', redirect: 'error',
            referrerPolicy: 'same-origin', ...options
        });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data) throw new Error(data?.error || '留言服务暂时不可用，请稍后再试。');
        return data;
    }

    const receiptStatus = byId('commentReceiptStatus');
    if (receiptStatus) {
        const [id, token, extra] = location.hash.slice(1).split('.');
        if (!idPattern.test(id) || !tokenPattern.test(token) || extra !== undefined) {
            receiptStatus.textContent = '请打开提交后保存的完整管理链接。';
            return;
        }
        const api = new URL(receiptStatus.dataset.api || '../api/', document.baseURI);
        const url = new URL(`receipts/${id}`, api);
        const withdraw = byId('commentWithdraw');
        const confirm = byId('commentWithdrawConfirm');
        async function update(method) {
            confirm.disabled = true;
            try {
                const result = await json(url, {method, headers: {Authorization: `Bearer ${token}`}});
                receiptStatus.textContent = result.deleted ? '留言已删除。' : `当前状态：${result.status}`;
                withdraw.hidden = result.deleted;
            } catch (error) {
                receiptStatus.textContent = error.message;
            } finally {
                confirm.disabled = false;
            }
        }
        confirm.addEventListener('click', () => update('DELETE'));
        update('GET');
        return;
    }

    const toggle = byId('scoreCommentsToggle');
    if (!toggle) return;
    const panel = byId('scoreCommentsPanel');
    const detailBody = byId('scoreDetailBody');
    const list = byId('scoreCommentsList');
    const listStatus = byId('scoreCommentsListStatus');
    const form = byId('scoreCommentForm');
    const submit = form.querySelector('button[type="submit"]');
    const formStatus = byId('scoreCommentFormStatus');
    const challengeBox = byId('scoreCommentChallenge');
    const receipt = byId('scoreCommentReceipt');
    const receiptUrl = byId('scoreCommentReceiptUrl');
    const manage = byId('scoreCommentManage');
    const more = byId('scoreCommentsMore');
    const attempts = new Map();
    let pilotIds = new Set();
    let scoreId = null;
    let generation = 0;
    let nextPage = 1;
    let apiBase = new URL('api/', document.baseURI);
    let receiptPath = 'receipt/';
    let cloud = false;
    let turnstileScript;
    let widget;
    let challenge = '';

    function turnstile() {
        turnstileScript ||= new Promise((resolve, reject) => {
            const script = document.createElement('script');
            const callback = 'maotongScoreCommentTurnstileLoaded';
            const failed = () => {
                clearTimeout(timeout);
                delete window[callback];
                script.remove();
                reject(new Error());
            };
            const timeout = setTimeout(failed, 15000);
            window[callback] = () => {
                clearTimeout(timeout);
                delete window[callback];
                resolve(window.turnstile);
            };
            script.src = `https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=${callback}`;
            script.async = true;
            script.onerror = failed;
            document.head.append(script);
        }).catch(error => { turnstileScript = undefined; throw error; });
        return turnstileScript;
    }

    async function prepareChallenge(siteKey, current) {
        if (!siteKey) {
            formStatus.textContent = '留言暂时仅供阅读。';
            return;
        }
        challengeBox.hidden = false;
        try {
            const service = await turnstile();
            if (current !== generation) return;
            const update = value => {
                if (current !== generation) return;
                challenge = value;
                submit.disabled = !value || !!attempts.get(scoreId)?.busy;
            };
            widget = service.render(challengeBox, {
                sitekey: siteKey, action: 'score_comment', language: 'zh-cn',
                size: challengeBox.clientWidth < 300 ? 'compact' : 'flexible',
                'response-field': false, callback: update,
                'expired-callback': () => update(''), 'error-callback': () => {
                    if (current !== generation) return;
                    update('');
                    formStatus.textContent = '验证码暂时不可用，请关闭留言区后重试。';
                }
            });
        } catch {
            if (current === generation) formStatus.textContent = '验证码加载失败，请关闭留言区后重试。';
        }
    }

    function showPanel(open) {
        panel.hidden = !open;
        detailBody.hidden = open;
        toggle.setAttribute('aria-expanded', String(open));
        toggle.textContent = open ? '返回乐谱资料' : '版本留言';
        generation++;
        if (widget !== undefined) window.turnstile.remove(widget);
        widget = undefined;
        challenge = '';
        challengeBox.hidden = true;
    }

    function showAttempt(state) {
        submit.disabled = !!state?.busy || (cloud && !challenge);
        formStatus.textContent = state?.message || '';
        receipt.hidden = !state?.receipt;
        receiptUrl.value = state?.receipt || '';
        manage.href = state?.receipt || '';
    }

    function select(item) {
        scoreId = pilotIds.has(item?.public_id) ? item.public_id : null;
        showPanel(false);
        toggle.hidden = !scoreId;
        byId('scoreCommentsTitle').textContent = scoreId ? [item.title, item.tonality].filter(Boolean).join(' · ') : '';
        form.reset();
        showAttempt(attempts.get(scoreId));
    }

    function commentsUrl(id) {
        return new URL(`scores/${id}/comments`, apiBase);
    }

    async function loadComments() {
        const current = generation;
        const url = commentsUrl(scoreId);
        url.searchParams.set('page', nextPage);
        more.hidden = true;
        listStatus.textContent = '正在加载留言…';
        try {
            const result = await json(url);
            if (current !== generation) return;
            if (cloud && nextPage === 1) prepareChallenge(result.site_key, current);
            for (const comment of result.comments) {
                const entry = document.createElement('article');
                entry.className = 'border rounded-3 p-3';
                const title = document.createElement('h3');
                title.className = 'h6 score-comment-text';
                title.textContent = `${comment.kind} · ${comment.nickname}`;
                const body = document.createElement('p');
                body.className = 'score-comment-text mb-0';
                body.textContent = comment.body;
                entry.append(title, body);
                list.append(entry);
            }
            listStatus.textContent = list.children.length ? '' : '这份乐谱还没有公开留言。';
            nextPage++;
            more.textContent = '更多留言';
            more.hidden = !result.more;
        } catch (error) {
            if (current !== generation) return;
            listStatus.textContent = error.message;
            more.textContent = '重试加载';
            more.hidden = false;
        }
    }

    toggle.addEventListener('click', () => {
        if (!scoreId) return;
        const open = panel.hidden;
        showPanel(open);
        if (open) {
            showAttempt(attempts.get(scoreId));
            nextPage = 1;
            list.replaceChildren();
            panel.scrollTop = 0;
            byId('scoreCommentsHeading').focus();
            loadComments();
        }
    });
    more.addEventListener('click', loadComments);

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!scoreId || (cloud && !challenge)) return;
        const id = scoreId;
        const state = attempts.get(id) || {};
        if (state.busy) return;
        state.token ||= Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('');
        state.busy = true;
        state.message = '正在提交…';
        attempts.set(id, state);
        showAttempt(state);
        const payload = {...Object.fromEntries(new FormData(form)), token: state.token, challenge};
        const currentWidget = widget;
        try {
            const result = await json(commentsUrl(id), {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
            });
            const url = new URL(receiptPath, document.baseURI);
            url.hash = `${result.id}.${state.token}`;
            state.receipt = url.href;
            state.token = null;
            state.message = result.previous ? `已找回上次提交的管理链接。当前状态：${result.status}。这次填写的内容仍可另行提交。`
                : `留言已提交。当前状态：${result.status}。`;
            if (scoreId === id && !result.previous) form.reset();
        } catch (error) {
            state.message = error.message;
        } finally {
            state.busy = false;
            if (cloud && currentWidget !== undefined && widget === currentWidget) {
                challenge = '';
                window.turnstile.reset(widget);
            }
            if (scoreId === id) showAttempt(state);
        }
    });

    byId('scoreCommentCopy').addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(receiptUrl.value);
            formStatus.textContent = '私密链接已复制。';
        } catch {
            receiptUrl.focus();
            receiptUrl.select();
            formStatus.textContent = '请手动复制选中的私密链接。';
        }
    });

    window.ScoreComments = {
        configure(config, publishedIds) {
            cloud = !!config?.apiBase;
            pilotIds = new Set(cloud ? (location.origin === config.origin ? publishedIds || [] : []) : config?.pilotIds || []);
            apiBase = new URL(config?.apiBase || 'api/', document.baseURI);
            receiptPath = config?.receiptPath || 'receipt/';
            byId('scoreCommentsBadge').textContent = cloud ? '试点' : '本地试点';
        },
        select
    };
})();

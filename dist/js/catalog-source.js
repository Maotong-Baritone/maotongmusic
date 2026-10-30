/* Public data only: credentials and publishing remain in the local admin tool. */
(function (root) {
    'use strict';
    async function load(config) {
        const source = config && config.catalogSource;
        if (!source || !source.manifestUrl) return null;
        const manifestUrl = new URL(source.manifestUrl, document.baseURI);
        if (manifestUrl.protocol !== 'https:') throw new Error('云端目录必须使用 HTTPS');
        manifestUrl.searchParams.set('v', Date.now().toString());
        const response = await fetch(manifestUrl.href, {cache:'no-store'});
        if (!response.ok) throw new Error('暂时无法读取云端目录，请稍后刷新重试');
        const pointer = await response.json();
        if (pointer.schema_version !== 1 || !/^[a-f0-9]{64}$/.test(pointer.revision) ||
            pointer.key !== `website/releases/${pointer.revision}.json`) throw new Error('云端目录版本无效');
        const url = new URL(pointer.key, manifestUrl.origin + manifestUrl.pathname.replace(/website\/current\.json$/, ''));
        if (url.origin !== manifestUrl.origin) throw new Error('云端目录地址无效');
        let bytes;
        for (let attempt=0;attempt<2;attempt++) {
            const version = await fetch(url.href, {cache:attempt?'no-store':'force-cache'});
            if (!version.ok) throw new Error('暂时无法读取云端资料，请稍后刷新重试');
            bytes = await version.arrayBuffer();
            const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2,'0')).join('');
            if (hash === pointer.revision) break;
            if (attempt) throw new Error('云端资料完整性校验失败');
            url.searchParams.set('verify',Date.now().toString());
        }
        const data = JSON.parse(new TextDecoder().decode(bytes));
        if (data.schema_version !== 1 || !Array.isArray(data.scores) || !Array.isArray(data.logs) ||
            !data.literature || !Array.isArray(data.literature.documents) || !data.lyrics ||
            data.scores.length !== pointer.score_count || data.literature.documents.length !== pointer.document_count) {
            throw new Error('云端目录内容无效');
        }
        return data;
    }
    root.WebsiteCatalog = {load};
})(window);

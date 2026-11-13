(function () {
    const POLL_INTERVAL_MS = 3000;
    let containerEl = null;
    let isPolling = false;
    const inFlightDecisions = new Set();

    function formatCallbackOrigin(uri) {
        if (!uri) return '';
        try {
            const parsed = new URL(uri);
            return parsed.origin && parsed.origin !== 'null'
                ? parsed.origin
                : `${parsed.protocol}//${parsed.host}`;
        } catch (e) {
            return uri;
        }
    }

    function ensureContainer() {
        if (!containerEl) {
            containerEl = document.createElement('div');
            containerEl.id = 'oauth-popup-container';
            containerEl.className = 'oauth-popup-container';
            containerEl.setAttribute('role', 'region');
            containerEl.setAttribute('aria-label', 'OAuth Approval Notifications');
            containerEl.setAttribute('aria-live', 'polite');
            const indexContainer = document.querySelector('.container');
            const indexHeader = indexContainer ? indexContainer.querySelector('.header') : null;
            const oauthSection = document.getElementById('oauth-section');
            if (indexHeader && indexContainer) {
                indexHeader.insertAdjacentElement('afterend', containerEl);
            } else if (oauthSection && oauthSection.parentNode) {
                oauthSection.parentNode.insertBefore(containerEl, oauthSection);
            } else {
                document.body.appendChild(containerEl);
            }
        }
        return containerEl;
    }

    function formatRemaining(expiresAtSec) {
        const rem = Math.max(0, Math.ceil(expiresAtSec - Date.now() / 1000));
        const m = Math.floor(rem / 60);
        const s = rem % 60;
        return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    async function ensureCsrfToken() {
        if (window.csrfToken) return window.csrfToken;
        try {
            const res = await fetch('/api/auth/status', {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (res.ok) {
                const data = await res.json();
                if (data && data.csrf_token) {
                    window.csrfToken = data.csrf_token;
                }
            }
        } catch (e) {
            // Ignore
        }
        return window.csrfToken || '';
    }

    async function handleOAuthDecision(requestId, action, approveBtn, denyBtn) {
        if (!requestId || inFlightDecisions.has(requestId)) return;
        inFlightDecisions.add(requestId);

        if (approveBtn) approveBtn.disabled = true;
        if (denyBtn) denyBtn.disabled = true;
        if (action === 'approve' && approveBtn) {
            approveBtn.textContent = 'Approving...';
        } else if (denyBtn) {
            denyBtn.textContent = 'Disapproving...';
        }

        try {
            await ensureCsrfToken();
            const headers = {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            };
            if (window.csrfToken) {
                headers['X-CSRF-Token'] = window.csrfToken;
            }
            const res = await fetch(`/api/oauth/pending/${encodeURIComponent(requestId)}/${action}`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: headers
            });
            inFlightDecisions.delete(requestId);
            if (res.ok) {
                if (containerEl) {
                    const existingCard = containerEl.querySelector(`[data-request-id="${CSS.escape(requestId)}"]`);
                    if (existingCard) existingCard.remove();
                    if (containerEl.children.length === 0) {
                        containerEl.style.display = 'none';
                    }
                }
                await checkPendingOAuth();
                window.dispatchEvent(new CustomEvent('oauth-requests-updated'));
            } else {
                if (approveBtn) {
                    approveBtn.disabled = false;
                    approveBtn.textContent = '✔ Approve';
                }
                if (denyBtn) {
                    denyBtn.disabled = false;
                    denyBtn.textContent = '✘ Disapprove';
                }
            }
        } catch (err) {
            inFlightDecisions.delete(requestId);
            console.error('OAuth decision error:', err);
            if (approveBtn) {
                approveBtn.disabled = false;
                approveBtn.textContent = '✔ Approve';
            }
            if (denyBtn) {
                denyBtn.disabled = false;
                denyBtn.textContent = '✘ Disapprove';
            }
        }
    }

    function createPopupCard(req) {
        const reqId = req.id || req.req_id;
        const card = document.createElement('div');
        card.className = 'oauth-popup-card';
        card.dataset.requestId = reqId;

        const header = document.createElement('div');
        header.className = 'oauth-popup-header';

        const title = document.createElement('strong');
        title.textContent = '🔐 Incoming OAuth Connection';

        const timer = document.createElement('span');
        timer.className = 'oauth-popup-timer';
        timer.textContent = formatRemaining(req.expires_at);

        header.appendChild(title);
        header.appendChild(timer);

        const body = document.createElement('div');
        body.className = 'oauth-popup-body';

        const userRow = document.createElement('div');
        userRow.className = 'oauth-popup-row';
        const userLabel = document.createElement('span');
        userLabel.textContent = 'Username: ';
        const userVal = document.createElement('code');
        userVal.className = 'oauth-username-badge';
        userVal.textContent = req.username || 'unknown';
        userRow.appendChild(userLabel);
        userRow.appendChild(userVal);

        const clientRow = document.createElement('div');
        clientRow.className = 'oauth-popup-meta';
        const displayName = req.client_name || req.client_id || 'Unknown client';
        const idSuffix = req.client_id && req.client_name && req.client_name !== req.client_id ? ` | ID: ${req.client_id}` : '';
        const codeSuffix = req.user_code ? ` (${req.user_code})` : '';
        clientRow.textContent = `Client: ${displayName}${idSuffix}${codeSuffix}`;

        body.appendChild(userRow);
        body.appendChild(clientRow);

        const originText = formatCallbackOrigin(req.redirect_uri);
        if (originText) {
            const originRow = document.createElement('div');
            originRow.className = 'oauth-popup-meta';
            originRow.textContent = `Callback: ${originText}`;
            if (req.redirect_uri) {
                originRow.title = req.redirect_uri;
            }
            body.appendChild(originRow);
        }

        const scopeRow = document.createElement('div');
        scopeRow.className = 'oauth-popup-meta';
        scopeRow.textContent = `Scope: ${req.scope || 'mcp:access'}`;
        body.appendChild(scopeRow);

        const actions = document.createElement('div');
        actions.className = 'oauth-popup-actions';

        const approveBtn = document.createElement('button');
        approveBtn.type = 'button';
        approveBtn.className = 'oauth-btn-approve';
        approveBtn.textContent = '✔ Approve';

        const denyBtn = document.createElement('button');
        denyBtn.type = 'button';
        denyBtn.className = 'oauth-btn-deny';
        denyBtn.textContent = '✘ Disapprove';

        approveBtn.onclick = () => handleOAuthDecision(reqId, 'approve', approveBtn, denyBtn);
        denyBtn.onclick = () => handleOAuthDecision(reqId, 'deny', approveBtn, denyBtn);

        actions.appendChild(approveBtn);
        actions.appendChild(denyBtn);

        card.appendChild(header);
        card.appendChild(body);
        card.appendChild(actions);
        return card;
    }

    function renderPopupCards(pendingList) {
        const container = ensureContainer();

        if (!Array.isArray(pendingList) || pendingList.length === 0) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';

        const activeIds = new Set(pendingList.map(r => r.id || r.req_id));

        Array.from(container.children).forEach(child => {
            const cid = child.dataset ? child.dataset.requestId : null;
            if (!cid || !activeIds.has(cid)) {
                child.remove();
            }
        });

        pendingList.forEach(req => {
            const reqId = req.id || req.req_id;
            let card = Array.from(container.children).find(
                c => c.dataset && c.dataset.requestId === reqId
            );
            if (card) {
                const timerEl = card.querySelector('.oauth-popup-timer');
                if (timerEl) {
                    timerEl.textContent = formatRemaining(req.expires_at);
                }
            } else {
                card = createPopupCard(req);
                container.appendChild(card);
            }
        });
    }

    async function checkPendingOAuth() {
        if (isPolling) return;
        isPolling = true;
        try {
            const res = await fetch('/api/oauth/pending', {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!res.ok) {
                if (containerEl) containerEl.style.display = 'none';
                return;
            }
            const data = await res.json();
            const pending = data.pending || [];
            renderPopupCards(pending);
            window.dispatchEvent(new CustomEvent('oauth-pending-data', { detail: data }));
        } catch (e) {
            // Ignore transient offline errors
        } finally {
            isPolling = false;
        }
    }

    window.checkPendingOAuth = checkPendingOAuth;
    window.handleOAuthDecision = handleOAuthDecision;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', checkPendingOAuth);
    } else {
        checkPendingOAuth();
    }
    setInterval(checkPendingOAuth, POLL_INTERVAL_MS);
    window.addEventListener('focus', checkPendingOAuth);
})();

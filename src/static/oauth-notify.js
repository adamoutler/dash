(function () {
    const POLL_INTERVAL_MS = 3000;
    let containerEl = null;

    function ensureContainer() {
        if (!containerEl) {
            containerEl = document.createElement('div');
            containerEl.id = 'oauth-popup-container';
            containerEl.className = 'oauth-popup-container';
            containerEl.setAttribute('role', 'region');
            containerEl.setAttribute('aria-label', 'OAuth Approval Notifications');
            containerEl.setAttribute('aria-live', 'polite');
            document.body.appendChild(containerEl);
        }
        return containerEl;
    }

    function formatRemaining(expiresAtSec) {
        const rem = Math.max(0, Math.ceil(expiresAtSec - Date.now() / 1000));
        const m = Math.floor(rem / 60);
        const s = rem % 60;
        return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    async function handleOAuthDecision(requestId, action, approveBtn, denyBtn) {
        if (approveBtn) approveBtn.disabled = true;
        if (denyBtn) denyBtn.disabled = true;
        if (action === 'approve' && approveBtn) {
            approveBtn.textContent = 'Approving...';
        } else if (denyBtn) {
            denyBtn.textContent = 'Disapproving...';
        }

        try {
            const res = await fetch(`/api/oauth/pending/${encodeURIComponent(requestId)}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (res.ok) {
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

    function renderPopupCards(pendingList) {
        const container = ensureContainer();
        container.innerHTML = '';

        if (!Array.isArray(pendingList) || pendingList.length === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';

        pendingList.forEach(req => {
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
            const codeSuffix = req.user_code ? ` (${req.user_code})` : '';
            clientRow.textContent = `Client: ${req.client_name || req.client_id}${codeSuffix}`;

            body.appendChild(userRow);
            body.appendChild(clientRow);

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
            container.appendChild(card);
        });
    }

    async function checkPendingOAuth() {
        try {
            const res = await fetch('/api/oauth/pending', { cache: 'no-store', credentials: 'same-origin' });
            if (!res.ok) return;
            const data = await res.json();
            const pending = data.pending || [];
            renderPopupCards(pending);
            window.dispatchEvent(new CustomEvent('oauth-pending-data', { detail: data }));
        } catch (e) {
            // Ignore transient offline errors
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

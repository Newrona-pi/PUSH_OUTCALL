const API_BASE = "/admin";
let currentScenario = null;
let currentQuestions = [];
let currentEndingGuidances = [];

// Helper: Format date to Japan Standard Time (JST)
function formatJST(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
}

// Helper: Format phone number to Japanese domestic format
function formatJapanesePhone(phoneNumber) {
    if (!phoneNumber) return '-';
    // Convert +81 to 0 for Japanese domestic display
    if (phoneNumber.startsWith('+81')) {
        return '0' + phoneNumber.substring(3);
    }
    return phoneNumber;
}

// --- Tab Switching ---
function openTab(tabId) {
    const el = document.getElementById(tabId);
    if (!el) return;
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
}

// --- Scenarios ---
async function loadScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const data = await res.json();
    const tbody = document.getElementById('scenario-list-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    data.forEach(s => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHtml(s.name)}</td>
            <td><span class="badge completed">${s.conversation_mode === 'A' ? '安定型' : '応用型'}</span></td>
            <td>${formatJST(s.created_at)}</td>
            <td>
                <button class="secondary small" onclick="editScenario(${s.id})">
                    <i class="fas fa-edit"></i> 設計
                </button>
                <button class="primary small" onclick="goToCallList(${s.id})">
                    <i class="fas fa-phone"></i> 架電リスト
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function editScenario(id) {
    window.location.href = `/admin/scenarios/design?id=${id}`;
}

function goToCallList(id) {
    window.location.href = `/admin/outbound?scenario_id=${id}`;
}

async function selectScenario(scenarioId) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
        if (!res.ok) throw new Error("Scenario not found");
        const scenario = await res.json();
        currentScenario = scenario;

        document.getElementById('editor-title').textContent = "シナリオ編集: " + scenario.name;
        document.getElementById('scenario-id').value = scenario.id;
        document.getElementById('scenario-name').value = scenario.name;
        document.getElementById('scenario-mode').value = scenario.conversation_mode || 'A';
        document.getElementById('scenario-start-time').value = scenario.start_time || '10:00';
        document.getElementById('scenario-end-time').value = scenario.end_time || '18:00';
        document.getElementById('scenario-timeout-short').value = scenario.silence_timeout_short || 15;
        document.getElementById('scenario-timeout-long').value = scenario.silence_timeout_long || 60;
        document.getElementById('scenario-greeting').value = scenario.greeting_text || '';
        document.getElementById('scenario-disclaimer').value = scenario.disclaimer_text || '';

        const guidance = document.getElementById('scenario-guidance');
        if (guidance) guidance.value = scenario.question_guidance_text || '';

        document.getElementById('scenario-bridge').value = scenario.bridge_number || '';
        document.getElementById('scenario-sms').value = scenario.sms_template || '';

        await loadQuestions(scenario.id);
        await loadEndingGuidances(scenario.id);
    } catch (e) {
        console.error(e);
        alert("読み込みに失敗しました");
    }
}

async function copyCurrentScenario() {
    if (!currentScenario) return;
    const name = prompt("コピー後の名称を入力してください", currentScenario.name + "_copy");
    if (!name) return;
    const payload = { ...currentScenario, name };
    delete payload.id;
    const res = await fetch(`${API_BASE}/scenarios/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const saved = await res.json();
    window.location.href = `/admin/scenarios/design?id=${saved.id}`;
}

async function deleteCurrentScenario() {
    if (!currentScenario) return;
    if (!confirm("このシナリオを削除しますか？")) return;
    await fetch(`${API_BASE}/scenarios/${currentScenario.id}`, { method: 'DELETE' });
    window.location.href = "/admin/scenarios";
}

function showCreateScenarioForm() {
    currentScenario = null;
    currentQuestions = [];
    currentEndingGuidances = [];

    document.getElementById('editor-title').textContent = "新規シナリオ作成";
    document.getElementById('scenario-id').value = '';
    const form = document.getElementById('scenario-form');
    if (form) form.reset();
    const qContainer = document.getElementById('questions-container');
    if (qContainer) qContainer.innerHTML = '';
    const eContainer = document.getElementById('ending-container');
    if (eContainer) eContainer.innerHTML = '';
}

async function loadQuestions(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    if (!res.ok) return;
    currentQuestions = await res.json();
    renderQuestions();
}

async function loadEndingGuidances(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/ending_guidances`);
    if (!res.ok) return;
    currentEndingGuidances = await res.json();
    renderEndingGuidances();
}

function renderQuestions() {
    const container = document.getElementById('questions-container');
    if (!container) return;
    container.innerHTML = '';
    currentQuestions.forEach((q, i) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.innerHTML = `
            <div class="q-order">${i + 1}</div>
            <div style="flex: 1;">
                <textarea class="question-text-input" data-index="${i}" style="min-height: 40px;">${escapeHtml(q.text)}</textarea>
                <div style="display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.5rem;">
                    <button type="button" class="secondary small" onclick="removeQuestion(${i})">削除</button>
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

function renderEndingGuidances() {
    const container = document.getElementById('ending-container');
    if (!container) return;
    container.innerHTML = '';
    currentEndingGuidances.forEach((g, i) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.style.borderLeft = "4px solid var(--accent)";
        div.innerHTML = `
            <div class="q-order" style="background: var(--accent);">${i + 1}</div>
            <div style="flex: 1;">
                <input type="text" class="ending-text-input" data-index="${i}" value="${escapeHtml(g.text)}" style="margin-bottom: 0.5rem;">
                <div style="display: flex; justify-content: flex-end;">
                    <button type="button" class="danger small" onclick="removeEnding(${i})" style="padding: 0.3rem 0.8rem; font-size: 0.75rem;">
                        削除
                    </button>
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

function addQuestionToList() {
    const textarea = document.getElementById('new-question-text');
    const text = textarea ? textarea.value.trim() : "";
    if (!text) return;
    currentQuestions.push({ text, sort_order: currentQuestions.length + 1, is_new: true });
    renderQuestions();
    if (textarea) textarea.value = '';
}

function addEndingGuidance() {
    currentEndingGuidances.push({ text: 'ありがとうございました。', sort_order: currentEndingGuidances.length + 1, is_new: true });
    renderEndingGuidances();
}

async function removeQuestion(i) {
    const q = currentQuestions[i];
    if (q.id) await fetch(`${API_BASE}/questions/${q.id}`, { method: 'DELETE' });
    currentQuestions.splice(i, 1);
    renderQuestions();
}

async function removeEnding(i) {
    const g = currentEndingGuidances[i];
    if (g.id) await fetch(`${API_BASE}/ending_guidances/${g.id}`, { method: 'DELETE' });
    currentEndingGuidances.splice(i, 1);
    renderEndingGuidances();
}

const scenarioForm = document.getElementById('scenario-form');
if (scenarioForm) {
    scenarioForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            const id = document.getElementById('scenario-id').value;
            const payload = {
                name: document.getElementById('scenario-name').value,
                greeting_text: document.getElementById('scenario-greeting').value,
                disclaimer_text: document.getElementById('scenario-disclaimer').value,
                conversation_mode: document.getElementById('scenario-mode').value,
                start_time: document.getElementById('scenario-start-time').value,
                end_time: document.getElementById('scenario-end-time').value,
                silence_timeout_short: parseInt(document.getElementById('scenario-timeout-short').value) || 15,
                silence_timeout_long: parseInt(document.getElementById('scenario-timeout-long').value) || 60,
                bridge_number: document.getElementById('scenario-bridge').value,
                sms_template: document.getElementById('scenario-sms').value,
                is_active: true
            };

            const guidanceEl = document.getElementById('scenario-guidance');
            if (guidanceEl) payload.question_guidance_text = guidanceEl.value;

            // 1. Save Scenario
            const scenarioUrl = id ? `${API_BASE}/scenarios/${id}` : `${API_BASE}/scenarios/`;
            const scenarioRes = await fetch(scenarioUrl, {
                method: id ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!scenarioRes.ok) throw new Error("シナリオの保存に失敗しました");
            const savedScenario = await scenarioRes.json();

            // 2. Save Questions based on DOM state
            const questionTextareas = document.querySelectorAll('.question-text-input');
            for (let i = 0; i < questionTextareas.length; i++) {
                const textarea = questionTextareas[i];
                const idx = parseInt(textarea.dataset.index);
                const q = currentQuestions[idx];
                if (!q) continue;

                const qPayload = {
                    text: textarea.value,
                    sort_order: i + 1,
                    scenario_id: savedScenario.id,
                    is_active: true
                };

                const qUrl = q.id ? `${API_BASE}/questions/${q.id}` : `${API_BASE}/questions/`;
                const qRes = await fetch(qUrl, {
                    method: q.id ? 'PUT' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(qPayload)
                });
                if (!qRes.ok) console.error("Question save failed", qPayload);
            }

            // 3. Save Ending Guidances based on DOM state
            const endingInputs = document.querySelectorAll('.ending-text-input');
            for (let i = 0; i < endingInputs.length; i++) {
                const input = endingInputs[i];
                const idx = parseInt(input.dataset.index);
                const g = currentEndingGuidances[idx];
                if (!g) continue;

                const gPayload = {
                    text: input.value,
                    sort_order: i + 1,
                    scenario_id: savedScenario.id
                };

                const gUrl = g.id ? `${API_BASE}/ending_guidances/${g.id}` : `${API_BASE}/ending_guidances/`;
                const gRes = await fetch(gUrl, {
                    method: g.id ? 'PUT' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(gPayload)
                });
                if (!gRes.ok) console.error("Ending guidance save failed", gPayload);
            }

            alert('保存しました');
            window.location.href = "/admin/scenarios";
        } catch (error) {
            console.error(error);
            alert("エラーが発生しました: " + error.message);
        }
    };
}

// --- Outbound ---
async function loadOutboundScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const scenarios = await res.json();
    const select = document.getElementById('outbound-scenario-select');
    if (!select) return;
    select.innerHTML = '<option value="">未選択</option>';
    scenarios.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = s.name;
        select.appendChild(opt);
    });

    const params = new URLSearchParams(window.location.search);
    const sid = params.get('scenario_id');
    if (sid) {
        select.value = sid;
        loadTargets(sid);
    }
    select.onchange = (e) => loadTargets(e.target.value);
}

async function handleFileUpload(input) {
    const scenarioId = document.getElementById('outbound-scenario-select').value;
    if (!scenarioId) { alert('シナリオを選択してください'); return; }

    const formData = new FormData();
    formData.append('file', input.files[0]);

    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/upload_targets`, {
        method: 'POST',
        body: formData
    });
    const result = await res.json();
    alert(result.message);
    loadTargets(scenarioId);
}

async function addTargetManually() {
    const scenarioId = document.getElementById('outbound-scenario-select').value;
    const phoneInput = document.getElementById('manual-phone');
    const phone = phoneInput.value.trim();

    if (!scenarioId) { alert('シナリオを選択してください'); return; }
    if (!phone) { alert('電話番号を入力してください'); return; }

    const res = await fetch(`${API_BASE}/targets/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: parseInt(scenarioId), phone_number: phone })
    });

    if (res.ok) {
        phoneInput.value = '';
        loadTargets(scenarioId);
    } else {
        const err = await res.json();
        alert("追加に失敗しました: " + (err.detail || "不明なエラー"));
    }
}

async function loadTargets(scenarioId) {
    if (!scenarioId) return;
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/targets`);
    const data = await res.json();
    const tbody = document.querySelector('#targets-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    data.forEach(t => {
        tbody.innerHTML += `
            <tr>
                <td>${formatJapanesePhone(t.phone_number)}</td>
                <td><span class="badge ${t.status}">${t.status}</span></td>
                <td>${formatJST(t.created_at)}</td>
                <td>
                    <button class="secondary small" onclick="deleteTarget(${t.id}, ${scenarioId})">削除</button>
                </td>
            </tr>
        `;
    });
}

async function deleteTarget(id, scenarioId) {
    if (!confirm('このターゲットを削除しますか？')) return;
    await fetch(`${API_BASE}/targets/${id}`, { method: 'DELETE' });
    loadTargets(scenarioId);
}

async function startCalls() {
    const scenarioId = document.getElementById('outbound-scenario-select').value;
    if (!scenarioId) { alert('シナリオを選択してください'); return; }

    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/start_calls`, { method: 'POST' });
    const result = await res.json();
    alert(result.message || result.detail);
    loadTargets(scenarioId);
}

async function stopAllCalls() {
    const scenarioId = document.getElementById('outbound-scenario-select').value;
    if (!scenarioId) { alert('シナリオを選択してください'); return; }
    if (!confirm('実行中の履歴を含め、このシナリオの未完了の架電をすべて停止しますか？')) return;

    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/stop_all`, { method: 'POST' });
    const result = await res.json();
    alert(result.message);
    loadTargets(scenarioId);
}

// --- Logs ---
async function loadLogs() {
    const toNumber = document.getElementById('filter-to')?.value || '';
    const startDate = document.getElementById('filter-start-date')?.value || '';
    const endDate = document.getElementById('filter-end-date')?.value || '';

    let url = `${API_BASE}/calls/?limit=100`;
    if (toNumber) url += `&to_number=${encodeURIComponent(toNumber)}`;
    if (currentScenarioFilter) url += `&scenario_id=${currentScenarioFilter}`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    data.forEach(call => {
        // Build answer data display
        let answerDataHtml = '';
        if (call.answers && call.answers.length > 0) {
            answerDataHtml = '<div style="max-width: 500px;">';
            call.answers.forEach((answer, idx) => {
                const questionText = answer.question_text || `質問${idx + 1}`;
                const transcript = answer.transcript_text || '(文字起こしなし)';
                const audioLink = answer.recording_sid
                    ? `<audio controls src="${API_BASE}/audio_proxy/${answer.recording_sid}" style="width: 100%; margin-top: 3px;"></audio>`
                    : '';

                answerDataHtml += `
                    <div style="margin-bottom: 10px; padding: 5px; background: #f9f9f9; border-left: 3px solid var(--primary);">
                        <strong>Q${idx + 1}:</strong> ${escapeHtml(questionText)}<br>
                        <strong>A:</strong> ${escapeHtml(transcript)}
                        ${audioLink}
                    </div>
                `;
            });
            answerDataHtml += '</div>';
        } else {
            answerDataHtml = '<span style="color: #999;">回答データなし</span>';
        }

        // Full call recording
        const fullRecording = call.recording_sid
            ? `<div style="margin-bottom: 10px;"><strong>全録音:</strong><br><audio controls src="${API_BASE}/audio_proxy/${call.recording_sid}" style="width: 100%;"></audio></div>`
            : '';

        tbody.innerHTML += `
            <tr>
                <td>${formatJST(call.started_at)}</td>
                <td>${formatJapanesePhone(call.from_number)}</td>
                <td>${formatJapanesePhone(call.to_number)}</td>
                <td>${escapeHtml(call.scenario_name || '-')}</td>
                <td><span class="badge ${call.status}">${call.status}</span></td>
                <td>
                    ${fullRecording}
                    ${answerDataHtml}
                </td>
            </tr>
        `;
    });
}

async function exportZIP() {
    window.location.href = `${API_BASE}/export_zip`;
}

// --- Helpers ---
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

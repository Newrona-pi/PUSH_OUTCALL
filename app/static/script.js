const API_BASE = "/admin";
let currentScenario = null;
let currentQuestions = [];
let currentEndingGuidances = [];
let draggedElement = null;

// --- Tab Switching ---
function openTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');

    // Find the button and add active class
    const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
    if (btn) btn.classList.add('active');

    if (tabId === 'tab-scenarios') loadScenarios();
    if (tabId === 'tab-outbound') loadOutboundScenarios();
    if (tabId === 'tab-logs') loadLogs();
}

// --- Scenarios ---
async function loadScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const data = await res.json();
    const list = document.getElementById('scenario-list');
    list.innerHTML = '';

    data.forEach(s => {
        const li = document.createElement('li');
        li.dataset.scenarioId = s.id;
        li.innerHTML = `
            <span onclick="selectScenario(${s.id})"><i class="fas fa-file-alt"></i> ${escapeHtml(s.name)}</span>
        `;
        if (currentScenario && currentScenario.id === s.id) li.classList.add('active');
        list.appendChild(li);
    });
}

async function selectScenario(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
    const scenario = await res.json();
    currentScenario = scenario;

    document.querySelectorAll('#scenario-list li').forEach(l => {
        l.classList.remove('active');
        if (parseInt(l.dataset.scenarioId) === scenarioId) l.classList.add('active');
    });

    document.getElementById('welcome-message').classList.add('hidden');
    document.getElementById('scenario-editor').classList.remove('hidden');

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
    document.getElementById('scenario-guidance').value = scenario.question_guidance_text || '';
    document.getElementById('scenario-bridge').value = scenario.bridge_number || '';
    document.getElementById('scenario-sms').value = scenario.sms_template || '';

    loadQuestions(scenario.id);
    loadEndingGuidances(scenario.id);
}

function showCreateScenarioForm() {
    currentScenario = null;
    currentQuestions = [];
    currentEndingGuidances = [];
    document.getElementById('welcome-message').classList.add('hidden');
    document.getElementById('scenario-editor').classList.remove('hidden');
    document.getElementById('scenario-id').value = '';
    document.getElementById('scenario-form').reset();
    document.getElementById('questions-container').innerHTML = '';
    document.getElementById('ending-container').innerHTML = '';
}

async function loadQuestions(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    currentQuestions = await res.json();
    renderQuestions();
}

async function loadEndingGuidances(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/ending_guidances`);
    currentEndingGuidances = await res.json();
    renderEndingGuidances();
}

// --- Rendering ---
function renderQuestions() {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';
    currentQuestions.forEach((q, i) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.innerHTML = `
            <div class="q-order">${i + 1}</div>
            <div style="flex: 1;">
                <input type="text" value="${escapeHtml(q.text)}" onchange="updateQuestion(${i}, this.value)" style="margin-bottom: 0.5rem;">
                <div style="display: flex; justify-content: flex-end;">
                    <button type="button" class="danger small" onclick="removeQuestion(${i})" style="padding: 0.3rem 0.8rem; font-size: 0.75rem;">
                        <i class="fas fa-trash-alt"></i> 削除
                    </button>
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

function renderEndingGuidances() {
    const container = document.getElementById('ending-container');
    container.innerHTML = '';
    currentEndingGuidances.forEach((g, i) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.style.borderLeft = "4px solid var(--accent)";
        div.innerHTML = `
            <div class="q-order" style="background: var(--accent);">${i + 1}</div>
            <div style="flex: 1;">
                <input type="text" value="${escapeHtml(g.text)}" onchange="updateEnding(${i}, this.value)" style="margin-bottom: 0.5rem;">
                <div style="display: flex; justify-content: flex-end;">
                    <button type="button" class="danger small" onclick="removeEnding(${i})" style="padding: 0.3rem 0.8rem; font-size: 0.75rem;">
                        <i class="fas fa-trash-alt"></i> 削除
                    </button>
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

function updateQuestion(i, val) { currentQuestions[i].text = val; }
function updateEnding(i, val) { currentEndingGuidances[i].text = val; }

function addQuestionToList() {
    const text = document.getElementById('new-question-text').value;
    if (!text) return;
    currentQuestions.push({ text, sort_order: currentQuestions.length + 1, is_new: true });
    renderQuestions();
    document.getElementById('new-question-text').value = '';
}

function addEndingGuidance() {
    currentEndingGuidances.push({ text: 'ありがとうございました。', sort_order: currentEndingGuidances.length + 1, is_new: true });
    renderEndingGuidances();
}

async function removeQuestion(i) {
    const q = currentQuestions[i];
    if (q.id && !q.is_new) await fetch(`${API_BASE}/questions/${q.id}`, { method: 'DELETE' });
    currentQuestions.splice(i, 1);
    renderQuestions();
}

async function removeEnding(i) {
    const g = currentEndingGuidances[i];
    if (g.id && !g.is_new) await fetch(`${API_BASE}/ending_guidances/${g.id}`, { method: 'DELETE' });
    currentEndingGuidances.splice(i, 1);
    renderEndingGuidances();
}

document.getElementById('scenario-form').onsubmit = async (e) => {
    e.preventDefault();
    const id = document.getElementById('scenario-id').value;
    const payload = {
        name: document.getElementById('scenario-name').value,
        greeting_text: document.getElementById('scenario-greeting').value,
        disclaimer_text: document.getElementById('scenario-disclaimer').value,
        question_guidance_text: document.getElementById('scenario-guidance').value,
        conversation_mode: document.getElementById('scenario-mode').value,
        start_time: document.getElementById('scenario-start-time').value,
        end_time: document.getElementById('scenario-end-time').value,
        silence_timeout_short: parseInt(document.getElementById('scenario-timeout-short').value),
        silence_timeout_long: parseInt(document.getElementById('scenario-timeout-long').value),
        bridge_number: document.getElementById('scenario-bridge').value,
        sms_template: document.getElementById('scenario-sms').value,
        is_active: true
    };

    let url = `${API_BASE}/scenarios/`;
    let res = await fetch(id ? url + id : url, {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const saved = await res.json();

    // Save questions
    for (let i = 0; i < currentQuestions.length; i++) {
        const q = currentQuestions[i];
        const qPayload = { text: q.text, sort_order: i + 1, scenario_id: saved.id, is_active: true };
        await fetch(q.id ? `${API_BASE}/questions/${q.id}` : `${API_BASE}/questions/`, {
            method: q.id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(qPayload)
        });
    }

    // Save endings
    for (let i = 0; i < currentEndingGuidances.length; i++) {
        const g = currentEndingGuidances[i];
        const gPayload = { text: g.text, sort_order: i + 1, scenario_id: saved.id };
        await fetch(g.id ? `${API_BASE}/ending_guidances/${g.id}` : `${API_BASE}/ending_guidances/`, {
            method: g.id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(gPayload)
        });
    }

    alert('保存しました');
    loadScenarios();
    selectScenario(saved.id);
};

// --- Outbound ---
async function loadOutboundScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const data = await res.json();
    const select = document.getElementById('outbound-scenario-select');
    select.innerHTML = '<option value="">シナリオを選択</option>';
    data.forEach(s => {
        select.innerHTML += `<option value="${s.id}">${escapeHtml(s.name)}</option>`;
    });
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

async function loadTargets(scenarioId) {
    if (!scenarioId) return;
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/targets`);
    const data = await res.json();
    const tbody = document.querySelector('#targets-table tbody');
    tbody.innerHTML = '';
    data.forEach(t => {
        tbody.innerHTML += `
            <tr>
                <td>${escapeHtml(t.phone_number)}</td>
                <td><span class="badge ${t.status}">${t.status}</span></td>
                <td>${new Date(t.created_at).toLocaleString()}</td>
                <td>${escapeHtml(t.metadata_json || '-')}</td>
            </tr>
        `;
    });
}

async function startCalls() {
    const scenarioId = document.getElementById('outbound-scenario-select').value;
    if (!scenarioId) { alert('シナリオを選択してください'); return; }

    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/start_calls`, { method: 'POST' });
    const result = await res.json();
    alert(result.message || result.detail);
    loadTargets(scenarioId);
}

async function stopScenario(mode) {
    if (!currentScenario) return;
    const res = await fetch(`${API_BASE}/scenarios/${currentScenario.id}/stop?mode=${mode}`, { method: 'POST' });
    const result = await res.json();
    alert(result.message);
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
    const phone = document.getElementById('filter-phone').value;
    let url = `${API_BASE}/calls/?limit=50`;
    if (phone) url += `&to_number=${encodeURIComponent(phone)}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    tbody.innerHTML = '';

    data.forEach(call => {
        const transcript = call.transcript_full || call.answers.map(a => a.transcript_text).join(' ');
        const recording = call.recording_sid ? `<audio controls src="${API_BASE}/audio_proxy/${call.recording_sid}"></audio>` : '-';

        tbody.innerHTML += `
            <tr>
                <td>${new Date(call.started_at).toLocaleString()}</td>
                <td>${call.direction}</td>
                <td>${escapeHtml(call.to_number)}</td>
                <td>${call.status}</td>
                <td>${call.classification || '-'}</td>
                <td>
                    ${recording}
                    <div class="transcript-box">${escapeHtml(transcript)}</div>
                </td>
            </tr>
        `;
    });
}


// --- Helpers ---
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initial load
loadScenarios();

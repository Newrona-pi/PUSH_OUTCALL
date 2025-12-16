const API_BASE = "/admin";
let currentScenario = null;
let currentQuestions = [];

// --- Notification System ---
function showNotification(title, items) {
    // items can be a string or an array of strings
    let itemsHtml = '';
    if (Array.isArray(items)) {
        itemsHtml = items.map(item => `<div style="margin: 5px 0;"><i class="fas fa-check" style="color:#27ae60; margin-right:8px;"></i>${item}</div>`).join('');
    } else {
        itemsHtml = `<p>${items}</p>`;
    }

    const overlay = document.createElement('div');
    overlay.className = 'notification-overlay';
    overlay.innerHTML = `
        <div class="notification-modal">
            <div class="icon"><i class="fas fa-check-circle"></i></div>
            <h3>${title}</h3>
            <div style="text-align: left; margin-top: 15px; color: #555;">${itemsHtml}</div>
        </div>
    `;
    document.body.appendChild(overlay);

    setTimeout(() => {
        overlay.style.opacity = '0';
        setTimeout(() => overlay.remove(), 200);
    }, 2500); // Longer display for multiple items
}

// --- Tab Switching ---
function openTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');

    if (tabId === 'tab-scenarios') loadScenarios();
    if (tabId === 'tab-numbers') loadPhoneNumbers();
    if (tabId === 'tab-logs') loadLogs();
}

// --- Scenarios (Left Pane) ---
async function loadScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const data = await res.json();
    const list = document.getElementById('scenario-list');
    list.innerHTML = '';

    data.forEach(s => {
        const li = document.createElement('li');
        li.dataset.scenarioId = s.id;
        li.innerHTML = `
            <span onclick="selectScenario(${s.id})"><i class="fas fa-file-alt" style="margin-right:8px; color:#bbb;"></i>${escapeHtml(s.name)}</span>
            <button class="list-copy-btn" onclick="event.stopPropagation(); copyScenario(${s.id})">コピー</button>
        `;
        if (currentScenario && currentScenario.id === s.id) {
            li.classList.add('active');
        }
        list.appendChild(li);
    });
}

async function selectScenario(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
    const scenario = await res.json();
    currentScenario = scenario;

    document.querySelectorAll('#scenario-list li').forEach(l => {
        l.classList.remove('active');
        if (parseInt(l.dataset.scenarioId) === scenarioId) {
            l.classList.add('active');
        }
    });

    document.getElementById('welcome-message').classList.add('hidden');
    document.getElementById('scenario-editor').classList.remove('hidden');

    document.getElementById('editor-title').textContent = "シナリオ編集: " + scenario.name;
    document.getElementById('scenario-id').value = scenario.id;
    document.getElementById('scenario-name').value = scenario.name;
    document.getElementById('scenario-greeting').value = scenario.greeting_text || '';
    document.getElementById('scenario-disclaimer').value = scenario.disclaimer_text || '';

    await loadQuestions(scenario.id);
    populateOrderSelect();
}

function showCreateScenarioForm() {
    currentScenario = null;
    currentQuestions = [];
    document.querySelectorAll('#scenario-list li').forEach(l => l.classList.remove('active'));
    document.getElementById('welcome-message').classList.add('hidden');
    document.getElementById('scenario-editor').classList.remove('hidden');

    document.getElementById('editor-title').textContent = "新規シナリオ作成";
    document.getElementById('scenario-id').value = "";
    document.getElementById('scenario-form').reset();
    document.getElementById('questions-container').innerHTML = '';
    populateOrderSelect();
}

// --- Scenario Actions ---
async function saveScenario() {
    const id = document.getElementById('scenario-id').value;
    const name = document.getElementById('scenario-name').value;
    const greeting = document.getElementById('scenario-greeting').value;
    const disclaimer = document.getElementById('scenario-disclaimer').value;

    if (!name) {
        alert('シナリオ名を入力してください');
        return null;
    }

    const payload = { name, greeting_text: greeting, disclaimer_text: disclaimer };

    let url = `${API_BASE}/scenarios/`;
    let method = 'POST';
    let isNew = !id;

    if (id) {
        url += `${id}`;
        method = 'PUT';
    }

    const res = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        const saved = await res.json();
        if (!id) {
            currentScenario = saved;
            document.getElementById('scenario-id').value = saved.id;
            document.getElementById('editor-title').textContent = "シナリオ編集: " + saved.name;
        } else {
            currentScenario = saved;
        }
        return { scenario: saved, isNew: isNew };
    }
    return null;
}

document.getElementById('scenario-form').onsubmit = async (e) => {
    e.preventDefault();
    const result = await saveScenario();
    if (result) {
        loadScenarios();
        const items = [`シナリオ「${result.scenario.name}」を${result.isNew ? '作成' : '更新'}`];
        showNotification('保存完了', items);
    }
};

async function copyCurrentScenario() {
    if (!currentScenario) return;
    await copyScenario(currentScenario.id);
}

async function copyScenario(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
    const scenario = await res.json();
    const name = scenario.name + " (コピー)";

    let createRes = await fetch(`${API_BASE}/scenarios/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            greeting_text: scenario.greeting_text,
            disclaimer_text: scenario.disclaimer_text
        })
    });
    const newScenario = await createRes.json();

    const qRes = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    const questions = await qRes.json();

    for (const q of questions) {
        await fetch(`${API_BASE}/questions/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: q.text,
                sort_order: q.sort_order,
                scenario_id: newScenario.id
            })
        });
    }

    await selectScenario(newScenario.id);
    loadScenarios();
    showNotification('コピー完了', `シナリオ「${newScenario.name}」を作成しました`);
}

async function deleteCurrentScenario() {
    if (!confirm("本当に削除しますか？")) return;
    const deletedName = currentScenario.name;
    await fetch(`${API_BASE}/scenarios/${currentScenario.id}`, { method: 'DELETE' });
    loadScenarios();
    showCreateScenarioForm();
    showNotification('削除完了', `シナリオ「${deletedName}」を削除しました`);
}

// --- Questions ---
async function loadQuestions(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    currentQuestions = await res.json();
    renderQuestions();
}

function renderQuestions() {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';

    currentQuestions.forEach(q => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.innerHTML = `
            <div>
                <span class="q-order">#${q.sort_order}</span>
                <span class="q-text">${escapeHtml(q.text)}</span>
            </div>
            <div class="q-actions">
                <button class="small secondary" onclick="editQuestion(${q.id}, \`${escapeHtml(q.text)}\`, ${q.sort_order})">編集</button>
                <button class="small danger" onclick="deleteQuestion(${q.id})">削除</button>
            </div>
        `;
        container.appendChild(div);
    });

    populateOrderSelect();
}

function populateOrderSelect() {
    const select = document.getElementById('question-order');
    const usedOrders = currentQuestions.map(q => q.sort_order);

    select.innerHTML = '';
    for (let i = 1; i <= 50; i++) {
        if (!usedOrders.includes(i)) {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = i;
            select.appendChild(opt);
        }
    }

    const currentEditId = document.getElementById('question-id').value;
    if (currentEditId) {
        const editingQ = currentQuestions.find(q => q.id == currentEditId);
        if (editingQ) {
            const currentOrder = editingQ.sort_order;
            if (!Array.from(select.options).find(o => o.value == currentOrder)) {
                const opt = document.createElement('option');
                opt.value = currentOrder;
                opt.textContent = currentOrder;
                select.appendChild(opt);
            }
            select.value = currentOrder;
        }
    }
}

function editQuestion(id, text, order) {
    document.getElementById('question-id').value = id;
    document.getElementById('question-text').value = text;
    document.getElementById('question-order').value = order;
    document.querySelector('.add-question-box h4').textContent = "質問を編集";
    populateOrderSelect();
}

function resetQuestionForm() {
    document.getElementById('question-id').value = '';
    document.getElementById('question-form').reset();
    document.querySelector('.add-question-box h4').textContent = "質問を追加";
    populateOrderSelect();
}

document.getElementById('question-form').onsubmit = async (e) => {
    e.preventDefault();

    const savedItems = [];
    let scenarioSaved = false;

    // Auto-save scenario if not saved yet or if there are changes
    if (!currentScenario || !document.getElementById('scenario-id').value) {
        const result = await saveScenario();
        if (!result) {
            alert('シナリオの保存に失敗しました');
            return;
        }
        scenarioSaved = true;
        savedItems.push(`シナリオ「${result.scenario.name}」を${result.isNew ? '作成' : '更新'}`);

        // Check if greeting/disclaimer were filled
        if (result.scenario.greeting_text) {
            savedItems.push('挨拶メッセージを保存');
        }
        if (result.scenario.disclaimer_text) {
            savedItems.push('免責事項を保存');
        }

        loadScenarios();
    }

    const qId = document.getElementById('question-id').value;
    const text = document.getElementById('question-text').value;
    const order = document.getElementById('question-order').value;

    let url = `${API_BASE}/questions/`;
    let method = 'POST';
    let isNewQuestion = !qId;

    if (qId) {
        url += `${qId}`;
        method = 'PUT';
    }

    await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            text: text,
            sort_order: parseInt(order),
            scenario_id: currentScenario.id,
            is_active: true
        })
    });

    const questionPreview = text.length > 30 ? text.substring(0, 30) + '...' : text;
    savedItems.push(`質問「${questionPreview}」を${isNewQuestion ? '作成' : '更新'}`);

    resetQuestionForm();
    await loadQuestions(currentScenario.id);

    showNotification('保存完了', savedItems);
};

async function deleteQuestion(id) {
    if (!confirm('この質問を削除しますか？')) return;
    await fetch(`${API_BASE}/questions/${id}`, { method: 'DELETE' });
    await loadQuestions(currentScenario.id);
    showNotification('削除完了', '質問を削除しました');
}

// --- Numbers & Logs ---
async function loadPhoneNumbers() {
    const sRes = await fetch(`${API_BASE}/scenarios/`);
    const scenarios = await sRes.json();
    const select = document.getElementById('number-scenario-select');
    select.innerHTML = '<option value="">選択してください</option>';
    scenarios.forEach(s => {
        select.innerHTML += `<option value="${s.id}">${escapeHtml(s.name)}</option>`;
    });

    const res = await fetch(`${API_BASE}/phone_numbers/`);
    const data = await res.json();
    const tbody = document.querySelector('#number-table tbody');
    tbody.innerHTML = '';
    data.forEach(p => {
        const sc = scenarios.find(s => s.id === p.scenario_id);
        const scName = sc ? escapeHtml(sc.name) : `ID: ${p.scenario_id}`;

        tbody.innerHTML += `
            <tr>
                <td>${escapeHtml(p.to_number)}</td>
                <td>${scName}</td>
                <td>${escapeHtml(p.label || '-')}</td>
                <td><button class="small secondary">編集</button></td>
            </tr>`;
    });
}

document.getElementById('number-form').onsubmit = async (e) => {
    e.preventDefault();
    const to = document.getElementById('phone-number').value;
    const sid = document.getElementById('number-scenario-select').value;
    const label = document.getElementById('phone-label').value;

    await fetch(`${API_BASE}/phone_numbers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_number: to, scenario_id: parseInt(sid), label: label, is_active: true })
    });
    loadPhoneNumbers();
    showNotification('保存完了', `電話番号「${to}」を設定しました`);
};

async function loadLogs() {
    const to = document.getElementById('filter-to').value;
    let url = `${API_BASE}/calls/?limit=50`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    tbody.innerHTML = '';

    data.forEach(call => {
        let answersHtml = '';
        if (call.answers) {
            call.answers.forEach(a => {
                let rec = a.recording_url_twilio ? `<a href="${a.recording_url_twilio}" target="_blank"><i class="fas fa-play"></i></a>` : '';
                answersHtml += `<div style="font-size:0.9rem; margin-bottom:4px;">
                    <span style="color:#aaa;">Q:</span> ${escapeHtml(a.question_text || '??')} <br>
                    <span style="color:#3498db;">A:</span> ${rec} ${escapeHtml(a.transcript_text || '(音声のみ)')}
                </div>`;
            });
        }

        tbody.innerHTML += `
            <tr>
                <td>${new Date(call.started_at).toLocaleString('ja-JP')}</td>
                <td>${escapeHtml(call.from_number)}</td>
                <td>${escapeHtml(call.to_number)}</td>
                <td style="font-size:0.85rem; color:#888;">${call.scenario_id || '-'}</td>
                <td>${answersHtml}</td>
            </tr>`;
    });
}

function exportCSV() {
    const to = document.getElementById('filter-to').value;
    let url = `${API_BASE}/export_csv`;
    if (to) url += `?to_number=${encodeURIComponent(to)}`;
    window.location.href = url;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Init
loadScenarios();

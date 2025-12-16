const API_BASE = "/admin";
let currentScenario = null;
let currentQuestions = []; // Array of {id, text, sort_order, is_deleted, is_new, temp_id}
let draggedElement = null;

// --- Notification System ---
function showNotification(title, items) {
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
    }, 2000);
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
    document.getElementById('scenario-guidance').value = scenario.question_guidance_text || 'このあと何点か質問をさせていただきます。回答が済みましたらシャープを押して次に進んでください';

    await loadQuestions(scenario.id);
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
    document.getElementById('scenario-guidance').value = 'このあと何点か質問をさせていただきます。回答が済みましたらシャープを押して次に進んでください';
    document.getElementById('questions-container').innerHTML = '';
}

// --- Scenario & Questions Actions (Bulk Save) ---
async function saveAll() {
    const id = document.getElementById('scenario-id').value;
    const name = document.getElementById('scenario-name').value;
    const greeting = document.getElementById('scenario-greeting').value;
    const disclaimer = document.getElementById('scenario-disclaimer').value;
    const guidance = document.getElementById('scenario-guidance').value;

    if (!name) {
        alert('シナリオ名を入力してください');
        return;
    }

    // 1. Save Scenario
    const payload = {
        name,
        greeting_text: greeting,
        disclaimer_text: disclaimer,
        question_guidance_text: guidance
    };

    let url = `${API_BASE}/scenarios/`;
    let method = 'POST';
    let isNew = !id;

    if (id) {
        url += `${id}`;
        method = 'PUT';
    }

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error('Failed to save scenario');
        const savedScenario = await res.json();

        // 2. Save Questions
        // Calculate current sort orders based on DOM order
        const qItems = document.querySelectorAll('.question-item');
        const finalOrder = [];
        qItems.forEach((item, index) => {
            const indexInArray = parseInt(item.dataset.index);
            const q = currentQuestions[indexInArray];
            if (q) {
                finalOrder.push({ ...q, sort_order: index + 1 });
            }
        });

        // Process additions/updates/deletions
        // Current logic: We will just sync everything.
        // For simplicity:
        // A. Delete removed questions (handled by immediate delete for now, or track deletions)
        // B. Update/Create questions

        // Note: For "deleted" questions, currently I implemented immediate delete on click.
        // To support "bulk save" fully including deletions, we would need to track deleted IDs.
        // For now, let's assume deletions are immediate (confirmation dialog) and this save is for additions/updates.

        const notificationItems = [`シナリオ「${savedScenario.name}」を保存しました`];

        for (const q of finalOrder) {
            let qUrl = `${API_BASE}/questions/`;
            let qMethod = 'POST';
            let qBody = {
                text: q.text,
                sort_order: q.sort_order,
                scenario_id: savedScenario.id,
                is_active: true
            };

            if (q.id && !q.is_new) {
                qUrl += `${q.id}`;
                qMethod = 'PUT';
            }

            await fetch(qUrl, {
                method: qMethod,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(qBody)
            });
        }

        // Reload everything
        if (isNew) {
            document.getElementById('scenario-id').value = savedScenario.id;
            currentScenario = savedScenario;
        }
        await selectScenario(savedScenario.id);
        loadScenarios();
        showNotification('保存完了', notificationItems);

    } catch (e) {
        console.error(e);
        alert('保存中にエラーが発生しました');
    }
}

document.getElementById('scenario-form').onsubmit = async (e) => {
    e.preventDefault();
    await saveAll();
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
            disclaimer_text: scenario.disclaimer_text,
            question_guidance_text: scenario.question_guidance_text
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

// --- Questions Logic (Client-side manip) ---
async function loadQuestions(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    const data = await res.json();
    currentQuestions = data.map(q => ({ ...q, is_new: false }));
    renderQuestions();
}

// Add Enter key support outside loadQuestions, or in init
document.addEventListener('DOMContentLoaded', function () {
    const input = document.getElementById('new-question-text');
    if (input) {
        input.addEventListener('keypress', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                addQuestionToList();
            }
        });
    }
});

function addQuestionToList() {
    console.log("Adding question to list...");
    const textInput = document.getElementById('new-question-text');
    const text = textInput.value.trim();
    if (!text) {
        console.log("Empty text, skipping");
        return;
    }

    currentQuestions.push({
        id: null, // No ID yet
        text: text,
        sort_order: currentQuestions.length + 1,
        is_new: true,
        temp_id: Date.now() // temporary ID for DOM
    });
    renderQuestions();
    textInput.value = '';
    textInput.focus();
    console.log("Question added:", text);
}

function renderQuestions() {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';

    currentQuestions.forEach((q, index) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.draggable = true;
        // Use real ID or temp ID
        div.dataset.index = index;

        div.innerHTML = `
            <i class="fas fa-grip-vertical drag-handle"></i>
            <div style="margin-left: 35px; width: 100%;">
                <span class="q-order">#${index + 1}</span>
                <input type="text" class="q-edit-input" value="${escapeHtml(q.text)}" onchange="updateQuestionText(${index}, this.value)" style="width: calc(100% - 120px);">
            </div>
            <div class="q-actions">
                <button type="button" class="small danger" onclick="removeQuestion(${index})">削除</button>
            </div>
        `;

        div.addEventListener('dragstart', handleDragStart);
        div.addEventListener('dragover', handleDragOver);
        div.addEventListener('drop', handleDrop);
        div.addEventListener('dragend', handleDragEnd);

        container.appendChild(div);
    });
}

// Immediate remove for now (simplifies things) - if it has ID, delete from DB. If new, just remove from array.
async function removeQuestion(index) {
    const q = currentQuestions[index];
    if (q.id && !q.is_new) {
        if (!confirm('保存済みの質問です。削除しますか？')) return;
        await fetch(`${API_BASE}/questions/${q.id}`, { method: 'DELETE' });
    }
    currentQuestions.splice(index, 1);
    renderQuestions();
}

function updateQuestionText(index, newText) {
    currentQuestions[index].text = newText;
}

// Drag & Drop
function handleDragStart(e) {
    draggedElement = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
}

function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = 'move';

    const afterElement = getDragAfterElement(e.currentTarget.parentElement, e.clientY);
    if (afterElement == null) {
        e.currentTarget.classList.add('drag-over');
    }
    return false;
}

function handleDrop(e) {
    if (e.stopPropagation) {
        e.stopPropagation();
    }

    if (draggedElement !== this) {
        // Reorder in DOM
        if (draggedElement.parentNode === this.parentNode) {
            const allItems = [...this.parentNode.children];
            const draggedIndex = allItems.indexOf(draggedElement);
            const targetIndex = allItems.indexOf(this);

            if (draggedIndex < targetIndex) {
                this.parentNode.insertBefore(draggedElement, this.nextSibling);
            } else {
                this.parentNode.insertBefore(draggedElement, this);
            }

            // Reorder in Array
            // Note: The DOM is already updated. We need to reflect this in currentQuestions.
            // But doing it effectively requires mapping DOM back to array.
            // Simplest way: re-read array from DOM
            rebuildArrayFromDOM();
        }
    }

    this.classList.remove('drag-over');
    return false;
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('.question-item').forEach(item => {
        item.classList.remove('drag-over');
    });
    renderQuestions(); // Re-render to update order numbers
}

function rebuildArrayFromDOM() {
    const newArr = [];
    const items = document.querySelectorAll('.question-item');
    items.forEach(item => {
        const index = parseInt(item.dataset.index);
        newArr.push(currentQuestions[index]);
    });
    currentQuestions = newArr;
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.question-item:not(.dragging)')];

    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}


// --- Phone Numbers ---
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
            <tr onclick="editPhoneNumber('${escapeHtml(p.to_number)}', ${p.scenario_id}, '${escapeHtml(p.label || '')}')">
                <td>${escapeHtml(p.to_number)}</td>
                <td>${scName}</td>
                <td>${escapeHtml(p.label || '-')}</td>
                <td onclick="event.stopPropagation();">
                    <button class="small danger" onclick="deletePhoneNumber('${escapeHtml(p.to_number)}')">削除</button>
                </td>
            </tr>`;
    });
}

function editPhoneNumber(number, scenarioId, label) {
    document.getElementById('phone-number').value = number;
    document.getElementById('number-scenario-select').value = scenarioId;
    document.getElementById('phone-label').value = label;
    document.getElementById('phone-number').focus();
}

async function deletePhoneNumber(number) {
    if (!confirm(`電話番号「${number}」を削除しますか？`)) return;
    await fetch(`${API_BASE}/phone_numbers/${encodeURIComponent(number)}`, { method: 'DELETE' });
    loadPhoneNumbers();
    showNotification('削除完了', `電話番号「${number}」を削除しました`);
}

document.getElementById('number-form').onsubmit = async (e) => {
    e.preventDefault();
    const to = document.getElementById('phone-number').value.trim();
    const sid = document.getElementById('number-scenario-select').value;
    const label = document.getElementById('phone-label').value;

    await fetch(`${API_BASE}/phone_numbers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_number: to, scenario_id: parseInt(sid), label: label, is_active: true })
    });

    document.getElementById('number-form').reset();
    loadPhoneNumbers();
    showNotification('保存完了', `電話番号「${to}」を設定しました`);
};

// --- Logs with Download ---
async function loadLogs() {
    const to = document.getElementById('filter-to').value;
    const start = document.getElementById('filter-start-date').value;
    const end = document.getElementById('filter-end-date').value;

    let url = `${API_BASE}/calls/?limit=50`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;
    if (start) url += `&start_date=${start}`;
    if (end) url += `&end_date=${end}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    tbody.innerHTML = '';

    data.forEach(call => {
        let answersHtml = '';
        if (call.answers) {
            call.answers.forEach(a => {
                let downloadLink = a.recording_sid ?
                    `<br><a href="${API_BASE}/download_recording/${a.recording_sid}" class="download-link-text"><i class="fas fa-download"></i> 音声DL</a>` : '';
                let transcript = a.transcript_text ? escapeHtml(a.transcript_text) : '<span style="color:#999;">(テキスト化処理中...)</span>';
                answersHtml += `<div style="font-size:0.9rem; margin-bottom:8px; padding:8px; background:#f9f9f9; border-radius:4px;">
                    <div style="color:#888; font-size:0.85rem; margin-bottom:4px;"><strong>Q:</strong> ${escapeHtml(a.question_text || '??')}</div>
                    <div style="color:#2c3e50;"><strong>A:</strong> ${transcript} ${downloadLink}</div>
                </div>`;
            });
        }

        const bulkDownload = `<a href="${API_BASE}/download_call_recordings/${call.call_sid}" class="btn-download-all" title="全録音をZIPでダウンロード"><i class="fas fa-file-audio"></i> 音声一括DL</a>`;

        tbody.innerHTML += `
            <tr>
                <td>${new Date(call.started_at).toLocaleString('ja-JP')}</td>
                <td>${escapeHtml(call.from_number)}</td>
                <td>${escapeHtml(call.to_number)}</td>
                <td style="font-weight:600; color:#3498db;">${escapeHtml(call.scenario_name || '-')}</td>
                <td>
                    ${answersHtml || '<span style="color:#999;">回答なし</span>'}
                    <div style="margin-top:10px; text-align:right;">${bulkDownload}</div>
                </td>
            </tr>`;
    });
}

function exportCSV() {
    const to = document.getElementById('filter-to').value;
    const start = document.getElementById('filter-start-date').value;
    const end = document.getElementById('filter-end-date').value;

    let url = `${API_BASE}/export_csv?`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;
    if (start) url += `&start_date=${start}`;
    if (end) url += `&end_date=${end}`;

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

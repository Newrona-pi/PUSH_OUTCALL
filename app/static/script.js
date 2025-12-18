const API_BASE = "/admin";
let currentScenario = null;
let currentQuestions = []; // Array of {id, text, sort_order, is_deleted, is_new, temp_id}
let currentEndingGuidances = []; // Array of {id, text, sort_order, is_new, temp_id}
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

    const changedItems = [];

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
        // Simple logic to detect basic changes (could be more robust)
        if (currentScenario) {
            if (currentScenario.name !== name) changedItems.push("シナリオ名");
            if ((currentScenario.greeting_text || '') !== greeting) changedItems.push("挨拶メッセージ");
            if ((currentScenario.disclaimer_text || '') !== disclaimer) changedItems.push("録音告知");
            if ((currentScenario.question_guidance_text || '') !== guidance) changedItems.push("質問前ガイダンス");
        } else {
            changedItems.push("新規シナリオ");
        }

        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error('Failed to save scenario');
        const savedScenario = await res.json();

        // 2. Save Questions
        const qItems = document.querySelectorAll('#questions-container .question-item');
        const finalOrder = [];
        qItems.forEach((item, index) => {
            const indexInArray = parseInt(item.dataset.index);
            const q = currentQuestions[indexInArray];
            if (q) {
                finalOrder.push({ ...q, sort_order: index + 1 });
            }
        });

        let questionsChanged = false;
        // Basic check: length diff or reorder or text diff
        // For strict diff, we'd compare detailed props. Here assume if we save, we check.
        // Or simply add "質問設定" if array is non-empty.
        // Let's rely on backend responses or simple "Questions updated"
        if (currentQuestions.some(q => q.is_new) || currentQuestions.length !== finalOrder.length) {
            questionsChanged = true;
        }
        // Deep compare for text changes?? Too heavy?
        // Let's just add "質問設定" if there are questions.
        // Actually user wants specific "Question #2" etc if possible.
        // For simplicity, let's list "質問設定(更新あり)" or similar if logic is complex.
        // Or, we can push "質問 #N" inside loop.

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
                // Check if changed?
                const original = currentQuestions.find(cq => cq.id === q.id);
                if (original && (original.text !== q.text || original.sort_order !== q.sort_order)) {
                    changedItems.push(`質問 #${q.sort_order}`);
                }
            } else {
                changedItems.push(`質問 #${q.sort_order} (新規)`);
            }

            await fetch(qUrl, {
                method: qMethod,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(qBody)
            });
        }

        // 3. Save Ending Guidances
        const gItems = document.querySelectorAll('#ending-container .ending-item');
        const gFinalOrder = [];
        gItems.forEach((item, index) => {
            const indexInArray = parseInt(item.dataset.index);
            const g = currentEndingGuidances[indexInArray];
            if (g) {
                gFinalOrder.push({ ...g, sort_order: index + 1 });
            }
        });

        for (const g of gFinalOrder) {
            let qUrl = `${API_BASE}/ending_guidances/`;
            let qMethod = 'POST';
            let qBody = {
                text: g.text,
                sort_order: g.sort_order,
                scenario_id: savedScenario.id
            };

            if (g.id && !g.is_new) {
                qUrl += `${g.id}`;
                qMethod = 'PUT';
                const original = currentEndingGuidances.find(cg => cg.id === g.id);
                if (original && (original.text !== g.text || original.sort_order !== g.sort_order)) {
                    changedItems.push(`終話ガイダンス #${g.sort_order}`);
                }
            } else {
                changedItems.push(`終話ガイダンス #${g.sort_order} (新規)`);
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

        if (changedItems.length === 0) changedItems.push("変更はありませんでした");
        // Remove duplicates just in case
        const uniqueItems = [...new Set(changedItems)];
        showNotification('保存完了', uniqueItems);

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

    // Copy Ending Guidances
    const egRes = await fetch(`${API_BASE}/scenarios/${scenarioId}/ending_guidances`);
    const endingGuidances = await egRes.json();

    for (const g of endingGuidances) {
        await fetch(`${API_BASE}/ending_guidances/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: g.text,
                sort_order: g.sort_order,
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

    // Load Ending Guidances too
    loadEndingGuidances(scenarioId);
}

// --- Ending Guidance Logic ---
async function loadEndingGuidances(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/ending_guidances`);
    const data = await res.json();
    currentEndingGuidances = data.map(g => ({ ...g, is_new: false }));
    renderEndingGuidances();
}

function addEndingGuidance() {
    currentEndingGuidances.push({
        id: null,
        text: '',
        sort_order: currentEndingGuidances.length + 1,
        is_new: true,
        temp_id: Date.now()
    });
    renderEndingGuidances();
}

function removeEndingGuidance(index) {
    const g = currentEndingGuidances[index];
    if (g.id && !g.is_new) {
        if (!confirm('保存済みのガイダンスです。削除しますか？')) return;
        fetch(`${API_BASE}/ending_guidances/${g.id}`, { method: 'DELETE' });
    }
    currentEndingGuidances.splice(index, 1);
    renderEndingGuidances();
}

function updateEndingGuidanceText(index, val) {
    currentEndingGuidances[index].text = val;
}

function renderEndingGuidances() {
    const container = document.getElementById('ending-container');
    container.innerHTML = '';

    currentEndingGuidances.forEach((g, index) => {
        const div = document.createElement('div');
        div.className = 'ending-item question-item'; // Re-use question-item styles
        div.draggable = true;
        div.dataset.index = index;
        div.dataset.type = 'ending';

        div.innerHTML = `
            <i class="fas fa-grip-vertical drag-handle"></i>
            <div style="margin-left: 35px; width: 100%;">
                <span class="q-order">#${index + 1}</span>
                <input type="text" class="q-edit-input" value="${escapeHtml(g.text)}" 
                    placeholder="終了メッセージを入力"
                    onchange="updateEndingGuidanceText(${index}, this.value)" style="width: calc(100% - 120px);">
            </div>
            <div class="q-actions">
                <button type="button" class="small danger" onclick="removeEndingGuidance(${index})">削除</button>
            </div>
        `;

        div.addEventListener('dragstart', handleDragStart);
        div.addEventListener('dragover', handleDragOver);
        div.addEventListener('drop', handleDrop);
        div.addEventListener('dragend', handleDragEnd);

        container.appendChild(div);
    });
}

// Add Enter key support outside loadQuestions, or in init
document.addEventListener('DOMContentLoaded', function () {
    console.log("DOM loaded, initializing script...");
    const input = document.getElementById('new-question-text');
    if (input) {
        input.addEventListener('keypress', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                console.log("Enter key pressed in new question input");
                addQuestionToList();
            }
        });
    } else {
        console.error("New question input not found in DOM!");
    }
});

// Explicitly attach to window to ensure it's globally accessible
window.addQuestionToList = function () {
    console.log("addQuestionToList called");
    const textInput = document.getElementById('new-question-text');
    if (!textInput) {
        console.error("Input element 'new-question-text' not found!");
        return;
    }

    const text = textInput.value.trim();
    if (!text) {
        console.log("Empty text, skipping");
        // Flash the input to indicate error/empty
        textInput.style.borderColor = "red";
        setTimeout(() => textInput.style.borderColor = "", 500);
        return;
    }

    currentQuestions.push({
        id: null, // No ID yet
        text: text,
        sort_order: currentQuestions.length + 1,
        is_new: true,
        temp_id: Date.now() // temporary ID for DOM
    });

    console.log("Question added to array, rendering...", currentQuestions);
    renderQuestions();

    textInput.value = '';
    textInput.focus();
    console.log("Input cleared and focused");
};

function renderQuestions() {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';

    currentQuestions.forEach((q, index) => {
        const div = document.createElement('div');
        div.className = 'question-item';
        div.draggable = true;
        // Use real ID or temp ID
        div.dataset.index = index;
        div.dataset.type = 'question';

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
    // Check if handle is clicked
    if (!e.target.classList.contains('drag-handle')) {
        e.preventDefault();
        return;
    }
    // Set dragged element to the row, not the handle
    draggedElement = e.target.closest('.question-item, .ending-item');
    draggedElement.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    // Fix for drag image if needed, or browser default
}

function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = 'move';

    // Target constraint
    const container = e.currentTarget.parentElement;
    const afterElement = getDragAfterElement(container, e.clientY);

    // Visual feedback logic (simplified)
    return false;
}

function handleDrop(e) {
    if (e.stopPropagation) {
        e.stopPropagation();
    }

    if (draggedElement !== this && draggedElement.parentNode === this.parentNode) {
        // Reorder in DOM
        // Check previous siblings count to determine index
        const allItems = [...this.parentNode.children];
        const draggedIndex = allItems.indexOf(draggedElement);
        const targetIndex = allItems.indexOf(this);

        if (draggedIndex < targetIndex) {
            this.parentNode.insertBefore(draggedElement, this.nextSibling);
        } else {
            this.parentNode.insertBefore(draggedElement, this);
        }

        // Reorder in Array
        if (this.dataset.type === 'ending') {
            rebuildEndingGuidancesArray();
        } else {
            rebuildQuestionsArray();
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
    // This is redundant if handleDrop calls rebuild, but safe
    if (this.dataset.type === 'ending') renderEndingGuidances();
    else renderQuestions();
}

function rebuildQuestionsArray() {
    const newArr = [];
    const items = document.querySelectorAll('#questions-container .question-item');
    items.forEach(item => {
        const index = parseInt(item.dataset.index);
        newArr.push(currentQuestions[index]);
    });
    currentQuestions = newArr;
}

function rebuildEndingGuidancesArray() {
    const newArr = [];
    const items = document.querySelectorAll('#ending-container .ending-item');
    items.forEach(item => {
        const index = parseInt(item.dataset.index);
        newArr.push(currentEndingGuidances[index]);
    });
    currentEndingGuidances = newArr;
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
let currentLogTab = 'active';

function switchLogTab(status) {
    currentLogTab = status;
    document.querySelectorAll('.log-tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`log-tab-${status}`).classList.add('active');
    loadLogs();
}

async function loadLogs() {
    const to = document.getElementById('filter-to').value;
    const start = document.getElementById('filter-start-date').value;
    const end = document.getElementById('filter-end-date').value;

    let url = `${API_BASE}/calls/?limit=50&scenario_status=${currentLogTab}`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;
    if (start) url += `&start_date=${start}`;
    if (end) url += `&end_date=${end}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    tbody.innerHTML = '';

    // Helper to format 090...
    const formatPhone = (num) => {
        if (!num) return '-';
        if (num.startsWith('+81')) {
            return '0' + num.slice(3);
        }
        return num;
    };

    data.forEach(call => {
        let answersHtml = '';
        if (call.answers) {
            call.answers.forEach(a => {
                let downloadLink = a.recording_sid ?
                    `<a href="${API_BASE}/download_recording/${a.recording_sid}" class="download-link-text"><i class="fas fa-download"></i> 音声DL</a>` : '';

                // Add Player
                let audioPlayer = '';
                if (a.recording_sid) {
                    audioPlayer = `<audio controls src="${API_BASE}/audio_proxy/${a.recording_sid}" style="height: 30px; margin-right: 10px; vertical-align: middle;"></audio>`;
                }

                let transcriptDisplay = '';
                if (a.transcript_text) {
                    transcriptDisplay = escapeHtml(a.transcript_text);
                } else {
                    if (a.transcript_status === 'failed') {
                        transcriptDisplay = `<span style="color:red;"><i class="fas fa-exclamation-circle"></i> 失敗</span> <button class="small secondary" onclick="retryTranscription(${a.id})" style="padding:2px 6px; font-size:0.75rem; margin-left:5px;">再試行</button>`;
                    } else if (a.transcript_status === 'processing' || !a.transcript_status) {
                        transcriptDisplay = '<span style="color:#f39c12;"><i class="fas fa-spinner fa-spin"></i> 処理中...</span>';
                    } else {
                        transcriptDisplay = '<span style="color:#999;">(テキストなし)</span>';
                    }
                }

                // Show Answer logic (accordion style item)
                answersHtml += `<div style="font-size:0.9rem; margin-bottom:8px; padding:8px; background:#fff; border: 1px solid #eee; border-radius:4px;">
                    <div style="color:#555; font-size:0.85rem; margin-bottom:4px;"><strong>Q:</strong> ${escapeHtml(a.question_text || '??')}</div>
                    <div style="color:#333;">
                        <div style="margin-bottom: 5px;">A: ${transcriptDisplay}</div>
                        <div style="display: flex; align-items: center; justify-content: flex-end;">
                            ${audioPlayer}
                            <span style="font-size: 0.8rem;">${downloadLink}</span>
                        </div>
                    </div>
                </div>`;
            });
        }

        // Phase 4: Messages UI
        let messagesHtml = '';
        if (call.messages && call.messages.length > 0) {
            call.messages.forEach(m => {
                let dlLink = m.recording_url ?
                    `<a href="${m.recording_url}" target="_blank" class="download-link-text"><i class="fas fa-play"></i> 再生</a>` : '';

                messagesHtml += `<div style="font-size:0.9rem; margin-top:8px; padding:8px; background:#e8f5e9; border: 1px solid #c8e6c9; border-radius:4px;">
                   <div style="color:#2e7d32; font-size:0.85rem; margin-bottom:4px;"><strong><i class="fas fa-comment-dots"></i> 伝言:</strong></div>
                   <div style="color:#333; display: flex; justify-content: space-between; align-items: flex-start;">
                       <span style="flex:1;">${escapeHtml(m.transcript_text || '(音声のみ)')}</span>
                       <span style="margin-left:10px; font-size: 0.8rem;">${dlLink}</span>
                   </div>
               </div>`;
            });
        }

        // Accordion container for answers
        const accordionId = `acc-${call.call_sid}`;
        const answersContainer = `<div id="${accordionId}" style="display:none; margin-top:10px; padding: 10px; background: #fdfdfd; border-radius: 4px;">${answersHtml || '<span style="color:#999;">回答なし</span>'}${messagesHtml}</div>`;
        const toggleBtn = `<button onclick="document.getElementById('${accordionId}').style.display = document.getElementById('${accordionId}').style.display === 'none' ? 'block' : 'none'" class="small secondary" style="margin-right:5px;">詳細表示</button>`;

        const bulkDownload = `<a href="${API_BASE}/download_call_recordings/${call.call_sid}" class="btn-download-all" title="全録音をZIPでダウンロード"><i class="fas fa-file-archive"></i> 音声ZIP</a>`;

        // Full Call Audio Player
        let fullAudioPlayer = '';
        if (call.recording_sid) {
            fullAudioPlayer = `<div style="margin-right: 15px; display: inline-flex; align-items: center;">
                <span style="font-size:0.8rem; color:#666; margin-right:5px;">通話全体:</span>
                <audio controls src="${API_BASE}/audio_proxy/${call.recording_sid}" style="height: 30px; vertical-align: middle;"></audio>
             </div>`;
        }

        // Status badge
        let statusBadge = `<span style="padding: 2px 6px; border-radius: 4px; background: #eee; font-size: 0.8rem;">${call.status}</span>`;
        if (call.status === 'completed') statusBadge = `<span style="padding: 2px 6px; border-radius: 4px; background: #e8f5e9; color: #2e7d32; font-size: 0.8rem;">完了</span>`;
        if (call.status === 'in-progress') statusBadge = `<span style="padding: 2px 6px; border-radius: 4px; background: #e3f2fd; color: #1565c0; font-size: 0.8rem;">通話中</span>`;

        tbody.innerHTML += `
            <tr>
                <td>${new Date(call.started_at).toLocaleString('ja-JP')}</td>
                <td>${escapeHtml(formatPhone(call.from_number))}</td>
                <td>${escapeHtml(formatPhone(call.to_number))}</td>
                <td>${escapeHtml(call.scenario_name || '-')} <br>${statusBadge}</td>
                <td>
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div style="display:flex; align-items:center;">
                            ${toggleBtn}
                        </div>
                        <div style="display:flex; align-items:center;">
                            ${fullAudioPlayer}
                            ${bulkDownload}
                        </div>
                    </div>
                    ${answersContainer}
                </td>
            </tr>`;
    });
}

function exportZIP() {
    const to = document.getElementById('filter-to').value;
    const start = document.getElementById('filter-start-date').value;
    const end = document.getElementById('filter-end-date').value;
    const scenarioStatus = currentLogTab;

    let url = `${API_BASE}/export_zip?`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;
    if (start) url += `&start_date=${start}`;
    if (end) url += `&end_date=${end}`;
    url += `&scenario_status=${scenarioStatus}`;

    window.location.href = url;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// Phase 2: Retry Transcription
async function retryTranscription(answerId) {
    if (!confirm("文字起こしを再実行しますか？")) return;
    try {
        const res = await fetch(`${API_BASE}/retranscribe/${answerId}`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed");
        }
        alert("再実行をキューに入れました。しばらくしてからリロードしてください。");
        loadLogs();
    } catch (e) {
        console.error(e);
        alert("エラーが発生しました: " + e);
    }
}

// Init
loadScenarios();

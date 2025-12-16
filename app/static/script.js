const API_BASE = "/admin";
let currentScenarioId = null;

// Tab Switching
function openTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.target.classList.add('active'); // Assumes event triggered
    if (tabId === 'tab-scenarios') loadScenarios();
    if (tabId === 'tab-numbers') loadPhoneNumbers(); // Re-use logic to populate select
    if (tabId === 'tab-logs') loadLogs();
}

// Scenarios
async function loadScenarios() {
    const res = await fetch(`${API_BASE}/scenarios/`);
    const data = await res.json();
    const list = document.getElementById('scenario-list');
    const select = document.getElementById('number-scenario-select');

    list.innerHTML = '';
    select.innerHTML = '<option value="">Select Scenario</option>';

    data.forEach(s => {
        // List Item
        const li = document.createElement('li');
        li.textContent = `${s.name} (ID: ${s.id})`;
        li.onclick = () => selectScenario(s);
        list.appendChild(li);

        // Select Option
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = s.name;
        select.appendChild(opt);
    });
}

document.getElementById('scenario-form').onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('scenario-name').value;
    const greeting = document.getElementById('scenario-greeting').value;
    const disclaimer = document.getElementById('scenario-disclaimer').value;

    await fetch(`${API_BASE}/scenarios/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, greeting_text: greeting, disclaimer_text: disclaimer })
    });

    document.getElementById('scenario-form').reset();
    loadScenarios();
};

function selectScenario(scenario) {
    currentScenarioId = scenario.id;
    document.getElementById('current-scenario-name').textContent = scenario.name;
    document.getElementById('questions-section').classList.remove('hidden');
    loadQuestions(scenario.id);
}

// Questions
async function loadQuestions(scenarioId) {
    const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/questions`);
    const data = await res.json();
    const list = document.getElementById('question-list');
    list.innerHTML = '';
    data.forEach(q => {
        const li = document.createElement('li');
        li.textContent = `[${q.sort_order}] ${q.text}`;
        list.appendChild(li);
    });
}

document.getElementById('question-form').onsubmit = async (e) => {
    e.preventDefault();
    if (!currentScenarioId) return;
    const text = document.getElementById('question-text').value;
    const order = document.getElementById('question-order').value;

    await fetch(`${API_BASE}/questions/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, sort_order: order, scenario_id: currentScenarioId })
    });

    document.getElementById('question-text').value = '';
    loadQuestions(currentScenarioId);
};

// Phone Numbers
async function loadPhoneNumbers() {
    loadScenarios(); // Ensure select is populated
    const res = await fetch(`${API_BASE}/phone_numbers/`);
    const data = await res.json();
    const tbody = document.querySelector('#number-table tbody');
    tbody.innerHTML = '';
    data.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${p.to_number}</td><td>${p.scenario_id}</td><td>${p.label || ''}</td><td>${p.is_active}</td>`;
        tbody.appendChild(tr);
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
        body: JSON.stringify({ to_number: to, scenario_id: sid, label: label, is_active: true })
    });
    loadPhoneNumbers();
};

// Logs
async function loadLogs() {
    const to = document.getElementById('filter-to').value;
    const from = document.getElementById('filter-from').value;
    let url = `${API_BASE}/calls/?limit=50`;
    if (to) url += `&to_number=${encodeURIComponent(to)}`;
    if (from) url += `&from_number=${encodeURIComponent(from)}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    tbody.innerHTML = '';

    data.forEach(call => {
        let answersHtml = '';
        if (call.answers) {
            call.answers.forEach(a => {
                let rec = a.recording_url_twilio ? `<a href="${a.recording_url_twilio}" target="_blank">Play</a>` : '';
                answersHtml += `<div>Q: ${a.question_text || '??'} <br> A: ${rec} ${a.transcript_text || ''}</div>`;
            });
        }

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${new Date(call.started_at).toLocaleString()}</td>
            <td>${call.from_number}</td>
            <td>${call.to_number}</td>
            <td>${call.status}</td>
            <td>${answersHtml}</td>
        `;
        tbody.appendChild(tr);
    });
}

function exportCSV() {
    const to = document.getElementById('filter-to').value;
    let url = `${API_BASE}/export_csv`;
    if (to) url += `?to_number=${encodeURIComponent(to)}`;
    window.location.href = url;
}

// Initial Load
loadScenarios();

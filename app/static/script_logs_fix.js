// --- Logs ---
async function loadLogs() {
    const toNumber = document.getElementById('filter-to')?.value || '';
    const startDate = document.getElementById('filter-start-date')?.value || '';
    const endDate = document.getElementById('filter-end-date')?.value || '';

    let url = `${API_BASE}/calls/?limit=100&_t=${Date.now()}`;
    if (toNumber) url += `&to_number=${encodeURIComponent(toNumber)}`;
    if (currentScenarioFilter) url += `&scenario_id=${currentScenarioFilter}`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;

    const res = await fetch(url);
    const data = await res.json();
    const tbody = document.querySelector('#logs-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    data.forEach((call, callIdx) => {
        const detailsId = `details-${callIdx}`;

        // Build answer data display (initially hidden)
        let answerDataHtml = '';
        if (call.answers && call.answers.length > 0) {
            answerDataHtml = `<div id="${detailsId}" style="display: none; max-width: 500px; margin-top: 10px; padding: 10px; background: rgba(99, 102, 241, 0.05); border-radius: 6px;">`;
            call.answers.forEach((answer, idx) => {
                const questionText = answer.question_text || `質問${idx + 1}`;
                const transcript = answer.transcript_text || '(文字起こしなし)';
                const audioLink = answer.recording_sid
                    ? `<audio controls src="${API_BASE}/audio_proxy/${answer.recording_sid}" style="width: 100%; margin-top: 3px;"></audio>`
                    : '';

                answerDataHtml += `
                    <div style="margin-bottom: 10px; padding: 8px; background: rgba(255, 255, 255, 0.5); border-left: 3px solid var(--primary); border-radius: 4px;">
                        <strong style="color: var(--primary);">Q${idx + 1}:</strong> ${escapeHtml(questionText)}<br>
                        <strong>A:</strong> ${escapeHtml(transcript)}
                        ${audioLink}
                    </div>
                `;
            });
            answerDataHtml += '</div>';
        }

        // Full call recording
        const fullRecording = call.recording_sid
            ? `<div style="margin-bottom: 5px;"><strong>全録音:</strong><br><audio controls src="${API_BASE}/audio_proxy/${call.recording_sid}" style="width: 100%; max-width: 300px;"></audio></div>`
            : '';

        // Toggle button for answer data
        const toggleButton = call.answers && call.answers.length > 0
            ? `<button onclick="toggleAnswerDetails('${detailsId}')" class="secondary small" style="margin-top: 5px;">
                <i class="fas fa-eye"></i> 回答詳細を表示
               </button>`
            : '';

        tbody.innerHTML += `
            <tr>
                <td style="white-space: nowrap;">${formatJST(call.started_at)}</td>
                <td style="white-space: nowrap;">${formatJapanesePhone(call.from_number)}</td>
                <td style="white-space: nowrap;">${formatJapanesePhone(call.to_number)}</td>
                <td>${escapeHtml(call.scenario_name || '-')}</td>
                <td><span class="badge ${call.status}">${call.status}</span></td>
                <td>
                    ${fullRecording}
                    ${toggleButton}
                    ${answerDataHtml}
                </td>
            </tr>
        `;
    });
}

function toggleAnswerDetails(detailsId) {
    const details = document.getElementById(detailsId);
    const button = event.target.closest('button');

    if (details.style.display === 'none') {
        details.style.display = 'block';
        button.innerHTML = '<i class="fas fa-eye-slash"></i> 回答詳細を非表示';
    } else {
        details.style.display = 'none';
        button.innerHTML = '<i class="fas fa-eye"></i> 回答詳細を表示';
    }
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

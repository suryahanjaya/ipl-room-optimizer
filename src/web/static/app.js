// Application State
let appState = {
    uploadedFile: null,
    filepath: null,
    uploadedFile: null,
    filepath: null,
    results: null,
    currentDetails: null // Store details for filtering
};

// Welcome Page Functions
function enterApplication() {
    document.getElementById('welcomePage').classList.add('hidden');
    document.getElementById('mainApp').classList.remove('hidden');
}

function resetToWelcome() {
    // Reset the app first
    resetApp();
    // Then show welcome page
    document.getElementById('mainApp').classList.add('hidden');
    document.getElementById('welcomePage').classList.remove('hidden');
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
});

function setupEventListeners() {
    const fileInput = document.getElementById('fileInput');
    const uploadArea = document.getElementById('uploadArea');

    // File input change
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    // Click to upload - but only if not clicking on button or input
    uploadArea.addEventListener('click', (e) => {
        // Don't trigger if clicking on button or input directly
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT') {
            return;
        }
        fileInput.click();
    });
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        handleFile(file);
    }
}

async function handleFile(file) {
    // Validate file
    if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.csv')) {
        showError('Please select an Excel (.xlsx) or CSV (.csv) file');
        return;
    }

    // Show file info
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatFileSize(file.size);
    hide('uploadArea');
    show('fileInfo');

    // Upload file
    await uploadFile(file);
}

async function uploadFile(file) {
    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            appState.uploadedFile = file;
            appState.filepath = data.filepath;

            // Show process section
            show('processSection');

            // Scroll to process section
            document.getElementById('processSection').scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        } else {
            showError(data.error || 'Upload failed');
        }

    } catch (error) {
        showError('Failed to upload file: ' + error.message);
    }
}

function clearFile() {
    document.getElementById('fileInput').value = '';
    show('uploadArea');
    hide('fileInfo');
    hide('processSection');

    appState.uploadedFile = null;
    appState.filepath = null;
}

async function startMerging() {
    if (!appState.filepath) {
        showError('No file uploaded');
        return;
    }

    // Hide start button, show processing
    hide('startBtn');
    show('processingState');

    try {
        const response = await fetch('/api/merge', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                filepath: appState.filepath
            })
        });

        const data = await response.json();

        if (data.success) {
            appState.results = data.data;
            showResults(data.data);
        } else {
            showError(data.error || 'Merging failed');
        }

    } catch (error) {
        showError('Failed to process: ' + error.message);
    } finally {
        hide('processingState');
        show('startBtn');
    }
}

function showResults(data) {
    // Hide other sections
    hide('uploadSection');
    hide('processSection');
    hide('errorSection');

    // Show results section
    show('resultsSection');

    // Show new upload button in header
    document.getElementById('newUploadBtn').classList.remove('hidden');

    // Populate overall stats
    const { overall } = data;
    document.getElementById('initialRooms').textContent = overall.initial_rooms.toLocaleString();
    document.getElementById('finalRooms').textContent = overall.final_rooms.toLocaleString();
    document.getElementById('roomsSaved').textContent = overall.rooms_saved.toLocaleString();
    document.getElementById('efficiency').textContent = `${overall.efficiency_percent}%`;

    // Store details for filtering
    appState.currentDetails = data.details;

    // Populate Campus Filter
    const uniqueCampuses = [...new Set(data.details.map(d => d.campus))].sort();
    const campusSelect = document.getElementById('campusFilter');
    // Keep "All Campuses" option
    campusSelect.innerHTML = '<option value="ALL">All Campuses</option>';
    uniqueCampuses.forEach(campus => {
        const option = document.createElement('option');
        option.value = campus;
        option.textContent = `Campus ${campus}`;
        campusSelect.appendChild(option);
    });

    // Populate details (initial render)
    filterAndRender();

    // Scroll to results
    document.getElementById('resultsSection').scrollIntoView({
        behavior: 'smooth',
        block: 'start'
    });
}

function filterAndRender() {
    if (!appState.currentDetails) return;

    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const campusFilter = document.getElementById('campusFilter').value;
    const sortFilter = document.getElementById('sortFilter').value;

    let filtered = appState.currentDetails.filter(detail => {
        // Campus Filter
        if (campusFilter !== 'ALL' && String(detail.campus) !== String(campusFilter)) {
            return false;
        }

        // Search Filter
        if (searchTerm) {
            const shiftMatch = String(detail.shift).toLowerCase().includes(searchTerm);
            const campusMatch = String(detail.campus).toLowerCase().includes(searchTerm);

            // Check rooms inside
            const keptMatch = detail.kept_rooms_data && detail.kept_rooms_data.some(room =>
                String(room.name).toLowerCase().includes(searchTerm) ||
                String(room.subject).toLowerCase().includes(searchTerm)
            );

            const removedMatch = detail.removed_rooms_data && detail.removed_rooms_data.some(room =>
                String(room.name).toLowerCase().includes(searchTerm) ||
                String(room.subject).toLowerCase().includes(searchTerm)
            );

            return shiftMatch || campusMatch || keptMatch || removedMatch;
        }

        return true;
    });

    // Sort
    filtered.sort((a, b) => {
        if (sortFilter === 'shift_asc') {
            // Try numeric sort for shift if possible
            const shiftA = parseInt(a.shift) || a.shift;
            const shiftB = parseInt(b.shift) || b.shift;
            if (shiftA < shiftB) return -1;
            if (shiftA > shiftB) return 1;
            return 0;
        } else if (sortFilter === 'shift_desc') {
            const shiftA = parseInt(a.shift) || a.shift;
            const shiftB = parseInt(b.shift) || b.shift;
            if (shiftA > shiftB) return -1;
            if (shiftA < shiftB) return 1;
            return 0;
        } else if (sortFilter === 'saved_desc') {
            return b.saved - a.saved;
        }
        return 0;
    });

    renderDetails(filtered);
}

function renderDetails(details) {
    const container = document.getElementById('detailsContainer');
    container.innerHTML = '';

    details.forEach((detail, index) => {
        const card = createDetailCard(detail, index);
        container.appendChild(card);
    });
}

function createDetailCard(detail, index) {
    const card = document.createElement('div');
    card.className = 'detail-card';
    card.style.animationDelay = `${0.1 * index}s`;

    const hasChanges = detail.removed_rooms.length > 0;
    const detailId = `detail-${detail.shift}-${detail.campus}`;

    card.innerHTML = `
        <div class="detail-header">
            <h3 class="detail-title">Shift ${escapeHtml(detail.shift)}, Campus ${escapeHtml(detail.campus)}</h3>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <span class="detail-badge">Saved: ${detail.saved}</span>
                <button class="detail-view-btn" onclick="showMergeDetail('${detailId}')">View Details</button>
            </div>
        </div>
        <div class="detail-body">
            <div class="detail-stats">
                <div class="detail-stat">
                    <div class="detail-stat-label">Initial Rooms</div>
                    <div class="detail-stat-value">${detail.initial}</div>
                </div>
                <div class="detail-stat">
                    <div class="detail-stat-label">Final Rooms</div>
                    <div class="detail-stat-value">${detail.final}</div>
                </div>
                <div class="detail-stat">
                    <div class="detail-stat-label">Rooms Saved</div>
                    <div class="detail-stat-value positive">${detail.saved}</div>
                </div>
            </div>
            
            ${renderRoomsSection(detail)}
        </div>
    `;

    // Store detail data for modal
    card.dataset.detailData = JSON.stringify(detail);

    return card;
}

function renderNoChanges(detail) {
    if (!detail || !detail.kept_rooms) return '';

    // Even if no merging possible, show the kept rooms as requested
    return `
        <div class="rooms-section">
            <div class="rooms-header">
                <span class="rooms-label">Active Rooms (No Merging Needed)</span>
                <span class="rooms-count">${detail.kept_rooms.length}</span>
            </div>
            <div class="rooms-list">
                ${detail.kept_rooms.map((room, idx) => {
        return `<span class="room-tag kept" onclick="showRoomDetail('${escapeHtml(room)}', 'kept', event)">${escapeHtml(room)}</span>`;
    }).join('')}
            </div>
        </div>
    `;
}

function renderRoomsSection(detail) {
    let html = '';

    if (detail.kept_rooms_data && detail.kept_rooms_data.length > 0) {
        html += `
            <div class="rooms-section">
                <div class="rooms-header">
                    <span class="rooms-label">Active Rooms (Optimized)</span>
                    <span class="rooms-count">${detail.kept_rooms_data.length}</span>
                </div>
                <div class="rooms-list">
                    ${detail.kept_rooms_data.map(room => `
                        <span class="room-tag kept" onclick="showRoomDetail('${escapeHtml(room.name)}', 'kept', event)">${escapeHtml(room.name)}</span>
                    `).join('')}
                </div>
            </div>
        `;
    }

    if (detail.removed_rooms_data && detail.removed_rooms_data.length > 0) {
        html += `
            <div class="rooms-section">
                <div class="rooms-header">
                    <span class="rooms-label">Removed Rooms (Merged)</span>
                    <span class="rooms-count">${detail.removed_rooms_data.length}</span>
                </div>
                <div class="rooms-list">
                    ${detail.removed_rooms_data.map(room => `
                        <span class="room-tag removed" onclick="showRoomDetail('${escapeHtml(room.name)}', 'removed', event)">${escapeHtml(room.name)}</span>
                    `).join('')}
                </div>
            </div>
        `;
    }

    return html;
}

// Room detail popup (shown on room tag click)
let currentRoomPopup = null;

// Helper to get consistent course name based on room
// Removed getDeterministicCourse and getDeterministicCount as we now use real data


function showRoomDetail(roomName, type, event) {
    // Stop event propagation
    event.stopPropagation();

    // Remove existing popup
    if (currentRoomPopup) {
        currentRoomPopup.remove();
        currentRoomPopup = null;
    }

    // Find the data
    const card = event.target.closest('.detail-card');
    let roomData = null;
    if (card && card.dataset.detailData) {
        const detail = JSON.parse(card.dataset.detailData);
        if (type === 'kept') {
            roomData = detail.kept_rooms_data.find(r => r.name === roomName);
        } else {
            roomData = detail.removed_rooms_data.find(r => r.name === roomName);
        }
    }

    if (!roomData) return;

    // Use actual data
    const courseName = roomData.subject || 'Unknown Subject';
    const currentStudents = roomData.students || 0;
    const capacity = roomData.capacity || 0;

    // Logic for Merge Data
    let mergeInfoHtml = '';
    let utilizationStr = '';

    // Utilization calculation
    const utilizationVal = capacity > 0 ? Math.round((currentStudents / capacity) * 100) : 0;

    if (type === 'kept') {
        utilizationStr = `${utilizationVal}%`;

        let sourcesHtml = '';
        if (roomData.merged_sources && roomData.merged_sources.length > 0) {
            sourcesHtml = roomData.merged_sources.map(src => `
                <div class="student-item" style="background: #f0fdf4; color: #15803d;">
                    ${escapeHtml(src.subject)} (${src.room}) - ${src.students} students
                </div>
            `).join('');

            const addedStudents = roomData.merged_sources.reduce((sum, src) => sum + (src.students || 0), 0);
            const originalStudents = currentStudents - addedStudents; // Approximate if total is sum

            mergeInfoHtml = `
                <div class="merge-stats-container" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #e6f3fb;">
                    <div class="student-list-title" style="color: #04249c;">Merge Impact Analysis</div>
                    <div class="room-detail-row">
                        <span class="room-detail-label">Current Total:</span>
                        <span class="room-detail-value">${currentStudents} students</span>
                    </div>
                     <div class="room-detail-row">
                        <span class="room-detail-label">Original (Est):</span>
                        <span class="room-detail-value">${originalStudents} students</span>
                    </div>
                    <div class="room-detail-row">
                        <span class="room-detail-label">Merged In:</span>
                        <span class="room-detail-value">+${addedStudents} students</span>
                    </div>
                    
                    <div class="student-list-title" style="margin-top: 8px;">Classes in this Room:</div>
                    <div class="student-item" style="background: #e6f3fb; color: #04249c;">
                        ${escapeHtml(courseName)} (Host)
                    </div>
                    ${sourcesHtml}
                </div>
            `;
        } else {
            mergeInfoHtml = `
                <div class="merge-stats-container" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #e6f3fb;">
                    <div class="student-item" style="background: #e6f3fb; color: #04249c;">
                        ${escapeHtml(courseName)} (No Merges) - ${currentStudents} students
                    </div>
                </div>
            `;
        }
    } else {
        // Removed room logic
        utilizationStr = `${utilizationVal}% (Before Move)`;
        const targetRoom = roomData.merged_to || 'Unknown';

        mergeInfoHtml = `
             <div class="merge-stats-container" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #ffe6e6;">
                <div class="student-list-title" style="color: #cc0000;">Merge Status</div>
                <div class="student-item" style="background: #ffe6e6; color: #cc0000; border: 1px solid #ffcccc;">
                    Merged into: <strong>${escapeHtml(targetRoom)}</strong>
                </div>
                <div class="room-detail-row" style="margin-top: 8px;">
                    <span class="room-detail-label">Original Count:</span>
                    <span class="room-detail-value">${currentStudents} students</span>
                </div>
             </div>
        `;
    }

    // Create popup
    const popup = document.createElement('div');
    popup.className = 'room-detail-popup';
    popup.innerHTML = `
        <div class="room-detail-header" style="display:flex; justify-content:space-between; align-items:center;">
            <span>${escapeHtml(roomName)}</span>
            <span style="font-size: 10px; padding: 2px 6px; border-radius: 4px; background: ${type === 'kept' ? '#e6f3fb' : '#ffe6e6'}; color: ${type === 'kept' ? '#04249c' : '#cc0000'};">
                ${type === 'kept' ? 'Active' : 'Removed'}
            </span>
        </div>
        <div class="room-detail-info">
            <div class="room-detail-row">
                <span class="room-detail-label">Course:</span>
                <span class="room-detail-value" style="font-weight:700;">${escapeHtml(courseName)}</span>
            </div>
            <div class="room-detail-row">
                <span class="room-detail-label">Students:</span>
                <span class="room-detail-value">${currentStudents}</span>
            </div>
            <div class="room-detail-row">
                <span class="room-detail-label">Capacity:</span>
                <span class="room-detail-value">${capacity}</span>
            </div>
            <div class="room-detail-row">
                <span class="room-detail-label">Utilization:</span>
                <span class="room-detail-value">${utilizationStr}</span>
            </div>
        </div>
        ${mergeInfoHtml}
    `;

    // Position popup near the clicked element
    const rect = event.target.getBoundingClientRect();
    popup.style.position = 'fixed';
    popup.style.left = `${rect.left}px`;
    popup.style.top = `${rect.bottom + 5}px`;

    // Prevent popup from being cut off at screen edges
    setTimeout(() => {
        const popupRect = popup.getBoundingClientRect();
        if (popupRect.right > window.innerWidth) {
            popup.style.left = `${window.innerWidth - popupRect.width - 10}px`;
        }
        if (popupRect.bottom > window.innerHeight) {
            popup.style.top = `${rect.top - popupRect.height - 5}px`;
        }
    }, 0);

    document.body.appendChild(popup);
    currentRoomPopup = popup;

    // Close popup when clicking outside or scrolling
    setTimeout(() => {
        document.addEventListener('click', closeRoomPopup, true);
        window.addEventListener('scroll', closeRoomPopup, true);
    }, 100);
}

function closeRoomPopup(e) {
    if (currentRoomPopup && (!e.target || !currentRoomPopup.contains(e.target))) {
        currentRoomPopup.remove();
        currentRoomPopup = null;
        document.removeEventListener('click', closeRoomPopup, true);
        window.removeEventListener('scroll', closeRoomPopup, true);
    }
}

function renderNoChanges() {
    return `
        <div class="no-changes">
            All rooms kept - No merging possible for this shift and campus
        </div>
    `;
}

function showError(message) {
    hide('uploadSection');
    hide('processSection');
    hide('resultsSection');
    show('errorSection');
    document.getElementById('errorMessage').textContent = message;

    document.getElementById('errorSection').scrollIntoView({
        behavior: 'smooth',
        block: 'center'
    });
}

function resetApp() {
    // Reset state
    appState = {
        uploadedFile: null,
        filepath: null,
        results: null
    };

    // Reset file input
    document.getElementById('fileInput').value = '';

    // Reset UI - show upload area, hide file info
    show('uploadArea');
    hide('fileInfo');

    // Hide new upload button
    document.getElementById('newUploadBtn').classList.add('hidden');

    // Show upload section, hide others
    show('uploadSection');
    hide('processSection');
    hide('resultsSection');
    hide('errorSection');

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Utility functions
function show(elementId) {
    document.getElementById(elementId).classList.remove('hidden');
}

function hide(elementId) {
    document.getElementById(elementId).classList.add('hidden');
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Modal and Detail Functions
function showMergeDetail(detailId) {
    // Create modal if it doesn't exist
    let modal = document.getElementById('mergeDetailModal');
    if (!modal) {
        modal = createMergeModal();
        document.body.appendChild(modal);
    }

    // Extract shift and campus from ID (format: detail-Shift-Campus)
    // But better: retrieve the data directly relative to the clicked button
    // Find the button that triggered this
    const btn = document.querySelector(`button[onclick="showMergeDetail('${detailId}')"]`);
    const card = btn ? btn.closest('.detail-card') : null;

    let detailData = null;
    if (card && card.dataset.detailData) {
        try {
            detailData = JSON.parse(card.dataset.detailData);
        } catch (e) {
            console.error("Error parsing detail data", e);
        }
    }

    if (!detailData) return;

    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');

    modalTitle.textContent = `Shift ${detailData.shift} - Campus ${detailData.campus} Details`;

    // Generate explanation based on REAL data
    const removedRooms = detailData.removed_rooms_data || [];
    const removedCount = removedRooms.length;
    const keptCount = detailData.kept_rooms ? detailData.kept_rooms.length : 0;

    let htmlContent = `
        <div class="merge-explanation">
            <h4 style="margin-bottom: 1rem; color: #04249c;">Optimization Summary:</h4>
            <p style="margin-bottom: 1rem;">
                In this shift, <strong style="color: #d97706">${removedCount} rooms</strong> were consolidated into 
                <strong style="color: #059669">${keptCount} active rooms</strong> to improve efficiency.
            </p>
    `;

    if (removedCount > 0) {
        htmlContent += `<h5 style="margin-bottom: 0.5rem; color: #04249c;">Merged Rooms (Sources):</h5>`;
        removedRooms.forEach(room => {
            // Find a target room
            const targetRoom = room.merged_to || 'Unknown';
            const students = room.students || 0;
            const capacity = room.capacity || 0;
            const percentage = capacity > 0 ? Math.round((students / capacity) * 100) : 0;

            htmlContent += `
                <div class="merge-item">
                    <div class="merge-item-header">${escapeHtml(room.name)} <span class="merge-arrow">→</span> ${escapeHtml(targetRoom)}</div>
                    <div class="merge-item-detail">
                        ${escapeHtml(room.subject)} (${students} students, Cap: ${capacity})
                        <br/>
                        Was ${percentage}% utilized. Moved to improve density.
                    </div>
                </div>
            `;
        });
    } else {
        htmlContent += `<p class="no-changes-text">No rooms were removed in this shift. Utilization is already optimal.</p>`;
    }

    htmlContent += `</div>`;
    modalBody.innerHTML = htmlContent;

    modal.classList.remove('hidden');
}

// Removed getDeterministicCount


function createMergeModal() {
    const modal = document.createElement('div');
    modal.id = 'mergeDetailModal';
    modal.className = 'modal-overlay hidden';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title" id="modalTitle">Merge Details</h3>
                <button class="modal-close" onclick="closeMergeModal()">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                    </svg>
                </button>
            </div>
            <div class="modal-body" id="modalBody"></div>
        </div>
    `;

    // Close on overlay click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeMergeModal();
        }
    });

    return modal;
}

function closeMergeModal() {
    const modal = document.getElementById('mergeDetailModal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// Room detail popup (shown on room tag click)
// End of file cleanup

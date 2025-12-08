/**
 * Soccer Rig Web UI
 * Mobile-friendly interface for camera control
 */

class SoccerRigApp {
    constructor() {
        this.apiBase = '/api/v1';
        this.cameras = new Map();
        this.isRecording = false;
        this.recordingStartTime = null;
        this.timerInterval = null;
        this.statusInterval = null;
        this.previewInterval = null;

        this.init();
    }

    async init() {
        this.bindEvents();
        await this.loadStatus();
        this.startStatusPolling();
        this.startPreviewRefresh();
    }

    bindEvents() {
        // Recording controls
        document.getElementById('start-all-btn').addEventListener('click', () => this.startRecording());
        document.getElementById('stop-all-btn').addEventListener('click', () => this.stopRecording());

        // Quick actions
        document.getElementById('test-btn').addEventListener('click', () => this.runTest());
        document.getElementById('sync-btn').addEventListener('click', () => this.triggerSync());
        document.getElementById('recordings-btn').addEventListener('click', () => this.showRecordings());

        // Settings
        document.getElementById('settings-btn').addEventListener('click', () => this.showSettings());
        document.getElementById('close-settings').addEventListener('click', () => this.hideModal('settings-modal'));
        document.getElementById('save-settings-btn').addEventListener('click', () => this.saveSettings());
        document.getElementById('check-update-btn').addEventListener('click', () => this.checkUpdates());
        document.getElementById('reboot-btn').addEventListener('click', () => this.reboot());
        document.getElementById('shutdown-btn').addEventListener('click', () => this.shutdown());

        // Recordings modal
        document.getElementById('close-recordings').addEventListener('click', () => this.hideModal('recordings-modal'));
        document.getElementById('refresh-recordings-btn').addEventListener('click', () => this.loadRecordings());
        document.getElementById('cleanup-btn').addEventListener('click', () => this.cleanupRecordings());

        // Close modals on backdrop click
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hideModal(modal.id);
                }
            });
        });
    }

    // API Methods
    async apiCall(endpoint, method = 'GET', data = null) {
        try {
            const options = {
                method,
                headers: {
                    'Content-Type': 'application/json',
                },
            };

            if (data) {
                options.body = JSON.stringify(data);
            }

            const response = await fetch(`${this.apiBase}${endpoint}`, options);
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || 'Request failed');
            }

            return result;
        } catch (error) {
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        }
    }

    // Status Management
    async loadStatus() {
        try {
            const status = await this.apiCall('/status');
            this.updateUI(status);
        } catch (error) {
            this.showToast('Failed to load status', 'error');
        }
    }

    startStatusPolling() {
        this.statusInterval = setInterval(() => this.loadStatus(), 2000);
    }

    updateUI(status) {
        // Update version
        document.getElementById('version').textContent = `v${status.node?.version || '1.0.0'}`;

        // Update sync indicator
        const syncDot = document.querySelector('.sync-dot');
        const syncStatus = status.sync;
        if (syncStatus) {
            syncDot.classList.remove('warning', 'error');
            if (!syncStatus.within_tolerance) {
                syncDot.classList.add('warning');
            }
            if (syncStatus.confidence === 'error') {
                syncDot.classList.add('error');
            }
        }

        // Update camera cards
        this.updateCameraCard(status);

        // Update recording state
        const recording = status.recording;
        if (recording && recording.is_recording !== this.isRecording) {
            this.isRecording = recording.is_recording;
            this.updateRecordingState();
        }
    }

    updateCameraCard(status) {
        const grid = document.getElementById('camera-grid');
        const cameraId = status.node?.camera_id || 'Unknown';

        // Find or create camera card
        let card = document.getElementById(`camera-${cameraId}`);
        if (!card) {
            card = this.createCameraCard(cameraId, status.node?.camera_position);
            grid.appendChild(card);
        }

        // Update card data
        const camera = status.camera || {};
        const recording = status.recording || {};
        const storage = status.storage || {};
        const system = status.system || {};
        const sync = status.sync || {};

        // Update status
        const statusDot = card.querySelector('.status-dot');
        const statusText = card.querySelector('.camera-status span:last-child');
        statusDot.classList.remove('recording', 'offline');

        if (recording.is_recording) {
            statusDot.classList.add('recording');
            statusText.textContent = 'Recording';
            card.classList.add('recording');
        } else if (!camera.detected) {
            statusDot.classList.add('offline');
            statusText.textContent = 'Offline';
            card.classList.add('offline');
            card.classList.remove('recording');
        } else {
            statusText.textContent = 'Ready';
            card.classList.remove('recording', 'offline');
        }

        // Update stats
        this.updateStat(card, 'resolution', camera.resolution || 'N/A');
        this.updateStat(card, 'fps', `${camera.fps || 0} fps`);
        this.updateStat(card, 'codec', camera.codec?.toUpperCase() || 'N/A');
        this.updateStat(card, 'bitrate', `${camera.bitrate_mbps || 0} Mbps`);

        const tempValue = card.querySelector('[data-stat="temp"] .stat-value');
        if (tempValue) {
            const temp = system.temperature_c || 0;
            tempValue.textContent = `${temp.toFixed(1)}°C`;
            tempValue.classList.toggle('warning', temp > 70);
            tempValue.classList.toggle('danger', temp > 80);
        }

        const storageValue = card.querySelector('[data-stat="storage"] .stat-value');
        if (storageValue) {
            const freeGb = storage.free_gb || 0;
            storageValue.textContent = `${freeGb.toFixed(1)} GB`;
            storageValue.classList.toggle('warning', freeGb < 20);
            storageValue.classList.toggle('danger', freeGb < 10);
        }

        const syncValue = card.querySelector('[data-stat="sync"] .stat-value');
        if (syncValue) {
            const offsetMs = sync.offset_ms || 0;
            syncValue.textContent = `${offsetMs.toFixed(1)} ms`;
            syncValue.classList.toggle('warning', Math.abs(offsetMs) > 5);
        }

        const timeValue = card.querySelector('[data-stat="time"] .stat-value');
        if (timeValue) {
            const estMinutes = storage.estimated_recording_minutes || 0;
            timeValue.textContent = `${Math.floor(estMinutes)} min`;
        }
    }

    createCameraCard(cameraId, position) {
        const card = document.createElement('div');
        card.className = 'camera-card';
        card.id = `camera-${cameraId}`;

        const positionLabel = {
            'left': 'Left',
            'center': 'Center',
            'right': 'Right'
        }[position] || position;

        card.innerHTML = `
            <div class="camera-header">
                <div>
                    <div class="camera-id">${cameraId}</div>
                    <div class="camera-position">${positionLabel}</div>
                </div>
                <div class="camera-status">
                    <span class="status-dot"></span>
                    <span>Ready</span>
                </div>
            </div>
            <div class="camera-preview">
                <img src="/preview/snapshot" alt="Preview" onerror="this.style.display='none'">
                <div class="preview-placeholder">No Preview</div>
            </div>
            <div class="camera-stats">
                <div class="stat-item" data-stat="resolution">
                    <span class="stat-label">Resolution</span>
                    <span class="stat-value">N/A</span>
                </div>
                <div class="stat-item" data-stat="fps">
                    <span class="stat-label">Frame Rate</span>
                    <span class="stat-value">0 fps</span>
                </div>
                <div class="stat-item" data-stat="codec">
                    <span class="stat-label">Codec</span>
                    <span class="stat-value">N/A</span>
                </div>
                <div class="stat-item" data-stat="bitrate">
                    <span class="stat-label">Bitrate</span>
                    <span class="stat-value">0 Mbps</span>
                </div>
                <div class="stat-item" data-stat="temp">
                    <span class="stat-label">Temperature</span>
                    <span class="stat-value">0°C</span>
                </div>
                <div class="stat-item" data-stat="storage">
                    <span class="stat-label">Storage Free</span>
                    <span class="stat-value">0 GB</span>
                </div>
                <div class="stat-item" data-stat="sync">
                    <span class="stat-label">Sync Offset</span>
                    <span class="stat-value">0 ms</span>
                </div>
                <div class="stat-item" data-stat="time">
                    <span class="stat-label">Est. Time</span>
                    <span class="stat-value">0 min</span>
                </div>
            </div>
        `;

        return card;
    }

    updateStat(card, stat, value) {
        const elem = card.querySelector(`[data-stat="${stat}"] .stat-value`);
        if (elem) {
            elem.textContent = value;
        }
    }

    // Preview
    startPreviewRefresh() {
        this.previewInterval = setInterval(() => {
            document.querySelectorAll('.camera-preview img').forEach(img => {
                img.src = `/preview/snapshot?t=${Date.now()}`;
            });
        }, 1000);
    }

    // Recording Controls
    async startRecording() {
        const sessionInput = document.getElementById('session-id');
        let sessionId = sessionInput.value.trim();

        if (!sessionId) {
            sessionId = `SESSION_${this.formatTimestamp(new Date())}`;
            sessionInput.value = sessionId;
        }

        try {
            const result = await this.apiCall('/record/start', 'POST', {
                session_id: sessionId
            });

            if (result.success) {
                this.isRecording = true;
                this.recordingStartTime = new Date();
                this.updateRecordingState();
                this.showToast('Recording started', 'success');
            }
        } catch (error) {
            this.showToast(`Failed to start recording: ${error.message}`, 'error');
        }
    }

    async stopRecording() {
        if (!confirm('Stop recording on all cameras?')) {
            return;
        }

        try {
            const result = await this.apiCall('/record/stop', 'POST');

            if (result.success) {
                this.isRecording = false;
                this.updateRecordingState();
                this.showToast('Recording stopped', 'success');
            }
        } catch (error) {
            this.showToast(`Failed to stop recording: ${error.message}`, 'error');
        }
    }

    updateRecordingState() {
        const startBtn = document.getElementById('start-all-btn');
        const stopBtn = document.getElementById('stop-all-btn');
        const timerDiv = document.getElementById('recording-timer');

        if (this.isRecording) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            timerDiv.style.display = 'flex';
            this.startTimer();
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            timerDiv.style.display = 'none';
            this.stopTimer();
        }
    }

    startTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
        }

        this.timerInterval = setInterval(() => {
            if (!this.recordingStartTime) return;

            const elapsed = Math.floor((Date.now() - this.recordingStartTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const minutes = Math.floor((elapsed % 3600) / 60);
            const seconds = elapsed % 60;

            document.getElementById('timer-text').textContent =
                `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }, 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        this.recordingStartTime = null;
    }

    // Quick Actions
    async runTest() {
        this.showToast('Running test recording...', 'info');

        try {
            const result = await this.apiCall('/selftest', 'POST');

            if (result.passed) {
                this.showToast('Test passed!', 'success');
            } else {
                this.showToast(`Test failed: ${result.errors?.join(', ') || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            this.showToast(`Test failed: ${error.message}`, 'error');
        }
    }

    async triggerSync() {
        try {
            const result = await this.apiCall('/sync/trigger', 'POST');
            this.showToast('Sync triggered', 'success');
        } catch (error) {
            this.showToast(`Sync failed: ${error.message}`, 'error');
        }
    }

    // Recordings
    async showRecordings() {
        this.showModal('recordings-modal');
        await this.loadRecordings();
    }

    async loadRecordings() {
        const list = document.getElementById('recordings-list');
        list.innerHTML = '<div class="loading"></div>';

        try {
            const result = await this.apiCall('/recordings');
            const recordings = result.recordings || [];

            if (recordings.length === 0) {
                list.innerHTML = '<p style="color: var(--text-secondary)">No recordings found</p>';
                return;
            }

            list.innerHTML = recordings.map(rec => `
                <div class="recording-item">
                    <div class="recording-item-header">
                        <span class="recording-filename">${rec.filename}</span>
                        <span class="recording-badge ${rec.offloaded ? 'offloaded' : 'pending'}">
                            ${rec.offloaded ? 'Offloaded' : 'Pending'}
                        </span>
                    </div>
                    <div class="recording-details">
                        <span>${rec.size_mb} MB</span>
                        <span>${rec.duration_sec ? Math.floor(rec.duration_sec / 60) + ' min' : 'N/A'}</span>
                        <span>${rec.resolution || 'N/A'}</span>
                    </div>
                    <div class="recording-actions">
                        <a class="btn btn-small btn-secondary" href="/download/${rec.filename}" download>Download</a>
                        <button class="btn btn-small btn-danger" onclick="app.deleteRecording('${rec.id}')">Delete</button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            list.innerHTML = `<p style="color: var(--danger)">Error: ${error.message}</p>`;
        }
    }

    async deleteRecording(recordingId) {
        if (!confirm('Delete this recording?')) {
            return;
        }

        try {
            await this.apiCall(`/recordings/${recordingId}`, 'DELETE');
            this.showToast('Recording deleted', 'success');
            await this.loadRecordings();
        } catch (error) {
            this.showToast(`Failed to delete: ${error.message}`, 'error');
        }
    }

    async cleanupRecordings() {
        if (!confirm('Delete all offloaded recordings?')) {
            return;
        }

        try {
            const result = await this.apiCall('/recordings/cleanup', 'POST');
            this.showToast(`Deleted ${result.deleted_count} recordings, freed ${result.freed_mb} MB`, 'success');
            await this.loadRecordings();
        } catch (error) {
            this.showToast(`Cleanup failed: ${error.message}`, 'error');
        }
    }

    // Settings
    async showSettings() {
        try {
            const config = await this.apiCall('/config');

            document.getElementById('setting-codec').value = config.camera?.codec || 'h265';
            document.getElementById('setting-bitrate').value = config.camera?.bitrate_mbps || 30;
            document.getElementById('setting-audio').checked = config.camera?.audio_enabled || false;
            document.getElementById('setting-mode').value = config.production_mode ? 'production' : 'development';
            document.getElementById('setting-camera-id').value = config.camera?.id || 'CAM_C';
            document.getElementById('current-version').textContent = `Version: ${config.version || '1.0.0'}`;

            this.showModal('settings-modal');
        } catch (error) {
            this.showToast(`Failed to load settings: ${error.message}`, 'error');
        }
    }

    async saveSettings() {
        const settings = {
            camera: {
                codec: document.getElementById('setting-codec').value,
                bitrate_mbps: parseInt(document.getElementById('setting-bitrate').value),
                audio_enabled: document.getElementById('setting-audio').checked,
                id: document.getElementById('setting-camera-id').value,
            },
            production_mode: document.getElementById('setting-mode').value === 'production',
        };

        try {
            await this.apiCall('/config', 'POST', settings);
            this.showToast('Settings saved', 'success');
            this.hideModal('settings-modal');
        } catch (error) {
            this.showToast(`Failed to save settings: ${error.message}`, 'error');
        }
    }

    async checkUpdates() {
        try {
            const result = await this.apiCall('/update/check', 'POST');

            if (result.available) {
                if (confirm(`Update available: ${result.latest_version}\n\nApply update?`)) {
                    await this.applyUpdate();
                }
            } else {
                this.showToast('Already up to date', 'success');
            }
        } catch (error) {
            this.showToast(`Update check failed: ${error.message}`, 'error');
        }
    }

    async applyUpdate() {
        try {
            const result = await this.apiCall('/update/apply', 'POST');

            if (result.success) {
                this.showToast('Update applied, restarting...', 'success');
            } else {
                this.showToast(`Update failed: ${result.error}`, 'error');
            }
        } catch (error) {
            this.showToast(`Update failed: ${error.message}`, 'error');
        }
    }

    async reboot() {
        if (!confirm('Reboot this node?')) {
            return;
        }

        try {
            await this.apiCall('/reboot', 'POST');
            this.showToast('Rebooting...', 'info');
        } catch (error) {
            this.showToast(`Reboot failed: ${error.message}`, 'error');
        }
    }

    async shutdown() {
        if (!confirm('Shutdown this node?')) {
            return;
        }

        try {
            await this.apiCall('/shutdown', 'POST');
            this.showToast('Shutting down...', 'info');
        } catch (error) {
            this.showToast(`Shutdown failed: ${error.message}`, 'error');
        }
    }

    // Modal Helpers
    showModal(modalId) {
        document.getElementById(modalId).classList.add('active');
    }

    hideModal(modalId) {
        document.getElementById(modalId).classList.remove('active');
    }

    // Toast Notifications
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 5000);
    }

    // Utility
    formatTimestamp(date) {
        return date.toISOString()
            .replace(/[-:]/g, '')
            .replace('T', '_')
            .split('.')[0];
    }
}

// Initialize app
const app = new SoccerRigApp();

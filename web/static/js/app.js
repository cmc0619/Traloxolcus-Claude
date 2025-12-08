/**
 * Soccer Rig - Multi-Camera Control System
 *
 * Controls all 3 cameras from a single dashboard
 */

class SoccerRigApp {
    constructor() {
        this.apiBase = '/api/v1';
        this.isRecording = false;
        this.recordingStartTime = null;
        this.timerInterval = null;
        this.statusInterval = null;
        this.currentSession = null;
        this.cameras = {};
        this.preflightPassed = false;
        this.framingAssistActive = false;

        this.init();
    }

    async init() {
        this.bindEvents();
        await this.loadCoordinatorStatus();
        this.startStatusPolling();
    }

    bindEvents() {
        // Main record button
        document.getElementById('record-btn').addEventListener('click', () => this.toggleRecording());

        // Action buttons
        document.getElementById('preflight-btn').addEventListener('click', () => this.runPreflight());
        document.getElementById('framing-btn').addEventListener('click', () => this.toggleFramingAssist());
        document.getElementById('sync-btn').addEventListener('click', () => this.syncAll());
        document.getElementById('test-btn').addEventListener('click', () => this.testAll());
        document.getElementById('files-btn').addEventListener('click', () => this.showRecordings());

        // Settings
        document.getElementById('settings-btn').addEventListener('click', () => this.showSettings());
        document.getElementById('manage-peers-btn')?.addEventListener('click', () => this.showPeers());
        document.getElementById('add-peer-btn')?.addEventListener('click', () => this.addPeer());
        document.getElementById('rerun-preflight-btn')?.addEventListener('click', () => this.runPreflight());

        // Pre-flight banner
        document.getElementById('run-preflight-btn')?.addEventListener('click', () => this.runPreflight());

        // Close modals on backdrop
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hideModal(modal.id);
                }
            });
        });

        // System control buttons
        document.getElementById('reboot-all-btn')?.addEventListener('click', () => this.rebootAll());
        document.getElementById('shutdown-all-btn')?.addEventListener('click', () => this.shutdownAll());
        document.getElementById('cleanup-all-btn')?.addEventListener('click', () => this.cleanupOffloaded());

        // Recording tabs
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.filterRecordings(e.target.dataset.camera);
            });
        });
    }

    // =========================================================================
    // Status & Updates
    // =========================================================================

    async loadCoordinatorStatus() {
        try {
            const status = await this.apiCall('/coordinator/status');
            this.updateDashboard(status);
        } catch (error) {
            console.error('Failed to load status:', error);
            // Try local status as fallback
            try {
                const localStatus = await this.apiCall('/status');
                this.updateLocalOnly(localStatus);
            } catch (e) {
                this.showToast('Failed to connect to camera', 'error');
            }
        }
    }

    startStatusPolling() {
        this.statusInterval = setInterval(() => this.loadCoordinatorStatus(), 2000);
    }

    updateDashboard(status) {
        const summary = status.summary || {};
        const cameras = status.cameras || [];
        const session = status.session || {};

        // Update system status badge
        const statusBadge = document.getElementById('system-status');
        if (session.status === 'recording') {
            statusBadge.textContent = 'RECORDING';
            statusBadge.className = 'status-badge recording';
            this.isRecording = true;
        } else if (summary.all_online) {
            statusBadge.textContent = 'Ready';
            statusBadge.className = 'status-badge ready';
            this.isRecording = false;
        } else {
            statusBadge.textContent = `${summary.cameras_online}/3 Online`;
            statusBadge.className = 'status-badge';
            this.isRecording = false;
        }

        // Update summary bar
        document.getElementById('cameras-online').textContent = `${summary.cameras_online || 0}/3`;
        document.getElementById('cameras-online').className =
            'summary-value ' + (summary.all_online ? 'success' : 'warning');

        const syncEl = document.getElementById('sync-status');
        syncEl.textContent = summary.all_synced ? 'OK' : 'Check';
        syncEl.className = 'summary-value ' + (summary.all_synced ? 'success' : 'warning');

        document.getElementById('total-storage').textContent = `${summary.total_storage_free_gb || 0} GB`;
        document.getElementById('est-time').textContent = `${summary.total_recording_minutes || 0} min`;

        // Update each camera card
        cameras.forEach(cam => this.updateCameraCard(cam));

        // Update record button state
        this.updateRecordButton(session.status === 'recording', session);

        // Show preflight warning if needed
        this.updatePreflightBanner(summary);
    }

    updateLocalOnly(status) {
        // Fallback when coordinator not available
        const node = status.node || {};
        const camera = status.camera || {};
        const recording = status.recording || {};

        document.getElementById('system-status').textContent = node.camera_id || 'Local';

        // Update just the local camera card
        const cameraId = node.camera_id;
        if (cameraId) {
            this.updateCameraCard({
                camera_id: cameraId,
                position: node.camera_position,
                status: recording.is_recording ? 'recording' : (camera.detected ? 'online' : 'offline'),
                is_local: true,
                camera: camera,
                recording: recording,
                storage: status.storage || {},
                sync: status.sync || {},
                system: status.system || {},
            });
        }
    }

    updateCameraCard(cam) {
        const card = document.getElementById(`camera-${cam.camera_id}`);
        if (!card) return;

        // Update status
        const statusDot = card.querySelector('.status-dot');
        const statusText = card.querySelector('.status-text');

        statusDot.className = 'status-dot ' + cam.status;
        statusText.textContent = this.capitalizeFirst(cam.status);

        card.className = 'camera-card ' + cam.status;

        // Update stats
        const system = cam.system || {};
        const storage = cam.storage || {};
        const sync = cam.sync || {};

        const tempEl = card.querySelector('[data-stat="temp"]');
        if (tempEl) {
            const temp = system.temperature_c || 0;
            tempEl.textContent = `${temp.toFixed(0)}°C`;
            tempEl.className = 'stat-value' + (temp > 70 ? ' warning' : '') + (temp > 80 ? ' danger' : '');
        }

        const storageEl = card.querySelector('[data-stat="storage"]');
        if (storageEl) {
            const free = storage.free_gb || 0;
            storageEl.textContent = `${free.toFixed(0)}GB`;
            storageEl.className = 'stat-value' + (free < 20 ? ' warning' : '') + (free < 10 ? ' danger' : '');
        }

        const syncEl = card.querySelector('[data-stat="sync"]');
        if (syncEl) {
            const offset = sync.offset_ms || 0;
            syncEl.textContent = `${offset.toFixed(1)}ms`;
            syncEl.className = 'stat-value' + (Math.abs(offset) > 5 ? ' warning' : '');
        }

        // Update framing status
        const framingEl = card.querySelector('[data-stat="framing"]');
        if (framingEl) {
            const framing = cam.framing || {};
            const status = framing.status || 'unknown';
            let displayText = '--';
            let className = 'stat-value';

            switch (status) {
                case 'excellent':
                    displayText = 'Excellent';
                    className = 'stat-value success';
                    break;
                case 'good':
                    displayText = 'Good';
                    className = 'stat-value success';
                    break;
                case 'partial':
                    displayText = 'Partial';
                    className = 'stat-value warning';
                    break;
                case 'no_field':
                    displayText = 'No Field';
                    className = 'stat-value danger';
                    break;
                default:
                    displayText = '--';
            }

            framingEl.textContent = displayText;
            framingEl.className = className;
        }

        // Update preview if camera has IP
        if (cam.ip && cam.ip !== 'localhost' && cam.status !== 'offline') {
            const preview = card.querySelector('.camera-preview');
            if (!preview.querySelector('img')) {
                preview.innerHTML = `<img src="http://${cam.ip}:${cam.port || 8080}/preview/snapshot"
                    onerror="this.style.display='none'; this.nextElementSibling.style.display='block';"
                    alt="Preview">
                    <div class="preview-placeholder" style="display:none">No Preview</div>`;
            }
        } else if (cam.is_local) {
            const preview = card.querySelector('.camera-preview');
            if (!preview.querySelector('img')) {
                preview.innerHTML = `<img src="/preview/snapshot"
                    onerror="this.style.display='none'; this.nextElementSibling.style.display='block';"
                    alt="Preview">
                    <div class="preview-placeholder" style="display:none">No Preview</div>`;
            }
        }

        // Store camera data
        this.cameras[cam.camera_id] = cam;
    }

    updateRecordButton(isRecording, session) {
        const btn = document.getElementById('record-btn');
        const recordText = btn.querySelector('.record-text');
        const recordSubtext = btn.querySelector('.record-subtext');
        const recordingInfo = document.getElementById('recording-info');

        if (isRecording) {
            btn.classList.add('recording');
            recordText.textContent = 'STOP RECORDING';
            recordSubtext.textContent = 'Tap to stop all cameras';
            recordingInfo.style.display = 'block';

            // Update session info
            document.getElementById('recording-session').textContent = session.id || '';

            // Start timer if not already running
            if (!this.timerInterval && session.started_at) {
                this.recordingStartTime = new Date(session.started_at);
                this.startTimer();
            }
        } else {
            btn.classList.remove('recording');
            recordText.textContent = 'START RECORDING';
            recordSubtext.textContent = 'All 3 Cameras';
            recordingInfo.style.display = 'none';
            this.stopTimer();
        }
    }

    updatePreflightBanner(summary) {
        const banner = document.getElementById('preflight-banner');
        const text = document.getElementById('preflight-text');

        if (!summary.all_online) {
            banner.style.display = 'block';
            text.textContent = `Only ${summary.cameras_online}/3 cameras online`;
        } else if (!summary.all_synced) {
            banner.style.display = 'block';
            text.textContent = 'Time sync check needed';
        } else if (!this.preflightPassed) {
            banner.style.display = 'block';
            text.textContent = 'Run pre-flight check before recording';
        } else {
            banner.style.display = 'none';
        }
    }

    // =========================================================================
    // Recording Control
    // =========================================================================

    async toggleRecording() {
        if (this.isRecording) {
            await this.stopRecording();
        } else {
            await this.startRecording();
        }
    }

    async startRecording() {
        // Confirmation
        const onlineCameras = Object.values(this.cameras).filter(c => c.status !== 'offline').length;
        if (onlineCameras < 3) {
            if (!confirm(`Only ${onlineCameras}/3 cameras online. Start recording anyway?`)) {
                return;
            }
        }

        const sessionInput = document.getElementById('session-id');
        let sessionId = sessionInput.value.trim();

        if (!sessionId) {
            sessionId = `GAME_${this.formatTimestamp(new Date())}`;
            sessionInput.value = sessionId;
        }

        this.showToast('Starting all cameras...', 'info');

        try {
            const result = await this.apiCall('/coordinator/start', 'POST', {
                session_id: sessionId
            });

            if (result.success) {
                this.showToast('Recording started on all cameras!', 'success');
                this.currentSession = sessionId;
            } else {
                this.showToast(`Some cameras failed: ${result.message}`, 'warning');
                // Show details
                console.log('Start results:', result.cameras);
            }
        } catch (error) {
            this.showToast(`Failed to start: ${error.message}`, 'error');
        }
    }

    async stopRecording() {
        if (!confirm('Stop recording on ALL cameras?')) {
            return;
        }

        this.showToast('Stopping all cameras...', 'info');

        try {
            const result = await this.apiCall('/coordinator/stop', 'POST');

            if (result.success) {
                this.showToast('Recording stopped on all cameras', 'success');
            } else {
                this.showToast(`Some cameras had issues: ${result.message}`, 'warning');
            }
        } catch (error) {
            this.showToast(`Failed to stop: ${error.message}`, 'error');
        }
    }

    startTimer() {
        if (this.timerInterval) return;

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
        document.getElementById('timer-text').textContent = '00:00:00';
    }

    // =========================================================================
    // Pre-flight Check
    // =========================================================================

    async runPreflight() {
        this.showModal('preflight-modal');

        const overall = document.getElementById('preflight-overall');
        const camerasDiv = document.getElementById('preflight-cameras');

        overall.className = 'preflight-overall';
        overall.innerHTML = '<span class="preflight-result">Running checks...</span>';
        camerasDiv.innerHTML = '<div class="loading">Checking all cameras...</div>';

        try {
            const result = await this.apiCall('/coordinator/preflight', 'POST');

            // Update overall status
            overall.className = 'preflight-overall ' + (result.passed ? 'passed' : 'failed');
            overall.innerHTML = `<span class="preflight-result">${result.passed ? '✓ ALL CHECKS PASSED' : '✗ CHECKS FAILED'}</span>`;

            // Update camera details
            camerasDiv.innerHTML = '';

            for (const [cameraId, camResult] of Object.entries(result.cameras || {})) {
                const camDiv = document.createElement('div');
                camDiv.className = 'preflight-camera';

                camDiv.innerHTML = `
                    <div class="preflight-camera-header">
                        <span class="preflight-camera-id">${cameraId} (${camResult.position})</span>
                        <span class="preflight-camera-status ${camResult.all_passed ? 'passed' : 'failed'}">
                            ${camResult.all_passed ? 'PASS' : 'FAIL'}
                        </span>
                    </div>
                    <div class="preflight-checks">
                        ${(camResult.checks || []).map(check => `
                            <div class="preflight-check-item">
                                <span>${check.name}: ${check.message}</span>
                                <span class="preflight-check-icon ${check.passed ? 'pass' : 'fail'}">
                                    ${check.passed ? '✓' : '✗'}
                                </span>
                            </div>
                        `).join('')}
                    </div>
                `;

                camerasDiv.appendChild(camDiv);
            }

            this.preflightPassed = result.passed;

            if (result.passed) {
                this.showToast('All pre-flight checks passed!', 'success');
            } else {
                this.showToast('Some checks failed - review issues', 'warning');
            }

        } catch (error) {
            overall.className = 'preflight-overall failed';
            overall.innerHTML = '<span class="preflight-result">Check Failed</span>';
            camerasDiv.innerHTML = `<p style="color: var(--danger)">Error: ${error.message}</p>`;
            this.showToast('Pre-flight check failed', 'error');
        }
    }

    // =========================================================================
    // Other Actions
    // =========================================================================

    async syncAll() {
        this.showToast('Syncing time on all cameras...', 'info');

        try {
            const result = await this.apiCall('/coordinator/sync', 'POST');

            if (result.success) {
                this.showToast('Time sync triggered on all cameras', 'success');
            } else {
                this.showToast('Some cameras failed to sync', 'warning');
            }
        } catch (error) {
            this.showToast(`Sync failed: ${error.message}`, 'error');
        }
    }

    async testAll() {
        if (!confirm('Run 10-second test recording on all cameras?')) {
            return;
        }

        this.showToast('Running test on all cameras...', 'info');

        try {
            const result = await this.apiCall('/coordinator/test', 'POST');

            if (result.all_passed) {
                this.showToast('All cameras passed test!', 'success');
            } else {
                const failed = Object.entries(result.cameras || {})
                    .filter(([_, r]) => !r.passed)
                    .map(([id]) => id);
                this.showToast(`Test failed on: ${failed.join(', ')}`, 'error');
            }
        } catch (error) {
            this.showToast(`Test failed: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Framing Assistance
    // =========================================================================

    async toggleFramingAssist() {
        const btn = document.getElementById('framing-btn');

        if (this.framingAssistActive) {
            // Stop framing assistance
            try {
                await this.apiCall('/framing/assist/stop', 'POST');
                this.framingAssistActive = false;
                btn.classList.remove('active');
                this.showToast('Framing assistance stopped', 'info');
            } catch (error) {
                this.showToast(`Failed to stop: ${error.message}`, 'error');
            }
        } else {
            // Start framing assistance
            try {
                const result = await this.apiCall('/framing/assist/start', 'POST');
                if (result.success) {
                    this.framingAssistActive = true;
                    btn.classList.add('active');
                    this.showToast('Framing assistance started - listen for audio cues', 'success');
                } else {
                    this.showToast(result.error || 'Failed to start framing assist', 'error');
                }
            } catch (error) {
                this.showToast(`Framing assist unavailable: ${error.message}`, 'warning');
            }
        }
    }

    async checkFraming() {
        try {
            const result = await this.apiCall('/framing/check', 'POST');
            const status = result.status || 'unknown';
            const message = result.message || '';

            if (status === 'good' || status === 'excellent') {
                this.showToast(`Framing: ${message}`, 'success');
            } else if (status === 'partial') {
                this.showToast(`Framing: ${message}`, 'warning');
            } else {
                this.showToast(`Framing: ${message}`, 'error');
            }

            return result;
        } catch (error) {
            this.showToast(`Framing check failed: ${error.message}`, 'error');
            return null;
        }
    }

    // =========================================================================
    // Recordings
    // =========================================================================

    async showRecordings() {
        this.showModal('recordings-modal');
        await this.loadRecordings();
    }

    async loadRecordings() {
        const list = document.getElementById('recordings-list');
        list.innerHTML = '<div class="loading">Loading recordings from all cameras...</div>';

        try {
            const result = await this.apiCall('/coordinator/recordings');
            this.allRecordings = result;
            this.filterRecordings('all');
        } catch (error) {
            list.innerHTML = `<p style="color: var(--danger)">Error: ${error.message}</p>`;
        }
    }

    filterRecordings(cameraFilter) {
        const list = document.getElementById('recordings-list');

        if (!this.allRecordings) {
            list.innerHTML = '<p>No recordings loaded</p>';
            return;
        }

        let html = '';

        for (const [cameraId, recordings] of Object.entries(this.allRecordings.cameras || {})) {
            if (cameraFilter !== 'all' && cameraFilter !== cameraId) continue;

            if (recordings.error) {
                html += `<div class="recording-item">
                    <span class="recording-camera">${cameraId}</span>
                    <span style="color: var(--danger)">Error: ${recordings.error}</span>
                </div>`;
                continue;
            }

            for (const rec of (recordings || [])) {
                const recId = rec.id || rec.filename;
                html += `
                    <div class="recording-item">
                        <div class="recording-header">
                            <span class="recording-camera">${cameraId}</span>
                            <span class="recording-filename">${rec.filename}</span>
                        </div>
                        <div class="recording-details">
                            <span>${rec.size_mb || 0} MB</span>
                            <span>${rec.duration_sec ? Math.floor(rec.duration_sec / 60) + ' min' : '--'}</span>
                            <span class="${rec.offloaded ? 'success' : 'warning'}">${rec.offloaded ? 'Offloaded' : 'Pending'}</span>
                        </div>
                        <div class="recording-actions">
                            <a class="btn btn-small btn-primary" href="${this.apiBase}/recordings/${encodeURIComponent(recId)}/download" download>Download</a>
                            <button class="btn btn-small btn-danger" onclick="app.deleteRecording('${recId}')">Delete</button>
                        </div>
                    </div>
                `;
            }
        }

        if (!html) {
            html = '<p style="color: var(--text-secondary)">No recordings found</p>';
        }

        list.innerHTML = html;
    }

    async deleteRecording(recordingId) {
        if (!confirm('Delete this recording permanently?')) return;

        try {
            await this.apiCall(`/recordings/${encodeURIComponent(recordingId)}`, 'DELETE');
            this.showToast('Recording deleted', 'success');
            await this.loadRecordings();
        } catch (error) {
            this.showToast(`Failed to delete: ${error.message}`, 'error');
        }
    }

    async cleanupOffloaded() {
        if (!confirm('Delete ALL offloaded recordings from this node? This frees up storage.')) return;

        this.showToast('Cleaning up offloaded recordings...', 'info');

        try {
            const result = await this.apiCall('/recordings/cleanup', 'POST');
            this.showToast(`Cleaned up ${result.deleted_count || 0} recordings, freed ${result.freed_mb || 0} MB`, 'success');
            await this.loadRecordings();
        } catch (error) {
            this.showToast(`Cleanup failed: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Peer Management
    // =========================================================================

    async showPeers() {
        this.hideModal('settings-modal');
        this.showModal('peers-modal');
        await this.loadPeers();
    }

    async loadPeers() {
        const list = document.getElementById('peer-list');

        try {
            const result = await this.apiCall('/coordinator/peers');
            const peers = result.peers || [];

            if (peers.length === 0) {
                list.innerHTML = '<p style="color: var(--text-secondary)">No cameras discovered</p>';
                return;
            }

            list.innerHTML = peers.map(peer => `
                <div class="peer-item">
                    <div class="peer-info">
                        <span class="peer-id">${peer.camera_id} ${peer.is_local ? '(this node)' : ''}</span>
                        <span class="peer-ip">${peer.ip}:${peer.port} - ${peer.status}</span>
                    </div>
                    ${!peer.is_local ? `<button class="btn btn-small btn-danger" onclick="app.removePeer('${peer.camera_id}')">Remove</button>` : ''}
                </div>
            `).join('');

        } catch (error) {
            list.innerHTML = `<p style="color: var(--danger)">Error: ${error.message}</p>`;
        }
    }

    async addPeer() {
        const cameraId = document.getElementById('add-peer-id').value;
        const ip = document.getElementById('add-peer-ip').value.trim();

        if (!ip) {
            this.showToast('Please enter an IP address', 'warning');
            return;
        }

        try {
            await this.apiCall('/coordinator/peers', 'POST', {
                camera_id: cameraId,
                ip: ip,
                port: 8080
            });

            this.showToast(`Added ${cameraId} at ${ip}`, 'success');
            document.getElementById('add-peer-ip').value = '';
            await this.loadPeers();
        } catch (error) {
            this.showToast(`Failed to add peer: ${error.message}`, 'error');
        }
    }

    async removePeer(cameraId) {
        if (!confirm(`Remove ${cameraId}?`)) return;

        try {
            await this.apiCall(`/coordinator/peers/${cameraId}`, 'DELETE');
            this.showToast(`Removed ${cameraId}`, 'success');
            await this.loadPeers();
        } catch (error) {
            this.showToast(`Failed to remove: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Settings
    // =========================================================================

    async showSettings() {
        this.showModal('settings-modal');

        try {
            const status = await this.apiCall('/status');
            const node = status.node || {};
            const network = status.network || {};

            document.getElementById('local-camera-id').textContent = node.camera_id || '--';
            document.getElementById('local-ip').textContent = network.ip_address || '--';
            document.getElementById('local-version').textContent = node.version || '1.0.0';
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    }

    async rebootAll() {
        if (!confirm('Reboot ALL camera nodes? This will interrupt any active recording!')) return;

        this.showToast('Sending reboot command to all nodes...', 'warning');

        // Send reboot command to all peers
        const peers = Object.values(this.cameras);
        for (const cam of peers) {
            try {
                if (cam.is_local) {
                    await this.apiCall('/reboot', 'POST');
                } else if (cam.ip) {
                    // Try to reach remote node
                    await fetch(`http://${cam.ip}:${cam.port || 8080}/api/v1/reboot`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' }
                    }).catch(() => {});
                }
            } catch (e) {
                console.error(`Failed to reboot ${cam.camera_id}:`, e);
            }
        }

        this.showToast('Reboot commands sent - nodes will restart shortly', 'info');
    }

    async shutdownAll() {
        if (!confirm('SHUTDOWN ALL camera nodes? You will need physical access to power them back on!')) return;
        if (!confirm('Are you SURE? This will power off all cameras!')) return;

        this.showToast('Sending shutdown command to all nodes...', 'warning');

        const peers = Object.values(this.cameras);
        for (const cam of peers) {
            try {
                if (cam.is_local) {
                    await this.apiCall('/shutdown', 'POST', { force: true });
                } else if (cam.ip) {
                    await fetch(`http://${cam.ip}:${cam.port || 8080}/api/v1/shutdown`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ force: true })
                    }).catch(() => {});
                }
            } catch (e) {
                console.error(`Failed to shutdown ${cam.camera_id}:`, e);
            }
        }

        this.showToast('Shutdown commands sent - nodes will power off shortly', 'info');
    }

    // =========================================================================
    // API & Utilities
    // =========================================================================

    async apiCall(endpoint, method = 'GET', data = null) {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' },
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
    }

    showModal(modalId) {
        document.getElementById(modalId).classList.add('active');
    }

    hideModal(modalId) {
        document.getElementById(modalId).classList.remove('active');
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => toast.remove(), 4000);
    }

    formatTimestamp(date) {
        return date.toISOString()
            .replace(/[-:]/g, '')
            .replace('T', '_')
            .split('.')[0];
    }

    capitalizeFirst(str) {
        return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
    }
}

// Initialize app
const app = new SoccerRigApp();

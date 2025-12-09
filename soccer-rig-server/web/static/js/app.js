/**
 * Soccer Rig Server - Analytics Dashboard v2.0
 * Modern dashboard with glassmorphism and dark mode
 */

class ServerDashboard {
    constructor() {
        this.apiBase = '/api/v1';
        this.currentSession = null;
        this.currentGameId = null;
        this.games = [];
        this.generatedClips = [];
        this.isDarkMode = false;
        this.init();
    }

    async init() {
        this.loadThemePreference();
        this.bindEvents();
        await this.checkHealth();
        await this.loadStats();
        await this.loadSessions();
        this.animateStatsOnLoad();
    }

    loadThemePreference() {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            this.setDarkMode(true);
        }
    }

    setDarkMode(enabled) {
        this.isDarkMode = enabled;
        document.documentElement.setAttribute('data-theme', enabled ? 'dark' : 'light');
        localStorage.setItem('theme', enabled ? 'dark' : 'light');
        const toggle = document.getElementById('theme-toggle');
        if (toggle) toggle.innerHTML = enabled ? '&#9728;' : '&#9790;';
    }

    toggleTheme() {
        this.setDarkMode(!this.isDarkMode);
    }

    animateStatsOnLoad() {
        const statValues = document.querySelectorAll('.stat-value');
        statValues.forEach(el => {
            const finalValue = el.textContent;
            if (finalValue && finalValue !== '--') {
                el.style.opacity = '0';
                el.style.transform = 'translateY(10px)';
                setTimeout(() => {
                    el.style.transition = 'all 0.5s ease';
                    el.style.opacity = '1';
                    el.style.transform = 'translateY(0)';
                }, 100);
            }
        });
    }

    bindEvents() {
        // Navigation tabs
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });

        // Refresh & Theme
        document.getElementById('refresh-btn').addEventListener('click', () => this.refresh());
        document.getElementById('theme-toggle')?.addEventListener('click', () => this.toggleTheme());

        // Sessions
        document.getElementById('complete-only')?.addEventListener('change', () => this.loadSessions());

        // Search
        document.getElementById('search-btn')?.addEventListener('click', () => this.executeSearch());
        document.getElementById('nl-search')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.executeSearch();
        });
        document.getElementById('nl-search')?.addEventListener('input', (e) => this.getSuggestions(e.target.value));

        // Game modal
        document.getElementById('delete-game-btn')?.addEventListener('click', () => this.deleteSession());
        document.getElementById('stitch-btn')?.addEventListener('click', () => this.triggerStitch());
        document.getElementById('analyze-btn')?.addEventListener('click', () => this.triggerAnalysis());

        // Game tabs
        document.querySelectorAll('.game-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchGameTab(tab.dataset.gtab));
        });

        // Players
        document.getElementById('add-player-btn')?.addEventListener('click', () => this.showModal('player-modal'));
        document.getElementById('save-player-btn')?.addEventListener('click', () => this.savePlayer());
        document.getElementById('roster-game')?.addEventListener('change', (e) => this.loadRoster(e.target.value));
        document.getElementById('export-stats-btn')?.addEventListener('click', () => this.exportStats());

        // Clips
        document.getElementById('generate-clip-btn')?.addEventListener('click', () => this.generateClip());
        document.getElementById('generate-highlight-btn')?.addEventListener('click', () => this.generateHighlight());
        document.getElementById('clip-game')?.addEventListener('change', (e) => this.loadPlayersForClip(e.target.value));

        // Heatmap
        document.getElementById('heatmap-player')?.addEventListener('change', () => this.drawHeatmap());
        document.getElementById('heatmap-type')?.addEventListener('change', () => this.drawHeatmap());

        // Modal backdrop close
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.hideModal(modal.id);
            });
        });
    }

    switchTab(tabName) {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelector(`[data-tab="${tabName}"]`)?.classList.add('active');
        document.getElementById(`tab-${tabName}`)?.classList.add('active');

        // Load data for specific tabs
        if (tabName === 'players' || tabName === 'clips') {
            this.populateGameSelects();
        }
    }

    switchGameTab(tabName) {
        document.querySelectorAll('.game-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.game-tab-content').forEach(c => c.classList.remove('active'));
        document.querySelector(`[data-gtab="${tabName}"]`)?.classList.add('active');
        document.getElementById(`gtab-${tabName}`)?.classList.add('active');

        if (tabName === 'heatmap') this.drawHeatmap();
        if (tabName === 'events') this.loadGameEvents();
        if (tabName === 'roster') this.loadModalRoster();
    }

    async refresh() {
        await this.checkHealth();
        await this.loadStats();
        await this.loadSessions();
    }

    async checkHealth() {
        try {
            const health = await this.apiCall('/health');
            document.getElementById('db-status')?.classList.toggle('online', true);
        } catch {
            document.getElementById('db-status')?.classList.add('offline');
        }

        try {
            const status = await this.apiCall('/analytics/status');
            const online = status.running && status.models_loaded;
            document.getElementById('analytics-status')?.classList.toggle('online', online);
            document.getElementById('analytics-status')?.classList.toggle('offline', !online);
        } catch {
            document.getElementById('analytics-status')?.classList.add('offline');
        }
    }

    // =========================================================================
    // Sessions/Games
    // =========================================================================

    async loadStats() {
        try {
            const stats = await this.apiCall('/stats');
            document.getElementById('session-count').textContent = stats.session_count || 0;
            document.getElementById('analyzed-count').textContent = stats.analyzed_count || 0;
            document.getElementById('event-count').textContent = stats.event_count || 0;
            document.getElementById('storage-used').textContent = `${(stats.total_size_gb || 0).toFixed(1)} GB`;
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    }

    async loadSessions() {
        const list = document.getElementById('sessions-list');
        list.innerHTML = '<p class="loading">Loading...</p>';

        try {
            const completeOnly = document.getElementById('complete-only')?.checked;
            const data = await this.apiCall(`/sessions?limit=50&complete=${completeOnly}`);
            this.games = data.sessions || [];

            if (this.games.length === 0) {
                list.innerHTML = '<div class="empty-state"><h3>No Games</h3><p>Recordings will appear when Pi nodes upload them.</p></div>';
                return;
            }

            list.innerHTML = this.games.map(s => this.renderSession(s)).join('');
            list.querySelectorAll('.session-item').forEach(item => {
                item.addEventListener('click', () => this.showSession(item.dataset.sessionId));
            });

        } catch (error) {
            list.innerHTML = `<p class="loading" style="color:var(--danger)">Error: ${error.message}</p>`;
        }
    }

    renderSession(session) {
        const date = new Date(session.created_at).toLocaleDateString();
        return `
            <div class="session-item" data-session-id="${session.id}">
                <div class="session-info">
                    <h3>${session.name || session.id}</h3>
                    <p>${date} - ${session.recording_count}/3 cameras - ${(session.total_size_mb || 0).toFixed(0)} MB</p>
                </div>
                <div class="session-badges">
                    ${session.analyzed ? '<span class="badge badge-info">Analyzed</span>' : ''}
                    ${session.stitched ? '<span class="badge badge-info">Stitched</span>' : ''}
                    <span class="badge ${session.complete ? 'badge-success' : 'badge-warning'}">${session.complete ? 'Complete' : 'Incomplete'}</span>
                </div>
            </div>
        `;
    }

    async showSession(sessionId) {
        try {
            const session = await this.apiCall(`/sessions/${sessionId}`);
            this.currentSession = session;
            this.currentGameId = session.game_id;

            document.getElementById('game-title').textContent = session.name || session.id;
            document.getElementById('game-overview').innerHTML = this.renderGameOverview(session);

            document.getElementById('stitch-btn').disabled = !session.complete || session.stitched;
            document.getElementById('analyze-btn').disabled = !session.complete;

            this.showModal('game-modal');
            this.switchGameTab('overview');

        } catch (error) {
            this.showToast(`Failed to load: ${error.message}`, 'error');
        }
    }

    renderGameOverview(session) {
        const recordings = Object.entries(session.recordings || {}).map(([cam, rec]) => `
            <div class="recording-item">
                <div><span class="camera-badge">${cam}</span> ${(rec.size_mb || 0).toFixed(0)} MB</div>
                <a href="/api/v1/sessions/${session.id}/download/${cam}" class="btn btn-small btn-secondary">Download</a>
            </div>
        `).join('');

        return `
            <div class="detail-section">
                <h3>Info</h3>
                <div class="detail-grid">
                    <div class="detail-item"><label>Created</label><span>${new Date(session.created_at).toLocaleString()}</span></div>
                    <div class="detail-item"><label>Size</label><span>${(session.total_size_mb || 0).toFixed(0)} MB</span></div>
                    <div class="detail-item"><label>Status</label><span>${session.complete ? 'Complete' : 'Incomplete'}</span></div>
                    <div class="detail-item"><label>Analyzed</label><span>${session.analyzed ? 'Yes' : 'No'}</span></div>
                </div>
            </div>
            <div class="detail-section">
                <h3>Recordings</h3>
                <div class="recording-list">${recordings || '<p>No recordings</p>'}</div>
            </div>
            ${session.stitched ? `
                <div class="detail-section">
                    <h3>Panorama</h3>
                    <a href="/api/v1/sessions/${session.id}/download/stitched" class="btn btn-primary">Download Panorama</a>
                </div>
            ` : ''}
        `;
    }

    async triggerStitch() {
        if (!this.currentSession) return;
        const btn = document.getElementById('stitch-btn');
        btn.disabled = true;
        btn.textContent = 'Processing...';

        try {
            const result = await this.apiCall(`/sessions/${this.currentSession.id}/stitch`, 'POST');
            this.showToast(`Stitch job queued: ${result.job_id}`, 'success');
            this.pollJob(result.job_id, () => {
                this.showToast('Stitching complete!', 'success');
                this.showSession(this.currentSession.id);
            });
        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = 'Stitch Panorama';
        }
    }

    async triggerAnalysis() {
        if (!this.currentSession) return;
        const btn = document.getElementById('analyze-btn');
        btn.disabled = true;
        btn.textContent = 'Analyzing...';

        try {
            const result = await this.apiCall(`/sessions/${this.currentSession.id}/analyze`, 'POST');
            this.showToast(`Analysis queued: ${result.job_id}`, 'success');
        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
        }
        btn.disabled = false;
        btn.textContent = 'Analyze Video';
    }

    async deleteSession() {
        if (!this.currentSession || !confirm('Delete this session?')) return;
        try {
            await this.apiCall(`/sessions/${this.currentSession.id}`, 'DELETE');
            this.showToast('Deleted', 'success');
            this.hideModal('game-modal');
            this.loadSessions();
        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Search
    // =========================================================================

    async executeSearch() {
        const query = document.getElementById('nl-search')?.value;
        if (!query) return;

        const gameId = document.getElementById('search-game')?.value;
        const resultsCard = document.getElementById('search-results-card');
        const resultsList = document.getElementById('search-results');

        resultsCard.style.display = 'block';
        resultsList.innerHTML = '<p class="loading">Searching...</p>';

        try {
            const data = await this.apiCall('/query', 'POST', { query, game_id: gameId || null });
            document.getElementById('result-count').textContent = `${data.count} results`;

            if (data.events.length === 0) {
                resultsList.innerHTML = '<p class="placeholder">No events found</p>';
                return;
            }

            resultsList.innerHTML = data.events.map(e => this.renderEvent(e)).join('');

        } catch (error) {
            resultsList.innerHTML = `<p class="placeholder" style="color:var(--danger)">${error.message}</p>`;
        }
    }

    async getSuggestions(partial) {
        if (partial.length < 2) {
            document.getElementById('search-suggestions').classList.remove('active');
            return;
        }

        try {
            const data = await this.apiCall(`/query/suggestions?q=${encodeURIComponent(partial)}`);
            const container = document.getElementById('search-suggestions');

            if (data.suggestions.length === 0) {
                container.classList.remove('active');
                return;
            }

            container.innerHTML = data.suggestions.map(s =>
                `<div class="search-suggestion" onclick="app.useSuggestion('${s}')">${s}</div>`
            ).join('');
            container.classList.add('active');

        } catch {
            document.getElementById('search-suggestions').classList.remove('active');
        }
    }

    useSuggestion(text) {
        document.getElementById('nl-search').value = text;
        document.getElementById('search-suggestions').classList.remove('active');
        this.executeSearch();
    }

    renderEvent(event) {
        const time = this.formatTime(event.timestamp_sec);
        const player = event.player ? `#${event.player.jersey_number} ${event.player.name || ''}` : '';
        return `
            <div class="event-item">
                <span class="event-time">${time}</span>
                <span class="event-type ${event.event_type}">${event.event_type.replace(/_/g, ' ')}</span>
                <span class="event-details">${player}</span>
                <span class="event-confidence">${((event.confidence || 1) * 100).toFixed(0)}%</span>
                <div class="event-actions">
                    <button class="btn btn-small btn-secondary" onclick="app.createClipForEvent(${event.timestamp_sec})">Clip</button>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Game Events
    // =========================================================================

    async loadGameEvents() {
        if (!this.currentGameId) return;
        const container = document.getElementById('game-events');
        container.innerHTML = '<p class="loading">Loading events...</p>';

        try {
            const data = await this.apiCall(`/games/${this.currentGameId}/events`);
            if (data.events.length === 0) {
                container.innerHTML = '<p class="placeholder">No events detected. Run analysis first.</p>';
                return;
            }
            container.innerHTML = data.events.map(e => this.renderEvent(e)).join('');
        } catch (error) {
            container.innerHTML = `<p class="placeholder">${error.message}</p>`;
        }
    }

    // =========================================================================
    // Roster Management
    // =========================================================================

    populateGameSelects() {
        const selects = ['roster-game', 'search-game', 'clip-game'];
        selects.forEach(id => {
            const select = document.getElementById(id);
            if (!select) return;
            const current = select.value;
            select.innerHTML = '<option value="">Select Game</option>' +
                this.games.map(g => `<option value="${g.game_id || g.id}">${g.name || g.id}</option>`).join('');
            select.value = current;
        });
    }

    async loadRoster(gameId) {
        const grid = document.getElementById('roster-grid');
        const statsCard = document.getElementById('player-stats-card');

        if (!gameId) {
            grid.innerHTML = '<p class="placeholder">Select a game to view roster</p>';
            statsCard.style.display = 'none';
            return;
        }

        grid.innerHTML = '<p class="loading">Loading...</p>';

        try {
            const data = await this.apiCall(`/games/${gameId}/players`);
            if (data.players.length === 0) {
                grid.innerHTML = '<p class="placeholder">No players added yet</p>';
                statsCard.style.display = 'none';
                return;
            }

            grid.innerHTML = data.players.map(p => `
                <div class="player-card ${p.is_goalkeeper ? 'goalkeeper' : ''}" onclick="app.showPlayerStats(${p.id}, ${gameId})">
                    <div class="player-number">${p.jersey_number || '?'}</div>
                    <div class="player-name">${p.name || 'Unknown'}</div>
                    <div class="player-position">${p.position || ''}</div>
                    <div class="player-team">${p.team || ''}</div>
                </div>
            `).join('');

        } catch (error) {
            grid.innerHTML = `<p class="placeholder">${error.message}</p>`;
        }
    }

    async loadModalRoster() {
        if (!this.currentGameId) return;
        const container = document.getElementById('modal-roster');
        await this.loadRosterInto(this.currentGameId, container);
    }

    async loadRosterInto(gameId, container) {
        try {
            const data = await this.apiCall(`/games/${gameId}/players`);
            if (data.players.length === 0) {
                container.innerHTML = '<p class="placeholder">No players. Add players in the Players tab.</p>';
                return;
            }
            container.innerHTML = '<div class="roster-grid">' + data.players.map(p => `
                <div class="player-card ${p.is_goalkeeper ? 'goalkeeper' : ''}">
                    <div class="player-number">${p.jersey_number || '?'}</div>
                    <div class="player-name">${p.name || 'Unknown'}</div>
                    <div class="player-position">${p.position || ''}</div>
                </div>
            `).join('') + '</div>';
        } catch {
            container.innerHTML = '<p class="placeholder">Failed to load roster</p>';
        }
    }

    async savePlayer() {
        const gameId = document.getElementById('roster-game')?.value;
        if (!gameId) {
            this.showToast('Select a game first', 'error');
            return;
        }

        const data = {
            name: document.getElementById('player-name')?.value,
            jersey_number: parseInt(document.getElementById('player-number')?.value) || null,
            team: document.getElementById('player-team')?.value,
            position: document.getElementById('player-position')?.value,
            is_goalkeeper: document.getElementById('player-is-gk')?.checked
        };

        try {
            await this.apiCall(`/games/${gameId}/players`, 'POST', data);
            this.showToast('Player added', 'success');
            this.hideModal('player-modal');
            this.loadRoster(gameId);

            // Clear form
            document.getElementById('player-name').value = '';
            document.getElementById('player-number').value = '';
        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
        }
    }

    async showPlayerStats(playerId, gameId) {
        const statsCard = document.getElementById('player-stats-card');
        const statsContainer = document.getElementById('player-stats');

        statsCard.style.display = 'block';
        statsContainer.innerHTML = '<p class="loading">Loading stats...</p>';

        try {
            const data = await this.apiCall(`/games/${gameId}/players/${playerId}/summary`);
            document.getElementById('player-stats-title').textContent =
                `${data.player.name || 'Player'} #${data.player.jersey_number || '?'}`;

            const counts = Object.entries(data.event_counts || {});
            if (counts.length === 0) {
                statsContainer.innerHTML = '<p class="placeholder">No events recorded for this player</p>';
                return;
            }

            statsContainer.innerHTML = '<div class="stat-card">' +
                counts.map(([type, count]) =>
                    `<div class="stat-row"><span class="stat-name">${type.replace(/_/g, ' ')}</span><span class="stat-value-small">${count}</span></div>`
                ).join('') +
                `<div class="stat-row"><span class="stat-name"><strong>Total</strong></span><span class="stat-value-small"><strong>${data.total_events}</strong></span></div>` +
                '</div>';

        } catch (error) {
            statsContainer.innerHTML = `<p class="placeholder">${error.message}</p>`;
        }
    }

    exportStats() {
        // Export current player stats as CSV
        const statsContainer = document.getElementById('player-stats');
        const rows = statsContainer.querySelectorAll('.stat-row');
        let csv = 'Event Type,Count\n';
        rows.forEach(row => {
            const name = row.querySelector('.stat-name')?.textContent || '';
            const value = row.querySelector('.stat-value-small')?.textContent || '';
            csv += `"${name}",${value}\n`;
        });

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'player_stats.csv';
        a.click();
    }

    // =========================================================================
    // Heatmap
    // =========================================================================

    drawHeatmap() {
        const canvas = document.getElementById('heatmap-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        // Create gradient for the field
        const fieldGradient = ctx.createLinearGradient(0, 0, w, h);
        fieldGradient.addColorStop(0, '#1a5c2e');
        fieldGradient.addColorStop(0.5, '#228b22');
        fieldGradient.addColorStop(1, '#1a5c2e');

        ctx.fillStyle = fieldGradient;
        ctx.fillRect(0, 0, w, h);

        // Draw grass stripes
        ctx.fillStyle = 'rgba(255,255,255,0.03)';
        for (let i = 0; i < 16; i++) {
            if (i % 2 === 0) {
                ctx.fillRect(50 * i, 0, 50, h);
            }
        }

        // Field lines
        ctx.strokeStyle = 'rgba(255,255,255,0.9)';
        ctx.lineWidth = 2.5;
        ctx.lineCap = 'round';

        const margin = 40;
        const fieldW = w - margin * 2;
        const fieldH = h - margin * 2;

        // Outer boundary
        ctx.strokeRect(margin, margin, fieldW, fieldH);

        // Center line
        ctx.beginPath();
        ctx.moveTo(w / 2, margin);
        ctx.lineTo(w / 2, h - margin);
        ctx.stroke();

        // Center circle
        ctx.beginPath();
        ctx.arc(w / 2, h / 2, 65, 0, Math.PI * 2);
        ctx.stroke();

        // Center spot
        ctx.beginPath();
        ctx.arc(w / 2, h / 2, 4, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.9)';
        ctx.fill();

        // Penalty areas
        const penaltyW = 130;
        const penaltyH = 260;
        const penaltyY = (h - penaltyH) / 2;
        ctx.strokeRect(margin, penaltyY, penaltyW, penaltyH);
        ctx.strokeRect(w - margin - penaltyW, penaltyY, penaltyW, penaltyH);

        // Goal areas (6-yard box)
        const goalAreaW = 50;
        const goalAreaH = 130;
        const goalAreaY = (h - goalAreaH) / 2;
        ctx.strokeRect(margin, goalAreaY, goalAreaW, goalAreaH);
        ctx.strokeRect(w - margin - goalAreaW, goalAreaY, goalAreaW, goalAreaH);

        // Penalty spots
        ctx.beginPath();
        ctx.arc(margin + 100, h / 2, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(w - margin - 100, h / 2, 4, 0, Math.PI * 2);
        ctx.fill();

        // Penalty arcs
        ctx.beginPath();
        ctx.arc(margin + 100, h / 2, 70, -0.65, 0.65);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(w - margin - 100, h / 2, 70, Math.PI - 0.65, Math.PI + 0.65);
        ctx.stroke();

        // Corner arcs
        ctx.beginPath();
        ctx.arc(margin, margin, 12, 0, Math.PI / 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(w - margin, margin, 12, Math.PI / 2, Math.PI);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(margin, h - margin, 12, -Math.PI / 2, 0);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(w - margin, h - margin, 12, Math.PI, Math.PI * 1.5);
        ctx.stroke();

        // Goals
        const goalW = 10;
        const goalH = 70;
        const goalY = (h - goalH) / 2;

        // Goal nets gradient
        const leftGoalGradient = ctx.createLinearGradient(20, goalY, 40, goalY);
        leftGoalGradient.addColorStop(0, 'rgba(255,255,255,0.6)');
        leftGoalGradient.addColorStop(1, 'rgba(255,255,255,0.2)');
        ctx.fillStyle = leftGoalGradient;
        ctx.fillRect(margin - goalW - 5, goalY, goalW + 5, goalH);

        const rightGoalGradient = ctx.createLinearGradient(w - 40, goalY, w - 20, goalY);
        rightGoalGradient.addColorStop(0, 'rgba(255,255,255,0.2)');
        rightGoalGradient.addColorStop(1, 'rgba(255,255,255,0.6)');
        ctx.fillStyle = rightGoalGradient;
        ctx.fillRect(w - margin, goalY, goalW + 5, goalH);

        // Goal posts
        ctx.strokeStyle = 'rgba(255,255,255,1)';
        ctx.lineWidth = 3;
        ctx.strokeRect(margin - goalW, goalY, goalW, goalH);
        ctx.strokeRect(w - margin, goalY, goalW, goalH);

        // Demo heatmap overlay (sample data points)
        this.drawSampleHeatmapData(ctx, w, h, margin);

        // Info text
        ctx.fillStyle = this.isDarkMode ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.7)';
        ctx.font = '13px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Run video analysis to populate position data', w / 2, h - 15);
    }

    drawSampleHeatmapData(ctx, w, h, margin) {
        // Generate sample heatmap points based on selected type
        const type = document.getElementById('heatmap-type')?.value || 'positions';

        // Sample data points for demonstration
        const samplePoints = [];

        if (type === 'positions') {
            // Midfielder positions (center)
            for (let i = 0; i < 30; i++) {
                samplePoints.push({
                    x: w / 2 + (Math.random() - 0.5) * 200,
                    y: h / 2 + (Math.random() - 0.5) * 200,
                    intensity: Math.random() * 0.5 + 0.3
                });
            }
        } else if (type === 'passes') {
            // Pass origins
            for (let i = 0; i < 20; i++) {
                samplePoints.push({
                    x: margin + 150 + Math.random() * 300,
                    y: h / 2 + (Math.random() - 0.5) * 250,
                    intensity: Math.random() * 0.6 + 0.4
                });
            }
        } else if (type === 'shots') {
            // Shot positions (near goal)
            for (let i = 0; i < 12; i++) {
                samplePoints.push({
                    x: w - margin - 200 + Math.random() * 100,
                    y: h / 2 + (Math.random() - 0.5) * 180,
                    intensity: Math.random() * 0.7 + 0.3
                });
            }
        }

        // Draw heatmap points with gradient
        samplePoints.forEach(point => {
            const gradient = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, 50);

            if (type === 'shots') {
                gradient.addColorStop(0, `rgba(239, 68, 68, ${point.intensity})`);
                gradient.addColorStop(0.5, `rgba(239, 68, 68, ${point.intensity * 0.3})`);
                gradient.addColorStop(1, 'rgba(239, 68, 68, 0)');
            } else if (type === 'passes') {
                gradient.addColorStop(0, `rgba(59, 130, 246, ${point.intensity})`);
                gradient.addColorStop(0.5, `rgba(59, 130, 246, ${point.intensity * 0.3})`);
                gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');
            } else {
                gradient.addColorStop(0, `rgba(245, 158, 11, ${point.intensity})`);
                gradient.addColorStop(0.5, `rgba(245, 158, 11, ${point.intensity * 0.3})`);
                gradient.addColorStop(1, 'rgba(245, 158, 11, 0)');
            }

            ctx.fillStyle = gradient;
            ctx.beginPath();
            ctx.arc(point.x, point.y, 50, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    // =========================================================================
    // Clips
    // =========================================================================

    async loadPlayersForClip(gameId) {
        const select = document.getElementById('clip-player');
        select.innerHTML = '<option value="">All Players (event clip only)</option>';

        if (!gameId) return;

        try {
            const data = await this.apiCall(`/games/${gameId}/players`);
            data.players.forEach(p => {
                select.innerHTML += `<option value="${p.id}">#${p.jersey_number} ${p.name || ''}</option>`;
            });
        } catch {}
    }

    async generateClip() {
        const sessionId = document.getElementById('clip-game')?.value;
        const timestamp = parseFloat(document.getElementById('clip-timestamp')?.value);
        const before = parseFloat(document.getElementById('clip-before')?.value) || 5;
        const after = parseFloat(document.getElementById('clip-after')?.value) || 5;

        if (!sessionId || isNaN(timestamp)) {
            this.showToast('Select game and enter timestamp', 'error');
            return;
        }

        try {
            const result = await this.apiCall('/clips/generate', 'POST', {
                session_id: sessionId,
                timestamp,
                duration_before: before,
                duration_after: after
            });

            this.showToast('Clip generated!', 'success');
            this.addClipToList(result.clip_path, timestamp);

        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
        }
    }

    async generateHighlight() {
        const sessionId = document.getElementById('clip-game')?.value;
        const playerId = document.getElementById('clip-player')?.value;

        if (!sessionId || !playerId) {
            this.showToast('Select game and player', 'error');
            return;
        }

        try {
            const result = await this.apiCall('/clips/player-highlight', 'POST', {
                session_id: sessionId,
                player_id: parseInt(playerId),
                max_duration: 120
            });

            this.showToast(`Highlight created with ${result.events_included} events!`, 'success');
            this.addClipToList(result.clip_path, null, true);

        } catch (error) {
            this.showToast(`Failed: ${error.message}`, 'error');
        }
    }

    createClipForEvent(timestamp) {
        document.querySelector('[data-tab="clips"]')?.click();
        document.getElementById('clip-timestamp').value = timestamp;
    }

    addClipToList(path, timestamp, isHighlight = false) {
        const filename = path.split('/').pop();
        this.generatedClips.unshift({ path, filename, timestamp, isHighlight });
        this.renderClipsList();
    }

    renderClipsList() {
        const list = document.getElementById('clips-list');
        if (this.generatedClips.length === 0) {
            list.innerHTML = '<p class="placeholder">No clips generated yet</p>';
            return;
        }

        list.innerHTML = this.generatedClips.map(clip => `
            <div class="clip-item">
                <div class="clip-info">
                    <h4>${clip.isHighlight ? 'Player Highlight' : `Event @ ${this.formatTime(clip.timestamp)}`}</h4>
                    <p>${clip.filename}</p>
                </div>
                <a href="/api/v1/clips/${encodeURIComponent(clip.filename)}/download" class="btn btn-primary btn-small">Download</a>
            </div>
        `).join('');
    }

    // =========================================================================
    // Utilities
    // =========================================================================

    formatTime(seconds) {
        if (seconds === null || seconds === undefined) return '--:--';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    async pollJob(jobId, onComplete) {
        const check = async () => {
            try {
                const job = await this.apiCall(`/jobs/${jobId}`);
                if (job.status === 'completed') {
                    onComplete();
                } else if (job.status === 'failed') {
                    this.showToast(`Job failed: ${job.error}`, 'error');
                } else {
                    setTimeout(check, 3000);
                }
            } catch {}
        };
        setTimeout(check, 2000);
    }

    showModal(modalId) {
        document.getElementById(modalId)?.classList.add('active');
    }

    hideModal(modalId) {
        document.getElementById(modalId)?.classList.remove('active');
        if (modalId === 'game-modal') {
            this.currentSession = null;
            this.currentGameId = null;
        }
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    async apiCall(endpoint, method = 'GET', data = null) {
        const options = { method, headers: { 'Content-Type': 'application/json' } };
        if (data) options.body = JSON.stringify(data);

        const response = await fetch(`${this.apiBase}${endpoint}`, options);
        const result = await response.json();

        if (!response.ok) throw new Error(result.error || 'API error');
        return result;
    }
}

// Initialize
const app = new ServerDashboard();

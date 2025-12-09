/**
 * Soccer Rig Viewer Portal
 * End-user interface for watching games and searching
 */

class SoccerViewer {
    constructor() {
        this.apiBase = '/api/v1';
        this.isAuthenticated = false;
        this.teamCode = null;
        this.teamName = null;
        this.games = [];
        this.players = [];
        this.savedClips = [];
        this.currentVideo = null;
        this.clipStart = null;
        this.clipEnd = null;
        this.isDarkMode = false;

        this.init();
    }

    async init() {
        this.loadThemePreference();
        this.loadSavedClips();
        this.bindEvents();

        // Check if already authenticated
        const savedCode = localStorage.getItem('teamCode');
        if (savedCode) {
            await this.authenticate(savedCode, true);
        }
    }

    loadThemePreference() {
        const savedTheme = localStorage.getItem('viewerTheme');
        if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            this.setDarkMode(true);
        }
    }

    setDarkMode(enabled) {
        this.isDarkMode = enabled;
        document.documentElement.setAttribute('data-theme', enabled ? 'dark' : 'light');
        localStorage.setItem('viewerTheme', enabled ? 'dark' : 'light');
        const toggle = document.getElementById('theme-toggle');
        if (toggle) toggle.innerHTML = enabled ? '&#9728;' : '&#9790;';
    }

    loadSavedClips() {
        const saved = localStorage.getItem('savedClips');
        if (saved) {
            try {
                this.savedClips = JSON.parse(saved);
            } catch (e) {
                this.savedClips = [];
            }
        }
    }

    saveSavedClips() {
        localStorage.setItem('savedClips', JSON.stringify(this.savedClips));
    }

    bindEvents() {
        // Auth form
        document.getElementById('auth-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            const code = document.getElementById('team-code').value.trim();
            if (code) this.authenticate(code);
        });

        // Navigation
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });

        // Theme toggle
        document.getElementById('theme-toggle')?.addEventListener('click', () => {
            this.setDarkMode(!this.isDarkMode);
        });

        // Logout
        document.getElementById('logout-btn')?.addEventListener('click', () => this.logout());

        // Search
        document.getElementById('search-btn')?.addEventListener('click', () => this.executeSearch());
        document.getElementById('nl-search')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.executeSearch();
        });

        // Quick searches
        document.querySelectorAll('.quick-search').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById('nl-search').value = btn.dataset.query;
                this.executeSearch();
            });
        });

        // Video clip controls
        document.getElementById('clip-start-btn')?.addEventListener('click', () => this.markClipStart());
        document.getElementById('clip-end-btn')?.addEventListener('click', () => this.markClipEnd());
        document.getElementById('save-clip-btn')?.addEventListener('click', () => this.saveClip());
        document.getElementById('share-btn')?.addEventListener('click', () => this.showShareModal());

        // Share modal
        document.getElementById('copy-link-btn')?.addEventListener('click', () => this.copyShareLink());
        document.getElementById('share-sms')?.addEventListener('click', () => this.shareViaSMS());
        document.getElementById('share-email')?.addEventListener('click', () => this.shareViaEmail());
        document.getElementById('share-download')?.addEventListener('click', () => this.downloadClip());

        // Modal backdrop close
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.hideModal(modal.id);
            });
        });
    }

    // =========================================================================
    // Authentication
    // =========================================================================

    async authenticate(code, silent = false) {
        try {
            // Validate team code with server
            const response = await this.apiCall(`/viewer/auth?code=${encodeURIComponent(code)}`);

            if (response.valid) {
                this.isAuthenticated = true;
                this.teamCode = code;
                this.teamName = response.team_name || code;

                localStorage.setItem('teamCode', code);
                document.getElementById('team-name').textContent = this.teamName;

                document.getElementById('auth-gate').classList.add('hidden');
                document.getElementById('main-viewer').classList.remove('hidden');

                await this.loadGames();
                await this.loadPlayers();
                this.renderSavedClips();

                if (!silent) {
                    this.showToast(`Welcome, ${this.teamName}!`, 'success');
                }
            } else {
                if (!silent) {
                    this.showToast('Invalid team code', 'error');
                }
                localStorage.removeItem('teamCode');
            }
        } catch (error) {
            // For demo/development: allow any code
            console.warn('Auth API not available, using demo mode');
            this.isAuthenticated = true;
            this.teamCode = code;
            this.teamName = code.toUpperCase();

            localStorage.setItem('teamCode', code);
            document.getElementById('team-name').textContent = this.teamName;

            document.getElementById('auth-gate').classList.add('hidden');
            document.getElementById('main-viewer').classList.remove('hidden');

            await this.loadGames();
            await this.loadPlayers();
            this.renderSavedClips();

            if (!silent) {
                this.showToast(`Welcome, ${this.teamName}!`, 'success');
            }
        }
    }

    logout() {
        this.isAuthenticated = false;
        this.teamCode = null;
        this.teamName = null;
        localStorage.removeItem('teamCode');

        document.getElementById('auth-gate').classList.remove('hidden');
        document.getElementById('main-viewer').classList.add('hidden');
        document.getElementById('team-code').value = '';
    }

    // =========================================================================
    // Navigation
    // =========================================================================

    switchTab(tabName) {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

        document.querySelector(`[data-tab="${tabName}"]`)?.classList.add('active');
        document.getElementById(`tab-${tabName}`)?.classList.add('active');

        if (tabName === 'highlights') {
            this.renderSavedClips();
        }
    }

    // =========================================================================
    // Games
    // =========================================================================

    async loadGames() {
        const grid = document.getElementById('games-grid');
        grid.innerHTML = '<div class="loading">Loading games...</div>';

        try {
            const data = await this.apiCall('/sessions?limit=50&complete=true');
            this.games = data.sessions || [];

            if (this.games.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">&#9917;</div>
                        <h3>No games yet</h3>
                        <p>Games will appear here after they're recorded and processed</p>
                    </div>
                `;
                return;
            }

            grid.innerHTML = this.games.map(game => this.renderGameCard(game)).join('');

            // Bind click events
            grid.querySelectorAll('.game-card').forEach(card => {
                card.addEventListener('click', () => this.openVideo(card.dataset.sessionId));
            });

        } catch (error) {
            grid.innerHTML = `<div class="empty-state"><p>Error loading games: ${error.message}</p></div>`;
        }
    }

    renderGameCard(game) {
        const date = new Date(game.created_at).toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric'
        });
        const isNew = (Date.now() - new Date(game.created_at).getTime()) < 7 * 24 * 60 * 60 * 1000;

        return `
            <div class="game-card" data-session-id="${game.id}">
                <div class="game-thumbnail">
                    <div class="play-icon">&#9658;</div>
                    ${game.duration ? `<span class="game-duration">${this.formatDuration(game.duration)}</span>` : ''}
                </div>
                <div class="game-info">
                    <h3>${game.name || 'Game ' + game.id.slice(0, 8)}</h3>
                    <div class="game-meta">
                        <span>&#128197; ${date}</span>
                        <span>&#127909; ${game.recording_count || 0} cameras</span>
                    </div>
                    <div class="game-badges">
                        ${isNew ? '<span class="badge badge-new">New</span>' : ''}
                        ${game.analyzed ? '<span class="badge badge-highlights">Highlights</span>' : ''}
                    </div>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Players
    // =========================================================================

    async loadPlayers() {
        const grid = document.getElementById('players-grid');
        grid.innerHTML = '<div class="loading">Loading players...</div>';

        try {
            // Get players from all games
            const allPlayers = new Map();

            for (const game of this.games.slice(0, 5)) {
                try {
                    const data = await this.apiCall(`/games/${game.game_id || game.id}/players`);
                    for (const player of (data.players || [])) {
                        if (!allPlayers.has(player.jersey_number)) {
                            allPlayers.set(player.jersey_number, player);
                        }
                    }
                } catch (e) {
                    // Ignore individual game errors
                }
            }

            this.players = Array.from(allPlayers.values());

            if (this.players.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">&#128101;</div>
                        <h3>No players yet</h3>
                        <p>Player profiles will appear after roster is set up</p>
                    </div>
                `;
                return;
            }

            grid.innerHTML = this.players.map(player => this.renderPlayerCard(player)).join('');

            // Bind click events
            grid.querySelectorAll('.player-card').forEach(card => {
                card.addEventListener('click', () => this.openPlayerProfile(card.dataset.playerId));
            });

        } catch (error) {
            grid.innerHTML = `<div class="empty-state"><p>Error loading players</p></div>`;
        }
    }

    renderPlayerCard(player) {
        return `
            <div class="player-card ${player.is_goalkeeper ? 'goalkeeper' : ''}" data-player-id="${player.id}">
                <div class="player-avatar">${player.jersey_number || '?'}</div>
                <h3>${player.name || 'Player ' + player.jersey_number}</h3>
                <div class="position">${player.position || (player.is_goalkeeper ? 'Goalkeeper' : 'Player')}</div>
                <div class="stat-preview">
                    <div class="stat">
                        <div class="stat-value">${player.games_played || 0}</div>
                        <div class="stat-label">Games</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value">${player.total_events || 0}</div>
                        <div class="stat-label">Events</div>
                    </div>
                </div>
            </div>
        `;
    }

    async openPlayerProfile(playerId) {
        const player = this.players.find(p => p.id == playerId);
        if (!player) return;

        document.getElementById('player-avatar').textContent = player.jersey_number || '?';
        document.getElementById('player-name').textContent = player.name || 'Player';
        document.getElementById('player-position').textContent = player.position || 'Player';

        // Load stats
        const statsGrid = document.getElementById('player-stats-grid');
        statsGrid.innerHTML = `
            <div class="player-stat-card">
                <div class="value">${player.games_played || 0}</div>
                <div class="label">Games</div>
            </div>
            <div class="player-stat-card">
                <div class="value">${player.goals || 0}</div>
                <div class="label">Goals</div>
            </div>
            <div class="player-stat-card">
                <div class="value">${player.assists || 0}</div>
                <div class="label">Assists</div>
            </div>
            <div class="player-stat-card">
                <div class="value">${player.saves || 0}</div>
                <div class="label">Saves</div>
            </div>
        `;

        // Draw heatmap
        this.drawPlayerHeatmap(player);

        this.showModal('player-modal');
    }

    drawPlayerHeatmap(player) {
        const canvas = document.getElementById('player-heatmap');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        // Field
        const gradient = ctx.createLinearGradient(0, 0, w, h);
        gradient.addColorStop(0, '#1a5c2e');
        gradient.addColorStop(0.5, '#228b22');
        gradient.addColorStop(1, '#1a5c2e');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, w, h);

        // Lines
        ctx.strokeStyle = 'rgba(255,255,255,0.7)';
        ctx.lineWidth = 2;

        const m = 30;
        ctx.strokeRect(m, m, w - m * 2, h - m * 2);
        ctx.beginPath();
        ctx.moveTo(w / 2, m);
        ctx.lineTo(w / 2, h - m);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(w / 2, h / 2, 50, 0, Math.PI * 2);
        ctx.stroke();

        // Sample heatmap data
        ctx.fillStyle = 'rgba(255,255,255,0.5)';
        ctx.font = '12px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Position data from analyzed games', w / 2, h / 2);
    }

    // =========================================================================
    // Search
    // =========================================================================

    async executeSearch() {
        const query = document.getElementById('nl-search').value.trim();
        if (!query) return;

        const resultsContainer = document.getElementById('search-results');
        const resultsList = document.getElementById('results-list');

        resultsContainer.style.display = 'block';
        resultsList.innerHTML = '<div class="loading">Searching...</div>';

        try {
            const data = await this.apiCall('/query', 'POST', { query });

            document.getElementById('result-count').textContent = `${data.count || 0} results`;

            if (!data.events || data.events.length === 0) {
                resultsList.innerHTML = `
                    <div class="empty-state">
                        <h3>No results found</h3>
                        <p>Try a different search like "goals" or "saves"</p>
                    </div>
                `;
                return;
            }

            resultsList.innerHTML = data.events.map(event => this.renderSearchResult(event)).join('');

            // Bind click events
            resultsList.querySelectorAll('.result-item').forEach(item => {
                item.addEventListener('click', () => {
                    this.openVideo(item.dataset.sessionId, parseFloat(item.dataset.timestamp));
                });
            });

        } catch (error) {
            resultsList.innerHTML = `<div class="empty-state"><p>Search error: ${error.message}</p></div>`;
        }
    }

    renderSearchResult(event) {
        const time = this.formatTime(event.timestamp_sec);
        const eventType = (event.event_type || '').replace(/_/g, ' ');
        const player = event.player ? `#${event.player.jersey_number} ${event.player.name || ''}` : '';

        return `
            <div class="result-item" data-session-id="${event.session_id}" data-timestamp="${event.timestamp_sec}">
                <div class="result-thumbnail">&#9917;</div>
                <div class="result-info">
                    <h4>${eventType}</h4>
                    <p>${player || 'Unknown player'}</p>
                </div>
                <div class="result-time">${time}</div>
            </div>
        `;
    }

    // =========================================================================
    // Video Player
    // =========================================================================

    async openVideo(sessionId, startTime = 0) {
        this.currentVideo = { sessionId, startTime };

        const video = document.getElementById('video-player');
        const overlay = document.getElementById('video-overlay');

        // Show modal
        this.showModal('video-modal');
        overlay.classList.remove('hidden');

        // Find game info
        const game = this.games.find(g => g.id === sessionId);
        document.getElementById('video-title').textContent = game?.name || 'Game Video';

        // Set video source (prefer stitched/panorama if available)
        const videoUrl = `/api/v1/sessions/${sessionId}/stream${game?.stitched ? '/stitched' : '/cam1'}`;

        video.src = videoUrl;
        video.currentTime = startTime;

        video.onloadeddata = () => {
            overlay.classList.add('hidden');
            video.play();
        };

        video.onerror = () => {
            overlay.innerHTML = '<p>Error loading video</p>';
        };

        // Load events for timeline
        await this.loadVideoEvents(sessionId);
    }

    async loadVideoEvents(sessionId) {
        const game = this.games.find(g => g.id === sessionId);
        if (!game?.game_id) return;

        try {
            const data = await this.apiCall(`/games/${game.game_id}/events`);
            this.renderVideoTimeline(data.events || []);
            this.renderVideoEventsList(data.events || []);
        } catch (error) {
            console.error('Failed to load events:', error);
        }
    }

    renderVideoTimeline(events) {
        const timeline = document.getElementById('timeline-events');
        const video = document.getElementById('video-player');
        const duration = video.duration || 5400; // Default 90 min

        timeline.innerHTML = events.map(event => {
            const position = (event.timestamp_sec / duration) * 100;
            const type = event.event_type.includes('goal') ? 'goal' :
                        event.event_type.includes('shot') ? 'shot' :
                        event.event_type.includes('save') ? 'save' : '';
            return `<div class="timeline-event ${type}" style="left: ${position}%" data-time="${event.timestamp_sec}" title="${event.event_type}"></div>`;
        }).join('');

        // Click to seek
        timeline.querySelectorAll('.timeline-event').forEach(el => {
            el.addEventListener('click', () => {
                video.currentTime = parseFloat(el.dataset.time);
            });
        });
    }

    renderVideoEventsList(events) {
        const list = document.getElementById('video-events');
        const video = document.getElementById('video-player');

        list.innerHTML = events.slice(0, 50).map(event => `
            <div class="event-item" data-time="${event.timestamp_sec}">
                <span class="event-time">${this.formatTime(event.timestamp_sec)}</span>
                <span class="event-type">${event.event_type.replace(/_/g, ' ')}</span>
            </div>
        `).join('');

        // Click to seek
        list.querySelectorAll('.event-item').forEach(el => {
            el.addEventListener('click', () => {
                video.currentTime = parseFloat(el.dataset.time);
            });
        });
    }

    closeVideo() {
        const video = document.getElementById('video-player');
        video.pause();
        video.src = '';
        this.currentVideo = null;
        this.clipStart = null;
        this.clipEnd = null;
        this.hideModal('video-modal');
    }

    // =========================================================================
    // Clip Creation
    // =========================================================================

    markClipStart() {
        const video = document.getElementById('video-player');
        this.clipStart = video.currentTime;
        document.getElementById('clip-end-btn').disabled = false;
        this.showToast(`Clip start: ${this.formatTime(this.clipStart)}`, 'success');
    }

    markClipEnd() {
        const video = document.getElementById('video-player');
        this.clipEnd = video.currentTime;

        if (this.clipEnd <= this.clipStart) {
            this.showToast('End must be after start', 'error');
            return;
        }

        document.getElementById('save-clip-btn').disabled = false;
        this.showToast(`Clip end: ${this.formatTime(this.clipEnd)}`, 'success');
    }

    async saveClip() {
        if (!this.currentVideo || this.clipStart === null || this.clipEnd === null) return;

        try {
            const result = await this.apiCall('/clips/generate', 'POST', {
                session_id: this.currentVideo.sessionId,
                timestamp: this.clipStart,
                duration_before: 0,
                duration_after: this.clipEnd - this.clipStart
            });

            // Save locally
            const clip = {
                id: Date.now(),
                sessionId: this.currentVideo.sessionId,
                start: this.clipStart,
                end: this.clipEnd,
                path: result.clip_path,
                created: new Date().toISOString()
            };

            this.savedClips.unshift(clip);
            this.saveSavedClips();

            this.showToast('Clip saved!', 'success');

            // Reset
            this.clipStart = null;
            this.clipEnd = null;
            document.getElementById('clip-end-btn').disabled = true;
            document.getElementById('save-clip-btn').disabled = true;

        } catch (error) {
            this.showToast('Failed to save clip', 'error');
        }
    }

    renderSavedClips() {
        const container = document.getElementById('saved-clips');

        if (this.savedClips.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">&#127909;</div>
                    <h3>No saved clips yet</h3>
                    <p>When you save clips from games, they'll appear here</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.savedClips.map(clip => `
            <div class="clip-card" data-clip-id="${clip.id}">
                <div class="clip-thumbnail">
                    <span>&#127909;</span>
                </div>
                <div class="clip-info">
                    <h4>Clip ${this.formatTime(clip.start)} - ${this.formatTime(clip.end)}</h4>
                    <p>${new Date(clip.created).toLocaleDateString()}</p>
                    <div class="clip-actions">
                        <button class="btn btn-small btn-primary" onclick="viewer.playClip('${clip.sessionId}', ${clip.start})">Play</button>
                        <button class="btn btn-small btn-secondary" onclick="viewer.deleteClip(${clip.id})">Delete</button>
                    </div>
                </div>
            </div>
        `).join('');
    }

    playClip(sessionId, startTime) {
        this.openVideo(sessionId, startTime);
    }

    deleteClip(clipId) {
        this.savedClips = this.savedClips.filter(c => c.id !== clipId);
        this.saveSavedClips();
        this.renderSavedClips();
        this.showToast('Clip deleted', 'success');
    }

    // =========================================================================
    // Sharing
    // =========================================================================

    showShareModal() {
        if (!this.currentVideo) return;

        const video = document.getElementById('video-player');
        const timestamp = Math.floor(video.currentTime);

        const shareUrl = `${window.location.origin}/watch?v=${this.currentVideo.sessionId}&t=${timestamp}`;
        document.getElementById('share-link').value = shareUrl;

        this.showModal('share-modal');
    }

    copyShareLink() {
        const input = document.getElementById('share-link');
        input.select();
        document.execCommand('copy');
        this.showToast('Link copied!', 'success');
    }

    shareViaSMS() {
        const link = document.getElementById('share-link').value;
        window.open(`sms:?body=Check out this soccer clip: ${encodeURIComponent(link)}`);
    }

    shareViaEmail() {
        const link = document.getElementById('share-link').value;
        window.open(`mailto:?subject=Soccer Clip&body=Check out this clip: ${encodeURIComponent(link)}`);
    }

    downloadClip() {
        if (this.clipStart !== null && this.clipEnd !== null && this.currentVideo) {
            window.open(`/api/v1/clips/download?session=${this.currentVideo.sessionId}&start=${this.clipStart}&end=${this.clipEnd}`);
        } else {
            this.showToast('Create a clip first', 'error');
        }
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

    formatDuration(seconds) {
        const mins = Math.floor(seconds / 60);
        if (mins >= 60) {
            const hrs = Math.floor(mins / 60);
            const remainingMins = mins % 60;
            return `${hrs}:${remainingMins.toString().padStart(2, '0')}:00`;
        }
        return `${mins}:00`;
    }

    showModal(modalId) {
        document.getElementById(modalId)?.classList.add('active');
    }

    hideModal(modalId) {
        document.getElementById(modalId)?.classList.remove('active');
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
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (data) options.body = JSON.stringify(data);

        const response = await fetch(`${this.apiBase}${endpoint}`, options);
        const result = await response.json();

        if (!response.ok) throw new Error(result.error || 'API error');
        return result;
    }
}

// Initialize
const viewer = new SoccerViewer();

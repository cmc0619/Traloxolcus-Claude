# Multi-Camera Soccer Recording System - Roadmap

## Completed (v1.0.0)
- [x] 3-camera Pi 5 node recording system (4K @ 30fps)
- [x] GPU processing server with panorama stitching
- [x] ML event detection (goals, shots, saves, passes, dribbles)
- [x] Viewer portal with natural language search
- [x] Team code authentication
- [x] Clip creation and sharing
- [x] Mobile-responsive CSS for viewer and admin dashboards
- [x] Docker containerization with SSL
- [x] TeamSnap integration

---

## High Priority (Core Features)

### Multi-Team & Parent Portal
Support multiple teams with parent/family logins
- [x] Database schema for multi-team support
- [x] Parent accounts (can have multiple children)
- [x] Players can be on multiple teams
- [x] Birth year for age grouping (not U13/U14)
- [ ] Parent login/registration
- [ ] Family dashboard (see all kids' clips)
- [ ] Per-child notification preferences

### Email Notifications
Alert parents when their kid has new content
- [ ] SMTP configuration
- [ ] Email templates (game ready, new clips, highlights)
- [ ] Per-player email triggers (goals, saves, etc.)
- [ ] Digest mode (daily summary vs instant)
- [ ] Unsubscribe handling

### Player Statistics
Track individual player stats across games and seasons
- [ ] Goals, assists, shots, saves per game
- [ ] Season totals and averages
- [ ] Player profile pages
- [ ] Game-by-game breakdown
- [ ] Position-specific stats (GK save %, striker conversion rate)
- [ ] Comparison across teammates

### Automated Highlights
Auto-generate 2-min highlight reel from top events
- [ ] Scoring algorithm for event importance
- [ ] Automatic clip extraction and concatenation
- [ ] Transition effects between clips
- [ ] Background music overlay option
- [ ] Per-player highlight reels

### Coach Annotation Tool
Draw on video, add notes at timestamps
- [ ] Canvas overlay on video player
- [ ] Drawing tools (arrows, circles, lines, freehand)
- [ ] Text annotations at timestamps
- [ ] Save/share annotated clips
- [ ] Telestrator-style playback

---

## Medium Priority (User Experience)

### Live Streaming
Stream games in real-time using WebRTC/HLS
- [ ] WebRTC signaling server on processing server
- [ ] HLS fallback for broader compatibility
- [ ] Low-latency mode for coaching
- [ ] Multi-camera view selector

### Enhanced Highlight Reels
Extended highlight reel features
- [ ] Custom highlight builder (drag-and-drop clips)
- [ ] "Top 10 plays" compilation
- [ ] Season best-of reels

### Social Media Export
Vertical clips for TikTok/Instagram Reels
- [ ] 9:16 aspect ratio cropping (auto-follow ball/action)
- [ ] Platform-specific templates
- [ ] Watermark/branding overlay
- [ ] Direct share to platforms

### Multi-language Support
i18n for viewer portal
- [ ] English (default)
- [ ] Spanish
- [ ] French
- [ ] Language detection from browser

---

## Low Priority (Advanced)

### Mobile App
React Native viewer app for iOS/Android
- [ ] iOS app with native video player
- [ ] Android app
- [ ] Push notifications for new content
- [ ] Offline clip download
- [ ] Share to device gallery

### Heat Map Generation
Player positioning visualization
- [ ] Position tracking from ML pipeline
- [ ] Interactive heat map canvas
- [ ] Per-player and team-wide views
- [ ] Time-slice filtering

### AI Commentary
Auto-generate play-by-play narration
- [ ] Event-to-text generation
- [ ] Text-to-speech synthesis
- [ ] Multiple voice options
- [ ] Real-time vs post-game modes

---

## Technical Debt / Improvements
- [ ] Add comprehensive test suite
- [ ] CI/CD pipeline setup
- [ ] Database migrations system
- [ ] API rate limiting
- [ ] Logging and monitoring (Prometheus/Grafana)
- [ ] Backup and disaster recovery procedures

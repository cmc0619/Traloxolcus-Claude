# Multi-Camera Soccer Recording System - Roadmap

## Completed (v1.0.0)
- [x] 3-camera Pi 5 node recording system (4K @ 30fps)
- [x] GPU processing server with panorama stitching
- [x] ML event detection (goals, shots, saves, passes, dribbles)
- [x] Viewer portal with natural language search
- [x] Team code authentication
- [x] Clip creation and sharing
- [x] Mobile-responsive CSS for viewer and admin dashboards
- [x] Complete deployment documentation

---

## High Priority (Core Features)

### Live Streaming
Stream games in real-time using WebRTC/HLS
- [ ] WebRTC signaling server on processing server
- [ ] HLS fallback for broader compatibility
- [ ] Low-latency mode for coaching
- [ ] Multi-camera view selector

### Email Notifications
Alert stakeholders when game processing is complete
- [ ] SMTP configuration in processing server
- [ ] Email templates (processing complete, highlights ready)
- [ ] Webhook support for custom integrations
- [ ] Team contact list management

### Automated Highlights
Auto-generate 2-min highlight reel from top events
- [ ] Scoring algorithm for event importance
- [ ] Automatic clip extraction and concatenation
- [ ] Transition effects between clips
- [ ] Background music overlay option

### Coach Annotation Tool
Draw on video, add notes at timestamps
- [ ] Canvas overlay on video player
- [ ] Drawing tools (arrows, circles, lines, freehand)
- [ ] Text annotations at timestamps
- [ ] Save/share annotated clips
- [ ] Telestrator-style playback

---

## Medium Priority (User Experience)

### Highlight Reels (Enhanced)
Extended highlight reel features beyond basic auto-generation
- [ ] Custom highlight builder (drag-and-drop clips)
- [ ] Per-player highlight reels
- [ ] "Top 10 plays" compilation
- [ ] Season best-of reels

### Roster Import
CSV/TeamSnap integration for player names
- [ ] CSV upload with column mapping
- [ ] TeamSnap API integration
- [ ] Jersey number to player matching
- [ ] Team photo import

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

### Season Statistics
Track player stats across multiple games
- [ ] Player profile pages
- [ ] Season totals (goals, assists, shots, etc.)
- [ ] Game-by-game breakdown
- [ ] Comparison charts

### Heat Map Generation
Player positioning visualization
- [ ] Position tracking from ML pipeline
- [ ] Interactive heat map canvas
- [ ] Per-player and team-wide views
- [ ] Time-slice filtering

### Parent Purchase Portal
Buy individual clips/highlights
- [ ] Stripe/PayPal integration
- [ ] Clip watermarking for previews
- [ ] HD download after purchase
- [ ] Subscription option for full access

### AI Commentary
Auto-generate play-by-play narration
- [ ] Event-to-text generation
- [ ] Text-to-speech synthesis
- [ ] Multiple voice options
- [ ] Real-time vs post-game modes

### Referee Incident Review
Slow-mo, multiple angles for disputed calls
- [ ] Frame-by-frame scrubbing
- [ ] Synchronized multi-angle view
- [ ] Timestamp bookmarking
- [ ] Export incident report

---

## Technical Debt / Improvements
- [ ] Add comprehensive test suite
- [ ] CI/CD pipeline setup
- [ ] Database migrations system
- [ ] API rate limiting
- [ ] Logging and monitoring (Prometheus/Grafana)
- [ ] Backup and disaster recovery procedures

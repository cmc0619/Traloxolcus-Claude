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
- [x] Multi-team database schema
- [x] Email notifications service
- [x] Player statistics service
- [x] Admin auth and config page

---

## High Priority (Core Features)

### Parent Portal
- [ ] Parent login/registration
- [ ] Family dashboard (see all kids' clips)
- [ ] Per-child notification preferences

### Automated Highlights
- [ ] Scoring algorithm for event importance
- [ ] Automatic clip extraction and concatenation
- [ ] Transition effects between clips
- [ ] Per-player highlight reels

### Coach Annotation Tool
- [ ] Canvas overlay on video player
- [ ] Drawing tools (arrows, circles, lines, freehand)
- [ ] Text annotations at timestamps
- [ ] Save/share annotated clips

### Heat Map Generation
- [ ] Position tracking from ML pipeline
- [ ] Interactive heat map canvas
- [ ] Per-player and team-wide views
- [ ] Time-slice filtering

### Social Media Export
- [ ] 9:16 aspect ratio cropping (auto-follow ball/action)
- [ ] Platform-specific templates
- [ ] Watermark/branding overlay

---

## Medium Priority (User Experience)

### Live Streaming
- [ ] WebRTC signaling server
- [ ] HLS fallback
- [ ] Multi-camera view selector

### Enhanced Highlight Reels
- [ ] Custom highlight builder (drag-and-drop)
- [ ] "Top 10 plays" compilation
- [ ] Season best-of reels

---

## Low Priority (Advanced)

### Mobile App
- [ ] React Native iOS/Android app
- [ ] Push notifications
- [ ] Offline clip download

### Multi-language Support
- [ ] i18n for viewer portal
- [ ] Spanish, French

### AI Commentary
- [ ] Event-to-text generation
- [ ] Text-to-speech synthesis

---

## Technical Debt
- [ ] Test suite
- [ ] CI/CD pipeline
- [ ] Database migrations (Alembic)
- [ ] API rate limiting
- [ ] Backup procedures

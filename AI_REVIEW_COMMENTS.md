# AI Reviewer Comments - Traloxolcus-Claude PRs

This document tracks AI reviewer comments from CodeRabbit and Codex across all PRs.

---

## ✅ ADDRESSED COMMENTS (All Fixed!)

| # | File | Issue | Fixed In |
|---|------|-------|----------|
| 1 | `processing-server/requirements.txt` | Upgrade gunicorn to 22.0.0+ (CVE-2024-1135) | 6f39b3f |
| 2 | `soccer-rig-server/app.py` | Remove duplicate /dashboard route | 6f39b3f |
| 3 | `social_export.py` | Replace eval() with safe parsing | 6f39b3f |
| 4 | `social_export.py` | Validate filename for path traversal | 6f39b3f |
| 5 | `app.py` | DB sessions in finally block | 464b982 |
| 6 | `teamsnap.py` | Bare except clause → specific exceptions | 968b395 |
| 7 | `teamsnap.py` | Add request timeouts (POST/GET) | 968b395 |
| 8 | `teamsnap.py` | logger.error → logger.exception | 968b395 |
| 9 | `teamsnap.py` | birth_year=2010 → birth_year=None | 968b395 |
| 10 | `teamsnap.py` | Add auth to /api/data endpoints | 968b395 |
| 11 | `admin.py` | Checkbox form unchecked handling | 968b395 |
| 12 | `admin.py` | Remove unused db parameter | 968b395 |
| 13 | `processing-server/requirements.txt` | Upgrade psutil 5.9.0 → 6.0.0 | 968b395 |
| 14 | `TODO.md` | Duplicate Heat Map entry | already fixed |
| 15 | `app.py` | **CORS configurable via CORS_ORIGINS env** | 5ba2fa9 |
| 16 | `app.py` | **Global DEBUG flag from env** | 5ba2fa9 |
| 17 | `teamsnap.py` | **Open redirect validation** | 5ba2fa9 |
| 18 | `social_export.py` | **focus_x=0.0 treated as None bug** | 5ba2fa9 |
| 19 | `social_export.py` | **FFmpeg text sanitization improved** | 5ba2fa9 |

---

## 🟡 REMAINING (Minor/Optional)

| # | File/Location | Issue | Details |
|---|---------------|-------|---------|
| 1 | `docker-compose.yml:8-32` | Add health checks | Docker may mark "running" before ready |

---

## 📋 DEFERRED (User chose to skip)

These issues were identified but user indicated they don't care about them:

| Category | Issues |
|----------|--------|
| Hardcoded credentials | DATABASE_URL, POSTGRES_USER/PASSWORD in docker-compose.yml |
| Unsafe secrets | SECRET_KEY default, TEAMSNAP_CLIENT_SECRET defaults |
| SMTP config | Empty defaults allowing silent failures |

---

## SUMMARY

| Status | Count |
|--------|-------|
| ✅ Fixed | **19** |
| � Minor remaining | 1 |
| � Deferred | ~5 |

**All critical and major issues have been fixed!**

# AI Reviewer Comments - Traloxolcus-Claude PRs

This document tracks AI reviewer comments from CodeRabbit and Codex across all PRs.

---

## ✅ ADDRESSED COMMENTS (Fixed)

| # | File | Issue | Fixed In |
|---|------|-------|----------|
| 1 | `processing-server/requirements.txt` | Upgrade gunicorn to 22.0.0+ (CVE-2024-1135) | commit 6f39b3f |
| 2 | `soccer-rig-server/app.py` | Remove duplicate /dashboard route | commit 6f39b3f |
| 3 | `social_export.py` | Replace eval() with safe parsing | commit 6f39b3f |
| 4 | `social_export.py` | Validate filename for path traversal | commit 6f39b3f |
| 5 | `app.py` | DB sessions in finally block | commit 464b982 |
| 6 | `teamsnap.py` | **Bare except clause → specific exceptions** | commit 968b395 |
| 7 | `teamsnap.py` | **Add request timeouts (POST/GET)** | commit 968b395 |
| 8 | `teamsnap.py` | **logger.error → logger.exception** | commit 968b395 |
| 9 | `teamsnap.py` | **birth_year=2010 → birth_year=None** | commit 968b395 |
| 10 | `teamsnap.py` | **Add auth to /api/data endpoints** | commit 968b395 |
| 11 | `admin.py` | **Checkbox form unchecked handling** | commit 968b395 |
| 12 | `admin.py` | **Remove unused db parameter** | commit 968b395 |
| 13 | `processing-server/requirements.txt` | **Upgrade psutil 5.9.0 → 6.0.0** | commit 968b395 |
| 14 | `TODO.md` | Duplicate Heat Map entry | Already fixed |

---

## ❌ REMAINING UNADDRESSED COMMENTS

### 🔴 Critical

| # | File/Location | Issue | Details |
|---|---------------|-------|---------|
| 1 | `social_export.py:220-255` | **FFmpeg command injection** | User strings not fully sanitized for drawtext filter |
| 2 | `app.py:55` | **CORS allows all origins** | `origins: "*"` in production - make configurable |

### 🟠 Major

| # | File/Location | Issue | Details |
|---|---------------|-------|---------|
| 3 | `teamsnap.py:793-801` | **Open redirect** | `return_url` from args used without validation |
| 4 | `social_export.py:427-432` | **focus_x=0.0 treated as falsy** | Use `is not None` check (also 502-505, 515-518) |

### � Minor / Optional

| # | File/Location | Issue | Details |
|---|---------------|-------|---------|
| 5 | `docker-compose.yml:8-32` | Add health checks | Docker may mark "running" before ready |
| 6 | `app.py:38-42` | SECRET_KEY predictable default | Require env var in production |
| 7 | `app.py:184-187` | Hardcoded debug=True | Make environment-driven |

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
| ✅ Fixed | 14 |
| 🔴 Critical remaining | 2 |
| 🟠 Major remaining | 2 |
| 🟡 Minor remaining | 3 |
| 📋 Deferred | ~5 |

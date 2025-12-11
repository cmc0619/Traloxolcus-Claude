# AI Reviewer Comments - Traloxolcus-Claude PRs

This document compiles AI reviewer comments from CodeRabbit and Codex across all PRs, categorized by status.

---

## ✅ ADDRESSED COMMENTS (Already Fixed)

These comments have been resolved in subsequent commits:

| # | File | Issue | Addressed In |
|---|------|-------|--------------|
| 1 | `processing-server/requirements.txt` | **Upgrade gunicorn to 22.0.0+** - gunicorn 21.0.0 has HTTP request-smuggling vulnerabilities (CVE-2024-1135, CVE-2024-6827) | commit 6f39b3f |
| 2 | `soccer-rig-server/app.py` | **Remove duplicate /dashboard route** - Conflicting unprotected static dashboard route shadowing authenticated one in auth.py | commit 6f39b3f |
| 3 | `soccer-rig-server/src/services/social_export.py` | **Replace eval() with safe parsing** - eval() on frame rate is RCE vulnerability | commit 6f39b3f |
| 4 | `soccer-rig-server/src/services/social_export.py` | **Validate filename for path traversal** - Path traversal vulnerability in download endpoint | commit 6f39b3f |
| 5 | `soccer-rig-server/app.py` | **DB sessions in finally block** - Sessions endpoint should close DB in finally block | commit 464b982 |

---

## ❌ UNADDRESSED COMMENTS (Need Fixing)

### 🔴 CRITICAL PRIORITY

| # | File/Location | Issue | Severity | Details |
|---|---------------|-------|----------|---------|
| 1 | `soccer-rig-server/src/services/social_export.py:220-255` | **FFmpeg command injection** | 🔴 Critical | User-controlled strings (player_name, event_type, score, game_info) not sanitized for drawtext filter. |
| 2 | `soccer-rig-server/app.py:55` | **CORS allows all origins** | 🔴 Critical | `origins: "*"` in production exposes API to unauthorized cross-origin requests. Make configurable. |

### 🟠 MAJOR PRIORITY

| # | File/Location | Issue | Severity | Details |
|---|---------------|-------|----------|---------|
| 6 | `docker-compose.yml:45` | **VIEWER_URL localhost default** | 🟠 Major | Hardcodes `localhost:7420` - won't work in multi-host deployments. Use service hostname. |
| 7 | `docker-compose.yml:46-50` | **SMTP credentials empty defaults** | 🟠 Major | SMTP config with empty defaults causes silent failures. Either require or document as optional. |
| 8 | `soccer-rig-server/src/integrations/teamsnap.py:612-635` | **Hard-coded birth_year=2010 default** | 🟠 Major | Creates incorrect ages for players without TeamSnap birthday. Make nullable or use sentinel value. |
| 9 | `soccer-rig-server/src/integrations/teamsnap.py:793-801` | **Open redirect vulnerability** | 🟠 Major | `return_url` from request.args used without validation. Validate it's a relative URL or same-host. |
| 10 | `soccer-rig-server/src/integrations/teamsnap.py:215-254` | **Missing request timeouts (POST)** | 🟠 Major | exchange_code() and refresh_token() POST calls have no timeout - can hang indefinitely. |
| 11 | `soccer-rig-server/src/integrations/teamsnap.py:260-274` | **Missing request timeout (GET)** | 🟠 Major | _api_request() GET call has no timeout - affects all API methods. |
| 12 | `soccer-rig-server/src/services/social_export.py:427-432` | **focus_x=0.0 treated as missing** | 🟠 Major | Truthiness check treats 0.0 as falsy. Use `is not None` check. Also at 502-505, 515-518. |
| 13 | `soccer-rig-server/src/admin.py:601` | **Checkbox form loses unchecked values** | 🟠 Major | Unchecked checkboxes don't submit - boolean config values won't update to False. |
| 14 | `soccer-rig-server/src/integrations/teamsnap.py:954-1004` | **Unauthenticated data endpoints** | 🟠 Major | `/api/data/teams` and `/api/data/players` expose roster data without auth checks. |

### 🟡 MINOR PRIORITY

| # | File/Location | Issue | Severity | Details |
|---|---------------|-------|----------|---------|
| 15 | `soccer-rig-server/src/integrations/teamsnap.py:64-71` | **Bare except clause** | 🟡 Minor | `birth_year` property uses bare `except:` - should catch specific exceptions (ValueError, IndexError, TypeError). |
| 16 | `TODO.md:39-43,83-88` | **Duplicate Heat Map Generation entry** | 🟡 Minor | "Heat Map Generation" appears in both High Priority and Low Priority sections. Remove duplicate. |
| 17 | `soccer-rig-server/app.py:38-42` | **SECRET_KEY predictable default** | 🟡 Minor | `'dev-secret-change-me'` fallback - require env var in production. |
| 18 | `soccer-rig-server/app.py:184-187` | **Hardcoded debug=True** | 🟡 Minor | Make debug flag environment-driven for flexibility. |
| 19 | `soccer-rig-server/src/integrations/teamsnap.py:495-499` | **Use logging.exception()** | 🟡 Minor | Use `logging.exception()` instead of `logging.error()` to preserve traceback. |
| 20 | `processing-server/requirements.txt:8-9` | **Consider upgrading psutil** | 🟡 Minor | psutil 5.9.0 is from 2021. Consider upgrading to 6.x for stability. |
| 21 | `docker-compose.yml:8-32` | **Add health checks** | 🟡 Minor | Services lack health checks - Docker may mark "running" before actually ready. |
| 22 | `soccer-rig-server/src/admin.py:410-421` | **Ensure psutil in requirements** | 🟡 Minor | Endpoint imports psutil which may not be in soccer-rig-server/requirements.txt. |
| 23 | `soccer-rig-server/src/admin.py:337` | **Remove unused db parameter** | 🟡 Minor | `db` parameter never used within function. |

---

## SUMMARY

| Priority | Count | Description |
|----------|-------|-------------|
| ✅ Addressed | 5 | Already fixed in commits |
| 🔴 Critical | 5 | Security vulnerabilities, must fix before merge |
| 🟠 Major | 9 | Significant issues affecting functionality/security |
| 🟡 Minor | 9 | Code quality, best practices |
| **TOTAL OPEN** | **23** | |

---

## RECOMMENDED FIX ORDER

### Phase 1: Security Critical (Fix Immediately)

1. Docker credentials to .env (#1, #2, #3)
2. FFmpeg command injection sanitization (#4)
3. CORS origin restriction (#5)

### Phase 2: Major Functionality

4. Request timeouts in TeamSnap client (#10, #11)
5. Open redirect validation (#9)
6. Auth on data endpoints (#14)
7. focus_x None checking (#12)

### Phase 3: Minor / Code Quality

8. Remaining minor issues as time permits

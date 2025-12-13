# Next PR TODO - Low Priority Fixes & Improvements

This document tracks items deferred from PR #7 (`finishing-touches-high-priority`) for the next PR.

## From CodeRabbit Review (Nitpicks)

### recorder.py - Codec Validation
- **Location**: `src/soccer_rig/camera/recorder.py` - `_init_camera()` method (line ~104)
- **Issue**: Config defaults to "h265" but `get_supported_codecs()` now only returns `["h264"]`. No validation rejects unsupported codec values.
- **Fix**: Add validation in `_init_camera()` or `start_recording()`:
  ```python
  supported_codecs = self.get_supported_codecs()
  if self.config.camera.codec not in supported_codecs:
      raise ValueError(
          f"Unsupported codec '{self.config.camera.codec}'. "
          f"Supported: {supported_codecs}"
      )
  ```
- **Also**: Update `config.py` to default to `"h264"` instead of `"h265"`

### app.py - Session Manager Auto-Commit
- **Location**: `soccer-rig-server/app.py` - `get_db_session()` (lines 96-108)
- **Issue**: Current implementation doesn't auto-commit, requiring callers to explicitly commit for write operations
- **Fix**: Add `session.commit()` before the except block for automatic transaction handling
- **Priority**: Low (current usage is read-only)

### app.py - Auth Decorator Pattern
- **Location**: `soccer-rig-server/app.py` - `_require_api_auth()` (lines 139-144)
- **Issue**: Manual auth check requires boilerplate in each endpoint
- **Fix**: Refactor to decorator:
  ```python
  from functools import wraps
  
  def require_api_auth(f):
      @wraps(f)
      def decorated_function(*args, **kwargs):
          if not flask_session.get('user_id'):
              return {'error': 'Not authenticated'}, 401
          return f(*args, **kwargs)
      return decorated_function
  ```
- **Priority**: Low (style improvement)

---

## From Previous Session (Deferred Items)

### Security (Requires Careful Implementation)
- **CRITICAL #2**: OAuth token encryption - Store TeamSnap tokens encrypted at rest
- **CRITICAL #3**: Admin password security - Don't store default admin password in code

### Minor Code Quality
- **app.py**: Hardcoded stubs (`storage_used_gb`, `processing_queue`) - Implement actual values
- **recorder.py**: Remove unused `subprocess` import
- **simulation.py**: Complete docstring
- **config.py**: Remove hardcoded `mesh_password`
- **social_export.py**: Complete path traversal check, add `@login_required`
- **admin.py**: Add `psutil` to requirements
- **base.py**: Remove redundant `pass` after abstract method
- **teamsnap.py**: Validate `Token.from_dict` input, fragile API parsing
- **processing_server/app.py**: Replace busy-wait loop with proper async

### Nitpicks (Low Priority)
- **framing.py**: Clean up line continuations
- **preview.py**: Document minimal JPEG hardcoded bytes
- **heatmap.py**: Improve `max()` nesting readability
- **models.py**: Complete `get_jersey_for_team()` method
- **config.py**: Consider alternative to `__dataclass_fields__` access

---

## Suggested PR Order

1. **Security PR**: OAuth encryption + admin password (Critical)
2. **Code Quality PR**: Minor fixes, imports cleanup, docstrings
3. **Style PR**: Decorator patterns, nitpicks, readability improvements

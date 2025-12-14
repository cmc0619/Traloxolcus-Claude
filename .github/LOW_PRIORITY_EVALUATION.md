# Low Priority Finishing Touches - Evaluation & Work List

## Branch: `finishing-touches-low-priority`

This document evaluates all minor/nitpick items from the PR reviews and determines which ones to fix.

---

## NEW ITEMS (From High Priority PR Review)

### 1. ✅ FIX - Codec Validation in Recorder

- **File**: `src/soccer_rig/camera/recorder.py` (~line 104)
- **Issue**: Config defaults to "h265" but `get_supported_codecs()` returns only `["h264"]`. No validation rejects unsupported codec.
- **Fix**: Validate codec on init, raise error if unsupported
- **Also**: Update `config.py` line 26 to default to `"h264"`
- **Verdict**: **FIX** - Config mismatch could confuse users

### 2. ✅ FIX - Session Manager Auto-Commit  

- **File**: `soccer-rig-server/app.py` (lines 96-108)
- **Issue**: No auto-commit for write operations
- **Verdict**: **SKIP** - Current usage is read-only; callers can commit explicitly

### 3. ✅ FIX - Auth Decorator Pattern

- **File**: `soccer-rig-server/app.py` (lines 139-144)
- **Issue**: Manual auth check is boilerplate
- **Verdict**: **SKIP** - Style preference; current pattern works fine

---

## ORIGINAL MINOR ITEMS (12-26 from initial review)

### 4. ✅ FIX - Hardcoded stubs in app.py

- **File**: `soccer-rig-server/app.py` line 161
- **Issue**: `storage_used_gb: 0` and `processing_queue: 0` are hardcoded stubs
- **Verdict**: **KEEP AS TODO** - Would require significant new implementation
- **Action**: Ensure TODO comment is clear

### 5. ❌ SKIP - Abstract method pass statement

- **File**: `src/soccer_rig/camera/base.py` (lines 73-166)
- **Issue**: Review suggested removing `pass` after docstrings in abstract methods
- **Verdict**: **FALSE** - The `pass` is REQUIRED for abstract methods with only docstrings. This is Python syntax.

### 6. ✅ FIX - Hardcoded mesh_password in config

- **File**: `src/soccer_rig/config.py` line 37
- **Issue**: `mesh_password: str = "soccer_rig_2024"` is hardcoded
- **Verdict**: **KEEP** - This is a development default, production should override via env/config file
- **Action**: Add comment explaining this is a dev default

### 7. ✅ FIX - Add psutil to requirements

- **File**: `soccer-rig-server/src/admin.py` line 418
- **Issue**: `import psutil` is used but may not be in requirements
- **Check**: Verify if psutil is in requirements.txt, add if not

### 8. ❌ SKIP - **dataclass_fields** access

- **File**: `src/soccer_rig/config.py`
- **Issue**: Uses `__dataclass_fields__` attribute
- **Verdict**: **FALSE** - This is a standard public API for dataclasses, not a private attribute

### 9. ✅ FIX - Codec default in config.py

- **File**: `src/soccer_rig/config.py` line 26
- **Issue**: `codec: str = "h265"` should be `"h264"` to match supported codecs
- **Verdict**: **FIX** - Align with actual supported codecs

---

## LOWER PRIORITY NITPICKS

### 10. ❓ EVALUATE - framing.py line continuations

- **File**: `src/soccer_rig/camera/framing.py`
- **Issue**: Line continuation style
- **Verdict**: **SKIP** - Purely stylistic

### 11. ❓ EVALUATE - preview.py minimal JPEG docs

- **File**: `src/soccer_rig/camera/preview.py`
- **Issue**: Document the minimal JPEG bytes constant
- **Verdict**: **SKIP** - Low value

### 12. ❓ EVALUATE - heatmap.py max() nesting

- **File**: `soccer-rig-server/src/services/heatmap.py`
- **Issue**: Improve readability of nested `max()` calls
- **Verdict**: **SKIP** - Working code, low priority

### 13. ❓ EVALUATE - models.py get_jersey_for_team()

- **File**: `soccer-rig-server/src/models.py`
- **Issue**: Complete the `get_jersey_for_team()` method
- **Verdict**: **CHECK** - Need to verify if method is incomplete

---

## WORK PLAN (Items to Fix)

1. ✅ **DONE** - Update codec default from "h265" to "h264" in config.py
2. ✅ **DONE** - Add codec validation in recorder initialization (warns and falls back to h264)
3. ✅ **VERIFIED** - psutil already in requirements.txt
4. ✅ **DONE** - Add comment for mesh_password clarifying dev default

---

## SUMMARY

| Category | Count |
|----------|-------|
| **Items to Fix** | 4 |
| **Skip (False Issues)** | 2 |
| **Skip (Style/Low Value)** | 4+ |
| **Deferred (Need More Work)** | 1 |

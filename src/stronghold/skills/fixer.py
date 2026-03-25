"""Security repair engine for marketplace skills and agents.

Attempts to automatically fix security issues found by the scanner.
Returns what was fixed, what couldn't be fixed, and the cleaned content.
"""

from __future__ import annotations

import re
import unicodedata


def fix_content(content: str) -> tuple[str, list[str], list[str]]:
    """Attempt to repair security issues in skill/agent content.

    Returns:
        (fixed_content, fixes_applied, unfixable_issues)

    Fixable: exec/eval/subprocess, hardcoded creds, prompt injection
             phrases, unicode attacks, shell commands.
    Unfixable: >50% instruction density, no meaningful content after
               stripping, obfuscated payloads, entire body is injection.
    """
    fixes: list[str] = []
    unfixable: list[str] = []
    fixed = content

    # ── 1. Unicode normalization (NFKD) ──
    normalized = unicodedata.normalize("NFKD", fixed)
    if normalized != fixed:
        fixes.append(
            "Normalized unicode characters (NFKD) — removed directional markers and lookalikes"
        )
        fixed = normalized

    # ── 2. Remove unicode direction markers ──
    direction_markers = re.findall(
        r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", fixed
    )
    if direction_markers:
        fixed = re.sub(
            r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", fixed
        )
        fixes.append(f"Removed {len(direction_markers)} hidden unicode direction markers")

    # ── 3. Strip code execution calls ──
    exec_patterns = [
        (r"\bexec\s*\([^)]*\)", "exec() call"),
        (r"\beval\s*\([^)]*\)", "eval() call"),
        (r"\bsubprocess\.\w+\s*\([^)]*\)", "subprocess call"),
        (r"\bos\.system\s*\([^)]*\)", "os.system() call"),
        (r"__import__\s*\([^)]*\)", "__import__() call"),
        (r"\bcompile\s*\([^)]*\)", "compile() call"),
        (r"\bimportlib\.\w+", "importlib usage"),
        (r"__builtins__", "__builtins__ access"),
        (r"\bglobals\s*\(\s*\)", "globals() access"),
    ]
    for pattern, desc in exec_patterns:
        matches = re.findall(pattern, fixed, re.IGNORECASE)
        if matches:
            fixed = re.sub(pattern, f"# [REMOVED: {desc}]", fixed, flags=re.IGNORECASE)
            fixes.append(f"Removed {len(matches)} {desc}(s)")

    # ── 4. Strip import statements for dangerous modules ──
    dangerous_imports = re.findall(
        r"^\s*(?:import|from)\s+(?:subprocess|os|sys|shutil|importlib|ctypes|socket)\b.*$",
        fixed,
        re.MULTILINE,
    )
    if dangerous_imports:
        for imp in dangerous_imports:
            fixed = fixed.replace(imp, "# [REMOVED: dangerous import]")
        fixes.append(f"Removed {len(dangerous_imports)} dangerous import statement(s)")

    # ── 5. Replace hardcoded credentials ──
    cred_pattern = (
        r"(?:api_key|secret|password|token|secret_key|secret_token"
        r"|master_password|database_url)\s*=\s*[\"'][^\"']{8,}[\"']"
    )
    cred_matches = re.findall(cred_pattern, fixed, re.IGNORECASE)
    if cred_matches:
        fixed = re.sub(
            cred_pattern,
            "# [REMOVED: hardcoded credential — use environment variable]",
            fixed,
            flags=re.IGNORECASE,
        )
        fixes.append(
            f"Replaced {len(cred_matches)} hardcoded credential(s) with env var placeholders"
        )

    # ── 6. Strip prompt injection phrases ──
    injection_phrases = [
        (
            r"ignore\s+(?:all\s+)?previous\s+(?:instructions?|rules?|prompts?|guidelines?)",
            "instruction override",
        ),
        (r"(?:new|override|replacement)\s+instructions?:", "instruction injection"),
        (
            r"you\s+are\s+now\s+(?:in\s+)?(?:developer|admin|unrestricted|jailbreak)\s+mode",
            "jailbreak attempt",
        ),
        (
            r"(?:disregard|forget|override)\s+(?:all\s+)?(?:safety|content|previous)\s+(?:guidelines?|restrictions?|policies?|rules?|instructions?|prompts?)",
            "safety bypass",
        ),
        (
            r"you\s+have\s+(?:no|full|unlimited)\s+(?:restrictions?|access|limitations?)",
            "restriction removal",
        ),
        (r"previous\s+restrictions?\s+(?:are\s+)?lifted", "restriction removal"),
        (r"system\s+prompt\s+override", "system prompt override"),
    ]
    for pattern, desc in injection_phrases:
        matches = re.findall(pattern, fixed, re.IGNORECASE)
        if matches:
            fixed = re.sub(pattern, f"[REMOVED: {desc}]", fixed, flags=re.IGNORECASE)
            fixes.append(f"Stripped {len(matches)} prompt injection phrase(s): {desc}")

    # ── 7. Replace dangerous shell commands ──
    shell_cmds = re.findall(r"\b(?:curl|wget)\s+-[^\n]*https?://[^\s]+", fixed)
    if shell_cmds:
        for cmd in shell_cmds:
            fixed = fixed.replace(
                cmd, "# [REMOVED: external shell command — use approved HTTP client]"
            )
        fixes.append(f"Replaced {len(shell_cmds)} shell command(s) with safe alternatives")

    # ── 8. Fix trust tier claims ──
    # Community skills should never claim t0 or t1
    tier_claim = re.search(r'trust_tier:\s*["\']?(t[01])["\']?', fixed)
    if tier_claim:
        fixed = re.sub(r'trust_tier:\s*["\']?t[01]["\']?', "trust_tier: t2", fixed)
        fixes.append(f"Downgraded trust tier claim from {tier_claim.group(1)} to t2 (community)")

    # ── 9. Check for unfixable conditions ──

    # Count remaining instruction-like lines vs total lines
    lines = [
        ln.strip()
        for ln in fixed.split("\n")
        if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("---")
    ]
    if lines:
        instruction_keywords = {
            "must",
            "always",
            "never",
            "ignore",
            "override",
            "execute",
            "run",
            "access",
            "unrestricted",
        }
        instruction_lines = sum(
            1 for ln in lines if any(kw in ln.lower() for kw in instruction_keywords)
        )
        density = instruction_lines / len(lines) if lines else 0
        if density > 0.5:
            unfixable.append(
                f"Content is {density:.0%} instruction-heavy — likely entirely prompt injection"
            )

    # Check if meaningful content remains
    body_start = False
    meaningful_body_lines = 0
    for line in fixed.split("\n"):
        if line.strip() == "---" and body_start:
            body_start = True
            continue
        if body_start and line.strip() and "[REMOVED:" not in line:
            meaningful_body_lines += 1
        if not body_start and line.strip() == "---":
            body_start = True

    if meaningful_body_lines < 2 and fixes:
        unfixable.append(
            "No meaningful content remaining after security fixes — skill is entirely malicious"
        )

    return fixed, fixes, unfixable


def is_deeply_flawed(fixes: list[str], unfixable: list[str]) -> bool:
    """Determine if content is too damaged to repair.

    Deeply flawed if:
    - Any unfixable issues exist, OR
    - More than 5 distinct security fixes were needed (suggests intentional malice)
    """
    if unfixable:
        return True
    return len(fixes) > 5

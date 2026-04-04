/**
 * Stronghold Auth Guard (BFF-aware) + Security Violation Popup
 * --------------------------------------------------------------
 * Include synchronously in <head> of every dashboard page:
 *   <script src="/dashboard/auth.js"></script>
 *
 * Supports two auth modes:
 *   1. OIDC via BFF �� JWT lives in HttpOnly cookie (never in JS).
 *      Indicator cookie "stronghold_logged_in=1" signals active session.
 *   2. API key — stored in localStorage, sent as Bearer header.
 *
 * Security violation interception:
 *   Wraps fetch() to detect security_violation responses and shows
 *   a modal with strike info, warning message, and appeal text box.
 *
 * Provides:
 *   - Auto-redirect to /login when no session is present
 *   - getAuth()           -> "Bearer <token>" for API key, or "" for cookie auth
 *   - authHeaders()       -> {Authorization, Content-Type, X-Stronghold-Request}
 *   - strongholdLogout()  -> clears session (cookie + localStorage) and redirects
 *   - getStrongholdUser() -> display name
 */
(function() {
  'use strict';

  var LOGIN = '/';
  var TOKEN_KEY = 'stronghold-token';
  var TOKEN_TYPE_KEY = 'stronghold-token-type';
  var USER_KEY = 'stronghold-user';

  // Don't guard the login page itself
  var path = location.pathname;
  if (path === LOGIN || path === '/' || path === '/login' || path === '/login/callback') return;

  var tokenType = localStorage.getItem(TOKEN_TYPE_KEY);

  // Check for session indicator cookie (non-HttpOnly, set alongside the session cookie)
  var hasCookieSession = document.cookie.split(';').some(function(c) {
    return c.trim().startsWith('stronghold_logged_in=');
  });

  // Check for API key in localStorage
  var hasApiKey = tokenType === 'api_key' && !!localStorage.getItem(TOKEN_KEY);
  
  // No session at all -> redirect to login
  if (!hasCookieSession && !hasApiKey) {
    console.error(
            "Auth guard redirect: No session cookie found, path=" + 
            path + location.search
        );
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_TYPE_KEY);
    localStorage.removeItem(USER_KEY);
    location.href = LOGIN + '?redirect=' + encodeURIComponent(path + location.search);
    return;
  }

  console.log("Auth guard: Session indicator present =", hasCookieSession);
})();

/* -- Global helpers (available to all dashboard pages) -- */

function getAuth() {
  var tokenType = localStorage.getItem('stronghold-token-type');
  if (tokenType === 'api_key') {
    var token = localStorage.getItem('stronghold-token');
    return token ? 'Bearer ' + token : '';
  }
  return '';
}

function authHeaders() {
  var headers = {
    'Content-Type': 'application/json',
    'X-Stronghold-Request': '1'
  };
  var auth = getAuth();
  if (auth) headers['Authorization'] = auth;
  return headers;
}

function strongholdLogout() {
  // Clear client-side state first
  localStorage.clear();
  sessionStorage.clear();
  document.cookie.split(';').forEach(function(c) {
    var name = c.split('=')[0].trim();
    document.cookie = name + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });
  // Hit /logout (GET) — clears HttpOnly cookies server-side, then redirects to /
  location.href = '/logout';
}

function getStrongholdUser() {
  return localStorage.getItem('stronghold-user') || '';
}

async function parseStrongholdResponse(resp) {
  var contentType = (resp.headers.get('content-type') || '').toLowerCase();
  var text = await resp.text();
  var data = null;

  if (text && contentType.indexOf('application/json') !== -1) {
    try {
      data = JSON.parse(text);
    } catch (e) {
      data = null;
    }
  }

  return { resp: resp, data: data, text: text };
}

function strongholdErrorMessage(parsed) {
  var resp = parsed.resp;
  var data = parsed.data || {};
  var text = (parsed.text || '').trim();

  if (data.detail) return String(data.detail);
  if (data.error && data.error.message) return String(data.error.message);
  if (data.message) return String(data.message);
  if (text) return text.slice(0, 300);
  return 'HTTP ' + resp.status;
}

/* -- Global profile cache (one fetch, many consumers) -- */
window._shProfile = null;
window._shProfileReady = new Promise(function(resolve) { window._shProfileResolve = resolve; });

/* -- Empty state helper (used by all dashboard pages) -- */
function strongholdEmptyState(icon, title, desc, ctaText, ctaHref) {
  var cta = ctaText ? '<a href="' + (ctaHref || '#') + '" style="display:inline-block;margin-top:16px;background:linear-gradient(135deg,#c9a227,#e2a529);color:#1a1a2e;padding:8px 20px;border-radius:6px;text-decoration:none;font-weight:600;font-size:0.8rem;font-family:inherit">' + ctaText + '</a>' : '';
  return '<div style="text-align:center;padding:40px 20px">'
    + '<div style="font-size:3rem;margin-bottom:12px;opacity:0.5">' + icon + '</div>'
    + '<div style="font-family:Playfair Display,serif;color:#e2a529;font-size:1.1rem;margin-bottom:8px">' + title + '</div>'
    + '<div style="color:#6b6b7b;font-size:0.8rem;line-height:1.5;max-width:400px;margin:0 auto">' + desc + '</div>'
    + cta + '</div>';
}

/* ========================================================
 * Header Profile Badge (injected into every page header)
 * ========================================================
 * Adds a user name + profile link to the top-right of the
 * page header. Fetches /auth/session for display name.
 */
(function() {
  'use strict';
  var path = location.pathname;
  if (path === '/' || path === '/login' || path === '/login/callback') return;

  function inject() {
    // Find the <header> element
    var header = document.querySelector('main > header');
    if (!header) return;
    if (header.querySelector('.sh-header-profile')) return;

    // Position badge absolutely in the top-right of the header
    header.style.position = 'relative';

    var badge = document.createElement('div');
    badge.className = 'sh-header-profile';
    badge.style.cssText = 'position:absolute;top:50%;right:2rem;transform:translateY(-50%);display:flex;align-items:center;gap:10px;z-index:10;';

    var nameLink = document.createElement('a');
    nameLink.href = '/dashboard/profile';
    nameLink.style.cssText = 'font-size:0.75rem;color:#6b6b7b;text-decoration:none;transition:color 0.2s;display:flex;align-items:center;gap:6px;';
    nameLink.innerHTML = '<span class="sh-header-avatar" style="width:28px;height:28px;border-radius:50%;overflow:hidden;display:flex;align-items:center;justify-content:center;border:1px solid #4a4a5a;font-size:0.9rem;flex-shrink:0">&#x1F464;</span> <span class="sh-header-username" style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">...</span>';
    nameLink.onmouseenter = function() { nameLink.style.color = '#e2a529'; };
    nameLink.onmouseleave = function() { nameLink.style.color = '#6b6b7b'; };

    var logoutBtn = document.createElement('button');
    logoutBtn.textContent = 'Logout';
    logoutBtn.onclick = strongholdLogout;
    logoutBtn.style.cssText = 'font-size:0.7rem;padding:4px 10px;border-radius:4px;border:1px solid #4a4a5a;background:none;color:#6b6b7b;cursor:pointer;font-family:inherit;transition:all 0.2s;';
    logoutBtn.onmouseenter = function() { logoutBtn.style.borderColor = '#c9a227'; logoutBtn.style.color = '#c9a227'; };
    logoutBtn.onmouseleave = function() { logoutBtn.style.borderColor = '#4a4a5a'; logoutBtn.style.color = '#6b6b7b'; };

    badge.appendChild(nameLink);
    badge.appendChild(logoutBtn);
    header.appendChild(badge);

    // Fetch user info + avatar (cached in window._shProfile for onboarding/nudge)
    _origFetch('/v1/stronghold/profile', {headers: authHeaders()}).then(function(r) {
      if (!r.ok) return _origFetch('/auth/session', {headers: authHeaders()}).then(function(r2) { return r2.ok ? r2.json() : null; });
      return r.json();
    }).then(function(s) {
      if (!s) return;
      window._shProfile = s;
      if (window._shProfileResolve) { window._shProfileResolve(s); window._shProfileResolve = null; }
      var el = badge.querySelector('.sh-header-username');
      if (el) el.textContent = s.display_name || s.username || s.user_id || 'Profile';
      if (s.avatar_data) {
        var avatarEl = badge.querySelector('.sh-header-avatar');
        if (avatarEl) {
          avatarEl.textContent = '';
          var img = document.createElement('img');
          img.src = s.avatar_data;
          img.style.cssText = 'width:100%;height:100%;object-fit:cover';
          avatarEl.appendChild(img);
          avatarEl.style.border = '1px solid #c9a227';
        }
      }
    }).catch(function() {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();


/* ========================================================
 * Security Violation Modal
 * ========================================================
 * Intercepts API responses with type: "security_violation"
 * and shows a full-screen modal with strike info + appeal box.
 */

(function() {
  'use strict';

  // Inject modal CSS once DOM is ready
  function injectStyles() {
    var style = document.createElement('style');
    style.textContent = [
      '#stronghold-strike-overlay {',
      '  position:fixed; top:0; left:0; width:100%; height:100%; z-index:99999;',
      '  background:rgba(13,13,26,0.92); display:flex; align-items:center; justify-content:center;',
      '  font-family:"JetBrains Mono",monospace; animation:sh-fade-in 0.3s ease;',
      '}',
      '@keyframes sh-fade-in { from{opacity:0} to{opacity:1} }',
      '#stronghold-strike-modal {',
      '  background:linear-gradient(180deg,rgba(30,45,74,0.98),rgba(26,26,46,0.99));',
      '  border:2px solid #8b2500; border-top:3px solid #ff4444; border-radius:12px;',
      '  box-shadow:0 0 60px rgba(139,37,0,0.4); max-width:520px; width:95vw; color:#d4d0c8;',
      '}',
      '#stronghold-strike-modal h2 { font-family:"Playfair Display",Georgia,serif; color:#ff4444; margin:0 0 8px; }',
      '#stronghold-strike-modal .sh-strike-badge {',
      '  display:inline-block; background:#2d0000; color:#ff4444; padding:3px 10px;',
      '  border-radius:4px; font-size:0.75rem; font-weight:600; border:1px solid #8b2500;',
      '}',
      '#stronghold-strike-modal .sh-body { font-size:0.85rem; line-height:1.6; color:#b0aaa0; }',
      '#stronghold-strike-modal textarea {',
      '  background:#1a1a2e; border:1px solid #4a4a5a; color:#f5f0e1; border-radius:6px;',
      '  padding:10px; width:100%; font-family:"JetBrains Mono",monospace; font-size:0.8rem;',
      '  resize:vertical; min-height:80px;',
      '}',
      '#stronghold-strike-modal textarea:focus { border-color:#e2a529; outline:none; }',
      '#stronghold-strike-modal .sh-btn {',
      '  padding:8px 20px; border:none; border-radius:6px; cursor:pointer;',
      '  font-family:"JetBrains Mono",monospace; font-size:0.8rem; font-weight:600;',
      '}',
      '#stronghold-strike-modal .sh-btn-appeal { background:linear-gradient(135deg,#c9a227,#e2a529); color:#1a1a2e; }',
      '#stronghold-strike-modal .sh-btn-appeal:hover { box-shadow:0 0 12px rgba(226,165,41,0.3); }',
      '#stronghold-strike-modal .sh-btn-close { background:#4a4a5a; color:#ccc; }',
      '#stronghold-strike-modal .sh-btn-close:hover { background:#6b6b7b; }',
      '#stronghold-strike-modal .sh-locked-msg {',
      '  background:rgba(139,37,0,0.15); border:1px solid rgba(139,37,0,0.3);',
      '  border-radius:6px; padding:12px; font-size:0.8rem; color:#ff6b6b;',
      '}',
      '/* Logout link hover via CSS (not JS — iOS compatible) */',
      '.sh-logout:hover, .sh-logout:focus, .sh-logout:active { color:var(--gold) !important; }',
      '/* ── iPad / iOS touch fixes (global) ── */',
      '/* Make all interactive elements touchable on iOS */',
      '[onclick], [role="button"], button, .btn-iron, .btn-blood, .btn-emerald, .btn-gold, .btn-sm, .btn-primary, .btn-secondary, .btn-green, .btn-amber, .btn-red, .tab-btn, .toggle {',
      '  cursor:pointer !important; -webkit-tap-highlight-color:rgba(226,165,41,0.2);',
      '}',
      '/* Touch feedback on all buttons */',
      'button:active, .btn-gold:active, .btn-iron:active, .btn-emerald:active, .btn-sm:active,',
      '.btn-blood:active, .sidebar-item:active, .tab-btn:active {',
      '  transform:scale(0.97); opacity:0.85; transition:transform 0.1s, opacity 0.1s;',
      '}',
      '/* Fix modals on iOS — prevent scroll-through */',
      '#stronghold-strike-overlay, #tool-modal { touch-action:none; -webkit-overflow-scrolling:touch; }',
      '#stronghold-strike-modal, #tool-modal > div { touch-action:auto; }',
      '/* Fix sidebar overlay touchability */',
      '.sidebar-overlay { cursor:pointer; -webkit-tap-highlight-color:transparent; }',
      '/* Fix hover states getting stuck on touch */',
      '@media (hover:none) {',
      '  .sidebar-item:hover { background:transparent; color:inherit; border-left-color:transparent; }',
      '  .sidebar-item.active:hover { background:rgba(226,165,41,0.12); color:var(--gold); border-left-color:var(--gold); }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  }

  // Build and show the strike modal
  function showStrikeModal(errorData) {
    // Remove any existing modal
    var existing = document.getElementById('stronghold-strike-overlay');
    if (existing) existing.remove();

    var strike = errorData.strike || {};
    var strikeNum = strike.number || 1;
    var maxStrikes = strike.max || 3;
    var flags = (errorData.flags || []).join(', ');
    var isLocked = !!strike.locked_until;
    var isDisabled = !!strike.account_disabled;

    // Title varies by severity
    var title, subtitle;
    if (isDisabled) {
      title = 'Account Disabled';
      subtitle = 'Your account has been disabled due to repeated security violations.';
    } else if (isLocked) {
      title = 'Account Locked';
      subtitle = 'Your account has been temporarily locked for 8 hours.';
    } else {
      title = 'Security Violation Detected';
      subtitle = 'Warning ' + strikeNum + ' of ' + maxStrikes;
    }

    var overlay = document.createElement('div');
    overlay.id = 'stronghold-strike-overlay';

    var modal = document.createElement('div');
    modal.id = 'stronghold-strike-modal';

    // Header
    var header = document.createElement('div');
    header.style.cssText = 'padding:24px 24px 16px; border-bottom:1px solid #4a4a5a;';
    header.innerHTML = '<h2 style="font-size:1.4rem">' + escHtml(title) + '</h2>'
      + '<span class="sh-strike-badge">Strike ' + strikeNum + ' / ' + maxStrikes + '</span>'
      + (flags ? ' <span style="font-size:0.7rem;color:#6b6b7b;margin-left:8px">' + escHtml(flags) + '</span>' : '');
    modal.appendChild(header);

    // Body
    var body = document.createElement('div');
    body.className = 'sh-body';
    body.style.cssText = 'padding:20px 24px;';

    if (isDisabled) {
      body.innerHTML = '<div class="sh-locked-msg">'
        + '<p>Your account has been disabled due to repeated security violations.</p>'
        + '<p style="margin-top:8px">An <strong>organization administrator</strong> must re-enable your account.</p>'
        + '</div>';
    } else if (isLocked) {
      body.innerHTML = '<div class="sh-locked-msg">'
        + '<p>Your account is locked until <strong>' + escHtml(strike.locked_until) + '</strong>.</p>'
        + '<p style="margin-top:8px">A <strong>team administrator</strong> must unlock your account, or wait for the lockout to expire.</p>'
        + '</div>';
    } else {
      body.innerHTML = '<p>Your attempt has been logged, your account has been flagged for '
        + 'increased scrutiny, and an administrator has been notified.</p>'
        + '<p style="margin-top:12px">If you believe this is an error and would like to provide '
        + 'further detail to the administrators reviewing your case, please enter that information below:</p>';
    }
    modal.appendChild(body);

    // Appeal section (only for non-disabled, non-locked users)
    if (!isDisabled && !isLocked) {
      var appealSection = document.createElement('div');
      appealSection.style.cssText = 'padding:0 24px 20px;';
      appealSection.innerHTML = '<textarea id="sh-appeal-text" placeholder="Explain why you believe this was a false positive..."></textarea>';
      modal.appendChild(appealSection);
    }

    // Footer buttons
    var footer = document.createElement('div');
    footer.style.cssText = 'padding:16px 24px; border-top:1px solid #4a4a5a; display:flex; gap:10px; justify-content:flex-end;';

    if (!isDisabled && !isLocked) {
      var appealBtn = document.createElement('button');
      appealBtn.className = 'sh-btn sh-btn-appeal';
      appealBtn.textContent = 'Submit Appeal';
      appealBtn.onclick = function() { submitAppeal(overlay); };
      footer.appendChild(appealBtn);
    }

    var closeBtn = document.createElement('button');
    closeBtn.className = 'sh-btn sh-btn-close';
    closeBtn.textContent = 'Dismiss';
    closeBtn.onclick = function() { overlay.remove(); };
    footer.appendChild(closeBtn);

    modal.appendChild(footer);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  function submitAppeal(overlay) {
    var textarea = document.getElementById('sh-appeal-text');
    var text = textarea ? textarea.value.trim() : '';
    if (!text) {
      textarea.style.borderColor = '#ff4444';
      textarea.placeholder = 'Please enter an explanation before submitting.';
      return;
    }

    var btn = overlay.querySelector('.sh-btn-appeal');
    if (btn) { btn.textContent = 'Submitting...'; btn.disabled = true; }

    fetch('/v1/stronghold/appeals', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({text: text}),
    }).then(function(resp) {
      if (resp.ok) {
        var body = overlay.querySelector('.sh-body');
        if (body) {
          body.innerHTML = '<p style="color:#4ade80">Your appeal has been submitted and will be reviewed by an administrator.</p>';
        }
        var appealSection = overlay.querySelector('div[style*="padding:0 24px 20px"]');
        if (appealSection) appealSection.remove();
        if (btn) btn.remove();
      } else {
        if (btn) { btn.textContent = 'Submit Appeal'; btn.disabled = false; }
      }
    }).catch(function() {
      if (btn) { btn.textContent = 'Submit Appeal'; btn.disabled = false; }
    });
  }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = String(s || '');
    return d.innerHTML;
  }

  // -- Connection banner (shows when server is down, auto-hides on recovery) --

  var _shServerDown = false;
  var _shPollTimer = null;
  function _shShowBanner(show) {
    var banner = document.getElementById('sh-connection-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'sh-connection-banner';
      banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99998;background:#8b2500;color:#fff;text-align:center;padding:10px 16px;font-size:0.85rem;font-family:"JetBrains Mono",monospace;display:none;box-shadow:0 2px 8px rgba(0,0,0,0.5);';
      banner.textContent = 'Server unreachable \u2014 the fortress is rebuilding. Will reconnect automatically.';
      document.body.prepend(banner);
    }
    banner.style.display = show ? 'block' : 'none';
    _shServerDown = show;

    // Start polling for recovery when down, stop when recovered
    if (show && !_shPollTimer) {
      _shPollTimer = setInterval(function() {
        _origFetch('/health').then(function(r) {
          if (r.ok) {
            _shShowBanner(false);
            location.reload(); // Reload page to restore full state
          }
        }).catch(function() {});
      }, 5000);
    }
    if (!show && _shPollTimer) {
      clearInterval(_shPollTimer);
      _shPollTimer = null;
    }
  }

  // -- Wrap fetch to intercept security violations AND network errors --

  var _origFetch = window.fetch;
  window.fetch = function() {
    return _origFetch.apply(this, arguments).then(function(resp) {
      // Server is reachable — hide banner if it was showing
      if (_shServerDown) _shShowBanner(false);

      // Intercept 400/403 security violations
      if ((resp.status === 400 || resp.status === 403) && resp.headers.get('content-type') && resp.headers.get('content-type').indexOf('json') !== -1) {
        var clone = resp.clone();
        clone.json().then(function(data) {
          if (data && data.error && data.error.type === 'security_violation') {
            showStrikeModal(data.error);
          }
        }).catch(function() {});
      }
      return resp;
    }).catch(function(err) {
      // Network error (server down, connection refused, etc.)
      _shShowBanner(true);
      throw err; // Re-throw so callers still see the error
    });
  };

  // Inject styles when DOM is ready
  function injectProfileStyles() {
    var s = document.createElement('style');
    s.textContent = [
      '@media (max-width: 768px) {',
      '  .sh-header-profile { right: 1rem !important; }',
      '  .sh-header-profile .sh-header-username { display: none !important; }',
      '}',
    ].join('\n');
    document.head.appendChild(s);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { injectStyles(); injectProfileStyles(); });
  } else {
    injectStyles();
    injectProfileStyles();
  }

  // ── Castle Tower Mode (global — applies on every page) ──
  function _shInjectTowerCSS() {
    if (document.getElementById('sh-tower-css')) return;
    var style = document.createElement('style');
    style.id = 'sh-tower-css';
    style.textContent = [
      '.sidebar-tower {',
      '  background: repeating-linear-gradient(0deg,rgba(74,74,90,0.08) 0px,rgba(74,74,90,0.08) 1px,transparent 1px,transparent 40px),',
      '  repeating-linear-gradient(90deg,rgba(74,74,90,0.05) 0px,rgba(74,74,90,0.05) 1px,transparent 1px,transparent 80px),',
      '  linear-gradient(180deg, #0a0e1a, #12152a 30%, #0d1020) !important;',
      '  border-right: 3px solid #2a2a3a !important;',
      '  box-shadow: inset -4px 0 12px rgba(0,0,0,0.4), 2px 0 8px rgba(0,0,0,0.3) !important;',
      '}',
      '.sidebar-tower::before {',
      '  content: ""; display: block; height: 16px;',
      '  background: repeating-linear-gradient(90deg,#0a0e1a 0px,#0a0e1a 20px,transparent 20px,transparent 30px,#0a0e1a 30px,#0a0e1a 50px);',
      '  border-bottom: 2px solid #2a2a3a;',
      '}',
      '.sidebar-tower .sidebar-item::before {',
      '  content: ""; display: inline-block; width: 3px; height: 14px;',
      '  background: rgba(226,165,41,0.15); border-radius: 1px; margin-right: -6px; flex-shrink: 0;',
      '}',
      '.sidebar-tower .sidebar-item:hover::before { background: rgba(226,165,41,0.4); box-shadow: 0 0 6px rgba(226,165,41,0.3); }',
      '.sidebar-tower .sidebar-item.active::before { background: #e2a529; box-shadow: 0 0 8px rgba(226,165,41,0.5); }',
      '.sidebar-tower .tower-crest { animation: torch-flicker 3s ease-in-out infinite alternate; }',
      '@keyframes torch-flicker {',
      '  0% { text-shadow: 0 0 25px rgba(226,165,41,0.5), 0 0 50px rgba(226,165,41,0.2); }',
      '  50% { text-shadow: 0 0 35px rgba(226,165,41,0.7), 0 0 70px rgba(226,165,41,0.4); }',
      '  100% { text-shadow: 0 0 20px rgba(226,165,41,0.4), 0 0 45px rgba(226,165,41,0.15); }',
      '}',
      '.sidebar-tower .py-4 > a:nth-child(even) { border-bottom: 1px solid rgba(42,42,58,0.5); }',
    ].join('\n');
    document.head.appendChild(style);
  }

  function _shApplyTower() {
    if (localStorage.getItem('sh_tower_mode') !== '1') return;
    _shInjectTowerCSS();
    // Apply class when DOM is ready
    function apply() {
      var sidebar = document.getElementById('sidebar');
      if (sidebar) sidebar.classList.add('sidebar-tower');
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', apply);
    } else {
      apply();
    }
  }
  _shApplyTower();

  // ── Dungeon Badge (notification bubble for active strikes) ──
  function _shLoadDungeonBadge() {
    _origFetch('/v1/stronghold/admin/strikes', {headers: authHeaders()}).then(function(resp) {
      if (!resp.ok) return;
      return resp.json();
    }).then(function(records) {
      if (!records || !Array.isArray(records) || records.length === 0) return;
      var badge = document.getElementById('sh-dungeon-badge');
      if (!badge) return;
      badge.textContent = records.length;
      badge.style.display = 'flex';
    }).catch(function() {});
  }

  // Inject dungeon badge pulse animation
  (function() {
    var style = document.createElement('style');
    style.textContent = '@keyframes sh-badge-pulse { 0%,100%{box-shadow:0 0 4px rgba(139,37,0,0.4)} 50%{box-shadow:0 0 12px rgba(139,37,0,0.8)} }';
    document.head.appendChild(style);
  })();

  // ── Admin Sidebar Links (injected based on user roles) ──
  function _shInjectAdminLinks() {
    function inject() {
      var sidebar = document.getElementById('sidebar');
      if (!sidebar) return;
      // Find the Profile section (py-2 border-t) to insert admin links before it
      var profileSection = null;
      var sections = sidebar.querySelectorAll('.py-2.border-t');
      for (var i = 0; i < sections.length; i++) {
        if (sections[i].querySelector('a[href="/dashboard/profile"]')) {
          profileSection = sections[i];
          break;
        }
      }
      if (!profileSection) return;

      _origFetch('/auth/session', {headers: authHeaders()}).then(function(resp) {
        if (!resp.ok) return;
        return resp.json();
      }).then(function(session) {
        if (!session || !session.authenticated) return;
        var roles = session.roles || [];

        var hasTeamAdmin = roles.indexOf('team_admin') !== -1 || roles.indexOf('admin') !== -1;
        var hasOrgAdmin = roles.indexOf('org_admin') !== -1 || roles.indexOf('admin') !== -1;

        if (!hasTeamAdmin && !hasOrgAdmin) return;

        var adminDiv = document.createElement('div');
        adminDiv.className = 'py-2 border-t border-[var(--iron)]';
        adminDiv.style.borderColor = 'var(--iron)';
        var label = document.createElement('div');
        label.className = 'px-5 py-1 text-xs font-bold uppercase tracking-wider';
        label.style.color = 'var(--gold-dim)';
        label.textContent = 'Admin';
        adminDiv.appendChild(label);

        // Dungeon link with notification badge (visible to team_admin+)
        var dungeonLink = document.createElement('a');
        dungeonLink.href = '/dashboard/dungeon';
        dungeonLink.className = 'sidebar-item' + (location.pathname === '/dashboard/dungeon' ? ' active' : '');
        dungeonLink.style.position = 'relative';
        dungeonLink.innerHTML = '<span style="width:24px;text-align:center">&#x26D3;</span> Dungeon'
          + '<span id="sh-dungeon-badge" style="display:none;position:absolute;right:12px;top:50%;transform:translateY(-50%);'
          + 'background:#8b2500;color:#fff;font-size:0.6rem;font-weight:700;min-width:18px;height:18px;'
          + 'border-radius:9px;display:none;align-items:center;justify-content:center;padding:0 5px;'
          + 'box-shadow:0 0 8px rgba(139,37,0,0.5);animation:sh-badge-pulse 2s ease-in-out infinite"></span>';
        adminDiv.appendChild(dungeonLink);

        if (hasTeamAdmin) {
          var teamLink = document.createElement('a');
          teamLink.href = '/dashboard/team';
          teamLink.className = 'sidebar-item' + (location.pathname === '/dashboard/team' ? ' active' : '');
          teamLink.innerHTML = '<span style="width:24px;text-align:center">&#x1F3E0;</span> Barracks';
          adminDiv.appendChild(teamLink);
        }
        if (hasOrgAdmin) {
          var orgLink = document.createElement('a');
          orgLink.href = '/dashboard/org';
          orgLink.className = 'sidebar-item' + (location.pathname === '/dashboard/org' ? ' active' : '');
          orgLink.innerHTML = '<span style="width:24px;text-align:center">&#x1F451;</span> Throne Room';
          adminDiv.appendChild(orgLink);
        }

        sidebar.insertBefore(adminDiv, profileSection);

        // Fetch strike count for dungeon badge
        _shLoadDungeonBadge();
      }).catch(function() {});
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', inject);
    } else {
      inject();
    }
  }
  _shInjectAdminLinks();
})();

/* ========================================================
 * Loading Animation CSS (global)
 * ======================================================== */
(function() {
  var s = document.createElement('style');
  s.textContent = '@keyframes sh-load-pulse{0%,100%{opacity:.3}50%{opacity:1}}.sh-loading{animation:sh-load-pulse 1.5s ease-in-out infinite;color:#6b6b7b;font-size:0.85rem;}';
  document.head.appendChild(s);
})();

/* ========================================================
 * First-Login Onboarding Wizard
 * ========================================================
 * Shows once for new users. 4 steps (+ admin step).
 * Gated by localStorage.sh_onboarding_complete.
 */
(function() {
  'use strict';
  var path = location.pathname;
  if (path === '/' || path === '/login' || path === '/login/callback') return;
  if (localStorage.getItem('sh_onboarding_complete') === '1') return;

  function launch(profile) {
    // Skip if user has engagement (avatar + bio + points > 0 = not new)
    if (profile && profile.avatar_data && profile.bio && profile.points > 0) {
      localStorage.setItem('sh_onboarding_complete', '1');
      return;
    }
    showWizard(profile);
  }

  function showWizard(profile) {
    var roles = (profile && profile.roles) || [];
    var isAdmin = roles.indexOf('admin') !== -1 || roles.indexOf('org_admin') !== -1 || roles.indexOf('team_admin') !== -1;
    var displayName = (profile && (profile.display_name || profile.email || '').split('@')[0]) || 'traveler';

    var steps = [
      {
        icon: '&#x1F3F0;',
        title: 'Welcome to the Stronghold, ' + displayName,
        body: 'You stand before the gates of the most secure agent governance platform. '
          + 'Within these walls, AI agents serve at your command &mdash; routed by intelligence, '
          + 'guarded by vigilance, governed by policy.'
      },
      {
        icon: '&#x1F3DB;',
        title: 'The Great Hall',
        body: 'Your command center. Issue missions to AI agents, chat with the fortress, '
          + 'and track your quests. This is where every adventure begins.'
      },
      {
        icon: '&#x1F5FA;',
        title: 'Explore the Fortress',
        body: '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;text-align:left;margin-top:12px">'
          + '<a href="/dashboard/agents" style="background:rgba(226,165,41,0.06);border:1px solid #4a4a5a;border-radius:6px;padding:12px;text-decoration:none;color:inherit"><div style="font-size:1.2rem">&#x2694;</div><div style="color:#e2a529;font-size:0.8rem;font-weight:600">Knights</div><div style="font-size:0.7rem;color:#6b6b7b">Your agent roster</div></a>'
          + '<a href="/dashboard/skills" style="background:rgba(226,165,41,0.06);border:1px solid #4a4a5a;border-radius:6px;padding:12px;text-decoration:none;color:inherit"><div style="font-size:1.2rem">&#x1F6E1;</div><div style="color:#e2a529;font-size:0.8rem;font-weight:600">Armory</div><div style="font-size:0.7rem;color:#6b6b7b">Skills &amp; tools</div></a>'
          + '<a href="/dashboard/security" style="background:rgba(226,165,41,0.06);border:1px solid #4a4a5a;border-radius:6px;padding:12px;text-decoration:none;color:inherit"><div style="font-size:1.2rem">&#x1F5FC;</div><div style="color:#e2a529;font-size:0.8rem;font-weight:600">Watchtower</div><div style="font-size:0.7rem;color:#6b6b7b">Security &amp; audit</div></a>'
          + '<a href="/dashboard/mcp" style="background:rgba(226,165,41,0.06);border:1px solid #4a4a5a;border-radius:6px;padding:12px;text-decoration:none;color:inherit"><div style="font-size:1.2rem">&#x1F525;</div><div style="color:#e2a529;font-size:0.8rem;font-weight:600">Forge</div><div style="font-size:0.7rem;color:#6b6b7b">MCP servers</div></a>'
          + '</div>'
      }
    ];

    if (isAdmin) {
      steps.push({
        icon: '&#x1F511;',
        title: 'The Inner Chambers',
        body: 'As an administrator, you have access to restricted areas:'
          + '<div style="margin-top:10px;font-size:0.8rem;line-height:1.8">'
          + '&#x26D3; <strong>Dungeon</strong> &mdash; Security violations &amp; appeals<br>'
          + '&#x1F3E0; <strong>Barracks</strong> &mdash; Manage your team<br>'
          + '&#x1F451; <strong>Throne Room</strong> &mdash; Organization governance</div>'
      });
    }

    steps.push({
      icon: '&#x1F464;',
      title: 'Begin Your Journey',
      body: 'Every hero needs an identity. Set your avatar and write your tale to claim '
        + 'your place in the fortress and start earning rank.'
        + '<div style="margin-top:16px"><a href="/dashboard/profile" onclick="document.getElementById(\'sh-onboard-overlay\').remove();localStorage.setItem(\'sh_onboarding_complete\',\'1\')" '
        + 'style="background:linear-gradient(135deg,#c9a227,#e2a529);color:#1a1a2e;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:0.85rem;display:inline-block">Visit Profile</a></div>'
    });

    var currentStep = 0;

    var overlay = document.createElement('div');
    overlay.id = 'sh-onboard-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:99997;background:rgba(13,13,26,0.95);display:flex;align-items:center;justify-content:center;font-family:JetBrains Mono,monospace;animation:sh-fade-in 0.4s ease;padding:16px;';

    var card = document.createElement('div');
    card.style.cssText = 'background:linear-gradient(180deg,rgba(30,45,74,0.98),rgba(26,26,46,0.99));border:2px solid #4a4a5a;border-top:3px solid #c9a227;border-radius:12px;max-width:520px;width:100%;box-shadow:0 0 80px rgba(226,165,41,0.1);color:#d4d0c8;';

    function render() {
      var s = steps[currentStep];
      card.innerHTML = '<div style="text-align:center;padding:32px 32px 16px">'
        + '<div style="font-size:4rem;margin-bottom:12px">' + s.icon + '</div>'
        + '<div style="font-family:Playfair Display,serif;color:#e2a529;font-size:1.4rem;margin-bottom:12px">' + s.title + '</div>'
        + '<div style="font-size:0.8rem;line-height:1.7;color:#b0aaa0">' + s.body + '</div>'
        + '</div>'
        // Dots
        + '<div style="display:flex;gap:8px;justify-content:center;padding:8px">'
        + steps.map(function(_, i) { return '<div style="width:8px;height:8px;border-radius:50%;background:' + (i === currentStep ? '#e2a529' : '#4a4a5a') + '"></div>'; }).join('')
        + '</div>'
        // Buttons
        + '<div style="padding:12px 32px 24px;display:flex;justify-content:space-between;align-items:center">'
        + '<button id="sh-ob-skip" style="background:none;border:none;color:#6b6b7b;cursor:pointer;font-family:inherit;font-size:0.75rem;padding:4px 8px">Skip tour</button>'
        + '<div style="display:flex;gap:8px">'
        + (currentStep > 0 ? '<button id="sh-ob-back" style="background:#4a4a5a;color:#d4d0c8;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-family:inherit;font-size:0.8rem">Back</button>' : '')
        + (currentStep < steps.length - 1
          ? '<button id="sh-ob-next" style="background:linear-gradient(135deg,#c9a227,#e2a529);color:#1a1a2e;border:none;border-radius:6px;padding:8px 20px;cursor:pointer;font-family:inherit;font-size:0.8rem;font-weight:600">Next</button>'
          : '<button id="sh-ob-done" style="background:linear-gradient(135deg,#c9a227,#e2a529);color:#1a1a2e;border:none;border-radius:6px;padding:8px 20px;cursor:pointer;font-family:inherit;font-size:0.8rem;font-weight:600">Enter the Fortress</button>')
        + '</div></div>';

      // Wire buttons
      var skipBtn = card.querySelector('#sh-ob-skip');
      if (skipBtn) skipBtn.onclick = dismiss;
      var backBtn = card.querySelector('#sh-ob-back');
      if (backBtn) backBtn.onclick = function() { currentStep--; render(); };
      var nextBtn = card.querySelector('#sh-ob-next');
      if (nextBtn) nextBtn.onclick = function() { currentStep++; render(); };
      var doneBtn = card.querySelector('#sh-ob-done');
      if (doneBtn) doneBtn.onclick = dismiss;
    }

    function dismiss() {
      localStorage.setItem('sh_onboarding_complete', '1');
      overlay.remove();
    }

    render();
    overlay.appendChild(card);
    document.body.appendChild(overlay);
  }

  // Wait for profile data (cached by header badge fetch)
  window._shProfileReady.then(function(profile) {
    launch(profile);
  });
})();

/* ========================================================
 * Profile Setup Nudge Toast
 * ========================================================
 * After onboarding dismissed, nudge incomplete profiles
 * on the next 3 page loads. Non-blocking bottom-right toast.
 */
(function() {
  'use strict';
  var path = location.pathname;
  if (path === '/' || path === '/login' || path === '/login/callback' || path === '/dashboard/profile') return;
  if (localStorage.getItem('sh_onboarding_complete') !== '1') return;
  if (localStorage.getItem('sh_profile_nudge_done') === '1') return;

  var count = parseInt(localStorage.getItem('sh_profile_nudge_count') || '0');
  if (count >= 3) { localStorage.setItem('sh_profile_nudge_done', '1'); return; }

  window._shProfileReady.then(function(p) {
    if (!p) return;
    if (p.avatar_data && p.bio) { localStorage.setItem('sh_profile_nudge_done', '1'); return; }
    localStorage.setItem('sh_profile_nudge_count', String(count + 1));

    setTimeout(function() {
      var toast = document.createElement('div');
      toast.id = 'sh-profile-nudge';
      toast.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9990;'
        + 'background:linear-gradient(135deg,rgba(30,45,74,0.98),rgba(26,26,46,0.99));'
        + 'border:1px solid #c9a227;border-radius:8px;padding:16px 20px;max-width:320px;'
        + 'box-shadow:0 4px 20px rgba(0,0,0,0.4);animation:sh-fade-in 0.4s ease;font-size:0.8rem;';
      toast.innerHTML = '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
        + '<span style="font-size:1.5rem">&#x1F6E1;</span>'
        + '<span style="color:#e2a529;font-family:Playfair Display,serif;font-size:0.95rem">Begin Your Journey</span></div>'
        + '<p style="color:#b0aaa0;line-height:1.5;margin:0 0 12px">Every ' + (p.rank || 'hero') + ' needs a sigil. Set your avatar and write your tale.</p>'
        + '<div style="display:flex;gap:8px">'
        + '<a href="/dashboard/profile" style="background:linear-gradient(135deg,#c9a227,#e2a529);color:#1a1a2e;padding:6px 16px;border-radius:4px;text-decoration:none;font-weight:600;font-size:0.75rem">Visit Profile</a>'
        + '<button onclick="this.parentElement.parentElement.remove();localStorage.setItem(\'sh_profile_nudge_done\',\'1\')" '
        + 'style="background:none;border:1px solid #4a4a5a;color:#6b6b7b;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:0.75rem;font-family:inherit">Not Now</button>'
        + '</div>';
      document.body.appendChild(toast);
    }, 2000);
  });
})();

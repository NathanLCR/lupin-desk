/**
 * Pet Skills panel (/static/skills.js -> window.DeskSkills)
 * Lets the user trigger the pet's interactive tricks and enable/disable agent skill packs.
 */
(function (global) {
  'use strict';

  let containerEl = null;
  let options = {};
  let cachedData = { packs: [], tricks: [], enabled_ids: [] };

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function render() {
    if (!containerEl) return;
    const tricks = Array.isArray(cachedData.tricks) ? cachedData.tricks : [];
    const packs = Array.isArray(cachedData.packs) ? cachedData.packs : [];

    containerEl.innerHTML = `
      <div class="skills-layout">
        <section class="panel-card skills-section">
          <div class="panel-head">
            <h2>🎭 Pet Interactive Tricks</h2>
            <span class="diag-pill is-ok">${tricks.length} tricks</span>
          </div>
          <p class="diag-hint">
            Tap to make the pet do it right away, or ask by voice/chat.
          </p>
          <div class="trick-grid">
            ${tricks
              .map(
                (trick) => `
                  <button
                    type="button"
                    class="trick-card-btn"
                    data-trick-id="${escapeHtml(trick.id)}"
                    title="${escapeHtml(trick.description)}"
                  >
                    <span class="trick-icon">${escapeHtml(trick.icon)}</span>
                    <span class="trick-meta">
                      <strong>${escapeHtml(trick.name)}</strong>
                      <small>${escapeHtml(trick.voice_hint)}</small>
                    </span>
                  </button>
                `
              )
              .join('')}
          </div>
        </section>

        <section class="panel-card skills-section">
          <div class="panel-head">
            <h2>✨ Agent Skill Packs</h2>
            <span class="diag-pill">${(cachedData.enabled_ids || []).length}/${packs.length} active</span>
          </div>
          <p class="diag-hint">
            Enable or disable behavior modules injected into the copilot.
          </p>
          <div class="skills-grid">
            ${packs
              .map(
                (pack) => `
                  <article class="skill-card ${pack.enabled ? 'is-enabled' : ''}">
                    <div class="skill-card-head">
                      <span class="skill-title">
                        <span class="skill-icon">${escapeHtml(pack.icon)}</span>
                        <strong>${escapeHtml(pack.name)}</strong>
                      </span>
                      <button
                        type="button"
                        class="skill-toggle-btn ${pack.enabled ? 'is-on' : ''}"
                        data-skill-id="${escapeHtml(pack.id)}"
                        data-enabled="${pack.enabled ? 'true' : 'false'}"
                        aria-pressed="${pack.enabled ? 'true' : 'false'}"
                        aria-label="${escapeHtml(pack.name)}: ${pack.enabled ? 'Active' : 'Inactive'}"
                      >
                        ${pack.enabled ? 'Active' : 'Inactive'}
                      </button>
                    </div>
                    <p class="skill-desc">${escapeHtml(pack.description)}</p>
                    <div class="skill-voice-hint">🎙️ ${escapeHtml(pack.voice_hint)}</div>
                  </article>
                `
              )
              .join('')}
          </div>
        </section>
      </div>
    `;

    containerEl.querySelectorAll('.trick-card-btn').forEach((btn) => {
      btn.addEventListener('click', () => triggerTrick(btn.dataset.trickId || ''));
    });

    containerEl.querySelectorAll('.skill-toggle-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.skillId || '';
        const currentlyEnabled = btn.dataset.enabled === 'true';
        toggleSkill(id, !currentlyEnabled);
      });
    });
  }

  async function refresh() {
    try {
      const res = await fetch('/api/skills');
      if (!res.ok) return;
      cachedData = await res.json();
      render();
    } catch {
      // Keep the current state on a transient failure
    }
  }

  async function toggleSkill(skillId, nextEnabled) {
    if (!skillId) return;
    try {
      const res = await fetch(`/api/skills/${encodeURIComponent(skillId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: Boolean(nextEnabled) }),
      });
      if (!res.ok) return;
      cachedData = await res.json();
      render();
    } catch {
      // Silent
    }
  }

  async function triggerTrick(trickId) {
    if (!trickId) return;
    if (typeof options.onPlayTrick === 'function') {
      options.onPlayTrick(trickId);
    }
    try {
      await fetch(`/api/skills/tricks/${encodeURIComponent(trickId)}`, { method: 'POST' });
    } catch {
      // The visual/sound trick already ran locally
    }
  }

  const DeskSkills = {
    init(rootEl, opts = {}) {
      containerEl = rootEl;
      options = opts || {};
      render();
    },

    activate() {
      refresh();
    },

    refresh,
  };

  global.DeskSkills = DeskSkills;
})(typeof window !== 'undefined' ? window : globalThis);

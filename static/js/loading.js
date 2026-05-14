/**
 * Global loading overlay + form helpers for Xero Runner.
 *
 * Cancel: window.stop() + AbortController.abort() when registered — stops client wait;
 * server-side work may still complete (no cancellation API on the server).
 *
 * Reuse:
 *   - Forms: data-loader-form="true", optional data-loader-message, data-loader-download="true"
 *   - Buttons: .js-loader-trigger, optional data-loader-message, data-loader-button-text
 *   - Lock targets while busy: .js-disable-while-loading
 *   - Manual flows (fetch): RunnerLoading.showLoader(msg, button) / hideLoader()
 */
(function (global) {
  "use strict";

  var COOKIE_NAME = "unleashed_download_token";
  var POLL_MS = 300;
  var FALLBACK_MS = 10 * 60 * 1000;

  var loaderEl;
  var loaderTextEl;
  var cancelBtn;
  var pollTimer = null;
  var fallbackTimer = null;
  var activeButton = null;
  var activeButtonOriginalHtml = null;
  var activeButtonOriginalDisabled = null;
  var lockedElements = [];
  var abortController = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function generateDownloadToken() {
    return "dl_" + Date.now() + "_" + Math.random().toString(36).slice(2, 14);
  }

  function getCookie(name) {
    var m = document.cookie.match(
      new RegExp("(?:^|; )" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)")
    );
    return m ? decodeURIComponent(m[1]) : "";
  }

  function clearCookie(name) {
    document.cookie = name + "=; Path=/; Max-Age=0; SameSite=Lax";
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function stopFallback() {
    if (fallbackTimer) {
      clearTimeout(fallbackTimer);
      fallbackTimer = null;
    }
  }

  function stopAllTimers() {
    stopPolling();
    stopFallback();
  }

  function collectLockTargets(root) {
    var sel =
      ".js-loader-trigger, .js-disable-while-loading, [data-loader-lock='true']";
    var set = new Set();
    (root || document).querySelectorAll(sel).forEach(function (el) {
      set.add(el);
    });
    return Array.from(set);
  }

  /** Disable all run/lock targets (typically includes the active button). */
  function lockRunControls() {
    unlockRunControls();
    collectLockTargets().forEach(function (el) {
      lockedElements.push([el, el.disabled]);
      el.disabled = true;
    });
  }

  function unlockRunControls() {
    lockedElements.forEach(function (pair) {
      var el = pair[0];
      var was = pair[1];
      if (el && el.isConnected) el.disabled = was;
    });
    lockedElements = [];
  }

  function setButtonLoadingState(btn) {
    if (!btn || !btn.classList) return;
    var alt =
      btn.getAttribute("data-loader-button-text") || "Running…";
    activeButtonOriginalHtml = btn.innerHTML;
    activeButtonOriginalDisabled = btn.disabled;
    btn.classList.add("is-loading");
    btn.textContent = "";
    var spin = document.createElement("span");
    spin.className = "btn-inline-spinner";
    spin.setAttribute("aria-hidden", "true");
    var lab = document.createElement("span");
    lab.className = "btn-loader-label";
    lab.textContent = alt;
    btn.appendChild(spin);
    btn.appendChild(lab);
  }

  function restoreButtonLoadingState(btn) {
    if (!btn || !btn.classList || activeButtonOriginalHtml === null) return;
    btn.classList.remove("is-loading");
    btn.innerHTML = activeButtonOriginalHtml;
    if (activeButtonOriginalDisabled !== null) btn.disabled = activeButtonOriginalDisabled;
    activeButtonOriginalHtml = null;
    activeButtonOriginalDisabled = null;
  }

  /**
   * @param {string} message
   * @param {HTMLElement|null} btn - button to show inline spinner (optional)
   * @param {{ deferButtonLock?: boolean }} opts - if true, skip locking + spinner until caller handles it (native form submit)
   */
  function showLoader(message, btn, opts) {
    opts = opts || {};
    loaderEl = loaderEl || $("#globalLoader");
    loaderTextEl = loaderTextEl || $("#loaderText");
    if (!loaderEl) return;

    activeButton = btn || null;

    loaderEl.classList.remove("hidden");
    loaderEl.setAttribute("aria-busy", "true");
    if (loaderTextEl) loaderTextEl.textContent = message || "Processing…";

    stopAllTimers();
    fallbackTimer = setTimeout(function () {
      hideLoader();
    }, FALLBACK_MS);

    if (!opts.deferButtonLock) {
      if (activeButton) setButtonLoadingState(activeButton);
      lockRunControls();
    }
  }

  function hideLoader() {
    stopAllTimers();
    loaderEl = loaderEl || $("#globalLoader");
    if (loaderEl) {
      loaderEl.classList.add("hidden");
      loaderEl.setAttribute("aria-busy", "false");
    }
    if (loaderTextEl) loaderTextEl.textContent = "Processing…";

    unlockRunControls();
    if (activeButton) restoreButtonLoadingState(activeButton);
    activeButton = null;

    document.querySelectorAll("form[data-loader-submitting='1']").forEach(function (f) {
      f.removeAttribute("data-loader-submitting");
    });

    try {
      document.dispatchEvent(new CustomEvent("runnerloading:end", { bubbles: true }));
    } catch (e) {}
  }

  function onCancelClick() {
    try {
      if (abortController) abortController.abort();
    } catch (e) {}
    try {
      window.stop();
    } catch (e) {}
    hideLoader();
  }

  /**
   * Poll cookie after a file response sets unleashed_download_token.
   * @param {{ signal?: AbortSignal, suppressHide?: boolean }} options — use suppressHide for fetch+blob flows
   *   where the caller will call hideLoader() in finally; still clears cookie when matched.
   */
  function watchDownloadToken(token, options) {
    options = options || {};
    var signal = options.signal;
    var suppressHide = !!options.suppressHide;
    stopPolling();
    if (!token) return;

    var done = false;
    function finish() {
      if (done) return;
      done = true;
      stopPolling();
      if (getCookie(COOKIE_NAME) === token) clearCookie(COOKIE_NAME);
      if (!suppressHide) hideLoader();
    }

    pollTimer = setInterval(function () {
      if (signal && signal.aborted) {
        finish();
        return;
      }
      if (getCookie(COOKIE_NAME) === token) finish();
    }, POLL_MS);

    if (signal) signal.addEventListener("abort", finish, { once: true });
  }

  function bindCancel() {
    cancelBtn = cancelBtn || $("#loaderCancelButton");
    if (!cancelBtn || cancelBtn.dataset.bound) return;
    cancelBtn.dataset.bound = "1";
    cancelBtn.addEventListener("click", onCancelClick);
  }

  function bindForms() {
    document.querySelectorAll("form[data-loader-form='true']").forEach(function (form) {
      if (form.dataset.loaderBound) return;
      form.dataset.loaderBound = "1";

      form.addEventListener(
        "submit",
        function (e) {
          if (form.getAttribute("data-loader-submitting") === "1") {
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          form.setAttribute("data-loader-submitting", "1");

          var msg =
            form.getAttribute("data-loader-message") || "Processing…";
          var submitter = e.submitter || null;

          showLoader(msg, null, { deferButtonLock: true });

          var downloadMode = form.getAttribute("data-loader-download") === "true";
          if (downloadMode) {
            var input = form.querySelector('input[name="download_token"]');
            if (!input) {
              input = document.createElement("input");
              input.type = "hidden";
              input.name = "download_token";
              form.appendChild(input);
            }
            var token = generateDownloadToken();
            input.value = token;
            watchDownloadToken(token);
          }

          // After browser serializes the form, lock UI and style the submitter.
          setTimeout(function () {
            if (submitter && submitter.matches("button, input[type='submit']")) {
              activeButton = submitter;
              setButtonLoadingState(submitter);
              submitter.disabled = true;
            }
            lockRunControls();
          }, 0);
        },
        false
      );
    });
  }

  function setAbortController(ctrl) {
    abortController = ctrl || null;
  }

  function clearAbortController() {
    abortController = null;
  }

  function init() {
    loaderEl = $("#globalLoader");
    loaderTextEl = $("#loaderText");
    bindCancel();
    bindForms();
  }

  global.RunnerLoading = {
    COOKIE_NAME: COOKIE_NAME,
    generateDownloadToken: generateDownloadToken,
    showLoader: showLoader,
    hideLoader: hideLoader,
    watchDownloadToken: watchDownloadToken,
    setAbortController: setAbortController,
    clearAbortController: clearAbortController,
    init: init,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);

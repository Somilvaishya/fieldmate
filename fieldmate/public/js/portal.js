/* Shared plumbing for the two distributor screens.
   No framework. Two pages, server-rendered chrome, a handful of fetches - a build step here
   would buy nothing and would put the depot's screens behind the PWA's release cycle. */
(function (global) {
  'use strict';

  var API = '/api/method/fieldmate.api.';

  function csrf() {
    return (global.frappe && global.frappe.csrf_token) || '';
  }

  /* Every endpoint answers in the envelope from api/_base.py: {ok, v, data} or
     {ok:false, code, message}. Unwrapping it in one place means no screen has to remember. */
  function call(method, params, post) {
    var url = API + method;
    var opts = {
      method: post ? 'POST' : 'GET',
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    };
    if (post) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Frappe-CSRF-Token'] = csrf();
      opts.body = JSON.stringify(params || {});
    } else {
      var qs = new URLSearchParams();
      Object.keys(params || {}).forEach(function (k) {
        if (params[k] !== undefined && params[k] !== null && params[k] !== '') qs.set(k, params[k]);
      });
      if (qs.toString()) url += '?' + qs.toString();
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        var payload = body.message || body;
        if (payload && payload.ok === false) {
          var e = new Error(payload.message || 'That did not work.');
          e.code = payload.code;
          throw e;
        }
        if (!r.ok) throw new Error((body && body.exc_type) || ('HTTP ' + r.status));
        return payload && payload.data !== undefined ? payload.data : payload;
      });
    });
  }

  var rupees = new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 2
  });

  function money(n) { return rupees.format(Number(n || 0)); }

  function count(n) { return new Intl.NumberFormat('en-IN').format(Number(n || 0)); }

  /* Dates arrive as the server's own strings. Parsing them into a Date only to format them
     back would move a depot's order into yesterday whenever the browser sits in another zone. */
  function day(value) {
    if (!value) return '';
    var parts = String(value).slice(0, 10).split('-');
    if (parts.length !== 3) return String(value);
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return parts[2] + ' ' + months[Number(parts[1]) - 1] + ' ' + parts[0];
  }

  function clock(value) {
    if (!value) return '';
    var t = String(value).slice(11, 16);
    return t ? day(value) + ' ' + t : day(value);
  }

  /* Anything that reaches innerHTML goes through here first. Shop names, rep names and the
     depot's own remarks are all free text somebody typed, and one apostrophe-and-angle-bracket
     away from rewriting the page. */
  function esc(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(message, kind) {
    var el = document.getElementById('toast');
    if (!el) { if (kind === 'crit') global.alert(message); return; }
    el.className = 'notice ' + (kind || 'ok');
    el.textContent = message;
    el.hidden = false;
    global.clearTimeout(el._t);
    el._t = global.setTimeout(function () { el.hidden = true; }, kind === 'crit' ? 8000 : 4000);
  }

  function busy(on) {
    document.body.style.cursor = on ? 'progress' : '';
    Array.prototype.forEach.call(document.querySelectorAll('[data-busy]'), function (b) {
      b.disabled = !!on;
    });
  }

  /* One prompt, promised, so a caller can await a reason the way it awaits everything else. */
  function ask(title, label, required) {
    var dlg = document.getElementById('ask');
    if (!dlg) return Promise.resolve(global.prompt(title) || '');
    dlg.querySelector('h2').textContent = title;
    dlg.querySelector('label').textContent = label;
    var field = dlg.querySelector('textarea');
    field.value = '';
    dlg.showModal();
    return new Promise(function (resolve) {
      dlg.addEventListener('close', function once() {
        dlg.removeEventListener('close', once);
        resolve(dlg.returnValue === 'ok' ? field.value.trim() : null);
      });
      dlg.querySelector('[value="ok"]').onclick = function (e) {
        if (required && !field.value.trim()) {
          e.preventDefault();
          field.focus();
          return;
        }
      };
    });
  }

  global.FM = {
    call: call, money: money, count: count, day: day, clock: clock,
    esc: esc, toast: toast, busy: busy, ask: ask
  };
}(window));

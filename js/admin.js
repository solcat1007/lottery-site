/* 后台通用 JS 工具 */
(function (window) {
  'use strict';

  // ========== Toast ==========
  function showToast(msg, type) {
    type = type || 'ok';
    let t = document.querySelector('.toast');
    if (!t) {
      t = document.createElement('div');
      t.className = 'toast';
      document.body.appendChild(t);
    }
    t.classList.remove('ok', 'err');
    t.classList.add(type);
    const icon = type === 'ok' ? '✅' : '⚠️';
    t.innerHTML = '<span class="toast-icon">' + icon + '</span><span class="toast-msg"></span>';
    t.querySelector('.toast-msg').textContent = msg;
    t.classList.add('show');
    clearTimeout(t._hideTimer);
    t._hideTimer = setTimeout(function () {
      t.classList.remove('show');
    }, 2200);
  }

  // ========== 格式化数字 ==========
  function fmtNum(n) {
    n = Number(n) || 0;
    return n.toLocaleString('zh-CN');
  }

  // ========== 转义 HTML ==========
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  // ========== URL 参数 ==========
  function getQuery(key) {
    const p = new URLSearchParams(window.location.search);
    return p.get(key);
  }

  // ========== 登出（带确认） ==========
  function bindSidebarLogout() {
    const el = document.querySelector('[data-logout]');
    if (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        if (confirm('确定要退出管理员登录吗？')) {
          window.location.href = '/admin/logout';
        }
      });
    }
  }

  window.Admin = {
    showToast: showToast,
    fmtNum: fmtNum,
    esc: esc,
    getQuery: getQuery,
    bindSidebarLogout: bindSidebarLogout
  };
})(window);

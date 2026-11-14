(() => {
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', () => {
      if (!form.checkValidity()) return;
      form.setAttribute('aria-busy', 'true');
      form.querySelectorAll('button[type="submit"], button:not([type])').forEach(button => {
        button.dataset.originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = 'جارِ تنفيذ الإجراء…';
      });
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('button[data-original-label]').forEach(button => {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel;
    });
    document.querySelectorAll('form[aria-busy]').forEach(form => form.removeAttribute('aria-busy'));
  });
})();

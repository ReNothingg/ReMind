{
  let theme;
  try {
    theme = JSON.parse(localStorage.getItem('settings_theme'));
  } catch {}

  if (theme !== 'light' && theme !== 'dark') {
    theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.documentElement.setAttribute('data-theme', theme);
}

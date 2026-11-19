// Highlight the visitor's platform in the download section and name it on the hero button.
// Phones and tablets get no highlight: there is no mobile build.
(() => {
  const ua = navigator.userAgent;
  const os = /Android|iPhone|iPad|CrOS/.test(ua) ? null
    : /Mac/.test(ua) ? (navigator.maxTouchPoints > 1 ? null : 'mac') // iPadOS also says "Mac"
    : /Win/.test(ua) ? 'windows'
    : /Linux|X11/.test(ua) ? 'linux'
    : null;
  const card = os && document.querySelector(`.platform[data-os="${os}"]`);
  if (!card) return;
  card.classList.add('is-yours');
  const hero = document.getElementById('hero-get');
  hero.textContent = `Download for ${card.querySelector('h3').textContent}`;
})();

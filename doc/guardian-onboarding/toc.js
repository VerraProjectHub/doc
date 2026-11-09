(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
  var toggles = Array.prototype.slice.call(document.querySelectorAll('.toc-toggle'));
  var downloadButton = document.querySelector('.download-pdf-button');
  var targets = links
    .map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); });

  if (downloadButton) {
    downloadButton.addEventListener('click', function () { window.print(); });
  }

  toggles.forEach(function (button) {
    button.addEventListener('click', function () {
      var items = document.getElementById(button.getAttribute('aria-controls'));
      if (!items) { return; }
      var expanded = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', String(!expanded));
      items.classList.toggle('expanded', !expanded);
      update();
    });
  });

  var initialLink = links.find(function (a) { return a.hash === window.location.hash; });
  var initialItems = initialLink && initialLink.closest('.toc-subitems');
  if (initialItems) {
    initialItems.classList.add('expanded');
    var initialToggle = initialItems.previousElementSibling.querySelector('.toc-toggle');
    if (initialToggle) { initialToggle.setAttribute('aria-expanded', 'true'); }
  }

  function update() {
    var current = 0;
    targets.forEach(function (el, i) {
      var items = links[i].closest('.toc-subitems');
      if (items && !items.classList.contains('expanded')) { return; }
      if (el && el.getBoundingClientRect().top <= 80) { current = i; }
    });
    links.forEach(function (a, i) { a.classList.toggle('active', i === current); });
    var active = links[current];
    document.querySelectorAll('.toc-main-row').forEach(function (row) {
      var mainLink = row.querySelector('a.top');
      row.classList.toggle('active', !!mainLink && mainLink.classList.contains('active'));
    });
    var toc = document.querySelector('.toc');
    if (active && toc) {
      var r = active.getBoundingClientRect();
      var t = toc.getBoundingClientRect();
      if (r.top < t.top || r.bottom > t.bottom) { active.scrollIntoView({ block: 'nearest' }); }
    }
  }

  window.addEventListener('scroll', update, { passive: true });
  update();
})();

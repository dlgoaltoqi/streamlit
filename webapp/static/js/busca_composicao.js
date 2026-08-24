(function () {
  document.addEventListener('input', function (e) {
    if (!e.target.matches('[data-busca-target]')) return;
    var tableId = e.target.dataset.buscaTarget;
    var table = document.getElementById(tableId);
    if (!table) return;
    var term = e.target.value.trim().toLowerCase();
    table.querySelectorAll('tbody tr').forEach(function (tr) {
      var haystack = (tr.dataset.search || tr.textContent).toLowerCase();
      tr.style.display = (!term || haystack.includes(term)) ? '' : 'none';
    });
  });
})();

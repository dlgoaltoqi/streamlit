// Motor genérico das grades editáveis (Parâmetros, Metas) e da tela de
// Config com vigência. Fica num arquivo carregado normalmente pela página
// (não pelo fragmento buscado via fetch de admin.html/_loader.html) porque
// <script> injetado via innerHTML nunca executa — por isso as funções aqui
// são globais e a tabela/grade carrega os dados via atributos (data-cols
// etc.), não via <script> embutido no HTML do fragmento.

function gridAdd(gridId) {
  var table = document.getElementById(gridId);
  var cols = JSON.parse(table.dataset.cols);
  var tbody = table.querySelector("tbody");
  var tr = document.createElement("tr");
  cols.forEach(function (c) {
    var td = document.createElement("td");
    td.style.padding = "2px";
    if (c.tipo === "bool") {
      td.style.textAlign = "center";
      td.innerHTML = "<input type='checkbox' data-col='" + c.nome + "' checked>";
    } else {
      var tipoHtml = c.tipo === "num" ? "number" : "text";
      td.innerHTML = "<input type='" + tipoHtml + "' data-col='" + c.nome + "' " +
        "style='width:100%;min-width:80px;border:1px solid #d1d5db;" +
        "border-radius:4px;padding:4px 6px;font:inherit;'>";
    }
    tr.appendChild(td);
  });
  var tdBtn = document.createElement("td");
  tdBtn.style.textAlign = "center";
  tdBtn.style.padding = "2px";
  tdBtn.innerHTML = "<button type='button' onclick=\"this.closest('tr').remove()\" " +
    "class='btn-remover'>🗑️</button>";
  tr.appendChild(tdBtn);
  tbody.appendChild(tr);
}

function gridSalvar(gridId, salvarUrl, voltarUrl) {
  var linhas = [];
  document.querySelectorAll("#" + gridId + " tbody tr").forEach(function (tr) {
    var linha = {};
    tr.querySelectorAll("[data-col]").forEach(function (inp) {
      linha[inp.dataset.col] = inp.type === "checkbox" ? inp.checked :
        (inp.value === "" ? null : inp.value);
    });
    linhas.push(linha);
  });
  var status = document.getElementById(gridId + "_status");
  if (status) status.textContent = "Salvando…";
  fetch(salvarUrl, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ linhas: linhas }),
  }).then(function (r) { return r.json(); }).then(function (data) {
    if (data.ok) {
      window.location.href = voltarUrl + "&msg=" + encodeURIComponent(data.msg);
    } else if (status) {
      status.textContent = "Erro: " + (data.erro || "falha ao salvar");
    }
  }).catch(function (e) {
    if (status) status.textContent = "Erro: " + e;
  });
}

function cfgSalvar(modo, ano, mes) {
  var alterados = {};
  document.querySelectorAll("#config_linhas input[data-chave]").forEach(function (inp) {
    if (inp.value !== inp.dataset.original) {
      alterados[inp.dataset.chave] = { valor: inp.value, ano: inp.dataset.ano, mes: inp.dataset.mes };
    }
  });
  var status = document.getElementById("config_status");
  if (status) status.textContent = "Salvando…";
  var rota = modo === "atual" ? "salvar-atual" : "nova-vigencia";
  fetch("/admin/config/" + rota + "?ano=" + ano + "&mes=" + mes, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ alterados: alterados }),
  }).then(function (r) { return r.json(); }).then(function (data) {
    if (data.ok) {
      window.location.href = "/admin/config?ano=" + ano + "&mes=" + mes +
        "&msg=" + encodeURIComponent(data.msg);
    } else if (status) {
      status.textContent = "Erro: " + (data.erro || "falha ao salvar");
    }
  }).catch(function (e) {
    if (status) status.textContent = "Erro: " + e;
  });
}

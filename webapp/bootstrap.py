"""Shim de utils.connection para o processo web.

utils/commission.py (linha ~1615) e utils/fechamento.py (linhas 14-17)
importam de utils.connection. O módulo real é Streamlit/SiS e NUNCA deve
entrar neste processo; este bootstrap registra um módulo sintético em
sys.modules expondo exatamente o que o código compartilhado consome,
delegando para webapp.services (mesmo padrão do validacao/harness.py).

Chame install_connection_shim() ANTES de qualquer import de utils.commission
ou utils.fechamento (webapp.main e webapp.smoke fazem isso na primeira linha).
"""
import sys
import types
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent


def install_connection_shim():
    raiz = str(_RAIZ)
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    if "utils.connection" in sys.modules:
        mod = sys.modules["utils.connection"]
        if not getattr(mod, "_WEBAPP_SHIM", False):
            raise RuntimeError(
                "utils.connection real foi importado neste processo — o webapp "
                "não pode conviver com o módulo do SiS. Importe webapp.bootstrap "
                "antes de utils.*")
        return mod

    from webapp.services import comissao_service as cs

    stub = types.ModuleType("utils.connection")
    stub._WEBAPP_SHIM = True
    # Consumido por utils/commission.py (import tardio no cálculo trimestral)
    stub.get_comissao = cs.get_comissao
    # Consumidos por utils/fechamento.py
    stub.get_comissao_cached = cs.get_comissao_cached
    stub.get_composicao_cached = cs.get_composicao_cached
    stub.get_composicao_bk_extra_cached = cs.get_composicao_bk_extra_cached
    stub.get_composicao_canc_recovery_cached = cs.get_composicao_canc_recovery_cached
    stub.get_ajustes_cached = cs.get_ajustes_cached
    stub._is_xp_err = cs._is_xp_err
    sys.modules["utils.connection"] = stub
    return stub

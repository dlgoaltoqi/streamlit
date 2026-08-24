"""Helpers de período — cópia fiel de utils/connection.py (linhas 330-384).

Copiados (não extraídos) de propósito: mexer no connection.py exigiria
redeploy do SiS, e a regra da migração é não tocar no que está no ar.
Qualquer mudança de regra de período deve ser feita NOS DOIS lugares
enquanto o SiS existir.
"""
import datetime as _dt

MESES_ABREV = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}
MESES_NOME = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

# O painel de comissões vale de abril/2026 em diante — fonte única do período.
MIN_ANO_PAINEL, MIN_MES_PAINEL = 2026, 4


def hoje_brt():
    """Data atual no fuso de Brasília (UTC-3; servidores rodam em UTC)."""
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=3)).date()


def ano_atual():
    return hoje_brt().year


def mes_atual():
    return hoje_brt().month


def periodo_anos():
    """Anos selecionáveis nos filtros principais: 2026 até o ano corrente."""
    return list(range(MIN_ANO_PAINEL, max(ano_atual(), MIN_ANO_PAINEL) + 1))


def periodo_meses(ano):
    """Meses selecionáveis do ano: Abr-Dez em 2026, Jan-Dez nos seguintes."""
    return [m for m in MESES_ABREV
            if (int(ano), m) >= (MIN_ANO_PAINEL, MIN_MES_PAINEL)]


def periodo_default():
    """(ano, mes) default dos filtros: período atual, nunca antes de abr/2026."""
    a, m = ano_atual(), mes_atual()
    if (a, m) < (MIN_ANO_PAINEL, MIN_MES_PAINEL):
        return MIN_ANO_PAINEL, MIN_MES_PAINEL
    return a, m


def hist_pares(ano, mes, n=6):
    """[(ano, mes)] dos n meses anteriores ao selecionado (de _comissao.py)."""
    pares = []
    for delta in range(1, n + 1):
        m_h, a_h = mes - delta, ano
        while m_h < 1:
            m_h += 12
            a_h -= 1
        pares.append((a_h, m_h))
    return pares


def safe_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

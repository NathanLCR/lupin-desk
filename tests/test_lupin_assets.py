"""Garante que a tabela expressões -> camadas do Lupin só aponta para SVGs que existem."""
import json
import re
from pathlib import Path

LUPIN = Path(__file__).resolve().parent.parent / "static" / "lupin"
TABELA = json.loads((LUPIN / "expressoes.json").read_text(encoding="utf-8"))
EMOCOES = [
    "neutral", "happy", "excited", "curious", "skeptical", "surprised",
    "sad", "wink", "love", "sleepy", "angry", "dizzy",
]


def test_toda_variante_da_tabela_tem_svg_480x320():
    for camada, variantes in TABELA["camadas"].items():
        for variante in variantes:
            svg = LUPIN / "camadas" / camada / f"{variante}.svg"
            assert svg.is_file(), f"falta {svg}"
            assert 'viewBox="0 0 480 320"' in svg.read_text(encoding="utf-8"), svg


def test_nenhum_svg_orfao_fora_da_tabela():
    previstos = {
        LUPIN / "camadas" / camada / f"{v}.svg"
        for camada, variantes in TABELA["camadas"].items()
        for v in variantes
    }
    for truque in TABELA["truques"].values():
        for quadro in truque.get("quadros", []):
            previstos.add(LUPIN / "corpo" / f"{quadro}.svg")
    assert set(LUPIN.rglob("*.svg")) == previstos


def test_doze_expressoes_e_cinco_estados_usam_variantes_validas():
    assert set(TABELA["expressoes"]) == set(EMOCOES)
    assert set(TABELA["estados"]) == {"idle", "listening", "thinking", "speaking", "error"}
    for origem in (*TABELA["expressoes"].values(), *TABELA["estados"].values()):
        for camada, variante in origem.items():
            if camada in TABELA["camadas"]:
                assert variante in TABELA["camadas"][camada], (camada, variante)


def test_truques_de_corpo_inteiro_sao_so_dance_stretch_e_nap():
    corpo = {nome for nome, t in TABELA["truques"].items() if t["modo"] == "corpo"}
    assert corpo == {"dance", "stretch", "nap"}
    assert {"sing", "meditate", "celebrate"} <= set(TABELA["truques"])


def test_arte_so_usa_a_paleta_do_lupin():
    permitidas = {
        "#000", "#0b0b0b", "#1d1d24", "#11c3fb", "#ebebea", "#d6d5d5", "#eb617e",
    }
    for svg in LUPIN.rglob("*.svg"):
        cores = {c.lower() for c in re.findall(r"(?<!\()#[0-9a-fA-F]{3,6}\b", svg.read_text(encoding="utf-8"))}
        assert cores <= permitidas, f"{svg}: {cores - permitidas}"

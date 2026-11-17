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
            assert 'width="480" height="320"' in svg.read_text(encoding="utf-8"), svg


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


def test_arte_nao_traz_codigo_nem_imagens_externas():
    for svg in LUPIN.rglob("*.svg"):
        texto = svg.read_text(encoding="utf-8").lower()
        for proibido in ("<script", "<image", "<foreignobject", "http://", "href="):
            if proibido == "http://":
                texto = texto.replace("http://www.w3.org/2000/svg", "")
            assert proibido not in texto, f"{svg}: {proibido}"


def test_piscada_e_fala_apontam_para_poses_que_existem():
    poses = set(TABELA["camadas"]["pose"])
    for origem, destino in TABELA["piscada"].items():
        assert origem in poses and destino in poses, (origem, destino)
    assert TABELA["piscada"], "o Lupin precisa piscar a partir da pose neutra"
    assert TABELA["fala"]["pose"] in poses

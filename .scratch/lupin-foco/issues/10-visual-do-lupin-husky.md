# 10 - Visual do Lupin: husky em camadas

Status: entregue (primeira arte); arte final e medição no ESP32 pendentes

## Contexto

Feedback do teste no RG406H: o rosto abstrato estilo EMO está errado. Lupin é um husky de desenho preto e branco (referência enviada pelo usuário): olhos ciano brilhantes, dois pontos ciano acima, contorno ciano fino, focinho branco com nariz rosa, rabo enrolado, coleira escura com onda sonora ciano. Relacionada à 02 (corpo vivo) e à 09 (Dock).

## Decisões (grilling, 2026-11-16)

- Busto como enquadramento padrão; corpo inteiro só em Truques (`dance`, `stretch`, `nap`). `sing`, `meditate` e `celebrate` ficam no busto com efeitos. A onda da coleira acende quando Lupin fala.
- Animação por camadas (cabeça, olhos, pálpebras, sobrancelhas, boca/língua, orelhas, coleira, pontos ciano), igual na web e no LVGL.
- Arte: primeira versão em SVG vetorial simples feita por mim; arte final entra depois pelo mesmo formato de camadas.
- Formato: SVG por camada é a fonte única; script gera PNGs com transparência 480x320 para o ESP32.
- Tabela única `expressões -> estados de camada` compartilhada pelos dois Corpos (12 Expressões). Piscar e olhar em volta são do Corpo.
- Orçamento ESP32: PNG por camada até ~20 KB, busto ~320x300, cores indexadas 8 bits, até ~24 camadas, corpo inteiro em 3 conjuntos de quadros carregados só durante o Truque. Medir quando a placa chegar.
- Paleta: fundo preto, ciano como único acento e só no Lupin; resto da interface em neutros escuros com texto branco, sem brilho em botões, sem emoji.

- Entrega depois da barra e dos Ajustes (issue 02). O rosto EMO antigo é removido quando o husky entrar, sem fallback.

## Critérios de aceite

- [x] Camadas SVG do husky e tabela expressões -> camadas (`static/lupin/`).
- [x] Face web desenha o husky por camadas e cobre as 12 Expressões (`static/lupin.js`; rosto EMO removido).
- [x] Onda da coleira acende ao falar.
- [x] 3 Truques com corpo inteiro (`dance`, `stretch`, `nap`, 2 quadros cada).
- [x] Script que gera os PNGs do ESP32 dentro do orçamento (`scripts/gerar_png_lupin.py`; maior PNG 8,4 KB).

## Entregue (2026-11-17)

- 34 variantes de camada em 7 camadas, mais 6 quadros de corpo inteiro. Total dos PNGs indexados: 86 KB.
- Arte é a primeira versão vetorial simples; a arte final entra trocando os SVGs, sem mexer em código.
- Pendente: o orçamento falava em até ~24 camadas, e são 34 variantes (só 7 aparecem ao mesmo tempo). Decidir com a medição na placa se isso é problema.
- Pendente: `setAccessory` só registra o valor; a arte de fones e Pomodoro no rosto ainda não existe. Clima, suor e bocejo do rosto antigo não foram portados.
- Sem tela física: o husky só foi visto no navegador (960x720), não no RG406H.

## Arte do Recraft (2026-11-17)

- A cabeça, a máscara, o nariz, as orelhas, o peito e a coleira agora vêm do traçado SVG gerado no Recraft (husky simétrico, vista frontal), dividido em camadas pelo mesmo formato de antes. A tabela `expressoes.json` não mudou de contrato.
- Só existia o SVG da pose neutra. Olhos, sobrancelhas e bocas das outras expressões foram redesenhados à mão no estilo do traçado. Os PNGs de feliz, surpreso e corações do Recraft não viraram SVG; se exportar esses SVGs, dá para trocar as variantes.
- Os 6 quadros de corpo inteiro reutilizam a nova cabeça num corpo simples ainda desenhado à mão.
- Paleta: ciano `#11c3fb`, branco `#ebebea`, cinza `#d6d5d5`, rosa `#eb617e`, preto. Maior PNG: 8 KB.

## Arte final em poses inteiras (2026-11-17)

- A arte nova (busto + 7 expressões + 3 Truques de corpo inteiro, traçados em SVG) substitui a primeira versão em peças. Ela vem como poses completas, não dá para separar olhos e boca sem refazer o traçado.
- Modelo atual: camada `pose` (8 variantes de busto) + camada `colar` (brilho da onda, só aceso quando fala). A tabela `expressoes.json` (versão 2) escolhe a pose por Expressão e Estado.
- Falar: a coleira acende e a pose alterna entre neutro e feliz (boca aberta) a partir do nível de áudio (`fala.limiar`).
- Piscar: a tabela tem `piscada` (pose → pose de olhos fechados), hoje vazia. Falta o SVG do busto neutro com olhos fechados.
- Sem pose própria: `curious` (neutro inclinado), `skeptical` e `sad` (usam sonolento). Faltam SVGs de curioso, cético e triste.
- Truque `dance` usa os quadros de acenar. Total: 16 SVGs, maior PNG 11 KB, 136 KB no conjunto, bem abaixo do orçamento do ESP32.

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

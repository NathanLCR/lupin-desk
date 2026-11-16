# 10 - Visual do Lupin: husky em camadas

Status: ready-for-agent (depois da barra/Ajustes da issue 02)

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

- [ ] Camadas SVG do husky e tabela expressões -> camadas.
- [ ] Face web desenha o husky por camadas e cobre as 12 Expressões.
- [ ] Onda da coleira acende ao falar.
- [ ] 3 Truques com corpo inteiro.
- [ ] Script que gera os PNGs do ESP32 dentro do orçamento.

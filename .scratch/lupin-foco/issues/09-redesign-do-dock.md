# 09 - Redesign do Dock

Status: needs-triage

## Contexto

O RG406H tem dois Modes separados, Pet e Dock, com um toggle. O Dock precisa ficar simples e previsível, como superfície de controle do Mac.

## Escopo

- Dock Mode vira uma grade fixa 3x3, paginada, só com os Shortcuts que o usuário escolheu.
- A lista de apps abertos sai da grade e vai para uma página separada.
- Shortcuts são configurados no Mac, nunca no RG406H.
- Um Lupin pequeno fica no canto do Dock Mode e volta para o Pet Mode quando Lupin fala algo longo.
- Respeitar o glossário: apenas dois Modes (Pet e Dock); sem novos Modes.

## Critérios de aceite

- [ ] A grade é 3x3 fixa, paginada, e mostra só os Shortcuts escolhidos.
- [ ] A lista de apps abertos está numa página separada.
- [ ] Não existe nenhuma tela de configuração de Shortcuts no RG406H; a configuração vive no Mac.
- [ ] Um Lupin pequeno aparece no canto do Dock Mode.
- [ ] Quando Lupin fala algo longo, a tela volta ao Pet Mode.
- [ ] O toggle entre Pet e Dock funciona nos dois sentidos.
- [ ] Define-se o que é "fala longa" (ex.: número de caracteres ou duração).

## Perguntas em aberto

- Quando começar, antes ou depois da chegada do ESP32 (quando o RG406H vira Dock puro, sem Pet Mode)?

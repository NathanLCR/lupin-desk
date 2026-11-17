# 01 - Cortes

Status: ready-for-agent

## Contexto

O Desk Assistant cresceu largo demais (ADR 0001). Antes de qualquer feature nova, cortamos o que não está em uso diário. O código removido permanece só no branch `snapshot/swarm-2026-11-16`.

## Escopo

- Remover Ambient Display como Mode próprio: relógio, Pomodoro e Now Playing passam a ficar ao redor de Lupin no Pet Mode.
- Skills e Diagnostics deixam de ser Modes e vão para uma área de Settings.
- Cowork passa a ser somente leitura: remover Cowork Tasks de escrita/externas, o preview de diff e o runner de aprovação, na UI e no prompt.
- Remover Screen Look e Clipboard Read (antes "Jarvis"); o nome "Jarvis" deve sumir do código, da UI e dos prompts.
- Congelar o mini-pet Electron: nenhum trabalho novo.
- iPhone não recebe trabalho dedicado.
- Manter tudo que Pet Mode, Dock, Today (somente leitura) e First Wake usam.

## Critérios de aceite

- [ ] O RG406H só tem dois Modes: Pet e Dock.
- [ ] Relógio, Pomodoro e Now Playing aparecem no Pet Mode, ao redor de Lupin.
- [ ] Skills e Diagnostics são acessados em Settings, não por Mode.
- [ ] Nenhuma Cowork Task de escrita ou externa existe; sem diff preview nem runner de aprovação; o prompt não os menciona.
- [ ] Today continua funcionando lendo o Cowork.
- [ ] `grep -ri jarvis` não encontra nada no código ativo.
- [ ] Screen Look e Clipboard Read não existem mais.
- [ ] Mini-pet Electron intacto e marcado como congelado.
- [ ] Testes existentes passam; o branch `snapshot/swarm-2026-11-16` continua com o código cortado.

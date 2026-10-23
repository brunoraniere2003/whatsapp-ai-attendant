# SPEC-001: AI WhatsApp Attendant

Id: SPEC-001
Título: AI WhatsApp Attendant
Status: rascunho
Dono: o autor
Data: 2026-10-22
Tamanho: M
Depende de: nada

> Como usar: copie para `docs/specs/SPEC-<NNN>-<slug>.md`.
> Apague as linhas de instrução (começam com `>`). Método completo em `handbook/metodologia.md`.
> Tamanho G: crie também `PLAN-<NNN>-<slug>.md` e `TASKS-<NNN>-<slug>.md` na mesma pasta.

## 1. Objetivo

> Uma frase com o resultado observável e uma com "por que agora". Máximo 5 linhas.

<resultado observável>. <por que agora>.

## 2. Contexto

> Fatos que moldam a spec, cada um com fonte. Fato sem fonte leva "(não verificado)".

| Fato | Fonte (link, arquivo ou comando) | Consequência |
|---|---|---|
| <fato> | <fonte> | <o que muda na spec> |

## 3. Requisitos (EARS)

> Um DEVE por requisito. Dois comportamentos viram dois requisitos.
> Palavras-chave em maiúsculas. Em repositório com várias specs, use prefixo de letra: RQ-E1.

| Padrão | Forma |
|---|---|
| Ubíquo | O `<sistema>` DEVE `<resposta>`. |
| Evento | QUANDO `<gatilho>`, o `<sistema>` DEVE `<resposta>`. |
| Estado | ENQUANTO `<estado>`, o `<sistema>` DEVE `<resposta>`. |
| Indesejado | SE `<condição indesejada>`, ENTÃO o `<sistema>` DEVE `<resposta>`. |
| Opcional | ONDE `<recurso opcional>`, o `<sistema>` DEVE `<resposta>`. |
| Complexo | ENQUANTO `<estado>`, QUANDO `<gatilho>`, o `<sistema>` DEVE `<resposta>`. |

- RQ-1: QUANDO <gatilho>, o <sistema> DEVE <resposta>.
- RQ-2: SE <condição indesejada>, ENTÃO o <sistema> DEVE <resposta>.
- RQ-3: <...>

## 4. Critérios de aceite

> Dado: estado conhecido. Quando: ação ou evento. Então: resultado observável de fora
> (saída, arquivo, código de saída, mensagem). Proibido: "corretamente", "internamente", "deve funcionar".
> Cada CA cita os RQ que cobre e tem pelo menos um teste que cita o id do CA.

### CA-1: <nome curto> (cobre RQ-1)

- Dado <estado conhecido>
- Quando <ação ou evento>
- Então <resultado observável>
- E <outro resultado observável>

### CA-2: <nome curto> (cobre RQ-2, RQ-3)

- Dado <...>
- Quando <...>
- Então <...>

## 5. Eventos e dados

| Id | Evento ou dado | Quando | Campos | Quem consome |
|---|---|---|---|---|
| EV-1 | <nome> | <gatilho> | <campos> | <consumidor> |

> Sem eventos nem dados novos: escreva "nenhum".

## 6. Fora de escopo

> Nunca vazio. Cada item com o motivo.

- <item>: <motivo>.

## 7. Riscos

| Risco | Mitigação |
|---|---|
| <risco> | <mitigação> |

## 8. Decisões

> Decisão estrutural ou difícil de reverter vira ADR (`templates/ADR.md`) e é linkada aqui.

| Id | Decisão | Motivo | ADR |
|---|---|---|---|
| D-1 | <decisão> | <motivo> | <ADR-NNN ou "não precisa"> |

## 9. Questões abertas

> Toda dúvida vira o marcador `[PRECISA ESCLARECER: <pergunta objetiva>]`, aqui ou no ponto do texto.
> Spec com marcador aberto não passa no DoR. Ao responder, troque o marcador pela resposta, data e quem respondeu.

- Q-1: [PRECISA ESCLARECER: <pergunta objetiva>]

## 10. Rastreabilidade

> Uma linha por CA. Preenchida na implementação.

| CA | Requisitos | Teste (arquivo::função) | Situação |
|---|---|---|---|
| CA-1 | RQ-1 | `<tests/test_x.py::test_ca_1_...>` | pendente / passa |
| CA-2 | RQ-2, RQ-3 | `<...>` | pendente / passa |

## 11. Emendas

> Só depois de aprovada. Nunca reescreva requisito aprovado: registre o delta.
> MODIFICADO traz o texto completo de antes e de agora. IDs removidos não são reaproveitados.

### Emenda 1 (proposta em <AAAA-MM-DD>, aprovada em <AAAA-MM-DD>)

- ADICIONADO: RQ-<N>: <texto completo>; CA-<N>: <nome>.
- MODIFICADO: RQ-<N>. Antes: "<texto completo>". Agora: "<texto completo>".
- REMOVIDO: RQ-<N>. Motivo: <motivo>.

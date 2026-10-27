# eleicao-projecao

Ideia: durante a apuração, ler periodicamente um site que mostra a votação por região
e quanto falta apurar em cada uma, e projetar o resultado final.

Método (extrapolação estratificada / election nowcasting):

- Para cada região: votos que faltam × percentual atual de cada candidato na região.
- Somar o já apurado com o projetado de todas as regiões → resultado final estimado.
- Repetir a cada leitura e guardar o histórico das projeções.

Cuidado conhecido: a ordem de apuração não é aleatória (urna urbana costuma chegar
antes da rural), então a projeção é instável no começo. Quanto menor a região usada
(município em vez de estado), menor o erro. Mostrar faixa de incerteza junto do número.

Fonte de dados: TSE, https://resultados.tse.jus.br/oficial/ele2026/6258/dados/<uf>/
(6258 = 2º turno federal 2026; 6257 = 1º turno; c0001 = presidente).
- `<uf>-e006258-ab.json`: andamento por município (seções, eleitorado), sem votos.
- `<uf><cod5>-c0001-e006258-u.json`: votos por município. Pode vir mais velho que o -ab (cache).
- `<uf>-c0001-e006258-u.json` / `br-...`: totais por UF / Brasil.
- Exterior (zz): entra no total br antes de aparecer nos arquivos por cidade → tratado
  como resíduo br − UFs.

Status (27/10/2026): concluído. Rodou ao vivo no 2º turno de 25/10/2026 (v1 + v2 com
Monte Carlo); resultado e método no README.md. Pendente opcional: relatório Power BI (.pbip).
Revisor independente: agente "Anticlaude" (`anticlaude`), em .claude\agents\anticlaude.md.

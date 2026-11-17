# 4rt3mi5

Companheiro de hunt: divide o loot da PT (Lootsplit), acumula as sessões individuais
(Hunt Session Stacker) e mostra tudo no celular e no PC.

```
 App desktop (Windows)  ─┐                                ┌─ TibiaData (valida personagens e
   janela WebView2       │  X-Access-Key + X-Device-Token  │   lê o comentário na verificação)
   + atualização auto    ├──────────────────▶  Servidor (Docker na sua máquina) ──┘
 Site no celular        ─┘                    FastAPI + SQLite (data/artemis.db)
```

A interface é **uma só** (`artemis/web/index.html`): o servidor entrega para o celular e o
app desktop abre a mesma página numa janela própria.

## Fluxo do usuário

1. Abertura animada → **código de acesso** (enviado pelo criador).
2. Abertura → **"Informe o nick do main character:"** → o app mostra um **código de verificação**
   (`4RT3MI5-XXXXXX`). A pessoa cola no comentário do personagem no tibia.com; o app confere pelo
   TibiaData (no botão e sozinho a cada 30 s). Depois de verificado, pode apagar do comentário.
3. Abertura → **nome do personagem** a consultar → tela inicial (última hunt, totais, histórico).
4. **Solo ou Party (0.22.0):** a tela do personagem pergunta se a sessão é hunt solo ou em party; uma barra fixa no
   rodapé troca a qualquer momento (Solo → Hunt Session Stacker, Party → Lootsplit). O menu ☰ segue essa escolha:
   **Solo** → Hunt Session Stacker, Bosses, Hunts; **Party** → Lootsplit, Bosses, Hunts. Em 🗺️ Hunts, solo só compara
   com solo e party com party (`/api/places/ranking|compare|mine?mode=solo|party`); detalhes (criaturas, itens, dano)
   só das hunts do próprio player e Input Analyzer público só para o Player Hardcore. No Lootsplit, primeiro vêm as
   transferências e a mensagem pronta para o chat do Tibia; depois o próximo passo pelo tipo de player.
   **Notícias do Tibia (0.22.0):** ☰ → **Tibia** → **📰 Novidades** (Latest News: ticker, Featured Article e
   notícias dos últimos 90 dias) e **💬 O que os CMs estão falando?** (News Archive com o mesmo filtro do tibia.com:
   período, categorias, tipos + pesquisa; abre na última semana com tudo marcado). Vêm pelo TibiaData
   (`/api/tibia/latest|archive|news/{id}`): o servidor guarda o índice inteiro na tabela `tibia_news` e baixa os textos
   aos poucos a cada 30 min (`ARTEMIS_NEWS_SYNC`, em segundos; `0` desliga) e na hora em que alguém abre. Com a fonte
   fora do ar, tudo sai do banco. O HTML passa por uma lista fechada de tags (`artemis/core/tibianews.py`); imagens
   viram link. As notas de versão do app agora são **🧾 Alterações** (menu e atalho fixo no canto inferior direito).
   **📅 Calendário (0.22.1):** o tibia.com não aceita leitura automática, então o administrador abre o Event Calendar
   no navegador, copia o `outerHTML` da caixa *Event Schedule* e cola no painel admin (seção 📅). O servidor
   (`artemis/core/tibiacal.py`) tira só os dados (dias, eventos, cores, ⏱ server save e descrições em texto) e guarda
   cada colagem na tabela `tibia_calendar` (histórico só no painel; "Desfazer última" volta para a anterior). O app
   (`/api/tibia/calendar`) mostra a colagem mais nova de cada mês, nunca o HTML colado.
   **0.22.2:** menu em galhos (Ferramentas → **Solo**: Hunt Session Stacker, Boss Session Stacker, Hunts solo ·
   **Party**: Lootsplit, Lootsplit de bosses, Hunts em party; depois **Tibia** e **Conta**). 👑 Bosses em Party recebe o
   Party Hunt Analyser e faz o lootsplit direto. O Início mostra a notícia mais nova do Tibia (`/api/tibia/headline`) e a
   última hunt do modo. **Tradução automática** (só notícias, News Archive e descrições do calendário): DeepL com a
   chave `ARTEMIS_DEEPL_KEY` no `.env` (plano grátis: 500 mil caracteres/mês; limite em `ARTEMIS_TRANSLATE_MONTHLY`,
   padrão 450 mil). Cada texto é traduzido uma vez por idioma e guardado na tabela `translations`; sem chave, fica em inglês.
   Menu ☰: **Início**; o grupo Solo/Party acima;
   **Progresso** → Ranking entre amigos, Conquistas; **Conta** → Meus personagens, Novidades,
   **Configurações** (também no ⚙️ do cabeçalho), trocar personagem, sair. Solo → Stacker já abre a janela para colar.
7. **Idioma (0.19.0 / 0.20.0):** ⚙️ Configurações → português, inglês, espanhol, japonês, alemão, polonês,
   francês ou russo (também na tela de login). O app é escrito em português; `artemis/web/i18n.js` traduz o que
   aparece na tela com os dicionários `i18n-<en|es|ja|de|pl|fr|ru>.json` (chave = texto em português,
   `{0}` = valor que muda). Texto novo na interface ou mensagem nova do servidor → acrescente a tradução nos
   sete arquivos (`tests/test_i18n.py` confere chaves iguais e os textos do `index.html`). Nomes do Tibia ficam
   como no jogo. **Padrão sempre português:** o idioma do sistema não escolhe sozinho; só o toque nos botões
   de idioma fica salvo no aparelho (chave `idioma`). As **Novidades** vêm traduzidas do próprio
   `changelog.json` (campo `tr` com os sete idiomas em cada versão).
8. **Tipo de player (0.20.0):** perguntado na criação da conta ("Você se considera um:", antes de informar o
   main; quem já tinha conta responde uma vez ao entrar) e trocado em ⚙️ Configurações (com confirmação;
   o tipo atual aparece como "(Atual)"). Vale para a conta (tabela `player_prefs`). A lista de tipos que a
   pessoa pode escolher vem do servidor (`player_types` em `/api/me`). Decide as perguntas depois de salvar:
   - **Stacker:** salva primeiro (sem local); Comum e Hardcore → "Deseja salvar qual a hunt você caçou?";
     Hardcore → também "Deseja compartilhar o Input Analyzer?". Novato só salva.
   - **Lootsplit:** nenhuma pergunta depois de colar (o importante é quem paga quem). O local, a própria sessão
     (`party_sessions`) e o Input Analyzer (`damage_inputs`) ficam como opções no card. Comum e Hardcore juntam
     os dois; o Novato não. Os membros veem tudo em "📎 Compartilhado pela PT"; quem não estava na PT não vê.
   - **Diferença com o Party Hunt Analyser:** só quando a sessão é do mesmo período da party hunt (±60 s).
     Loot type Leader → compara só os supplies; Market → loot, supplies e balance. Aviso discreto no card.
   - **"hunt sem local":** escolher o local é livre; trocar depois, no máximo 2 vezes (`place_edits`). Na 3ª o
     servidor recusa e o app mostra "Para alterar novamente entre em contato com o administrador."
     No painel do administrador, tocar num personagem mostra as hunts dele; dá para trocar o local (sem gastar
     as trocas da pessoa) e liberar as 2 trocas de novo.
10. **Chave sem vencimento (0.20.0):** toda chave de acesso é vitalícia (o banco marca todas ao abrir). Não há
   mais renovação nem aviso de vencimento; a sequência de dias continua, mas não dá mais dias de validade.
   - **Input Analyzer** (`artemis/core/damage.py`): total, Max-DPS, tipos de dano e fontes; `(other)` só entra
     no total. Salvou, não edita (409). A comparação de 🗺️ Hunts mostra o % de dano por elemento e por criatura.
9. **Privacidade (0.20.0):** quem vê o Stacker de outro personagem recebe só o geral (XP, balance, tempo);
   criaturas, itens, loot, lucro líquido, metas e lista de venda ficam só com o dono. Na comparação de Hunts,
   criaturas e itens aparecem sem quantidade. 📊 **Comparar minhas hunts** (XP/h e balance/h por local) é só do dono.
5. Sem conexão: tela de abertura com o aviso, tentando de novo a cada 10 s.
6. **Colar direto:** com o texto do analyser copiado, Ctrl+V em qualquer tela abre o aviso "Enviar agora".

## Conquistas e sequência de dias (0.10.0)

- 13 conquistas por personagem (`artemis/core/achievements.py`), calculadas das sessões e party hunts.
- **Sequência:** dias seguidos (horário de Brasília) em que o código de acesso enviou alguma hunt ou sessão.
  A cada **30 dias seguidos** o código ganha **+7 dias** de validade, uma vez por bloco de 30 dias
  (tabela `key_rewards`). O app explica a regra no Início e em 🏆 Conquistas.

## 👑 Rotação de bosses (0.11.0)

- Menu ☰ → **Rotação de bosses**, com **Solo** e **Party**. Recebe o Hunt Session Analyser da luta.
- **Party:** depois da sessão o app pergunta se a pessoa quer fazer o lootsplit. Se sim, ela cola o
  Party Hunt Analyser; a divisão vai para a aba de bosses de todos da PT. Sessões de boss dos outros
  jogadores no mesmo horário (±15 min) se juntam sozinhas a esse lootsplit, antes ou depois dele.
- **Bosses em hunts comuns:** se uma sessão do Stacker tem um boss nas criaturas mortas, ele entra na aba
  de bosses com o loot **estimado** (itens da tabela do boss que as outras criaturas mortas não dropam).
- **Privado:** só o dono do personagem vê a aba; o lootsplit de boss só aparece para quem estava na PT.
  Fica em tabelas próprias (`boss_sessions`, `boss_hunts`), fora do Lootsplit, do Stacker e do ranking de Hunts.
- Lista de bosses e loot: `artemis/data/bosses.json`, gerado por `tools/import_bosses.py` (TibiaWiki em
  tibia.fandom.com, CC BY-SA). Rode de novo quando sair boss novo.
- **💎 Drops raros (0.12.0):** item de boss "very rare"/"extremely rare" na TibiaWiki ou que vale 500 mil gp ou mais
  (`RARE_RARITIES` e `RARE_VALUE` em `artemis/core/bosses.py`). O app comemora no envio e guarda o histórico na aba.
- **💰 Itens sem NPC:** a aba lista os itens de boss que nenhum NPC compra, para a pessoa informar o preço
  (entra na média de todos, como no Stacker).

## Lootsplit: acertos e regras (0.12.0)

- **Já paguei / Recebi:** cada transferência pode ser marcada por quem paga ou por quem recebe (tabela
  `hunt_payments`). O Início mostra o que a pessoa ainda deve ou tem a receber.
- **Regras de divisão:** quem enviou o lootsplit pode deixar alguém **fora da divisão** (termina com lucro 0:
  recebe os supplies de volta e entrega o loot) ou com **valor fixo** (termina com aquele lucro). O resto divide
  igual (`split_with_rules` em `artemis/core/split.py`, tabela `hunt_rules`). Mudar as regras apaga as marcações
  de pagamento daquela hunt. Vale também para o lootsplit de bosses.

## Outras novidades da 0.12.0

- **Comparação com a média:** ao enviar uma sessão no Stacker (10 min ou mais), o app compara XP/h e balance/h
  com a média das outras sessões do personagem na mesma hunt.
- **🥇 Ranking entre amigos:** opcional, por personagem (tabela `ranking_optin`); só o dono entra/sai.
- **Rascunho sem internet:** envio que falha por falta de conexão fica guardado no aparelho e é enviado sozinho
  quando a conexão volta.
- **Aviso de código vencendo:** o Início avisa 3 dias antes. O painel mostra os códigos que vencem na semana e o
  último uso de cada um.
- **Imagens no banco:** o site pede `/img/wiki/<Nome>.gif`; o servidor busca na TibiaWiki BR só na primeira vez e
  guarda em `wiki_images`. Itens, preços, NPCs, hunts e bosses já ficam no projeto/banco; a wiki só é consultada
  para imagens novas. (No app desktop as imagens ainda vêm direto da wiki, por causa do CSP da página local.)

## Backup e vigia do site

- **Backup automático:** o servidor faz uma cópia por dia em `data/backups/artemis-AAAAMMDD.db` e guarda as 14
  mais novas (`ARTEMIS_BACKUP_KEEP`). O painel mostra o último backup.
- **Vigia:** `tools/vigia.ps1` confere o site no PC e pelo ngrok. Se o servidor parou, roda
  `docker compose --profile public up -d`; se só o ngrok caiu, reinicia o ngrok. Se continuar fora do ar, mostra
  uma notificação do Windows (e outra quando voltar). Instale uma vez com **`vigia.bat`** (Agendador de Tarefas,
  a cada 5 minutos). Resultado em `data/vigia.json` (aparece no painel) e histórico em `data/vigia.log`.
  Desligar por um tempo: `schtasks /Change /TN "4rt3mi5 vigia" /DISABLE` (religar com `/ENABLE`).
  Remover: `schtasks /Delete /TN "4rt3mi5 vigia" /F`.

## Loja e chave grátis (0.13.0)

Na tela de entrada, **🔑 Gere sua nova chave** abre a loja. Hoje só existe **"Gere sua chave gratuita agora
mesmo!"**: cria na hora um código de 7 dias (rótulo "Loja (grátis)"). Limites: 1 por pessoa por dia (o IP vira
hash com sal que muda a cada reinício, o banco nunca guarda o IP) e no máximo 20 por dia no total. O painel tem
**Pausar/Ligar** a chave grátis.

**Renovação grátis (0.14.0):** no menu ☰, **🔑 Renove 7 dias grátis da sua chave** (`POST /api/key/renew-free`).
Só completa para 7 dias a partir de agora quando falta menos que isso; nunca tira dias. Códigos vitalícios
não veem o item.

**Senhas, esqueci a senha e chave vencida (0.17.0):**
- **Hash da senha:** Argon2id (`argon2-cffi`, só no servidor) sobre um HMAC-SHA256 da senha com um **pepper**.
  O pepper fica **fora do banco**: `pw_pepper` em `data/server.json` (criado sozinho), ou `ARTEMIS_PW_PEPPER` no
  ambiente, que tem prioridade. Quem copiar só o banco ou um backup dele não consegue testar senha nenhuma.
  Hashes PBKDF2 da 0.16.0 são trocados por Argon2id no próximo login certo.
- ⚠️ **Guarde uma cópia do `server.json` (ou do pepper) fora do PC.** Se ele se perder, nenhuma senha confere mais
  e todo mundo precisa do código de nova senha.
- **Mensagem de erro:** login errado mostra "Conta/Senha incorreta(s).", sem dizer qual dos dois errou.
- **Esqueceu conta/senha?:** pede o WhatsApp, a conta e um personagem que a pessoa lembre
  (`POST /api/recovery/login`, sem login, até 3 pedidos por IP por dia). No painel, o pedido aparece em azul
  (🔐 Conta/senha), separado dos pedidos de código de acesso (🔑). O painel mostra as contas que batem com o que a
  pessoa lembra e o botão **Gerar código p/ nova senha**: um código `SENHA-…` de uso único, válido por 24 horas,
  guardado só como hash. Depois disso, o botão do WhatsApp já leva a mensagem com o código. A pessoa usa
  "Já recebi um código para criar nova senha". Trocar a senha encerra a conta em todos os aparelhos.
  O adm nunca vê nem define a senha de ninguém.
- **WhatsApp com país:** o campo tem a bandeira e o DDI de cada país, com busca por qualquer parte do nome. O número
  é salvo com o código do país, e o link `wa.me` usa o número como está.
- **Chave vencida de conta:** ela não é mais apagada. Só as chaves sem conta continuam sendo apagadas ao vencer.
  Ao entrar, a conta vê "Chave vencida" e renova 7 dias grátis na hora (`POST /api/account/renew`).
- **Sequência congelada:** os dias em que a chave ficou vencida (tabela `key_pauses`) não contam nem zeram a
  sequência, a recompensa de 30 dias nem a conquista "Semana perfeita". No calendário, eles aparecem em azul
  tracejado. Um dia sem envio com a chave ativa continua zerando a sequência.

**Endurecimento (0.17.0):**
- **Portas:** no `docker-compose.yml`, a 8000 (servidor) e a 4040 (painel do ngrok) só abrem para este PC
  (`127.0.0.1`). O painel do ngrok mostra cada requisição inteira, com senhas de login, e antes ficava visível
  para toda a rede de casa. O acesso de fora continua pelo ngrok.
- **CSP sem `'unsafe-inline'` nos scripts:** o código saiu do HTML para `artemis/web/app.js` (site) e
  `artemis/web/admin.js` (painel; `/admin.js` só sai no PC, como o `/admin`). Imagens que falham usam
  `data-err="hide|remove"` em vez de `onerror=`. O `connect-src` só permite o próprio site, `api.tibiadata.com`,
  domínios do ngrok e `127.0.0.1`/`localhost`. Se trocar o servidor do app de PC para outro domínio, inclua-o no
  CSP de `index.html`. O teste `tests/test_csp.py` falha se algum script ou evento voltar para dentro do HTML.
- **Cache offline:** o `sw.js` (cache `artemis-v2`) guarda `/` e `/app.js`. O `/admin` nunca vai para o cache.

**Conta com senha (0.16.0):**
- Antes da chave vem a tela de login: **Entrar** (Conta e Senha) ou **Criar uma conta** (Conta, Senha e Confirmar
  senha). A conta aceita só letras e números (3 a 20). A senha aceita só letras, números e `_ ! @ -` (6 a 64).
- A senha é guardada só como hash PBKDF2-SHA256 com sal (tabela `accounts`). A sessão da conta (`X-Account-Token`)
  fica no banco só como hash e expira depois de 90 dias parada.
- Senha errada mostra "Senha incorreta, tente novamente." Na 30ª senha errada, o IP fica bloqueado por 30 minutos
  (`LOGIN_FAIL_LIMIT` e `LOGIN_BLOCK` em `app.py`). O contador fica na memória e zera quando o servidor reinicia.
- **Primeiro acesso da conta:** gerar a chave grátis (uma vez por conta; ela já fica ligada à conta) ou **Já tenho um código**. Depois de verificar o personagem, a chave fica ligada à conta
  (`POST /api/account/link`). Em outro aparelho, basta conta e senha para cair direto na escolha do personagem.
- Quem já usava o app com código neste aparelho tem a chave ligada à conta sozinha, no primeiro login.
- **Código errado:** a tela pergunta "Tem certeza que possui um código de acesso?". **Sim** pede o WhatsApp.
  **Não** mostra a geração da chave. Se o personagem digitado já está em outra chave, a tela diz "Este character
  já possui código de acesso" e pede o WhatsApp.
- O painel mostra **Pedidos de recuperação**, com o botão **💬 Abrir conversa no WhatsApp** (`wa.me`, abre o
  WhatsApp Web ou o app) e o botão **✔ Resolvido**. Cada card de código mostra a **Conta** dona.
- A API antiga (código + token do aparelho) continua funcionando. O login é exigido pelas telas.

**Uma chave por conta (0.15.0):**
- A loja é o cadastro: o aparelho que já gerou uma chave (ou já entrou com uma) não gera outra.
- Cada personagem só pode estar em **uma** chave. Verificar um personagem que já está em outra chave dá erro 409.
  Cada chave tem no máximo **50** personagens (`MAX_CHARS_PER_KEY` em `db.py`).
- No painel, **Validar personagem → Adicionar sem verificação** vincula um personagem na mão
  (`POST /api/admin/keys/{key}/chars`). Se ele está em outra chave, use **Resetar dono** lá antes.
- Toda chave nova nasce com **7 dias** (`NEW_KEY_DAYS` em `app.py`), pelo painel ou pela loja. O painel continua
  podendo renovar por 7/15/30 dias.
- O item de renovação grátis só aparece quando faltam **menos de 3 dias** e a chave tem personagem verificado.

## Música

As trilhas tocam direto do site oficial (`static.tibia.com/music/`, © CipSoft) — nada é copiado para o
projeto. Anthem na abertura, Special Boss Lairs em Hunts, "King Tibianus, Queen Eloise, Emperor Kruzak" no
Stacker. Volume bem baixo (a barra no máximo chega a 12% do volume do aparelho; `MAX_GAIN` em `index.html`),
sem repetir, e botão de som em todas as telas (o app lembra volume/mudo). No iPhone/iPad o navegador não deixa a
página controlar o volume, então lá a música fica desligada. Para tirar a música, apague as faixas de `TRACKS`
em `index.html`.

## Ícone na tela inicial

`manifest.webmanifest` + `icon-*.png` (gerados por `tools/make_icons.py`). O site só pede ao navegador para
criar o ícone depois que a pessoa toca em **Sim, adicionar** no aviso que explica o que vai acontecer.

## Regras de acesso

- Códigos de acesso valem no máximo **30 dias**; vencidos são **apagados** (com personagens e aparelhos).
- Na primeira verificação o código **fica preso ao main character**. Quem copiar o código de outra
  pessoa não passa: não pode usar outro personagem e não consegue mexer no comentário do dono.
- Cada aparelho verificado recebe um token próprio; um aparelho novo verifica de novo (com um
  personagem já vinculado).
- **Meus personagens**: vincular alts / novo main (mesma verificação), "Tornar main", remover.
- Qualquer aparelho liberado **vê** qualquer personagem; só **envia** em nome de personagens vinculados.

## Administração

**Painel** (só no PC do servidor): dê dois cliques em `painel.bat` ou abra `http://localhost:8000/admin`.
A senha aparece no `painel.bat` (ou `docker compose exec server python -m artemis.server admin-token`).
Pela internet (ngrok) o painel é bloqueado, mesmo com a senha.

- Criar código de 7, 15 ou 30 dias, com botão "Copiar convite" (convite da fase beta com código e SITE).
- Renovar por 7, 15 ou 30 dias a partir de hoje (mantém personagens e aparelhos).
- **Completar todos para 7/15/30 dias**: só quem tem menos que isso ganha dias; ninguém perde dias.
- **⭐ Amigo do adm (vitalício)**: o código nunca vence e nunca é apagado; a pessoa não vê data de
  vencimento (nem sabe que é vitalício). "Tirar vitalício" devolve o vencimento (se já passou, ganha 7 dias).
- **Entradas**: quantas vezes cada código entrou nos últimos 7 dias e o histórico (data, app Windows ou
  site). Aberturas com menos de 30 minutos de intervalo contam uma vez; guarda 180 dias.
- **Uso das telas** (7 ou 30 dias): visitas por tela, quantas fizeram algo (tocaram em botão/campo ou
  colaram texto) e a % que só olhou. Só contadores por dia, sem dizer quem.
- **Forçar main (contato de confiança)**: define o main sem código de verificação; a pessoa entra só
  com o código de acesso + nick do main. "Remover confiança" volta a exigir verificação.
- Resetar dono e apagar código.

Pela linha de comando, com Docker:

```powershell
docker compose up -d --build                                               # liga (reinicia sozinho)
docker compose exec server python -m artemis.server keys create --label "Atx Buubo"
docker compose exec server python -m artemis.server keys list
docker compose exec server python -m artemis.server keys renew ART-XXXX-XXXX   # +30 dias, mantém personagens
docker compose exec server python -m artemis.server keys reset ART-XXXX-XXXX   # desvincula o dono
docker compose exec server python -m artemis.server keys revoke ART-XXXX-XXXX  # apaga
```

Sem Docker: `start_server.bat` e `admin.bat create "Nome" | list | renew | reset | revoke`.

Banco: `data/artemis.db` (abre no DB Browser for SQLite). Tabelas: `access_keys`, `key_chars`,
`devices`, `verifications`, `hunts` + `hunt_players`, `solo_sessions`, `key_rewards` (recompensas de
sequência), `char_info` (vocação para colorir a PT), entre outras.

## Desenvolvimento

> Use uma pasta de caminho curto (ex.: `C:\dev\4rt3mi5`): o componente de janela do Windows
> falha em caminhos muito longos.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\python -m artemis.server      # servidor + site em http://localhost:8000
.venv\Scripts\python run_desktop.py         # app desktop
.venv\Scripts\python tools\demo_server.py   # DEMO com dados de teste em http://localhost:8765
```

O servidor de demonstração usa um banco próprio (`demo-data/`, fora do Git), não consulta o TibiaData e
entra com o código `ART-DEMO-TEST` + nick `Atx Buubo`. Serve para conferir telas e gravar vídeos.

## Segurança dos dados sensíveis

- **Nada sensível vai para o GitHub.** `tools/check_secrets.py` procura códigos de acesso, tokens
  (ngrok, GitHub, admin), senhas, chaves privadas, e-mails e arquivos proibidos (`.env`, banco,
  `server.json`). Roda sozinho antes de cada commit (`git config core.hooksPath .githooks`) e no
  GitHub Actions antes de gerar a versão — se achar algo, bloqueia.
- **Segredos só no `.env` e em `data/`** (ambos fora do Git e da imagem Docker).
- **Servidor:** token de aparelho guardado só como hash (SHA-256); 10 tentativas erradas de
  código ou senha do painel em 10 min bloqueiam o IP; painel só no PC do servidor; sem página
  pública de documentação da API; cabeçalhos de segurança e respostas da API sem cache.
- **App desktop:** código de acesso e token criptografados com o DPAPI do Windows (só o mesmo
  usuário do Windows, no mesmo PC, consegue abrir).
- **Testes** sempre usam um banco temporário (`tests/__init__.py`), nunca o `data/artemis.db`.
- **Anti-abuso (0.9.0):** limite por IP (240 leituras/min, 40 alterações/min, 30 envios/10 min),
  corpo máximo de 512 KB, campos validados (tamanho, formato, faixas de valores), no máximo 30 hunts
  criadas por código, nomes impossíveis nem consultam o TibiaData, CORS só para o app local,
  CSP no site (só carrega imagens da TibiaWiki/tibiamaps, fontes do Google e áudio de `static.tibia.com`), container Docker
  sem root e sem cabeçalho de versão do servidor. Um teste garante que o código de acesso de um
  usuário nunca aparece nas respostas vistas por outro.
- **Atualizações do app:** só aceita manifesto e instalador das Releases oficiais
  (`github.com/50nnyc/4rt3mi5/releases/`), segue redirecionamento só para o GitHub e confere o SHA-256.

## Novidades (changelog)

Toda versão nova precisa de uma entrada no topo de `artemis/data/changelog.json` (um teste falha
se faltar). O site mostra a aba 📰 Novidades e avisa no Início quando há versão que o usuário não viu.

## Acesso fora de casa

O celular e o app precisam de um endereço público **fixo** para o servidor. Opções:
Tailscale Funnel (grátis, endereço `*.ts.net`), Cloudflare Tunnel com domínio próprio, ou
ngrok com domínio estático gratuito. Para um teste rápido (endereço muda a cada vez):

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```

O endereço vai em `DEFAULT_SERVER_URL` (`artemis/desktop/config.py`) ou na tela do código → "alterar".

## Servidor na nuvem (VM grátis)

Para o servidor ficar no ar 24 h sem depender deste PC, ele pode rodar numa VM grátis (Oracle Cloud "Always
Free"), com o **mesmo domínio do ngrok**. Assim nada muda para os apps instalados. O passo a passo completo está em
**[deploy/GUIA-VM.md](deploy/GUIA-VM.md)**. Resumo dos arquivos:

| Arquivo | Onde roda | Para quê |
|---|---|---|
| `deploy/instalar-vm.sh` | VM (uma vez) | atualiza o Ubuntu, instala o Docker, fuso de Brasília, agenda o vigia |
| `deploy/vigia.sh` | VM (cron, 5 min) | mesmo papel do `tools/vigia.ps1`: religa servidor/ngrok e grava `data/vigia.json` |
| `deploy/enviar-para-vm.ps1` | este PC | envia o código e religa na VM; `-Migrar` leva também `data\` e `.env` (uma vez) |
| `deploy/painel-vm.bat` | este PC | abre o painel admin da VM por um túnel SSH (o bloqueio pela internet continua) |
| `deploy/puxar-backup.ps1` / `.bat` | este PC | copia o backup diário da VM para `backup-vm\` (agendado todo dia) |
| `deploy/manter-ativa.sh` | VM (cron, 10 min) | evita a Oracle recolher a VM grátis por ociosidade |
| `deploy/Caddyfile` + `abrir-portas-web.sh` | VM | HTTPS automático no domínio `SITE_DOMAIN` (perfil `dominio` do compose) |

**Endereço do site:** https://artemishunt.com.br (Caddy com Let's Encrypt). O endereço antigo
artemis-hunt.duckdns.org continua respondendo a API para os apps já instalados, e a página leva ao domínio novo.

**Download do app:** o site mostra o botão "Baixar o app" (só no navegador, nunca dentro do app) e
`/download` sempre leva ao instalador da última Release do GitHub. O link do VirusTotal usa o SHA-256 do
`latest.json`: depois de cada versão, envie o `.exe` em virustotal.com uma vez para o relatório existir.

Na migração, a pasta `data\` vai inteira: o `server.json` tem o "pepper" das senhas, e sem ele nenhuma conta entra.

## Lançar versão nova

1. Altere `__version__` em `artemis/__init__.py` e faça commit.
2. Crie a tag `vX.Y.Z` e envie (`git tag v0.3.0` + `git push --tags`).
3. O GitHub Actions gera o instalador e publica a Release com `latest.json`.
4. O app instalado mostra "Nova versão disponível — Atualizar".

O endereço de atualização fica em `artemis/desktop/config.py` (`DEFAULT_UPDATE_URL`). O download
automático das Releases só funciona com o repositório **público**.

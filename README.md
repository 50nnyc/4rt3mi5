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
4. Menu ☰: **Início**, **Lootsplit**, **Hunt Session Stacker**, **Rotação de bosses** (Solo / Party), **Hunts**, **Conquistas**, **Meus personagens**,
   **Novidades**, trocar personagem, sair.
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

- Criar código de 7, 15 ou 30 dias, com botão "Copiar convite" (código + links do app e do site).
- Renovar por 7, 15 ou 30 dias a partir de hoje (mantém personagens e aparelhos).
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

## Lançar versão nova

1. Altere `__version__` em `artemis/__init__.py` e faça commit.
2. Crie a tag `vX.Y.Z` e envie (`git tag v0.3.0` + `git push --tags`).
3. O GitHub Actions gera o instalador e publica a Release com `latest.json`.
4. O app instalado mostra "Nova versão disponível — Atualizar".

O endereço de atualização fica em `artemis/desktop/config.py` (`DEFAULT_UPDATE_URL`). O download
automático das Releases só funciona com o repositório **público**.

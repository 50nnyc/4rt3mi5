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
4. Menu ☰: **Início**, **Lootsplit**, **Hunt Session Stacker**, **Meus personagens**, trocar personagem, sair.
5. Sem conexão: tela de abertura com o aviso, tentando de novo a cada 10 s.

## Regras de acesso

- Códigos de acesso valem no máximo **30 dias**; vencidos são **apagados** (com personagens e aparelhos).
- Na primeira verificação o código **fica preso ao main character**. Quem copiar o código de outra
  pessoa não passa: não pode usar outro personagem e não consegue mexer no comentário do dono.
- Cada aparelho verificado recebe um token próprio; um aparelho novo verifica de novo (com um
  personagem já vinculado).
- **Meus personagens**: vincular alts / novo main (mesma verificação), "Tornar main", remover.
- Qualquer aparelho liberado **vê** qualquer personagem; só **envia** em nome de personagens vinculados.

## Administração

Com Docker (recomendado):

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
`devices`, `verifications`, `hunts` + `hunt_players`, `solo_sessions`.

## Desenvolvimento

> Use uma pasta de caminho curto (ex.: `C:\dev\4rt3mi5`): o componente de janela do Windows
> falha em caminhos muito longos.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\python -m artemis.server      # servidor + site em http://localhost:8000
.venv\Scripts\python run_desktop.py         # app desktop
```

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

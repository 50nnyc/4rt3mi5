# Launcher do 4rt3mi5 (o instalador sem versão)

`4rt3mi5-Launcher.exe` é o que o botão **Baixar o app** do site entrega. Ele:

1. lê o `latest.json` da última Release do GitHub;
2. se o app não está instalado, mostra **INSTALAR**; se há versão nova, **ATUALIZAR**; se está em dia, **ENTRAR**;
3. baixa o instalador da versão, confere o SHA-256 e instala em silêncio (o app abre sozinho no final).

Ele só aceita arquivos das Releases de `github.com/50nnyc/4rt3mi5`, por HTTPS, e só instala se o SHA-256 bater.

## Por que ele é congelado
Sem assinatura digital, o SmartScreen do Windows guarda a reputação de um `.exe` **pelo hash dos bytes**.
Cada instalador novo começava do zero e mostrava "O Windows protegeu o computador". O launcher nunca muda, então a
reputação dele só cresce: depois de liberado pela Microsoft, o aviso não volta. O que ele baixa por conta própria
não passa pelo SmartScreen.

- `4rt3mi5-Launcher.exe` está no repositório e vai **igual** em toda Release (o `build.ps1` copia).
- `SHA256.txt` guarda o hash. O `build.ps1` e o teste `tests/test_download.py` falham se o arquivo mudar.
- **Não recompile sem necessidade.** Se precisar, rode `build-launcher.ps1`, atualize o `SHA256.txt`, mude
  `LauncherVersion` no código e envie o arquivo novo para a Microsoft (microsoft.com/wdsi/filesubmission) e para o
  VirusTotal outra vez.

## Arquivos
| Arquivo | O que é |
|---|---|
| `Launcher.cs` | código (C# 5, compilado pelo csc do .NET Framework 4 que já vem no Windows) |
| `app.manifest` | roda sem administrador e fica nítido em telas com escala |
| `arte/fundo.html` | a arte: Ártemis no Olimpo, sob a lua cheia (SVG) |
| `arte/renderizar.ps1` | gera `arte/fundo.png` com o Edge |
| `build-launcher.ps1` | gera o ícone e compila o `.exe` com a arte embutida |

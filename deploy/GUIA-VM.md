# Levar o servidor do 4rt3mi5 para uma VM grátis (Oracle Cloud)

Objetivo: o site, a API, o ngrok, os backups e o vigia rodam 24 h numa VM grátis, e este PC pode ficar desligado.

**O que não muda:** o domínio do ngrok continua o mesmo. Por isso os apps já instalados, o CSP, os links
divulgados e o instalador (Releases do GitHub) continuam funcionando sem nenhuma alteração.

Tempo total: uns 40 minutos. O site fica fora do ar só 2 a 5 minutos, no passo 6.

---

## 1. Criar a conta na Oracle Cloud
1. Acesse **oracle.com/cloud/free** e clique em *Start for free*.
2. **Home region:** escolha **Brazil East (São Paulo)** ou **Brazil Southeast (Vinhedo)**. *Não dá para trocar
   depois*, e as máquinas grátis só podem ser criadas na home region.
3. A Oracle pede um cartão de crédito só para conferir a identidade. Ela pode fazer uma cobrança pequena e devolver
   em seguida. Os recursos "Always Free" não geram cobrança.

## 2. Criar a VM
Menu ☰ → **Compute → Instances → Create instance**:

| Campo | O que escolher |
|---|---|
| Name | `artemis` |
| Image | **Canonical Ubuntu 24.04** |
| Shape | *Change shape* → **Ampere** → `VM.Standard.A1.Flex` com **2 OCPU e 12 GB** (o grátis vai até 4 OCPU e 24 GB) |
| Networking | deixe o padrão (cria a rede e um **IP público**) |
| SSH keys | **Generate a key pair for me** → clique em **Save private key** (guarde bem esse arquivo!) |
| Boot volume | padrão (cerca de 47 GB, o grátis vai até 200 GB) |

Clique em **Create** e espere ficar *Running*. Anote o **Public IP address**.

> **"Public IP address" com "-"?** A VM nasceu sem IP público. Para resolver: aba **Networking** → clique na VNIC →
> **IP administration** → ⋮ na linha do IP privado → **Edit** → **Ephemeral public IP** → **Update**.
>
> **Sem chave SSH?** Se não salvou a chave, gere uma neste PC com
> `ssh-keygen -t rsa -b 4096 -f $env:USERPROFILE\.ssh\artemis-vm.key -N '""'` e recrie a VM com
> **Paste public keys**, colando o conteúdo de `artemis-vm.key.pub`. Sem a chave não tem como entrar.

> **"Out of capacity"?** Isso acontece com o Ampere em São Paulo. Tente outro *Availability domain*, tente
> 1 OCPU / 6 GB, ou tente de novo em outro horário. Plano B: o shape `VM.Standard.E2.1.Micro` (AMD, 1 GB, também
> grátis). Ele fica em *Change shape* → **Specialty and previous generation**. **Cuidado:** E4.Flex e E5.Flex, que
> aparecem na aba "AMD", são **pagos**. Escolha só shapes com a etiqueta "Always Free-eligible". Depois de trocar o
> shape, confira se a imagem continua Ubuntu 24.04. O script de instalação cria a memória swap sozinho nesse caso, e ele aguenta o 4rt3mi5.

Não precisa abrir porta nenhuma no firewall da Oracle: o ngrok faz conexão *de saída*. Só o SSH (22) fica aberto,
que já é o padrão.

## 3. Configurar o SSH neste PC (uma vez)
1. Mova a chave baixada para `C:\Users\<você>\.ssh\artemis-vm.key`.
2. Deixe a chave legível só por você. O SSH recusa a chave se outras contas puderem ler. Rode no PowerShell:
   ```powershell
   icacls "$env:USERPROFILE\.ssh\artemis-vm.key" /inheritance:r /grant:r "$($env:USERNAME):R"
   ```
3. Crie (ou edite) o arquivo `C:\Users\<você>\.ssh\config` (sem extensão) com:
   ```
   Host artemis-vm
       HostName IP_PUBLICO_DA_VM
       User ubuntu
       IdentityFile ~/.ssh/artemis-vm.key
       ServerAliveInterval 30
   ```
4. Teste com `ssh artemis-vm`. Na primeira vez, responda `yes`. Se aparecer `ubuntu@artemis:~$`, está certo.
   Digite `exit` para sair.

Todos os scripts da pasta `deploy\` usam esse apelido `artemis-vm`.

## 4. Mandar o código para a VM
Na pasta do projeto, neste PC:
```powershell
powershell -ExecutionPolicy Bypass -File deploy\enviar-para-vm.ps1
```
Esse comando envia só o código. O banco e o `.env` ficam para o passo 6, e o servidor deste PC continua no ar.
No final ele vai avisar que a VM ainda não tem Docker. Isso é esperado.

## 5. Preparar a VM (uma vez)
```powershell
ssh artemis-vm
bash ~/4rt3mi5/deploy/instalar-vm.sh
exit
```
O script atualiza o Ubuntu, liga as atualizações de segurança automáticas, instala o Docker, coloca o fuso de
Brasília e agenda o vigia a cada 5 minutos. **Saia e entre de novo no SSH** depois dele, para a permissão do
Docker valer.

## 6. Migrar (o site fica fora do ar por 2 a 5 minutos)
```powershell
powershell -ExecutionPolicy Bypass -File deploy\enviar-para-vm.ps1 -Migrar
```
O que ele faz, em ordem:
1. Confere se a VM já tem Docker e se *não* tem banco lá (para nunca sobrescrever nada).
2. Desliga o servidor e o ngrok **deste PC** e remove o vigia do Windows (senão ele religaria tudo aqui).
3. Envia o código, a pasta `data\` (com `artemis.db` e **`server.json`**) e o `.env`.
   - O `server.json` guarda a senha do painel e o "pepper" das senhas das contas. **Sem ele ninguém consegue
     entrar.** Por isso a pasta vai inteira.
4. Liga o servidor e o ngrok na VM e confere se respondeu.

## 7. Conferir
- Abra o site pelo domínio do ngrok e faça login com uma conta.
- Abra o app desktop: ele deve conectar normalmente.
- **Painel admin:** rode `deploy\painel-vm.bat`. Ele mostra a senha e abre um túnel SSH, então para o servidor é
  como se você estivesse na própria VM, e o bloqueio do painel pela internet continua valendo. O painel mostra o
  vigia e os backups da VM. Feche a janela do túnel quando terminar.

## 8. Backup fora da nuvem (importante)
O servidor faz um backup por dia em `data/backups` **na VM**. Se a VM sumir, esses backups somem junto.
Rode uma vez neste PC:
```
deploy\puxar-backup.bat
```
Ele agenda uma cópia diária do backup mais novo para a pasta `backup-vm\` deste projeto e guarda os 30 últimos.
Se o PC estiver desligado no horário, a cópia roda quando ele ligar.

## 9. Evitar que a Oracle recolha a VM
A Oracle pode recolher VMs grátis que ficam "ociosas" por 7 dias, e o 4rt3mi5 usa pouca CPU.

**Sem gastar nada (já vem instalado):** o `deploy/manter-ativa.sh` roda pelo cron a cada 10 minutos e ocupa a CPU por
1 minuto, com a prioridade mais baixa (o site sempre passa na frente). Isso deixa o percentil 95 da CPU acima dos 20%
que a Oracle usa para decidir. Para conferir, abra a VM no console → **Monitoring** → gráfico **CPU utilization**: ele
deve mostrar picos a cada 10 minutos.

**Se tiver US$ 100 de limite no cartão** (a Oracle faz uma pré-autorização desse valor e devolve depois):
- Menu ☰ → **Billing → Upgrade and Manage Payment** → **Pay As You Go**. Os recursos *Always Free* continuam
  grátis, e contas pagas não sofrem esse recolhimento.
- Por segurança, crie um alerta: **Billing → Budgets → Create budget** com valor de R$ 5 e alerta por e-mail.
  Se algum dia aparecer cobrança, você fica sabendo na hora.

---

## Dia a dia

| Quero… | Comando (neste PC) |
|---|---|
| Atualizar o servidor depois de mudar o código | `powershell -ExecutionPolicy Bypass -File deploy\enviar-para-vm.ps1` |
| Ver os logs | `ssh artemis-vm "cd 4rt3mi5 && docker compose logs --tail 100"` |
| Abrir o painel admin | `deploy\painel-vm.bat` |
| Criar um código de acesso | `ssh artemis-vm "cd 4rt3mi5 && docker compose exec -T server python -m artemis.server keys create --label Nome"` |
| Listar códigos | `ssh artemis-vm "cd 4rt3mi5 && docker compose exec -T server python -m artemis.server keys list"` |
| Reiniciar tudo | `ssh artemis-vm "cd 4rt3mi5 && docker compose --profile public restart"` |
| Histórico do vigia | `ssh artemis-vm "tail -n 30 4rt3mi5/data/vigia.log"` |

`admin.bat`, `painel.bat`, `start_server.bat` e `vigia.bat` são do servidor **neste PC**. Depois da migração, use os
comandos acima. O instalador e as versões novas continuam saindo pelo GitHub (`git tag` → Release), como antes.

## Voltar para o PC (se algo der errado)
1. Na VM: `ssh artemis-vm "cd 4rt3mi5 && docker compose --profile public down"` (libera o domínio do ngrok).
2. Se a VM já recebeu dados novos, traga o banco de volta antes de religar aqui. Com o servidor da VM desligado:
   `scp artemis-vm:4rt3mi5/data/artemis.db data\artemis.db`
3. Neste PC: `docker compose --profile public up -d` e, se quiser, `vigia.bat` de novo.

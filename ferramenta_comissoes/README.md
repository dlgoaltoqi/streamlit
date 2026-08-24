# Formatador de Comissões (protótipo)

Ferramenta de desktop que pega os arquivos exportados do painel (Downloads),
formata, salva na pasta do OneDrive com versionamento e envia por e-mail para
validação dos líderes.

## Cabeçalho: Ano e Mês

No topo da janela, acima das abas, ficam os seletores de **Ano** e **Mês**.
Eles são únicos para a janela toda: trocar o período ali atualiza o que
aparece nas abas "Configurar E-mails" e "Enviar". Por exemplo, se Ares não
teve arquivo exportado nem processado em julho, Ares não aparece nessas duas
abas enquanto o filtro estiver em julho.

## Abas

### 1. Processar

1. Escolha a **pasta de Downloads** e a **pasta de saída** (ficam salvas como
   padrão entre execuções).
2. Ao clicar em **Processar**, varre a pasta de Downloads por
   `comissoes_AAAA_MM_<Equipe>.xlsx`, usando o Ano/Mês do cabeçalho.
3. Se houver duplicados (`... (1).xlsx`), pergunta qual usar.
4. Formata **todas as abas** de cada arquivo (Governo tem 2 abas, as duas
   são mantidas):
   - coluna **Mês** vira número;
   - **caixa grossa** em volta de cada grupo de colunas (grupos vêm da 2ª linha, a de categorias);
   - colunas de **Totalizações** com texto **vermelho**;
   - colunas de **Aceleradores Forma de Pagamento** **ocultadas**;
   - **cabeçalho em negrito**, conteúdo **centralizado**, **largura ajustada** ao texto;
   - a **linha de categorias é removida** no final.
5. Salva como **`Comissões OTE AAAAMM - <Nome> vN.xlsx`** na pasta de saída;
   a versão anterior é movida para a subpasta **`V Olds`**.

### 2. Configurar E-mails

Topo da aba: **Conta Gmail para envio** — preencha seu e-mail e a
**Senha de App** gerada em `myaccount.google.com` > Segurança > Senhas de app
(requer verificação em duas etapas ativa). Clique em **Salvar conta Gmail**.
Essas credenciais ficam salvas no `config.json` local e não são perdidas em
atualizações do exe.

Abaixo, uma linha por **grupo de envio**, com dois campos:

- **Para**: quem recebe os arquivos daquele grupo (o líder), para validação.
- **Cc**: quem fica em cópia. É **por grupo** (cada grupo pode ter um Cc diferente).

Na maioria dos casos um grupo é uma única equipe (ex.: Ares, FSB). Mas
`GRUPOS_ENVIO`, no topo do `.py`, pode juntar equipes com arquivos separados
num único grupo de envio: hoje, Saving e Cancelamento continuam sendo dois
arquivos distintos (cada um com seu próprio nome e numeração de versão), mas
compartilham uma linha de destinatário aqui e saem juntos no mesmo e-mail.

Só aparecem grupos com pelo menos um arquivo baixado ou já processado para o
Ano/Mês do cabeçalho. Vários endereços no mesmo campo são separados por
**ponto e vírgula (;)**. **Salvar destinatários** grava tudo no `config.json`;
salvar num mês não apaga os e-mails já configurados de outros grupos de outros meses.

### 3. Enviar

1. **↻ Atualizar lista** varre a pasta de saída pelo arquivo mais recente de
   cada equipe para o Ano/Mês do cabeçalho, já juntando os grupos definidos
   em `GRUPOS_ENVIO` (atualiza também sozinha ao trocar de aba ou ao trocar
   o Ano/Mês).
2. Cada grupo com pelo menos um arquivo processado aparece como uma linha
   com checkbox, mostrando o nome de todos os arquivos que vão como anexo.
   Grupos sem **Para** configurado na aba anterior aparecem desmarcados e
   desabilitados, com o aviso "sem e-mail configurado".
3. **Assunto** e **Corpo** valem para todos os e-mails selecionados; aceitam
   os placeholders `{equipe}`, `{mes}` e `{ano}` (`{equipe}` usa o nome do
   grupo, não o nome de cada arquivo).
4. Escolha o modo:
   - **Prévia antes de enviar**: abre uma janela por e-mail com todos os
     detalhes (destinatário, assunto, corpo, anexos) para revisar. Botões:
     Enviar, Pular ou Cancelar tudo. Comece por aqui.
   - **Enviar direto**: dispara todos os e-mails selecionados via Gmail SMTP
     sem janela de revisão. Use só depois de confiar no fluxo.
5. **Salvar padrão de assunto/corpo** grava o Assunto, o Corpo e o modo
   atuais como padrão, sem precisar enviar nada.
6. **Executar envio** envia um e-mail por grupo marcado, com um anexo por
   arquivo do grupo, via Gmail SMTP, e mostra o resultado no log da aba.

## Rodar direto (sem gerar .exe)

```
pip install openpyxl
python formatador_comissoes.py
```

## Gerar o executável (.exe)

O build requer o Python do Anaconda e um venv em caminho curto (evita estourar
o MAX_PATH do Windows). Exemplo com `C:\fcbuild`:

```powershell
$py = "C:\Users\Higor.Nocetti\AppData\Local\anaconda3\python.exe"
$anaconda = "C:\Users\Higor.Nocetti\AppData\Local\anaconda3"

# 1. Criar venv e instalar dependências
& $py -m venv C:\fcbuild\venv
C:\fcbuild\venv\Scripts\python.exe -m pip install openpyxl pyinstaller

# 2. Copiar fonte (caminho sem acento para o PyInstaller)
Copy-Item ".\formatador_comissoes.py" "C:\fcbuild\formatador_comissoes.py"

# 3. Compilar
C:\fcbuild\venv\Scripts\python.exe -m PyInstaller --onefile --windowed `
  --name "Formatador Comissoes" `
  --distpath "C:\fcbuild\dist" `
  --workpath "C:\fcbuild\build" `
  --specpath "C:\fcbuild" `
  --add-binary "$anaconda\Library\bin\tcl86t.dll;." `
  --add-binary "$anaconda\Library\bin\tk86t.dll;." `
  --add-data  "$anaconda\Library\lib\tcl8.6;tcl8.6" `
  --add-data  "$anaconda\Library\lib\tk8.6;tk8.6" `
  --add-binary "$anaconda\Library\bin\libssl-1_1-x64.dll;." `
  --add-binary "$anaconda\Library\bin\libcrypto-1_1-x64.dll;." `
  C:\fcbuild\formatador_comissoes.py
```

O exe gerado fica em `C:\fcbuild\dist\Formatador Comissoes.exe`. Copie para
`C:\Users\Higor.Nocetti\Documents\` substituindo o anterior. Apague `C:\fcbuild`
manualmente pelo Explorer após o build.

> Observação: executáveis gerados com PyInstaller às vezes são sinalizados por
> antivírus (falso positivo). Se acontecer, libere o arquivo na sua ferramenta de AV.

## Onde fica salva a configuração

`%APPDATA%\FormatadorComissoes\config.json` guarda as pastas
(Downloads/saída), Ano/Mês selecionado, destinatários por equipe (`emails`)
e o último assunto/corpo/modo de envio usados (`envio`).

## Mapa de nomes das equipes e grupos de envio

No topo do `.py`, `EQUIPE_NOME`: slug do arquivo exportado (nome como
aparece após `comissoes_AAAA_MM_`) → nome final usado no arquivo formatado.
Hoje: `Governo` → `B2G`, demais equipes com o mesmo nome (só troca `_` por
espaço). Qualquer equipe não listada usa o fallback (troca `_` por espaço).

`GRUPOS_ENVIO`, logo abaixo, define quais equipes compartilham destinatário
e saem juntas num único e-mail nas abas Configurar E-mails e Enviar, mesmo
tendo arquivos e nomes separados. Hoje: `Saving e Cancelamento` agrupa
`Saving` e `Cancelamento`. Uma equipe fora de qualquer grupo continua
configurável e enviável sozinha, do jeito de sempre.

## Limitações conhecidas (protótipo)

- Só lê arquivos **`.xlsx`**. Se o export vier como `.csv`, a ferramenta avisa
  e ignora (garanta que o painel esteja exportando em xlsx; o
  `environment.yml` com `openpyxl` já habilita isso).
- A **largura das colunas** é uma estimativa (o formato xlsx não tem "autofit" real);
  fica boa, mas pode precisar de um retoque fino no fator.
- O envio por e-mail requer uma **Senha de App do Google** configurada na aba
  "Configurar E-mails". Não funciona com a senha normal da conta Google.
- Um grupo de `GRUPOS_ENVIO` só aparece na lista de envio com os arquivos
  que já existem; se Saving foi processado e Cancelamento ainda não, o
  e-mail do grupo sai só com o anexo de Saving.

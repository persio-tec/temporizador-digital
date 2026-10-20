# Temporizador Digital

Aplicativo desktop com relógio digital, temporizador, alarme sonoro e anotações
de tarefas salvas automaticamente. Funciona no Linux e também há versões para
Windows e macOS.

O ícone personalizado também aparece na bandeja do sistema. Clique duas vezes
para abrir a janela; clique com o botão direito para abrir, iniciar, pausar,
retomar ou zerar o temporizador, ou sair do aplicativo.

## Requisitos

- Linux com uma sessão gráfica
- Python 3 e PySide6 instalados
- `systemctl` para solicitar o desligamento opcional do computador

Neste computador, o aplicativo usa o Python em `/usr/sbin/python3` e o PySide6
que já estão instalados.

## Executar

Abra **Temporizador Digital** pelo menu de aplicativos ou execute:

```sh
/usr/sbin/python3 /home/persio/Projetos/temporizador-digital/main.py
```

As tarefas, as preferências e o estado do temporizador são salvos em
`~/.local/share/temporizador-digital/estado.json`. O temporizador em andamento
é restaurado ao abrir o aplicativo novamente.

## Desligamento opcional

Marque **Desligar o computador ao terminar** antes de iniciar o temporizador.
Quando ele terminar, haverá 60 segundos para cancelar o desligamento. No KDE
Plasma, o aplicativo pede ao gerenciador de sessão para encerrar os
aplicativos normalmente antes de desligar. Eles podem solicitar que você salve
arquivos ou cancelar o encerramento; nenhum aplicativo é finalizado à força.
Em outros ambientes Linux, o desligamento é solicitado ao `systemctl` e o
comportamento de fechamento depende do ambiente e do sistema operacional. Se o
temporizador vencer enquanto este aplicativo estiver fechado, o desligamento é
cancelado por segurança.

## Windows e macOS

Há pacotes prontos para instalar sem precisar do Python:

1. Abra a aba **Actions** do repositório no GitHub.
2. Selecione o fluxo **Build Windows e macOS** e clique em **Run workflow**.
3. Ao terminar, baixe o artefato desejado na própria execução:
   - `TemporizadorDigital-Windows` — arquivo `TemporizadorDigital.exe`
   - `TemporizadorDigital-macOS` — arquivo `TemporizadorDigital.dmg`
4. No Windows, execute o `.exe`. No macOS, abra o `.dmg` e arraste o aplicativo
   para a pasta **Aplicativos**.

O desligamento automático do computador está disponível apenas no Linux. Nos
demais sistemas o alarme e as demais funções continuam funcionando normalmente.

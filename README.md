# Temporizador Digital

Aplicativo desktop para Linux com relógio digital, temporizador, alarme sonoro e
anotações de tarefas salvas automaticamente.

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
/usr/sbin/python3 main.py
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

## Dados e privacidade

- Tarefas, preferências e estado do temporizador ficam em
  `~/.local/share/temporizador-digital/estado.json`.
- O aplicativo não acessa a internet nem envia dados para lugar nenhum.

## Testes

```bash
python3 -m unittest discover -s tests
```

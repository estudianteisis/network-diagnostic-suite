# Network Diagnostic Suite

Suite de diagnóstico para Windows orientada a microcortes: recoge evidencia simultánea
de la red local, Internet, DNS y conexiones TCP/TLS para ayudar a explicar eventos como
**“Reconnecting”** de League of Legends. No atribuye culpa automáticamente al ISP, Riot,
Vanguard ni al computador.

## Qué observa

- Latencia, jitter, timeouts y pérdida aparente por ICMP al gateway y a dos destinos públicos.
- Resolución DNS usando el resolvedor del sistema y, opcionalmente, consultas directas.
- Apertura TCP y negociación TLS, separadas para distinguir fallos de ruta y aplicación.
- Cambios de estado, dirección y contadores de las interfaces de Windows.
- Marcadores manuales con hora UTC (por ejemplo, al ver “Reconnecting”).
- Reporte HTML autocontenido y resumen JSON comparable entre dos jugadores.

Un timeout ICMP aislado **no equivale necesariamente a pérdida de paquetes**: algunos equipos
depriorizan o bloquean ping. La clasificación combina señales independientes y conserva el
nivel de confianza y las explicaciones alternativas.

## Instalación

Requiere Windows 10/11 y Python 3.11 o posterior.

```powershell
git clone <URL-DEL-REPOSITORIO>
cd network-diagnostic-suite
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Uso rápido

En una terminal, inicia una sesión antes de jugar:

```powershell
netdiag monitor --label jugador-1
```

Cuando ocurra el problema, abre otra terminal y marca el evento:

```powershell
netdiag mark reconnecting --note "League mostró Reconnecting durante ~2 s"
```

Detén el monitor con `Ctrl+C`. Genera el reporte:

```powershell
netdiag report sessions\<sesion>
```

Para comparar sesiones de dos jugadores (idealmente con relojes sincronizados):

```powershell
netdiag compare sessions\jugador-1\summary.json sessions\jugador-2\summary.json
```

También puedes ajustar destinos y frecuencia:

```powershell
netdiag monitor --interval 1 --public 1.1.1.1 --public 8.8.8.8 `
  --dns-host example.com --tcp-host 1.1.1.1:443 --tls-host www.cloudflare.com:443
```

## Cómo interpretar una clasificación

| Evidencia cercana al marcador | Hipótesis prudente |
|---|---|
| Gateway falla junto con Internet | LAN/Wi-Fi/router local |
| Gateway estable; varios destinos públicos fallan | acceso ISP o salida común, sin identificar responsable |
| Solo un destino/ruta falla | ruta selectiva, filtrado o destino |
| ICMP estable; DNS falla | resolvedor o camino DNS |
| ICMP/DNS/TCP/TLS estables | problema específico del juego/cliente es compatible, no demostrado |
| Ambos jugadores fallan a la vez en redes distintas | servicio/ruta compartida es compatible |

El reporte usa ventanas alrededor de cada marcador y muestra datos crudos. Para separar Wi-Fi
de ISP, siempre se prueba el gateway. Para separar “Internet caído” de una ruta particular, se
prueban al menos dos redes públicas. No se captura tráfico ni credenciales.

## Archivos de una sesión

- `events.jsonl`: eventos append-only con timestamps UTC y monotónicos.
- `session.json`: configuración y metadatos sanitizados.
- `summary.json`: métricas y clasificaciones reproducibles.
- `report.html`: reporte local autocontenido.
- `active-session.txt`: puntero para `netdiag mark` (en el directorio `sessions`).

## Desarrollo

```powershell
python -m pytest
ruff check .
```

Consulta [docs/METHODOLOGY.md](docs/METHODOLOGY.md) para límites, privacidad y lógica de
clasificación. La integración de estado Riot es opcional y deliberadamente externa al juicio
causal: una incidencia publicada puede aportar contexto, pero no prueba qué causó un evento.


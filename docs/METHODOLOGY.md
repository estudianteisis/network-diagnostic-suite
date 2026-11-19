# Metodología y límites

## Modelo de medición

Cada sonda emite un evento JSON independiente con hora UTC, reloj monotónico, duración,
resultado y error normalizado. Las sondas corren concurrentemente para evitar que un timeout
oculte las demás señales. El intervalo es una meta, no tiempo real estricto: suspensión del
equipo, saturación del scheduler o antivirus pueden introducir huecos.

El jitter se calcula como la media de diferencias absolutas entre latencias exitosas
consecutivas. La “pérdida” reportada es la proporción de intentos sin respuesta de esa sonda;
en ICMP se denomina pérdida *aparente* porque un router puede depriorizar eco sin perder
tráfico de juego.

## Clasificación

Para cada marcador manual se inspecciona una ventana configurable (por defecto ±10 s). Se
considera degradación cuando hay timeouts, una tasa de fallos relevante o latencia muy por
encima de la línea base de la sesión. La jerarquía evita saltos causales:

1. Gateway degradado: compatible con LAN, Wi-Fi, NIC o router.
2. Gateway sano y dos destinos públicos degradados: compatible con acceso/salida común.
3. Solo una familia de destino degradada: compatible con ruta o servicio selectivo.
4. DNS degradado con conectividad IP: compatible con DNS.
5. Solo TCP/TLS degradado: compatible con transporte, filtrado o servicio.
6. Todo sano: la red medida no muestra evidencia; cliente/juego sigue siendo una hipótesis.

Las etiquetas son hipótesis, incluyen confianza (`low`, `medium`, `high`) y no nombran a Claro
como causa sin datos adicionales del proveedor. NAT, CGNAT, peering y rutas internas no pueden
inferirse solo con estas sondas.

## Comparación entre jugadores

La comparación alinea marcadores por UTC dentro de una tolerancia. Requiere relojes del sistema
sincronizados. Coincidencia temporal aumenta el peso de una causa compartida, pero no demuestra
que sea Riot: ambos usuarios podrían compartir ISP, región, DNS o ruta.

## Privacidad

No se capturan paquetes, procesos, nombres de usuario ni direcciones MAC. Los nombres de
interfaces y direcciones IP locales pueden aparecer en eventos; revisa los JSON antes de
compartirlos. Los endpoints configurados y la etiqueta de sesión quedan registrados.


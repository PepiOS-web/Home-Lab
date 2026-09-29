# Problemas y soluciones

## La memoria USB no aparecia al arrancar

Se habilito el menu de arranque F12 en la BIOS y se selecciono la entrada UEFI del instalador.

## No bootable device despues de instalar Ubuntu

El firmware InsydeH2O no reconocio automaticamente la entrada de Ubuntu. Se registro como archivo UEFI de confianza el cargador `EFI/ubuntu/shimx64.efi` y el sistema pudo arrancar.

## Error al crear la configuracion de logind

Se creo accidentalmente `/etc/systemd/logind.conf.d` como archivo en vez de directorio. Se hizo una copia temporal, se elimino el archivo y se creo correctamente el directorio con el fichero `10-homelab.conf`.

## La temperatura del mensaje de bienvenida parecia alta

El valor del mensaje de inicio no coincidia con las lecturas directas. `sensors` y `/sys/class/thermal` confirmaron temperaturas normales del procesador en reposo.

## Se pego una configuracion de Caddy directamente en Bash

Bloques como `portal.home.arpa { ... }` son contenido de un Caddyfile, no
comandos de terminal. Bash intento ejecutar palabras como `route`, `handle` y
`reverse_proxy`. No se instalan esos supuestos comandos. Se edita el Caddyfile,
se valida con `caddy validate` y despues se recarga Caddy.

## Grafana redirigia otra vez al inicio de sesion

Grafana conservaba un dominio raiz diferente del utilizado por el portal. Se
configuro la URL raiz bajo `/grafana/`, se habilito el servicio desde subruta y
se mantuvieron las cookies seguras bajo el mismo origen que Homepage. Una
peticion a `/grafana/login` paso de redirigir al dominio antiguo a responder
`200`. No fue necesario habilitar acceso anonimo.

## Windows no encontraba ESPHome o Python

`py` y `python` no estaban disponibles inicialmente. Tras instalar Python y
ESPHome, se utilizo la ruta absoluta del ejecutable en una variable de
PowerShell. Las variables deben volver a definirse al abrir una nueva ventana.

## COM5 estaba ocupado o no se podia abrir

Otro monitor serie o proceso Python conservaba el puerto. Se cerraron
`miniterm`, ESPHome y procesos Python anteriores, se reconecto el USB y se
comprobo el puerto CH340 con `Get-PnpDevice`. Dos programas no pueden abrir el
mismo puerto serie simultaneamente.

## El DHT11 mostraba Communication failed

Se verificaron con la placa sin alimentacion la continuidad de `D4`, `GND` y
`3V3`, y la ausencia de cortocircuito entre alimentacion y tierra. La
configuracion correcta utiliza `D4`, que corresponde a `GPIO2`. Tras corregir
el montaje, el monitor serie mostro temperatura y humedad validas.

## La salida serie contenia caracteres ilegibles

El cargador de arranque del ESP8266 utiliza una velocidad diferente a la del
logger. Es normal observar caracteres ilegibles durante unos instantes. Los
registros de ESPHome aparecen despues a 115200 baudios.

## La actualizacion OTA rechazaba la autenticacion

La contrasena de `secrets.yaml` no coincidia con la almacenada en el firmware.
Se realizo una carga por USB, que no necesita la contrasena OTA anterior y
grabo la nueva. Las siguientes actualizaciones OTA funcionaron normalmente.

## El nombre sensor-prototipo.local no resolvia en Windows

La resolucion mDNS `.local` no estaba disponible, aunque el dispositivo seguia
conectado. Se obtuvo su direccion desde los registros serie y se creo una
reserva DHCP. La falta de resolucion de nombre no implica por si sola un fallo
del sensor.

## Prometheus devolvia un vector vacio despues de reiniciar

La consulta se realizo antes del primer intervalo de recogida. Tras esperar mas
de un `scrape_interval`, `up{job="sensor-prototipo"}` aparecio con valor `1`.

## Homepage mostraba lecturas antiguas

El archivo `status.json` se actualizaba en el servidor, pero el contenedor veia
una version antigua. El exportador reemplaza el archivo de forma atomica y el
montaje Docker apuntaba al inode anterior. Se corrigio montando el directorio
completo como solo lectura y actualizando los widgets a
`/homelab-status/status.json`. Fue necesario recrear el contenedor, no solo
reiniciarlo.

## Todos los widgets Custom API mostraban Error de API

Despues de cambiar el montaje, `services.yaml` todavia utilizaba la URL antigua
`/homelab-status.json`. Se actualizaron todas las referencias a la nueva ruta y
se reinicio Homepage.

## La pagina del sensor dejo de cargar al moverlo

El servidor devolvia `No route to host` y Prometheus mostraba `up=0`. El sensor
habia perdido alimentacion, cobertura Wi-Fi o conectividad en la nueva
ubicacion. Se comprobo primero con un cable, cargador y ubicacion conocidos. No
se modificaron Prometheus ni Homepage porque las capas superiores funcionaban.

## El DHT11 indica una temperatura demasiado alta

El shield esta muy cerca del ESP8266 y puede medir parte del calor de la placa.
Para una lectura ambiental mas fiable se debe usar una caja ventilada, separar
el sensor mediante cables y, en la siguiente version, sustituirlo por un sensor
de mayor precision como el SHT31-D.
